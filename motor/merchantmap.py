"""Qué vende cada vendedor sin tener que hablar con él: los datos del addon Merchant Map.

Merchant Map (https://github.com/knofle/MerchantMap, GPLv3) trae dos listas para Forever:
  - VendorData.lua: los vendedores del Classic sacados de Questie, con lo que vende cada uno, su
    facción y su zona, sin precios;
  - VerifiedData.lua: los vendedores que se han comprobado en Forever, con el precio de verdad, si
    tienen existencias limitadas o se pagan con divisa, y lo del Classic que ya no venden.
El motor las baja con los datos del juego y las junta en mm_vendor_items. Lo que no sale en
ninguna se da por no vendido; lo que ves tú al abrir un vendedor sigue mandando (vendor_items).

Precio de cada oferta: el comprobado puede llevar descuentos de reputación de quien lo vio, así
que se usa el de los datos del juego si se parece (±15 %) y, si no, el comprobado. Lo que solo sale
en la lista del Classic se cuenta al precio de los datos del juego, como «sin comprobar». Los dos
son por compra (un lote de vendor_stack unidades) y se pasan a precio por unidad.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .db import get_meta, set_meta
from .gamedata import _get

SOURCE = "https://raw.githubusercontent.com/knofle/MerchantMap/main"
FILES = ["VendorData.lua", "VerifiedData.lua"]
REFRESH_DAYS = 7
PRICE_MATCH = 0.15       # el precio de los datos del juego vale si está a ±15 % del comprobado

_STRING = r'"((?:[^"\\]|\\.)*)"'
_CLASSIC = re.compile(r'^\[(\d+)\]=\{' + _STRING + r',(?:nil|"(?:[^"\\]|\\.)*"),"(\w*)",(\d+),[-0-9.]+,[-0-9.]+,'
                      r'\{([0-9,]*)\}', re.M)
_VERIFIED = re.compile(r'^\s*\[(.+?)\] = \{ ' + _STRING + r', (\d+|nil), [^,]+, [^,]+, [^,]+, \{(.*)\}, '
                       r'([^,]*), \{([^{}]*)\} \},?\s*$')
_OFFER = re.compile(r'\[(\d+)\] = \{ ([^{}]*) \}')
_HOLIDAY = re.compile(r'^\[(\d+)\]=', re.M)


@dataclass
class ClassicVendor:
    name: str
    faction: str             # A, H o AH
    area_id: int
    items: list[int]


@dataclass
class VerifiedVendor:
    name: str
    map_id: int | None
    stock: dict[int, tuple[int | None, bool, bool]]   # objeto -> (precio, con divisa, limitado)
    seed: str | None          # el PNJ del Classic cuando su número cambió en Forever
    not_seen: set[int] = field(default_factory=set)   # del Classic, pero no estaba en la tienda


def _block(text: str, name: str) -> str:
    start = text.find(f"MM.{name} = {{")
    if start < 0:
        return ""
    end = text.find("\n}", start)
    return text[start:end if end >= 0 else len(text)]


def _unquote(value: str) -> str:
    return re.sub(r'\\(.)', r'\1', value)


def _fields(text: str) -> list[str]:
    """'0, "30 |T1:0|t", true' -> ['0', '"30 |T1:0|t"', 'true'] (sin partir las cadenas)."""
    return [f.strip() for f in re.findall(r'"(?:[^"\\]|\\.)*"|[^,]+', text)]


def parse_classic(text: str) -> tuple[dict[int, ClassicVendor], set[int]]:
    """VendorData.lua: {PNJ: vendedor} y los PNJ de fiestas (solo salen unos días al año)."""
    vendors = {}
    for m in _CLASSIC.finditer(_block(text, "knownVendors")):
        vendors[int(m[1])] = ClassicVendor(name=_unquote(m[2]), faction=m[3], area_id=int(m[4]),
                                           items=[int(x) for x in m[5].split(",") if x])
    holidays = {int(m[1]) for m in _HOLIDAY.finditer(_block(text, "holidaySpots"))}
    return vendors, holidays


def parse_verified(text: str) -> dict[str, VerifiedVendor]:
    vendors = {}
    for line in _block(text, "shippedVendors").splitlines():
        m = _VERIFIED.match(line)
        if not m:
            continue
        stock = {}
        for offer in _OFFER.finditer(m[4]):
            parts = _fields(offer[2])
            price = int(parts[0]) if parts and parts[0].isdigit() else None
            currency = (len(parts) > 1 and parts[1] != "nil") or (len(parts) > 3 and parts[3] == "true")
            limited = len(parts) > 2 and parts[2] == "true"
            stock[int(offer[1])] = (None if currency or not price else price, currency, limited)
        seed = m[5].strip().strip('"')
        vendors[m[1].strip().strip('"')] = VerifiedVendor(
            name=_unquote(m[2]), map_id=None if m[3] == "nil" else int(m[3]), stock=stock,
            seed=None if seed in ("", "nil") else seed,
            not_seen={int(x) for x in re.findall(r'\d+', m[6])})
    return vendors


def _classic_id(key: str) -> int | None:
    """'1234' o '1234@1497' (vendedor de fiesta en una zona) -> 1234."""
    m = re.match(r'(\d+)(@\d+)?$', key)
    return int(m[1]) if m else None


def build_offers(classic: dict[int, ClassicVendor], verified: dict[str, VerifiedVendor],
                 holidays: set[int]) -> list[tuple]:
    """Filas de mm_vendor_items. Lo comprobado manda sobre la lista del Classic de ese PNJ."""
    rows = []
    covered = set()
    for key, v in verified.items():
        base = _classic_id(v.seed or key)
        c = classic.get(base) if base is not None else None
        if c is not None:
            covered.add(base)
        holiday = "@" in (v.seed or key) or base in holidays
        faction = c.faction if c is not None else None
        for item_id, (price, currency, limited) in v.stock.items():
            rows.append((item_id, key, v.name, faction, c.area_id if c else None, v.map_id, price,
                         int(limited), int(currency), 1, int(holiday)))
        for item_id in (c.items if c is not None else []):
            if item_id not in v.stock and item_id not in v.not_seen:
                rows.append((item_id, key, v.name, faction, c.area_id, v.map_id, None, 0, 0, 0, int(holiday)))
    for npc, c in classic.items():
        if npc not in covered:
            for item_id in c.items:
                rows.append((item_id, str(npc), c.name, c.faction, c.area_id, None, None, 0, 0, 0,
                             int(npc in holidays)))
    return rows


def import_files(conn: sqlite3.Connection, folder: Path) -> int:
    classic, holidays = parse_classic((folder / "VendorData.lua").read_text(encoding="utf-8"))
    verified = parse_verified((folder / "VerifiedData.lua").read_text(encoding="utf-8"))
    if not classic:  # el formato ha cambiado: mejor quedarse con lo que había
        raise ValueError("no entiendo VendorData.lua de Merchant Map")
    rows = build_offers(classic, verified, holidays)
    with conn:
        conn.execute("DELETE FROM mm_vendor_items")
        conn.executemany("INSERT INTO mm_vendor_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        set_meta(conn, "merchant_map_updated", str(int(time.time())))
    return len({r[0] for r in rows})


def update_merchant_map(conn: sqlite3.Connection, cache_dir: Path, force: bool = False,
                        max_age_days: float = REFRESH_DAYS) -> int | None:
    """Baja e importa los datos si tienen más de max_age_days. Objetos que vende algún PNJ, o None
    si ya estaban al día."""
    age = time.time() - int(get_meta(conn, "merchant_map_updated") or 0)
    if not force and age < max_age_days * 86400:
        return None
    folder = cache_dir / "merchantmap"
    folder.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = folder / name
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(_get(f"{SOURCE}/{name}"))
        tmp.replace(target)
    return import_files(conn, folder)


# Consulta ------------------------------------------------------------------------------

@dataclass
class KnownVendor:
    """El mejor vendedor de un objeto según Merchant Map, para tus facciones."""
    vendor: str
    zone: str | None
    price: int | None        # por unidad; None si se paga con divisa o no hay precio
    limited: bool
    currency: bool
    verified: bool           # comprobado en Forever; si no, sale de la lista del Classic
    vendors: int = 1         # cuántos PNJ lo venden

    @property
    def where(self) -> str:
        return self.vendor + (f" ({self.zone})" if self.zone else "")


def has_data(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM mm_vendor_items LIMIT 1").fetchone() is not None


def sold_item_ids(conn: sqlite3.Connection) -> set[int]:
    """Objetos que algún vendedor vende por oro (para buscar reventas)."""
    return {r[0] for r in conn.execute("SELECT DISTINCT item_id FROM mm_vendor_items WHERE currency = 0 "
                                       "AND holiday = 0")}


def _sides(conn: sqlite3.Connection) -> set[str]:
    """Facciones de tus personajes: A, H o las dos si no hay ninguno."""
    found = {r[0] for r in conn.execute("SELECT DISTINCT faction FROM characters WHERE faction IS NOT NULL")}
    sides = {"A" for f in found if f == "Alliance"} | {"H" for f in found if f == "Horde"}
    return sides or {"A", "H"}


def offer_price(verified_price: int | None, catalog: int | None, stack: int = 1) -> int | None:
    """Precio por unidad. Merchant Map apunta lo que cuesta cada compra, que puede ser un lote
    (los viales van de 5 en 5): stack es el lote según los datos del juego."""
    if verified_price is None:
        return round(catalog / stack) if catalog else None
    if catalog and abs(verified_price - catalog) <= catalog * PRICE_MATCH:
        verified_price = catalog
    return round(verified_price / stack)


def known_vendors(conn: sqlite3.Connection) -> dict[int, KnownVendor]:
    """El vendedor más útil de cada objeto: sin divisa, sin límite, comprobado y barato, por ese orden.
    Fuera los de fiestas y los de la otra facción."""
    sides = _sides(conn)
    # buy_price: lo que cobra un vendedor por vendor_stack unidades.
    catalog = {r[0]: (r[1] or None, max(r[2] or 1, 1)) for r in conn.execute(
        "SELECT item_id, buy_price, vendor_stack FROM gd_items WHERE item_id IN "
        "(SELECT item_id FROM mm_vendor_items)")}
    best: dict[int, tuple] = {}
    counts: dict[int, int] = {}
    rows = conn.execute(
        """SELECT v.item_id, v.vendor, v.faction, v.price, v.limited, v.currency, v.verified,
                  COALESCE(m.name, a.name) AS zone
           FROM mm_vendor_items v
           LEFT JOIN gd_maps m ON m.map_id = v.map_id
           LEFT JOIN gd_areas a ON a.area_id = v.area_id
           WHERE v.holiday = 0""")
    for r in rows:
        if r["faction"] and not sides & set(r["faction"]):
            continue
        item_id = r["item_id"]
        counts[item_id] = counts.get(item_id, 0) + 1
        price = None if r["currency"] else offer_price(r["price"], *catalog.get(item_id, (None, 1)))
        k = KnownVendor(vendor=r["vendor"], zone=r["zone"], price=price, limited=bool(r["limited"]),
                        currency=bool(r["currency"]), verified=bool(r["verified"]))
        rank = (k.currency, k.price is None, k.limited, not k.verified, k.price or 0)
        if item_id not in best or rank < best[item_id][0]:
            best[item_id] = (rank, k)
    result = {}
    for item_id, (_, k) in best.items():
        k.vendors = counts[item_id]
        result[item_id] = k
    return result
