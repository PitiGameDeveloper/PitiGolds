"""Cajones saqueados: cuál sale más barato llenar por cada punto de favor de mercader.

Cada cajón se llena con UNO de sus lotes (20 de polvo extraño, o 4 esencias mágicas superiores...).
Lo que cuesta un cajón lleno es el cajón más el lote más barato, y lo que importa es ese total
entre el favor que da. Solo cuentan los precios de la subasta, no los de vendedor. Qué pide cada
uno y el favor están en conocimiento/cajones.json; el addon hace las mismas cuentas en la subasta
con lo que ves en ella (Crates.lua).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .pricing import ItemPrice

CRATES_PATH = Path(__file__).resolve().parent.parent / "conocimiento" / "cajones.json"


@dataclass
class CrateOption:
    item_id: int
    quantity: int
    name: str = ""


@dataclass
class Crate:
    item_id: int
    name: str
    favor: int
    estimated: bool = False          # favor sin comprobar (el de artesano)
    options: list[CrateOption] = field(default_factory=list)


@dataclass
class CrateCost:
    crate: Crate
    crate_price: int | None
    option: CrateOption | None        # el lote más barato
    fill_cost: int | None
    # Todos los lotes con lo que cuestan (precio por cantidad), del más barato al más caro; sin precio, al final.
    options: list[tuple[CrateOption, int | None]] = field(default_factory=list)

    @property
    def total(self) -> int | None:
        if self.crate_price is None or self.fill_cost is None:
            return None
        return self.crate_price + self.fill_cost

    @property
    def per_favor(self) -> float | None:
        total = self.total
        return None if total is None else total / self.crate.favor


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_crates(path: Path = CRATES_PATH) -> list[Crate]:
    if not path.exists():
        return []
    crates = []
    for c in _read(path).get("cajones", []):
        crates.append(Crate(
            item_id=int(c["cajon"]), name=c.get("nombre", ""), favor=int(c["favor"]),
            estimated=bool(c.get("favor_estimado")),
            options=[CrateOption(int(o["objeto"]), int(o["cantidad"]), o.get("nombre", ""))
                     for o in c.get("opciones", [])],
        ))
    return crates


def crate_problems(conn: sqlite3.Connection | None = None, path: Path = CRATES_PATH) -> list[str]:
    """Lo que está mal en cajones.json. Con conn, comprueba también que los objetos existen."""
    if not path.exists():
        return []
    try:
        crates = load_crates(path)
    except (ValueError, KeyError, TypeError) as exc:
        return [f"{path.name}: no se puede leer ({exc})"]
    known = None
    if conn is not None:
        known = {r[0] for r in conn.execute("SELECT item_id FROM gd_items")} or None
    problems, seen = [], set()
    for c in crates:
        label = c.name or str(c.item_id)
        if c.item_id in seen:
            problems.append(f"{label}: cajón repetido")
        seen.add(c.item_id)
        if c.favor <= 0:
            problems.append(f"{label}: el favor tiene que ser mayor que 0")
        if not c.options:
            problems.append(f"{label}: no tiene lotes para llenarlo")
        ids = [c.item_id] + [o.item_id for o in c.options]
        for o in c.options:
            if o.quantity <= 0:
                problems.append(f"{label}: la cantidad de {o.name or o.item_id} tiene que ser mayor que 0")
        if known is not None:
            for item_id in ids:
                if item_id not in known:
                    problems.append(f"{label}: el objeto {item_id} no sale en los datos del juego")
    return problems


def crate_item_ids(crates: list[Crate]) -> set[int]:
    ids = set()
    for c in crates:
        ids.add(c.item_id)
        ids.update(o.item_id for o in c.options)
    return ids


def evaluate_crates(crates: list[Crate], prices: dict[int, ItemPrice]) -> list[CrateCost]:
    """Coste de cada cajón lleno con su lote más barato, de más barato a más caro por favor.
    Los que no tienen precio van al final."""
    result = []
    for c in crates:
        crate_price = prices[c.item_id].market if c.item_id in prices else None
        options = []
        for o in c.options:
            p = prices.get(o.item_id)
            unit = p.market if p is not None else None
            options.append((o, None if unit is None else unit * o.quantity))
        options.sort(key=lambda x: (x[1] is None, x[1] or 0, x[0].name))
        best, best_cost = options[0] if options and options[0][1] is not None else (None, None)
        result.append(CrateCost(c, crate_price, best, best_cost, options))
    result.sort(key=lambda r: (r.per_favor is None, r.per_favor or 0, r.crate.name))
    return result


def crates_export(crates: list[Crate]) -> dict[int, dict]:
    """Para Generated.lua: [cajón] = { name, favor, est (favor sin comprobar), opts = { {objeto, cantidad,
    nombre}, ... } }. Los nombres, por si el juego aún no tiene el objeto en la caché. Los precios de
    la subasta van en prices, como los del resto de objetos."""
    out = {}
    for c in crates:
        opts = [[o.item_id, o.quantity, o.name] for o in c.options]
        out[c.item_id] = {"name": c.name, "favor": c.favor, "est": c.estimated or None, "opts": opts}
    return out
