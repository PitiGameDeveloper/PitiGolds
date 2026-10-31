"""Vendedores: reventa de lo que venden por debajo de la subasta, y posibles chollos por comprobar.

Las tablas del juego dicen cuánto cobraría un vendedor por cada objeto, pero no si alguno lo
vende: eso solo se sabe al abrir su ventana o mirando fuera del juego (Wowhead...). Para no
comprobar todo el juego, solo son candidatos los objetos de crafteos y farmeos que dan dinero
que en la subasta (ya sin comisión) se pagan muy por encima de lo que costaría comprárselos a
un vendedor (no de lo que paga un vendedor si se lo vendes tú: eso lo usa selling.py).

Cuándo se vuelve a comprobar un candidato:
  - si nunca se ha mirado: ya;
  - si salió «no lo vende nadie»: a la semana, a las dos y a las cuatro; después, solo cuando
    salga una versión nueva del juego;
  - si es material de botín (tela, mineral, hierbas, cuero...) o lo has farmeado tú: tras el
    primer «nadie», solo con versiones nuevas (es casi seguro que no lo vende nadie);
  - si salió «lo vende»: con cada versión nueva, por si cambia.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .business import MARKET_SHARE
from .crafting import CraftResult
from .farming import FarmSession, TRADEGOODS
from .pricing import ItemPrice

DAY = 86400
MIN_GAP = 1.3                      # la subasta paga al menos un 30 % más de lo que costaría comprarlo al vendedor
MIN_GAIN = 5                       # y al menos 5 cobres por unidad
BACKOFF_DAYS = (7, 14, 28)
LOOT_SUBCLASSES = {5, 6, 7, 8, 9, 10, 12}  # tela, cuero, metal y piedra, carne, hierba, elemental, encantamiento


@dataclass
class VendorFlip:
    item_id: int
    name: str
    vendor: str
    buy: int
    sell: int              # lo que cobras en la subasta, ya sin comisión
    limited: bool
    sales_per_day: float | None = None
    sell_week: int | None = None   # lo que cobrarías con el precio previsto a 7 días

    @property
    def profit(self) -> int:
        return self.sell - self.buy

    @property
    def profit_week(self) -> int | None:
        return None if self.sell_week is None else self.sell_week - self.buy

    @property
    def gold_per_day(self) -> int | None:
        if not self.sales_per_day:
            return None
        return round(self.profit * self.sales_per_day * MARKET_SHARE)


def vendor_flips(conn: sqlite3.Connection, prices: dict[int, ItemPrice], signals: dict) -> list[VendorFlip]:
    """Lo que un vendedor que has visto vende por debajo de lo que pagan en la subasta."""
    flips = []
    for r in conn.execute("SELECT item_id, price, limited, vendor FROM vendor_items WHERE price > 0"):
        p = prices.get(r["item_id"])
        if p is None or not p.net_sale or p.net_sale < r["price"] * 1.1 or p.net_sale - r["price"] < MIN_GAIN:
            continue
        s = signals.get(r["item_id"])
        flips.append(VendorFlip(item_id=r["item_id"], name=p.name, vendor=r["vendor"] or "?", buy=r["price"],
                                sell=p.net_sale, limited=bool(r["limited"]),
                                sales_per_day=s.sales_per_day if s is not None else None,
                                sell_week=p.net_of(s.forecast_7d) if s is not None and s.forecast_7d
                                else None))
    return sorted(flips, key=lambda f: f.gold_per_day or f.profit, reverse=True)


@dataclass
class VendorCandidate:
    item_id: int
    name: str
    why: str
    catalog_buy: int
    sell: int
    loot: bool
    status: str = "sin comprobar"    # sin comprobar, nadie o vende
    detail: str | None = None
    checked_at: int | None = None
    due: bool = True
    next_check: str = "ya"

    @property
    def gain(self) -> int:
        return self.sell - self.catalog_buy


def _schedule(row: sqlite3.Row | None, loot: bool, build: str | None, now: float) -> tuple[bool, str]:
    """¿Toca comprobarlo? y cuándo, en texto."""
    if row is None:
        return True, "ya"
    new_version = build is not None and row["game_build"] != build
    if row["status"] == "vende" or loot or (row["misses"] or 0) > len(BACKOFF_DAYS):
        return new_version, "ya (versión nueva del juego)" if new_version else "con la próxima versión del juego"
    due_at = row["checked_at"] + BACKOFF_DAYS[(row["misses"] or 1) - 1] * DAY
    if now >= due_at or new_version:
        return True, "ya"
    return False, f"en {max(1, round((due_at - now) / DAY))} días"


def vendor_candidates(conn: sqlite3.Connection, prices: dict[int, ItemPrice], crafts: list[CraftResult],
                      farms: list[FarmSession], now: float | None = None) -> list[VendorCandidate]:
    now = now if now is not None else time.time()
    reasons: dict[int, str] = {}
    for c in crafts:
        if c.yours and c.complete and c.profit > 0:
            for r in c.reagents:
                if r.item_id is not None:
                    reasons.setdefault(r.item_id, f"material de {c.name}")
    farmed = set()
    for s in farms:
        if s.value_now > 0:
            for item_id in s.items:
                farmed.add(item_id)
                reasons.setdefault(item_id, f"lo farmeas en {s.zone}")

    classes = {r["item_id"]: (r["class_id"], r["subclass_id"]) for r in conn.execute(
        "SELECT item_id, class_id, subclass_id FROM gd_items")}
    checks = {r["item_id"]: r for r in conn.execute("SELECT * FROM vendor_checks")}
    build = conn.execute("SELECT value FROM meta WHERE key = 'game_data_build'").fetchone()
    build = build[0] if build else None

    result = []
    for item_id, why in reasons.items():
        p = prices.get(item_id)
        # Si ya lo has visto en un vendedor no hace falta mirarlo fuera.
        if p is None or p.vendor_buy or not p.catalog_buy or not p.net_sale:
            continue
        if p.net_sale < p.catalog_buy * MIN_GAP or p.net_sale - p.catalog_buy < MIN_GAIN:
            continue
        class_id, subclass = classes.get(item_id, (None, None))
        loot = item_id in farmed or (class_id == TRADEGOODS and subclass in LOOT_SUBCLASSES)
        c = VendorCandidate(item_id=item_id, name=p.name, why=why, catalog_buy=p.catalog_buy, sell=p.net_sale,
                            loot=loot)
        row = checks.get(item_id)
        if row is not None:
            c.status, c.detail, c.checked_at = row["status"], row["detail"], row["checked_at"]
        c.due, c.next_check = _schedule(row, loot, build, now)
        result.append(c)
    return sorted(result, key=lambda c: (not c.due, -c.gain))


def record_check(conn: sqlite3.Connection, item_id: int, sold: bool, detail: str | None = None,
                 now: float | None = None) -> None:
    """Apunta el resultado de mirar fuera del juego si algún vendedor vende el objeto."""
    now = int(now if now is not None else time.time())
    build = conn.execute("SELECT value FROM meta WHERE key = 'game_data_build'").fetchone()
    previous = conn.execute("SELECT status, misses FROM vendor_checks WHERE item_id = ?", (item_id,)).fetchone()
    misses = 0 if sold else ((previous["misses"] or 0) + 1 if previous and previous["status"] == "nadie" else 1)
    conn.execute("INSERT OR REPLACE INTO vendor_checks VALUES (?, ?, ?, ?, ?, ?)",
                 (item_id, "vende" if sold else "nadie", detail, now, misses, build[0] if build else None))
    conn.commit()
