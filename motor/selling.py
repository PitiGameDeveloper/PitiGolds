"""Qué hacer con lo que tienes: subastarlo, vendérselo al vendedor, esperar o guardarlo."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from .crafting import CraftResult
from .money import format_money, format_pct
from .pricing import AH_CUT, ItemPrice

DROP_TO_WAIT = -0.20   # si está un 20 % por debajo de su mediana, mejor esperar

LOCATION_NAMES = {
    "bags": "bolsas", "bank": "banco", "mail": "correo",
    "mail_incoming": "correo en camino", "warband": "banda",
}


@dataclass
class SellAdvice:
    item_id: int
    name: str
    count: int
    places: str
    action: str                 # subastar, vendedor, esperar, guardar, sin precio
    unit_price: int | None      # precio al que ponerlo (o el del vendedor)
    total: int | None           # lo que cobrarías por todo, ya sin comisión
    reason: str = ""


def sellable_inventory(conn: sqlite3.Connection) -> dict[int, list[tuple[str, str, int]]]:
    """Objetos no ligados que tienes, con dónde están: {item: [(personaje, sitio, cantidad)]}."""
    stock: dict[int, list[tuple[str, str, int]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT char_key, location, item_id, SUM(count) AS n FROM inventory "
        "WHERE bound = 0 AND location != 'auctions' GROUP BY char_key, location, item_id"
    ):
        stock[r["item_id"]].append((r["char_key"], r["location"], r["n"]))
    return stock


def _places(entries: list[tuple[str, str, int]]) -> str:
    by_char: dict[str, list[str]] = defaultdict(list)
    for char, location, n in entries:
        who = "banda" if char == "_warband" else char
        if char == "_warband":
            by_char[who].append(str(n))
        else:
            by_char[who].append(f"{LOCATION_NAMES.get(location, location)} {n}")
    return "; ".join(f"{who}: {', '.join(parts)}" for who, parts in by_char.items())


def advise(conn: sqlite3.Connection, prices: dict[int, ItemPrice],
           crafts: list[CraftResult]) -> list[SellAdvice]:
    # Materiales de recetas que conoces y que dan beneficio: mejor no venderlos.
    keep_for: dict[int, CraftResult] = {}
    for craft in crafts:
        if craft.known and craft.complete and craft.profit > 0:
            for r in craft.reagents:
                if r.item_id is not None:
                    current = keep_for.get(r.item_id)
                    if current is None or craft.profit > current.profit:
                        keep_for[r.item_id] = craft

    advice = []
    for item_id, entries in sellable_inventory(conn).items():
        count = sum(n for _, _, n in entries)
        p = prices.get(item_id) or ItemPrice(item_id=item_id, name=f"objeto {item_id}")
        a = SellAdvice(item_id=item_id, name=p.name, count=count, places=_places(entries),
                       action="sin precio", unit_price=None, total=None)

        craft = keep_for.get(item_id)
        if craft is not None:
            a.action = "guardar"
            a.unit_price = p.sale_price
            a.total = p.net_sale * count if p.net_sale else None
            a.reason = f"material de {craft.name} (+{format_money(craft.profit)} por fabricación)"
        elif p.vendor_sell and (p.net_sale is None or p.net_sale <= p.vendor_sell):
            a.action = "vendedor"
            a.unit_price = p.vendor_sell
            a.total = p.vendor_sell * count
            a.reason = "el vendedor paga más que la subasta" if p.net_sale else "no está en la subasta"
        elif p.market is None:
            a.reason = "no hay precio de subasta todavía"
        elif p.deviation is not None and p.deviation <= DROP_TO_WAIT:
            a.action = "esperar"
            a.unit_price = p.median
            a.total = round(p.median * (1 - AH_CUT)) * count
            a.reason = f"está un {format_pct(abs(p.deviation))} por debajo de su mediana de 7 días"
        else:
            a.action = "subastar"
            floor = (p.vendor_sell or 0) + 1
            a.unit_price = max((p.min_price or p.market) - 1, floor)
            a.total = round(a.unit_price * (1 - AH_CUT)) * count
            if p.quantity is not None and count > p.quantity:
                a.reason = f"tienes más que todo lo que hay a la venta ({p.quantity}); súbelo poco a poco"
            elif p.deviation is not None and p.deviation >= 0.2:
                a.reason = f"está un {format_pct(p.deviation)} por encima de su mediana: buen momento"
        advice.append(a)

    order = {"subastar": 0, "esperar": 1, "vendedor": 2, "guardar": 3, "sin precio": 4}
    advice.sort(key=lambda a: (order[a.action], -(a.total or 0)))
    return advice
