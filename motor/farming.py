"""Tus farmeos: oro por hora real, a los precios de hoy y a los previstos dentro de 7 días.

El addon apunta lo que ganas en tramos de 5 minutos por zona. Aquí los tramos seguidos de
la misma zona y etiqueta se unen en sesiones (más de 15 minutos sin ganar nada corta la
sesión), y cada sesión se valora: objetos a precio de mercado menos la comisión (o lo que
paga el vendedor si no están en la subasta) más el oro conseguido.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from .pricing import ItemPrice

DAY = 86400
SEGMENT_GAP = 15 * 60
MIN_SECONDS = 300          # una sesión cuenta como mínimo 5 minutos
HISTORY_DAYS = 14
TRADEGOODS = 7             # gd_items.class_id de los materiales
ACTIVITY_BY_SUBCLASS = {5: "Tela", 6: "Desuello", 7: "Minería", 8: "Carne", 9: "Herboristería",
                        10: "Elementales", 12: "Encantamiento"}
MONEY_ACTIVITY = "Oro de bichos y misiones"


@dataclass
class FarmSession:
    char_key: str
    zone: str
    label: str | None
    start: int
    end: int
    money: int = 0
    items: dict[int, int] = field(default_factory=dict)
    value_now: int = 0          # lo ganado a precios de hoy (ya sin comisión)
    value_week: int = 0         # lo mismo con los precios previstos a 7 días
    activity: str = ""
    top_items: list[str] = field(default_factory=list)
    unpriced: list[str] = field(default_factory=list)

    @property
    def hours(self) -> float:
        return max(self.end - self.start, MIN_SECONDS) / 3600

    @property
    def per_hour(self) -> int:
        return round(self.value_now / self.hours)

    @property
    def per_hour_week(self) -> int:
        return round(self.value_week / self.hours)


@dataclass
class FarmSummary:
    activity: str
    zone: str
    sessions: int
    hours: float
    value_now: int
    value_week: int

    @property
    def per_hour(self) -> int:
        return round(self.value_now / self.hours) if self.hours else 0

    @property
    def per_hour_week(self) -> int:
        return round(self.value_week / self.hours) if self.hours else 0


def load_sessions(conn: sqlite3.Connection, days: float = HISTORY_DAYS) -> list[FarmSession]:
    newest = conn.execute("SELECT MAX(last) FROM farm_buckets").fetchone()[0]
    if not newest:
        return []
    items: dict[str, dict[int, int]] = defaultdict(dict)
    for r in conn.execute("SELECT bucket_key, item_id, count FROM farm_items"):
        items[r["bucket_key"]][r["item_id"]] = r["count"]

    sessions: list[FarmSession] = []
    current: FarmSession | None = None
    rows = conn.execute("SELECT * FROM farm_buckets WHERE t >= ? ORDER BY char_key, t, first",
                        (newest - days * DAY,))
    for b in rows:
        first, last = b["first"] or b["t"], b["last"] or b["t"]
        zone, label = b["zone_name"] or "?", b["label"]
        same = (current is not None and current.char_key == b["char_key"] and current.zone == zone
                and current.label == label and first - current.end <= SEGMENT_GAP)
        if not same:
            current = FarmSession(char_key=b["char_key"], zone=zone, label=label, start=first, end=last)
            sessions.append(current)
        current.end = max(current.end, last)
        current.money += b["money"] or 0
        for item_id, n in items.get(b["bucket_key"], {}).items():
            current.items[item_id] = current.items.get(item_id, 0) + n
    return sessions


def farm_item_ids(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT DISTINCT item_id FROM farm_items")}


def value_sessions(conn: sqlite3.Connection, sessions: list[FarmSession], prices: dict[int, ItemPrice],
                   signals: dict) -> None:
    classes = {r["item_id"]: (r["class_id"], r["subclass_id"])
               for r in conn.execute("SELECT item_id, class_id, subclass_id FROM gd_items")}
    for s in sessions:
        by_activity: dict[str, int] = defaultdict(int)
        worth = []
        for item_id, n in s.items.items():
            p = prices.get(item_id)
            name = p.name if p else f"objeto {item_id}"
            unit = (p.net_sale or p.vendor_sell or 0) if p else 0
            unit_week = unit
            sig = signals.get(item_id)
            if p and p.net_sale and sig is not None and sig.forecast_7d:
                unit_week = p.net_of(sig.forecast_7d)
            if not unit:
                s.unpriced.append(name)
            s.value_now += unit * n
            s.value_week += unit_week * n
            class_id, subclass = classes.get(item_id, (None, None))
            activity = ACTIVITY_BY_SUBCLASS.get(subclass) if class_id == TRADEGOODS else None
            by_activity[activity or "Otros objetos"] += unit * n
            worth.append((unit * n, f"{name} x{n}"))
        by_activity[MONEY_ACTIVITY] += s.money
        s.value_now += s.money
        s.value_week += s.money
        best = max(by_activity, key=by_activity.get) if any(by_activity.values()) else "Sin valor"
        s.activity = s.label or best
        s.top_items = [text for _, text in sorted(worth, reverse=True)[:3]]


def summarize(sessions: list[FarmSession]) -> list[FarmSummary]:
    groups: dict[tuple[str, str], FarmSummary] = {}
    for s in sessions:
        key = (s.activity, s.zone)
        g = groups.get(key)
        if g is None:
            g = groups[key] = FarmSummary(activity=s.activity, zone=s.zone, sessions=0, hours=0.0,
                                          value_now=0, value_week=0)
        g.sessions += 1
        g.hours += s.hours
        g.value_now += s.value_now
        g.value_week += s.value_week
    return sorted(groups.values(), key=lambda g: g.per_hour, reverse=True)
