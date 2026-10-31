"""Precios: cuánto vale de verdad un objeto en la subasta.

El precio mínimo engaña: basta una sola unidad barata para hundirlo. Por eso se usa
el «precio de mercado»: lo que costaría de media comprar el 15 % más barato de las
unidades a la venta. Con varios escaneos se calcula además la mediana de 7 días, que
sirve para no valorar las cosas por un pico puntual y para saber si ahora está barato.

Lo que te queda de una venta descuenta la comisión y el depósito: en Forever cada puesta (una
pila) cuesta como mínimo 1 plata, que se devuelve si se vende y se pierde si no. Con tanta
competencia en los megaservidores se cuenta una puesta perdida por cada pila vendida, repartida
entre sus unidades: 5 cobre por unidad en una pila de 20, 1 plata entera en lo que no se apila.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

MARKET_SHARE = 0.15      # parte más barata de las unidades que forma el precio de mercado
HISTORY_DAYS = 7
MIN_HISTORY_SCANS = 3    # escaneos necesarios para fiarse de la mediana
SPIKE_CAP = 1.25         # nunca se valora por encima de la mediana + 25 %
AH_CUT = 0.05            # comisión de la casa de subastas
AH_DEPOSIT = 100         # depósito mínimo por puesta (por pila), en cobre
LOST_POSTS_PER_SALE = 1  # puestas que no se venden por cada pila vendida


def parse_book(book: str | None) -> list[tuple[int, int]]:
    """'40:15;45:20' -> [(40, 15), (45, 20)]"""
    if not book:
        return []
    levels = []
    for level in book.split(";"):
        price, _, qty = level.partition(":")
        levels.append((int(float(price)), int(qty)))
    return levels


def market_price(min_price: int, quantity: int, book: str | None) -> int:
    levels = parse_book(book)
    if not levels or quantity <= 0:
        return min_price
    target = max(1, math.ceil(quantity * MARKET_SHARE))
    taken = cost = 0
    for price, qty in levels:
        take = min(qty, target - taken)
        cost += take * price
        taken += take
        if taken >= target:
            break
    return round(cost / taken)


@dataclass
class ItemPrice:
    item_id: int
    name: str
    min_price: int | None = None
    market: int | None = None
    quantity: int | None = None
    auctions: int | None = None
    owners: int | None = None
    seen: int | None = None          # hora del último escaneo en el que apareció
    median: int | None = None        # mediana del precio de mercado en 7 días
    history_scans: int = 0
    vendor_buy: int | None = None    # lo que cuesta comprárselo a un vendedor (visto en el juego)
    vendor_limited: bool = False
    vendor_sell: int | None = None   # lo que paga un vendedor
    stack_size: int = 1              # unidades por pila (lo que va en cada puesta)
    # Precio de vendedor según los datos del juego. No dice si algún vendedor lo vende, así
    # que no se usa para costes: solo como pista cuando falta un precio.
    catalog_buy: int | None = None

    @property
    def has_history(self) -> bool:
        return self.median is not None and self.history_scans >= MIN_HISTORY_SCANS

    @property
    def deviation(self) -> float | None:
        """Cuánto se aparta el precio actual de la mediana (+0.3 = un 30 % más caro)."""
        if not self.has_history or not self.median or self.market is None:
            return None
        return self.market / self.median - 1

    @property
    def sale_price(self) -> int | None:
        """Precio por unidad al que es razonable vender en la subasta, antes de la comisión."""
        if self.market is None:
            return None
        if self.has_history:
            return min(self.market, round(self.median * SPIKE_CAP))
        return self.market

    @property
    def deposit_per_unit(self) -> float:
        """Depósito perdido por unidad vendida en la subasta."""
        return AH_DEPOSIT * LOST_POSTS_PER_SALE / max(self.stack_size or 1, 1)

    def net_of(self, price: float) -> int:
        """Lo que te queda por unidad vendiéndola a `price`: sin comisión ni depósito perdido."""
        return max(0, round(price * (1 - AH_CUT) - self.deposit_per_unit))

    @property
    def net_sale(self) -> int | None:
        sale = self.sale_price
        return None if sale is None else self.net_of(sale)

    @property
    def buy_price(self) -> int | None:
        """Lo que cuesta conseguir una unidad: en la subasta o a un vendedor sin límite."""
        options = []
        if self.market is not None:
            options.append(self.market)
        if self.vendor_buy and not self.vendor_limited:
            options.append(self.vendor_buy)
        return min(options) if options else None

    @property
    def buy_source(self) -> str | None:
        price = self.buy_price
        if price is None:
            return None
        if self.vendor_buy == price and not self.vendor_limited:
            return "vendedor"
        return "subasta"


def load_prices(conn: sqlite3.Connection, item_ids: Iterable[int] | None = None) -> dict[int, ItemPrice]:
    """Precios de los objetos pedidos (o de todos los conocidos si no se pide ninguno)."""
    wanted = set(item_ids) if item_ids is not None else None

    def keep(item_id: int) -> bool:
        return wanted is None or item_id in wanted

    result: dict[int, ItemPrice] = {}

    def get(item_id: int) -> ItemPrice:
        if item_id not in result:
            result[item_id] = ItemPrice(item_id=item_id, name=f"objeto {item_id}")
        return result[item_id]

    # Primero los datos del juego y después lo visto en partida, que manda si existe.
    for row in conn.execute("SELECT item_id, name, buy_price, vendor_stack, sell_price, stackable FROM gd_items"):
        if keep(row["item_id"]):
            p = get(row["item_id"])
            if row["name"]:
                p.name = row["name"]
            p.vendor_sell = row["sell_price"] or None
            p.stack_size = row["stackable"] or 1
            if row["buy_price"]:
                p.catalog_buy = round(row["buy_price"] / max(row["vendor_stack"] or 1, 1))

    for row in conn.execute("SELECT item_id, name, sell_price FROM items"):
        if keep(row["item_id"]):
            p = get(row["item_id"])
            if row["name"]:
                p.name = row["name"]
            if row["sell_price"] is not None:
                p.vendor_sell = row["sell_price"]

    for row in conn.execute("SELECT item_id, price, limited FROM vendor_items WHERE price IS NOT NULL"):
        if keep(row["item_id"]):
            p = get(row["item_id"])
            p.vendor_buy = row["price"]
            p.vendor_limited = bool(row["limited"])

    for row in conn.execute("SELECT * FROM latest_prices"):
        if keep(row["item_id"]):
            p = get(row["item_id"])
            p.min_price = row["min_price"]
            p.market = row["market_price"] if row["market_price"] is not None else row["min_price"]
            p.quantity = row["quantity"]
            p.auctions = row["num_auctions"]
            p.owners = row["num_owners"]
            p.seen = row["time"]

    # La ventana de 7 días cuenta desde el último escaneo, no desde hoy: si dejas de
    # escanear una semana, la mediana sigue teniendo datos.
    reference = conn.execute("SELECT MAX(time) FROM scans").fetchone()[0]
    if reference:
        history: dict[int, list[int]] = defaultdict(list)
        rows = conn.execute(
            """SELECT p.item_id, COALESCE(p.market_price, p.min_price) AS price
               FROM prices p JOIN scans s ON s.scan_id = p.scan_id
               WHERE s.time >= ?""",
            (reference - HISTORY_DAYS * 86400,),
        )
        for row in rows:
            if keep(row["item_id"]):
                history[row["item_id"]].append(row["price"])
        for item_id, values in history.items():
            p = get(item_id)
            p.median = round(statistics.median(values))
            p.history_scans = len(values)

    if wanted is not None:
        for item_id in wanted:
            get(item_id)
    return result
