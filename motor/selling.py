"""Qué hacer con lo que tienes: subastarlo, vendérselo al vendedor, esperar o guardarlo.

Y, si es para subastar, a qué ritmo: si se venden 10 al día en toda la subasta y tienes 100,
ponerlos todos de golpe hunde el precio. Se supone que te puedes llevar un 30 % de las ventas
diarias sin hundirlo, y con la previsión de precio se calcula cuánto sacarías de media mientras
lo vendes todo.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from .business import MARKET_SHARE
from .crafting import CraftResult
from .market import forecast_price
from .money import format_money, format_pct
from .pricing import AH_CUT, ItemPrice

DROP_TO_WAIT = -0.20   # si está un 20 % por debajo de su mediana, mejor esperar
SLOW_DAYS = 1.5        # a partir de aquí se avisa del ritmo de venta
TOO_SLOW_DAYS = 14     # lo que no se coloca en dos semanas quizá sea mejor para el vendedor
MANY_SELLERS = 5
MAX_PLAN_DAYS = 60

LOCATION_NAMES = {
    "bags": "bolsas", "bank": "banco", "mail": "correo",
    "mail_incoming": "correo en camino", "warband": "banda",
}


@dataclass
class SellPlan:
    per_day: int | None = None       # cuántas poner cada día
    days: float | None = None        # días para colocarlo todo a ese ritmo
    avg_price: int | None = None     # precio medio esperado mientras lo vendes (antes de comisión)
    notes: list[str] = field(default_factory=list)


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
    plan: SellPlan = field(default_factory=SellPlan)

    @property
    def pace(self) -> str:
        if self.plan.per_day is None:
            return ""
        return f"{self.plan.per_day}/día · ~{max(1, round(self.plan.days))} días"


def sell_plan(count: int, p: ItemPrice, sig) -> SellPlan:
    """Cuántas poner al día, en cuánto se vende todo y a qué precio medio."""
    plan = SellPlan()
    if sig is None or not sig.sales_per_day:
        if p.quantity is not None and count > p.quantity:
            plan.notes.append(f"tienes más que todo lo que hay a la venta ({p.quantity}) y aún no se sabe cuánto "
                              "se vende al día: súbelo poco a poco")
        return plan
    rate = sig.sales_per_day * MARKET_SHARE
    plan.per_day = max(1, math.floor(rate))
    plan.days = count / rate
    remaining, total, day = float(count), 0.0, 0
    while remaining > 0 and day < MAX_PLAN_DAYS:
        sold = min(rate, remaining)
        total += sold * (forecast_price(sig, day) or sig.current)
        remaining -= sold
        day += 1
    total += remaining * (forecast_price(sig, MAX_PLAN_DAYS) or sig.current)
    plan.avg_price = round(total / count)
    if plan.days > SLOW_DAYS:
        plan.notes.append(f"se venden unas {sig.sales_per_day:.0f} al día en toda la subasta: pon unas "
                          f"{plan.per_day} al día y no todo de golpe (tardarías unos {plan.days:.0f} días)")
        if plan.avg_price < sig.current * 0.95:
            drop = 1 - plan.avg_price / sig.current
            plan.notes.append(f"con la tendencia actual sacarías de media {format_money(plan.avg_price)} por unidad, "
                              f"un {format_pct(drop)} menos que hoy")
        if sig.owners and sig.owners >= MANY_SELLERS:
            plan.notes.append(f"hay {sig.owners} vendedores: te rebajarán el precio a menudo, revisa tus subastas "
                              "cada día")
    return plan


def sellable_inventory(conn: sqlite3.Connection) -> dict[int, list[tuple[str, str, int]]]:
    """Objetos no ligados que tienes, con dónde están: {item: [(personaje, sitio, cantidad)]}."""
    stock: dict[int, list[tuple[str, str, int]]] = defaultdict(list)
    for r in conn.execute(
        "SELECT char_key, location, item_id, SUM(count) AS n FROM inventory "
        "WHERE bound = 0 AND location != 'auctions' GROUP BY char_key, location, item_id"
    ):
        stock[r["item_id"]].append((r["char_key"], r["location"], r["n"]))
    return stock


def _why(sig) -> str:
    return "; ".join(sig.reasons[:2]) or f"previsión a 7 días: {format_money(sig.forecast_7d)}"


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
           crafts: list[CraftResult], signals: dict | None = None) -> list[SellAdvice]:
    signals = signals or {}
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

        sig = signals.get(item_id)
        trusted = sig is not None and sig.confidence != "baja"
        falling = trusted and sig.outlook == "baja"
        rising = trusted and sig.outlook == "sube"

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
        elif p.deviation is not None and p.deviation <= DROP_TO_WAIT and not falling:
            # Barato respecto a su mediana y sin tendencia de bajada: lo normal es que se recupere.
            a.action = "esperar"
            a.unit_price = p.median
            a.total = round(p.median * (1 - AH_CUT)) * count
            a.reason = f"está un {format_pct(abs(p.deviation))} por debajo de su mediana de 7 días"
        elif rising and sig.forecast_7d and sig.forecast_7d > p.market:
            a.action = "esperar"
            a.unit_price = sig.forecast_7d
            a.total = round(sig.forecast_7d * (1 - AH_CUT)) * count
            a.reason = "está subiendo: " + _why(sig)
        else:
            a.action = "subastar"
            floor = (p.vendor_sell or 0) + 1
            a.unit_price = max((p.min_price or p.market) - 1, floor)
            a.plan = plan = sell_plan(count, p, sig)
            expected = min(a.unit_price, plan.avg_price) if plan.avg_price else a.unit_price
            a.total = round(expected * (1 - AH_CUT)) * count
            notes = []
            if falling:
                slow = plan.days is not None and plan.days > SLOW_DAYS
                notes.append(f"tiende a bajar ({_why(sig)}): " + ("empieza a venderlo ya" if slow else "mejor vender ya"))
            notes += plan.notes
            if plan.days is not None and plan.days > TOO_SLOW_DAYS and p.vendor_sell:
                leftover = count - round(sig.sales_per_day * MARKET_SHARE * TOO_SLOW_DAYS)
                notes.append(f"lo que no vayas a vender en dos semanas (unas {leftover}) quizá compense "
                             f"vendérselo al vendedor a {format_money(p.vendor_sell)}")
            if p.deviation is not None and p.deviation >= 0.2 and not falling:
                notes.append(f"está un {format_pct(p.deviation)} por encima de su mediana: buen momento")
            a.reason = "; ".join(notes)
        advice.append(a)

    order = {"subastar": 0, "esperar": 1, "vendedor": 2, "guardar": 3, "sin precio": 4}
    advice.sort(key=lambda a: (order[a.action], -(a.total or 0)))
    return advice
