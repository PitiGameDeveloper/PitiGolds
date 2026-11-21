"""Precios: cuánto vale de verdad un objeto en la subasta.

Todos los precios de la subasta salen de Auctionator: el addon copia su base de precios al salir
o con /reload (Auctionator.lua) y el motor la guarda como un escaneo por día (ingest.py). Cada día
vale el mínimo más alto que vio Auctionator ese día (una sola unidad barata de cebo no lo hunde) y
el último día de cada objeto, su último mínimo, que es el que enseña Auctionator.

Con varios días se calcula además la mediana de la última semana, que sirve para no valorar las
cosas por un pico puntual y para saber si ahora está barato.

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

from .merchantmap import KnownVendor, has_data, known_vendors

# De cuando PitiGolds escaneaba la subasta entera (book): media del 1 % más barato, mínimo 5 unidades.
MARKET_SHARE = 0.01
MARKET_MIN_UNITS = 5
MARKET_FORMULA = "1%-5"  # cambia si cambia la cuenta: los precios guardados se recalculan
HISTORY_DAYS = 7         # ventana de la mediana y de las señales: Auctionator da un precio por día
MIN_HISTORY_SCANS = 3    # días con precio necesarios para fiarse de la mediana
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
    target = max(MARKET_MIN_UNITS, math.ceil(quantity * MARKET_SHARE))
    taken = cost = 0
    for price, qty in levels:
        take = min(qty, target - taken)
        cost += take * price
        taken += take
        if taken >= target:
            break
    return round(cost / taken)


def refresh_market_prices(conn: sqlite3.Connection) -> None:
    """Recalcula el precio de mercado guardado si ha cambiado la cuenta (MARKET_FORMULA)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'market_formula'").fetchone()
    if row is not None and row[0] == MARKET_FORMULA:
        return
    rows = conn.execute(
        "SELECT scan_id, item_id, min_price, quantity, book FROM prices WHERE book IS NOT NULL AND book <> ''"
    ).fetchall()
    conn.executemany(
        "UPDATE prices SET market_price = ? WHERE scan_id = ? AND item_id = ?",
        [(market_price(r[2], r[3] or 0, r[4]), r[0], r[1]) for r in rows],
    )
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('market_formula', ?)", (MARKET_FORMULA,))
    conn.commit()


@dataclass
class ItemPrice:
    item_id: int
    name: str
    min_price: int | None = None
    market: int | None = None
    quantity: int | None = None
    auctions: int | None = None
    owners: int | None = None
    seen: int | None = None          # hora del último precio de Auctionator
    median: int | None = None        # mediana del precio en la última semana
    history_scans: int = 0
    vendor_buy: int | None = None    # lo que cuesta comprárselo a un vendedor (visto en el juego)
    vendor_limited: bool = False
    vendor_sell: int | None = None   # lo que paga un vendedor
    stack_size: int = 1              # unidades por pila (lo que va en cada puesta)
    # Precio de vendedor según los datos del juego. No dice si algún vendedor lo vende, así
    # que no se usa para costes: solo como pista cuando falta un precio.
    catalog_buy: int | None = None
    # Quién lo vende según Merchant Map (merchantmap.py). Con vendors_known, si no hay
    # known_vendor es que no lo vende nadie; sin datos de Merchant Map no se sabe.
    known_vendor: KnownVendor | None = None
    vendors_known: bool = False

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
    def shop_price(self) -> int | None:
        """Lo que cuesta a un vendedor sin límite: el que has visto o, si no, uno de Merchant Map."""
        if self.vendor_buy:
            return None if self.vendor_limited else self.vendor_buy
        k = self.known_vendor
        if k is not None and k.price and not k.limited and not k.currency:
            return k.price
        return None

    @property
    def buy_price(self) -> int | None:
        """Lo que cuesta conseguir una unidad: en la subasta. Solo si no está en la subasta, a un
        vendedor sin límite (aunque un vendedor lo tenga más barato, se compra en la subasta)."""
        return self.market if self.market is not None else self.shop_price

    @property
    def buy_source(self) -> str | None:
        if self.market is not None:
            return "subasta"
        return "vendedor" if self.shop_price else None


def load_prices(conn: sqlite3.Connection, item_ids: Iterable[int] | None = None) -> dict[int, ItemPrice]:
    """Precios de los objetos pedidos (o de todos los conocidos si no se pide ninguno)."""
    wanted = set(item_ids) if item_ids is not None else None
    refresh_market_prices(conn)

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

    # La ventana cuenta desde el último precio, no desde hoy: si dejas de
    # escanear unos días, la mediana sigue teniendo datos.
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

    if has_data(conn):
        known = known_vendors(conn)
        for item_id, p in result.items():
            p.vendors_known = True
            p.known_vendor = known.get(item_id)
    return result
