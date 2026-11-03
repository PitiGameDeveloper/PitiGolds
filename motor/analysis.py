"""Junta precios, recetas, mercado e inventario en un solo análisis que usan el informe y el addon."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from .business import Business, compute_business, craft_capacity
from .catalogo import CatalogEntry, CatalogError, GuideMethod, evaluate_catalog, load_catalog, resolve_items
from .crafting import CraftResult, evaluate_recipes, recipe_item_ids
from .farming import FarmSession, FarmSummary, farm_item_ids, load_sessions, summarize, value_sessions
from .market import Backtest, MarketSignals, backtest, compute_signals, load_series
from .merchantmap import sold_item_ids
from .pricing import ItemPrice, load_prices
from .selling import SellAdvice, advise
from .vendors import VendorCandidate, VendorFlip, vendor_candidates, vendor_flips


@dataclass
class Analysis:
    prices: dict[int, ItemPrice]
    crafts: list[CraftResult]
    sales: list[SellAdvice]
    owned: dict[int, int] = field(default_factory=dict)
    signals: dict[int, MarketSignals] = field(default_factory=dict)
    accuracy: Backtest = field(default_factory=Backtest)
    farms: list[FarmSession] = field(default_factory=list)
    farm_summary: list[FarmSummary] = field(default_factory=list)
    business: Business = field(default_factory=Business)
    vendor_flips: list[VendorFlip] = field(default_factory=list)
    vendor_candidates: list[VendorCandidate] = field(default_factory=list)
    guide_methods: list[GuideMethod] = field(default_factory=list)
    guide_unknown_items: list[str] = field(default_factory=list)   # objetos de las guías sin reconocer
    guide_resolved: dict[str, int] = field(default_factory=dict)   # nombre en las guías -> objeto
    catalog_error: str | None = None   # el catálogo de métodos no se ha podido leer
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

    def relevant_items(self) -> set[int]:
        """Lo que tienes, lo que farmeas y lo que entra o sale de las recetas que sabes hacer."""
        ids = set(self.owned)
        for s in self.farms:
            ids.update(s.items)
        ids.update(e.item_id for e in self.business.items if e.item_id is not None)
        for c in self.crafts:
            if c.known:
                ids.update(r.item_id for r in c.reagents if r.item_id is not None)
                if c.output_item_id:
                    ids.add(c.output_item_id)
        return ids


def owned_items(conn: sqlite3.Connection) -> dict[int, int]:
    """Todo lo que tienes, ligado o no, menos lo que ya está en la subasta."""
    owned: dict[int, int] = defaultdict(int)
    for r in conn.execute("SELECT item_id, SUM(count) AS n FROM inventory WHERE location != 'auctions' "
                          "GROUP BY item_id"):
        owned[r["item_id"]] = r["n"]
    return dict(owned)


def analyze(conn: sqlite3.Connection, catalog: list[CatalogEntry] | None = None) -> Analysis:
    """catalog: los métodos de tus guías; sin él se lee conocimiento/metodos.json."""
    catalog_error = None
    if catalog is None:
        try:
            catalog = load_catalog()
        except CatalogError as exc:  # un catálogo roto no debe dejarte sin informe
            catalog, catalog_error = [], str(exc)
    resolved, unknown = resolve_items(conn, catalog)
    owned = owned_items(conn)
    ledger_ids = {r[0] for r in conn.execute("SELECT DISTINCT item_id FROM ledger WHERE item_id IS NOT NULL")}
    vendor_ids = {r[0] for r in conn.execute("SELECT item_id FROM vendor_items")}
    ids = (set(owned) | recipe_item_ids(conn) | farm_item_ids(conn) | ledger_ids | vendor_ids
           | sold_item_ids(conn) | set(resolved.values()))
    prices = load_prices(conn, ids)

    series, fulls = load_series(conn, ids)
    signals = {}
    for item_id, points in series.items():
        s = compute_signals(points, fulls)
        if s is not None:
            signals[item_id] = s

    crafts = evaluate_recipes(conn, prices, owned)
    business = compute_business(conn, prices, crafts)
    for c in crafts:
        s = c.output_signals = signals.get(c.output_item_id)
        c.capacity = craft_capacity(c, business.seconds_per_unit)
        out = prices.get(c.output_item_id)
        if c.complete and s is not None and s.forecast_7d and out is not None:
            c.profit_week = out.net_of(s.forecast_7d) * c.output_qty - c.cost
    sales = advise(conn, prices, crafts, signals)
    last_scan = conn.execute("SELECT MAX(time) FROM scans").fetchone()[0]
    result = Analysis(prices=prices, crafts=crafts, sales=sales, owned=owned, signals=signals,
                      business=business, last_scan=last_scan)
    result.farms = load_sessions(conn)
    value_sessions(conn, result.farms, prices, signals)
    result.farm_summary = summarize(result.farms)
    result.vendor_flips = vendor_flips(conn, prices, signals)
    result.vendor_candidates = vendor_candidates(conn, prices, crafts, result.farms)
    result.guide_methods = evaluate_catalog(conn, catalog, resolved, prices, signals, crafts, result.farm_summary)
    result.guide_unknown_items = unknown
    result.guide_resolved = resolved
    result.catalog_error = catalog_error
    relevant = result.relevant_items()
    result.accuracy = backtest({i: p for i, p in series.items() if i in relevant}, fulls)
    return result
