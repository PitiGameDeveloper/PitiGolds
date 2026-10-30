"""Junta precios, recetas e inventario en un solo análisis que usan el informe y el addon."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from .crafting import CraftResult, evaluate_recipes, recipe_item_ids
from .pricing import ItemPrice, load_prices
from .selling import SellAdvice, advise


@dataclass
class Analysis:
    prices: dict[int, ItemPrice]
    crafts: list[CraftResult]
    sales: list[SellAdvice]
    owned: dict[int, int] = field(default_factory=dict)
    last_scan: int | None = None

    def best_known_craft(self) -> dict[int, CraftResult]:
        """Para cada objeto que sabes fabricar, la receta conocida más barata."""
        best: dict[int, CraftResult] = {}
        for c in self.crafts:
            if c.known and c.complete and c.output_item_id:
                current = best.get(c.output_item_id)
                if current is None or c.cost / c.output_qty < current.cost / current.output_qty:
                    best[c.output_item_id] = c
        return best


def owned_items(conn: sqlite3.Connection) -> dict[int, int]:
    """Todo lo que tienes, ligado o no, menos lo que ya está en la subasta."""
    owned: dict[int, int] = defaultdict(int)
    for r in conn.execute("SELECT item_id, SUM(count) AS n FROM inventory WHERE location != 'auctions' "
                          "GROUP BY item_id"):
        owned[r["item_id"]] = r["n"]
    return dict(owned)


def analyze(conn: sqlite3.Connection) -> Analysis:
    owned = owned_items(conn)
    ids = set(owned) | recipe_item_ids(conn)
    prices = load_prices(conn, ids)
    crafts = evaluate_recipes(conn, prices, owned)
    sales = advise(conn, prices, crafts)
    last_scan = conn.execute("SELECT MAX(time) FROM scans").fetchone()[0]
    return Analysis(prices=prices, crafts=crafts, sales=sales, owned=owned, last_scan=last_scan)
