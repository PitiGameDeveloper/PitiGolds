"""Señales de mercado y previsión de precios a partir del historial de escaneos.

Todo es cálculo, sin IA. Para cada objeto se mira la última semana:
  - tendencia del precio (regresión sobre el logaritmo del precio de mercado),
  - si hay cada vez más o menos unidades a la venta, y más o menos vendedores,
  - cuántas unidades se venden al día (comparando escaneos completos seguidos),
  - para cuántos días de ventas hay género («días de oferta»),
  - si el precio está por encima o por debajo de su mediana.
Con eso se calcula un riesgo de bajada (0-100) y una previsión a 3 y 7 días que mezcla la
tendencia (amortiguada) con la vuelta a la mediana. Son reglas fijas y explicables; el
acierto se mide con el propio historial (backtest) para saber cuánto fiarse.
"""

from __future__ import annotations

import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from .money import format_pct
from .pricing import parse_book

DAY = 86400
WINDOW_DAYS = 7
MIN_POINTS = 3            # escaneos mínimos para hablar de tendencia
MIN_SPAN_DAYS = 1.0       # y que cubran al menos un día
MAX_PAIR_GAP_HOURS = 12   # escaneos más separados no sirven para contar ventas (las subastas caducan)
SALE_ZONE = 1.2           # solo cuentan como vendidas las unidades hasta un 20 % sobre el precio de mercado
DAMPING = 0.5             # la tendencia se proyecta a mitad de fuerza
REVERSION = 0.8           # cada día se mantiene el 80 % de la distancia a la mediana


@dataclass
class Point:
    time: int
    price: int            # precio de mercado
    quantity: int
    owners: int | None
    book: str | None
    kind: str             # full o browse


@dataclass
class MarketSignals:
    current: int
    median: int
    quantity: int
    points: int
    span_days: float
    owners: int | None = None              # vendedores en el último escaneo completo
    trend_per_day: float | None = None     # +0.02 = sube un 2 % al día
    trend_strength: float = 0.0            # R² de la tendencia: 1 = línea limpia, 0 = ruido
    supply_per_day: float | None = None    # cambio relativo de unidades a la venta por día
    sellers_per_day: float | None = None
    supply_change: float | None = None     # cambio observado de unidades en la ventana (+0.6 = +60 %)
    sellers_change: float | None = None
    volatility: float | None = None
    sales_per_day: float | None = None
    days_of_supply: float | None = None
    drop_risk: int = 0
    rise_score: int = 0
    forecast_3d: int | None = None
    forecast_7d: int | None = None
    outlook: str = "sin datos"             # baja, estable, sube o sin datos
    confidence: str = "baja"
    reasons: list[str] = field(default_factory=list)

    @property
    def week_change(self) -> float | None:
        if self.forecast_7d is None or not self.current:
            return None
        return self.forecast_7d / self.current - 1


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float] | None:
    """Recta de mínimos cuadrados: (pendiente, R²). R² dice lo limpia que es la tendencia."""
    if len(xs) < 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    var_x = sum((x - mx) ** 2 for x in xs)
    if var_x == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var_x
    var_y = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 if var_y == 0 else (slope ** 2 * var_x) / var_y
    return slope, min(1.0, r2)


def _slope(xs: list[float], ys: list[float]) -> float | None:
    fit = _fit(xs, ys)
    return fit[0] if fit else None


def estimate_sales(points: list[Point], full_scan_times: list[int]) -> float | None:
    """Unidades vendidas al día. Entre dos escaneos completos seguidos, las unidades que había
    a buen precio y ya no están se cuentan como vendidas. Incluye las que alguien retiró para
    bajarles el precio, así que es una cota alta."""
    by_time = {p.time: p for p in points if p.kind == "full"}
    sold = 0
    days = 0.0
    for a_time, b_time in zip(full_scan_times, full_scan_times[1:]):
        a = by_time.get(a_time)
        gap_hours = (b_time - a_time) / 3600
        if a is None or not a.book or gap_hours <= 0 or gap_hours > MAX_PAIR_GAP_HOURS:
            continue
        b = by_time.get(b_time)
        current = dict(parse_book(b.book)) if b is not None and b.book else {}
        # Solo se puede afirmar que algo falta en precios que el libro nuevo enseña entero.
        visible = max(current) if current else math.inf
        for price, qty in parse_book(a.book):
            if price <= a.price * SALE_ZONE and price <= visible:
                sold += max(0, qty - current.get(price, 0))
        days += gap_hours / 24
    return sold / days if days > 0 else None


def _relative_slope(xs: list[float], values: list[float]) -> float | None:
    slope = _slope(xs, values)
    mean = statistics.fmean(values) if values else 0
    return slope / mean if slope is not None and mean else None


def _signed(fraction: float) -> str:
    return ("+" if fraction > 0 else "-") + format_pct(abs(fraction))


def _score(s: MarketSignals) -> None:
    risk = rise = 0.0
    reasons = []
    days = f"{max(1, round(s.span_days))} días"
    if s.trend_per_day is not None:
        # Una tendencia ruidosa (R² bajo) apenas cuenta.
        week = (1 + s.trend_per_day) ** 7 - 1
        weight = 35 * s.trend_strength
        if week < 0:
            risk += weight * min(1, -week / 0.3)
        else:
            rise += weight * min(1, week / 0.3)
        if abs(week) >= 0.05 and s.trend_strength >= 0.5:
            reasons.append(f"precio {_signed(week)} a 7 días al ritmo actual")
    if s.supply_per_day is not None:
        week = s.supply_per_day * 7
        if week > 0:
            risk += 25 * min(1, week / 0.5)
        else:
            rise += 25 * min(1, -week / 0.5)
        if s.supply_change is not None and abs(s.supply_change) >= 0.15:
            reasons.append(f"{_signed(s.supply_change)} de unidades a la venta en {days}")
    if s.sellers_per_day is not None:
        week = s.sellers_per_day * 7
        if week > 0:
            risk += 15 * min(1, week / 0.5)
        else:
            rise += 15 * min(1, -week / 0.5)
        if s.sellers_change is not None and abs(s.sellers_change) >= 0.2:
            reasons.append(f"{_signed(s.sellers_change)} de vendedores en {days}")
    if s.points >= MIN_POINTS and s.median:
        # Volver a la mediana solo es de esperar si no hay una tendencia clara.
        deviation = s.current / s.median - 1
        weight = 15 * (1 - s.trend_strength)
        if deviation > 0:
            risk += weight * min(1, deviation / 0.3)
        else:
            rise += weight * min(1, -deviation / 0.3)
        if abs(deviation) >= 0.15:
            where = "por encima" if deviation > 0 else "por debajo"
            reasons.append(f"un {format_pct(abs(deviation))} {where} de su mediana")
    if s.days_of_supply is not None:
        if s.days_of_supply > 7:
            risk += 10 * min(1, (s.days_of_supply - 7) / 14)
            reasons.append(f"hay género para {s.days_of_supply:.0f} días de ventas")
        elif s.days_of_supply < 2:
            rise += 10
            reasons.append("se agota en menos de 2 días")
    s.drop_risk, s.rise_score, s.reasons = round(risk), round(rise), reasons


def _forecast(s: MarketSignals, days: float) -> int:
    """Mezcla la tendencia amortiguada con la vuelta a la mediana, según lo limpia que sea
    la tendencia: una caída constante sigue cayendo; un precio que va y viene, vuelve."""
    trend = s.current * (1 + s.trend_per_day) ** (days * DAMPING)
    reversion = s.median + (s.current - s.median) * REVERSION ** days
    w = s.trend_strength
    value = trend * w + reversion * (1 - w)
    return round(min(max(value, s.current * 0.5), s.current * 2))


def forecast_price(s: MarketSignals | None, days: float) -> int | None:
    """Precio de mercado previsto dentro de `days` días (el actual si no hay tendencia)."""
    if s is None:
        return None
    if s.trend_per_day is None:
        return s.current
    return _forecast(s, days)


def compute_signals(points: list[Point], full_scan_times: list[int], now: int | None = None) -> MarketSignals | None:
    """Señales de un objeto con los escaneos hasta `now` (por defecto, el último)."""
    if not points:
        return None
    now = now if now is not None else points[-1].time
    window = [p for p in points if now - WINDOW_DAYS * DAY <= p.time <= now]
    if not window:
        return None
    last = window[-1]
    s = MarketSignals(current=last.price, median=round(statistics.median(p.price for p in window)),
                      quantity=last.quantity, points=len(window),
                      span_days=(last.time - window[0].time) / DAY,
                      owners=next((p.owners for p in reversed(window) if p.owners is not None), None))
    if s.points >= MIN_POINTS and s.span_days >= MIN_SPAN_DAYS:
        xs = [(p.time - now) / DAY for p in window]
        fit = _fit(xs, [math.log(max(p.price, 1)) for p in window])
        slope, s.trend_strength = fit if fit else (0.0, 0.0)
        s.trend_per_day = math.exp(slope) - 1
        s.supply_per_day = _relative_slope(xs, [p.quantity for p in window])
        if window[0].quantity:
            s.supply_change = last.quantity / window[0].quantity - 1
        owned = [(x, p.owners) for x, p in zip(xs, window) if p.owners is not None]
        if len(owned) >= MIN_POINTS:
            s.sellers_per_day = _relative_slope([x for x, _ in owned], [o for _, o in owned])
            if owned[0][1]:
                s.sellers_change = owned[-1][1] / owned[0][1] - 1
        mean = statistics.fmean(p.price for p in window)
        s.volatility = statistics.pstdev(p.price for p in window) / mean if mean else None
    fulls = [t for t in full_scan_times if window[0].time <= t <= now]
    s.sales_per_day = estimate_sales(window, fulls)
    if s.sales_per_day:
        s.days_of_supply = s.quantity / s.sales_per_day
    _score(s)
    if s.trend_per_day is not None:
        s.forecast_3d = _forecast(s, 3)
        s.forecast_7d = _forecast(s, 7)
        change = s.week_change
        net = s.drop_risk - s.rise_score
        if change <= -0.08 or net >= 35:
            s.outlook = "baja"
        elif change >= 0.08 or net <= -35:
            s.outlook = "sube"
        else:
            s.outlook = "estable"
        if s.points >= 20 and s.span_days >= 5:
            s.confidence = "alta"
        elif s.points >= 6 and s.span_days >= 2:
            s.confidence = "media"
    return s


def load_series(conn: sqlite3.Connection, item_ids: Iterable[int] | None = None,
                days: float = WINDOW_DAYS * 3) -> tuple[dict[int, list[Point]], list[int]]:
    """Historial de cada objeto (últimos `days` días de datos) y horas de los escaneos completos."""
    reference = conn.execute("SELECT MAX(time) FROM scans").fetchone()[0]
    if not reference:
        return {}, []
    since = reference - days * DAY
    wanted = set(item_ids) if item_ids is not None else None
    series: dict[int, list[Point]] = defaultdict(list)
    rows = conn.execute(
        """SELECT p.item_id, s.time, COALESCE(p.market_price, p.min_price) AS price, p.quantity,
                  p.num_owners, p.book, s.type
           FROM prices p JOIN scans s ON s.scan_id = p.scan_id
           WHERE s.time >= ? ORDER BY s.time""",
        (since,),
    )
    for r in rows:
        if wanted is None or r["item_id"] in wanted:
            series[r["item_id"]].append(Point(r["time"], r["price"], r["quantity"] or 0,
                                              r["num_owners"], r["book"], r["type"]))
    fulls = [r[0] for r in conn.execute(
        "SELECT DISTINCT time FROM scans WHERE type = 'full' AND time >= ? ORDER BY time", (since,))]
    return dict(series), fulls


def market_signals(conn: sqlite3.Connection, item_ids: Iterable[int] | None = None) -> dict[int, MarketSignals]:
    series, fulls = load_series(conn, item_ids)
    result = {}
    for item_id, points in series.items():
        s = compute_signals(points, fulls)
        if s is not None:
            result[item_id] = s
    return result


@dataclass
class Backtest:
    cases: int = 0
    hits: int = 0
    baseline_hits: int = 0   # aciertos de decir siempre «estable»

    @property
    def accuracy(self) -> float | None:
        return self.hits / self.cases if self.cases else None

    @property
    def baseline(self) -> float | None:
        return self.baseline_hits / self.cases if self.cases else None


def backtest(series: dict[int, list[Point]], full_scan_times: list[int], horizon_days: float = 3,
             tolerance: float = 0.05) -> Backtest:
    """Repite la previsión en momentos pasados (una vez al día por objeto) y la compara con lo
    que pasó `horizon_days` después. Acierto: dijo baja y bajó más del 5 %, dijo sube y subió
    más del 5 %, o dijo estable y no se movió más del 5 %."""
    result = Backtest()
    for points in series.values():
        last_eval = -math.inf
        for i, p in enumerate(points):
            if p.time - last_eval < DAY:
                continue
            target = p.time + horizon_days * DAY
            future = next((q for q in points[i + 1:] if q.time >= target), None)
            if future is None or future.time - target > DAY / 2:
                continue
            s = compute_signals(points[:i + 1], full_scan_times, now=p.time)
            if s is None or s.outlook == "sin datos":
                continue
            last_eval = p.time
            actual = future.price / p.price - 1 if p.price else 0
            stable = abs(actual) <= tolerance
            result.cases += 1
            result.baseline_hits += stable
            result.hits += ((s.outlook == "baja" and actual < -tolerance)
                            or (s.outlook == "sube" and actual > tolerance)
                            or (s.outlook == "estable" and stable))
    return result
