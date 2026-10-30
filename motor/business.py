"""Tu negocio en la subasta: lo que compras, fabricas, revendes y vendes, y cuánto te deja de
verdad por cada hora de gestión (con la subasta, la profesión o el correo abiertos).

Coste de lo vendido:
  - fabricado: los materiales de la receta a lo que te costaron a ti (media de tus compras)
    o, si no los compraste, a precio de mercado de hoy;
  - revendido (comprado y vuelto a vender sin fabricar): la media de lo que pagaste.
Depósitos perdidos: los pagados al poner a la venta menos los devueltos al venderse.
Las ventas de lo que has farmeado no cuentan aquí como negocio: ya están en «Tus farmeos».

También calcula la capacidad de cada crafteo rentable: un farmeo lo limita tu tiempo, pero un
crafteo lo limita el mercado. Si se venden 12 al día y te puedes llevar un 30 % sin hundir el
precio, da igual que puedas fabricar 200.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field

from .crafting import CraftResult
from .pricing import ItemPrice

DAY = 86400
HISTORY_DAYS = 14
MARKET_SHARE = 0.3          # parte de las ventas diarias que te puedes llevar sin hundir el precio
SECONDS_PER_UNIT = 10       # fabricar y poner a la venta una unidad, hasta tener medidas tuyas
MIN_UNITS_TO_MEASURE = 20


@dataclass
class ItemBusiness:
    item_id: int | None
    name: str
    bought: int = 0
    spent: int = 0
    crafted: float = 0.0
    posted: int = 0
    deposits_paid: int = 0
    sold: int = 0
    gross: int = 0
    cut: int = 0
    deposits_back: int = 0
    unit_cost: int | None = None
    actions: int = 0
    seconds: float = 0.0

    @property
    def origin(self) -> str:
        if self.crafted:
            return "fabricado"
        if self.bought:
            return "reventa" if self.sold else "material"
        return "farmeado"

    @property
    def net_revenue(self) -> int:
        return self.gross - self.cut

    @property
    def deposits_lost(self) -> int:
        return max(0, self.deposits_paid - self.deposits_back)

    @property
    def avg_sale(self) -> int | None:
        return round(self.gross / self.sold) if self.sold else None

    @property
    def profit(self) -> int | None:
        if self.unit_cost is None:
            return None
        return self.net_revenue - round(self.sold * self.unit_cost) - self.deposits_lost

    @property
    def per_hour(self) -> int | None:
        if self.profit is None or not self.seconds:
            return None
        return round(self.profit / (self.seconds / 3600))


@dataclass
class Business:
    items: list[ItemBusiness] = field(default_factory=list)
    seconds: float = 0.0
    seconds_per_unit: float | None = None   # medido con tus crafteos, si hay suficientes

    @property
    def trading(self) -> list[ItemBusiness]:
        return [i for i in self.items if i.origin in ("fabricado", "reventa")]

    @property
    def profit(self) -> int:
        return sum(i.profit for i in self.trading if i.profit is not None)

    @property
    def farmed_sales(self) -> int:
        return sum(i.net_revenue for i in self.items if i.origin == "farmeado")

    @property
    def hours(self) -> float:
        return self.seconds / 3600

    @property
    def trading_hours(self) -> float:
        return sum(i.seconds for i in self.trading) / 3600

    @property
    def per_hour(self) -> int | None:
        hours = self.trading_hours
        return round(self.profit / hours) if hours else None


def _item_names(conn: sqlite3.Connection) -> tuple[dict[str, int], dict[int, str]]:
    """Nombre -> objeto (las ventas por correo solo traen el nombre) y objeto -> nombre."""
    by_name: dict[str, int] = {}
    by_id: dict[int, str] = {}
    for table in ("gd_items", "items"):  # lo visto en partida manda
        for r in conn.execute(f"SELECT item_id, name FROM {table} WHERE name IS NOT NULL"):
            by_name[r["name"].lower()] = r["item_id"]
            by_id[r["item_id"]] = r["name"]
    return by_name, by_id


def compute_business(conn: sqlite3.Connection, prices: dict[int, ItemPrice], crafts: list[CraftResult],
                     days: float = HISTORY_DAYS) -> Business:
    newest = conn.execute("SELECT MAX(t) FROM ledger").fetchone()[0]
    if not newest:
        return Business()
    names, id_names = _item_names(conn)
    entries: dict[object, ItemBusiness] = {}
    recipes_used: dict[object, Counter] = {}
    business = Business()

    def entry(item_id: int | None, name: str | None) -> ItemBusiness:
        key = item_id if item_id is not None else ("nombre", name)
        if key not in entries:
            p = prices.get(item_id) if item_id is not None else None
            known = (p.name if p and not p.name.startswith("objeto ") else None) or id_names.get(item_id)
            entries[key] = ItemBusiness(item_id=item_id, name=known or name or "?")
        return entries[key]

    for r in conn.execute("SELECT * FROM ledger WHERE t >= ? ORDER BY t", (newest - days * DAY,)):
        kind = r["type"]
        if kind == "time":
            business.seconds += r["seconds"] or 0
            continue
        item_id = r["item_id"] or names.get((r["item_name"] or "").lower())
        e = entry(item_id, r["item_name"])
        qty = r["quantity"] or 1
        e.actions += 1
        if kind == "buy":
            e.bought += qty
            e.spent += r["money"] or 0
        elif kind == "post":
            e.posted += qty
            e.deposits_paid += r["deposit"] or 0
        elif kind == "sale":
            e.sold += qty
            e.gross += r["money"] or 0
            e.cut += r["cut"] or 0
            e.deposits_back += r["deposit"] or 0
        elif kind == "craft":
            e.crafted += qty
            recipes_used.setdefault(id(e), Counter())[r["recipe_id"]] += 1

    # Lo que te costó a ti cada material, si lo compraste.
    paid = {e.item_id: e.spent / e.bought for e in entries.values() if e.item_id is not None and e.bought}
    by_recipe = {c.recipe_id: c for c in crafts}
    for e in entries.values():
        if e.crafted:
            recipe = by_recipe.get(recipes_used[id(e)].most_common(1)[0][0])
            if recipe is not None:
                costs = [(r.quantity, paid.get(r.item_id, r.unit_cost))
                         for r in recipe.reagents if r.item_id is not None]
                if all(cost is not None for _, cost in costs):
                    e.unit_cost = round(sum(q * c for q, c in costs) / recipe.output_qty)
        elif e.bought:
            e.unit_cost = round(e.spent / e.bought)

    # El tiempo de gestión se reparte según cuántas cosas has hecho con cada objeto. Comprar
    # materiales es parte de fabricar: ese tiempo va a lo fabricado, según las unidades.
    total_actions = sum(e.actions for e in entries.values())
    crafted_total = sum(e.crafted for e in entries.values())
    material_actions = sum(e.actions for e in entries.values() if e.origin == "material")
    for e in entries.values():
        actions = e.actions
        if e.origin == "material" and crafted_total:
            actions = 0
        elif e.crafted and crafted_total:
            actions += material_actions * e.crafted / crafted_total
        e.seconds = business.seconds * actions / total_actions if total_actions else 0
    crafted_units = sum(e.crafted for e in entries.values())
    if crafted_units >= MIN_UNITS_TO_MEASURE:
        business.seconds_per_unit = sum(e.seconds for e in entries.values() if e.crafted) / crafted_units

    business.items = sorted(entries.values(), key=lambda e: (e.profit is None, -(e.profit or 0)))
    return business


@dataclass
class Capacity:
    units_per_day: float
    gold_per_day: int
    minutes_per_day: float
    gold_per_hour: int


def craft_capacity(craft: CraftResult, seconds_per_unit: float | None = None) -> Capacity | None:
    """Lo máximo que da al día un crafteo rentable según lo que se vende, y el tiempo que lleva."""
    s = craft.output_signals
    if not craft.complete or craft.profit <= 0 or s is None or not s.sales_per_day:
        return None
    seconds = seconds_per_unit or SECONDS_PER_UNIT
    per_unit = craft.profit / craft.output_qty
    units = s.sales_per_day * MARKET_SHARE
    return Capacity(units_per_day=units, gold_per_day=round(per_unit * units),
                    minutes_per_day=units * seconds / 60, gold_per_hour=round(per_unit * 3600 / seconds))
