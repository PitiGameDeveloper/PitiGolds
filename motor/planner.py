"""Comparador de métodos: ¿qué te conviene hacer con tu tiempo?

Tu referencia es tu mejor farmeo medido. Cada método se compara con ella a lo largo de un
horizonte (4 semanas por defecto) según las horas que juegas a la semana:

  - Farmeos: ocupan tu tiempo. Si hay que prepararlos (subir una profesión), las horas de
    preparación no dan nada y el oro invertido se resta.
  - Crafteos y reventas: los limita el mercado, no tu tiempo. Se hacen además de tu farmeo:
    dan lo que el mercado absorbe cada día, menos el rato que le quitan a tu farmeo.

En los dos casos el oro por hora (o por día) va cambiando del de hoy al previsto a 36 horas, y
después se mantiene. Así, si tu farmeo actual va a bajar, un método nuevo puede compensar
aunque hoy dé casi lo mismo.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field

from .analysis import Analysis
from .business import MARKET_SHARE
from .crafting import profession_levels
from .db import get_meta, set_meta
from .leveling import LevelingPlan, plan_leveling
from .market import OUTLOOK_DAYS

DEFAULT_HOURS_PER_WEEK = 10.0
DEFAULT_HORIZON_WEEKS = 4.0
DEFAULT_MIN_GOLD_HOUR = 5.0   # por debajo de este oro por hora, un farmeo «no da dinero»
MIN_BASELINE_HOURS = 0.5      # un farmeo de menos de media hora no sirve de referencia
FLIP_SECONDS = 15             # comprar al vendedor y poner a la venta, por unidad
MAX_LEARN_OPTIONS = 5
MAX_OTHER_PROFESSIONS = 3


@dataclass
class Settings:
    hours_per_week: float = DEFAULT_HOURS_PER_WEEK
    horizon_weeks: float = DEFAULT_HORIZON_WEEKS
    legacy_skillup: float = 0.0   # % que suma el talento de Legacy a la probabilidad de subir habilidad
    min_gold_hour: float = DEFAULT_MIN_GOLD_HOUR

    @property
    def skillup_bonus(self) -> float:
        return self.legacy_skillup / 100

    @property
    def horizon_days(self) -> int:
        return round(self.horizon_weeks * 7)

    @property
    def hours_per_day(self) -> float:
        return self.hours_per_week / 7


def load_settings(conn: sqlite3.Connection) -> Settings:
    return Settings(hours_per_week=float(get_meta(conn, "play_hours_week") or DEFAULT_HOURS_PER_WEEK),
                    horizon_weeks=float(get_meta(conn, "horizon_weeks") or DEFAULT_HORIZON_WEEKS),
                    legacy_skillup=float(get_meta(conn, "legacy_skillup_pct") or 0),
                    min_gold_hour=float(get_meta(conn, "min_gold_hour") or DEFAULT_MIN_GOLD_HOUR))


def save_settings(conn: sqlite3.Connection, settings: Settings) -> None:
    set_meta(conn, "play_hours_week", str(settings.hours_per_week))
    set_meta(conn, "horizon_weeks", str(settings.horizon_weeks))
    set_meta(conn, "legacy_skillup_pct", str(settings.legacy_skillup))
    set_meta(conn, "min_gold_hour", str(settings.min_gold_hour))
    conn.commit()


@dataclass
class Method:
    name: str
    kind: str                         # farmeo, crafteo o reventa
    who: str | None = None
    per_hour: int | None = None       # crafteos y reventas: por hora de gestión
    per_hour_later: int | None = None
    per_day_cap: int | None = None    # crafteos y reventas: lo máximo al día
    per_day_cap_later: int | None = None
    minutes_per_day: float | None = None
    measured: bool = False
    setup_gold: int = 0
    setup_hours: float = 0.0
    notes: list[str] = field(default_factory=list)
    guide: LevelingPlan | None = None
    gain: int | None = None           # frente a tu referencia, en todo el horizonte
    payback: str = ""
    verdict: str = ""
    is_baseline: bool = False

    @property
    def needs_setup(self) -> bool:
        return bool(self.setup_gold or self.setup_hours)


def _rate(now: float, later: float | None, day: float) -> float:
    """Valor que va del de hoy al previsto dentro de 36 horas y luego se queda fijo."""
    if later is None:
        return now
    return now + (later - now) * min(day, OUTLOOK_DAYS) / OUTLOOK_DAYS


def time_value(now: float, later: float | None, s: Settings, setup_hours: float = 0.0) -> float:
    """Oro de un método que ocupa tu tiempo, jugando tus horas, tras `setup_hours` de preparación."""
    total, pending = 0.0, setup_hours
    for day in range(s.horizon_days):
        hours = s.hours_per_day
        used = min(hours, pending)
        pending -= used
        total += (hours - used) * _rate(now, later, day + 0.5)
    return total


def _evaluate(m: Method, base_now: float, base_later: float | None, s: Settings) -> None:
    base_value = time_value(base_now, base_later, s)
    if m.kind == "farmeo":
        if m.per_hour is None:
            return
        value = time_value(m.per_hour, m.per_hour_later, s, m.setup_hours) - m.setup_gold
        m.gain = round(value - base_value)
        extra = m.per_hour - base_now
        if m.needs_setup:
            if extra > 0:
                hours = (m.setup_gold + m.setup_hours * base_now) / extra + m.setup_hours
                m.payback = f"{hours:.0f} h de juego (~{hours / s.hours_per_day:.0f} días)"
            else:
                m.payback = "nunca: rinde menos que tu referencia"
    else:
        if m.per_day_cap is None:
            m.verdict = "falta saber cuánto se vende al día"
            return
        start = math.ceil(m.setup_hours / s.hours_per_day) if m.setup_hours else 0
        value = 0.0
        for day in range(start, s.horizon_days):
            lost = (m.minutes_per_day or 0) / 60 * _rate(base_now, base_later, day + 0.5)
            value += _rate(m.per_day_cap, m.per_day_cap_later, day + 0.5) - lost
        value -= m.setup_gold + m.setup_hours * base_now
        m.gain = round(value)
        daily = m.per_day_cap - (m.minutes_per_day or 0) / 60 * base_now
        if m.needs_setup:
            if daily > 0:
                days = (m.setup_gold + m.setup_hours * base_now) / daily + start
                m.payback = f"~{days:.0f} días"
            else:
                m.payback = "nunca"
    weeks = f"{s.horizon_weeks:g} semanas"
    if m.is_baseline:
        m.verdict = "tu referencia"
    elif m.gain is None:
        m.verdict = m.verdict or "faltan datos"
    elif not m.needs_setup:
        if m.kind == "farmeo":
            m.verdict = "rinde más que tu referencia" if m.gain > 0 else "rinde menos que tu referencia"
        else:
            m.verdict = "hazlo además de farmear" if m.gain > 0 else "no compensa"
    else:
        m.verdict = "compensa" if m.gain > 0 else f"no compensa en {weeks}"


def _primaries(conn: sqlite3.Connection) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for r in conn.execute("SELECT char_key, name FROM profession_summary WHERE slot LIKE 'primary%'"):
        result.setdefault(r["char_key"], []).append(r["name"])
    return result


def _craft_method(c, name: str, who: str | None) -> Method:
    cap = c.capacity
    m = Method(name=name, kind="crafteo", who=who)
    if cap is not None:
        m.per_hour = cap.gold_per_hour
        m.per_day_cap = cap.gold_per_day
        m.minutes_per_day = cap.minutes_per_day
        if c.profit_later is not None and c.profit:
            ratio = max(0.0, c.profit_later / c.profit)
            m.per_day_cap_later = round(cap.gold_per_day * ratio)
            m.per_hour_later = round(cap.gold_per_hour * ratio)
    return m


def build_methods(conn: sqlite3.Connection, a: Analysis, s: Settings | None = None) -> tuple[list[Method], Method]:
    s = s or load_settings(conn)
    methods: list[Method] = []

    farms = [g for g in a.farm_summary if g.hours >= MIN_BASELINE_HOURS] or a.farm_summary
    for g in a.farm_summary:
        methods.append(Method(name=f"{g.activity} en {g.zone}", kind="farmeo", per_hour=g.per_hour,
                              per_hour_later=g.per_hour_later, measured=True))
    if farms:
        best = max(farms, key=lambda g: g.per_hour)
        baseline = next(m for m in methods if m.name == f"{best.activity} en {best.zone}")
        baseline.is_baseline = True
    else:
        baseline = Method(name="sin farmeos medidos", kind="farmeo", per_hour=0, per_hour_later=0,
                          is_baseline=True)

    for c in a.crafts:
        if c.known and c.complete and c.profit > 0:
            methods.append(_craft_method(c, f"Fabricar {c.name}", c.known_by[0]))

    for f in a.vendor_flips:
        m = Method(name=f"Revender {f.name} de {f.vendor}", kind="reventa", per_hour=f.profit * 3600 // FLIP_SECONDS)
        if f.sales_per_day:
            units = f.sales_per_day * MARKET_SHARE
            m.per_day_cap = f.gold_per_day
            m.minutes_per_day = units * FLIP_SECONDS / 60
            if f.profit_later is not None and f.profit:
                m.per_day_cap_later = round(f.gold_per_day * max(0.0, f.profit_later / f.profit))
        if f.limited:
            m.notes.append("existencias limitadas: el máximo real puede ser menor")
        methods.append(m)

    levels = profession_levels(conn)
    primaries = _primaries(conn)
    owned = a.owned

    def with_guide(m: Method, c, line: int, start: int, known: set[int]) -> Method:
        if start < c.required_skill:
            guide = plan_leveling(a.crafts, a.prices, owned, line, start, c.required_skill, known, s.skillup_bonus)
            m.guide = guide
            m.setup_gold += guide.cash_needed
            m.setup_hours += guide.hours
            for low, high in guide.gaps:
                m.notes.append(f"sin precios para subir de {low} a {high}: el coste real será mayor")
        if c.learn_price and c.recipe_id not in known:
            m.setup_gold += c.learn_price
        elif c.learn_item_name is None and c.recipe_id not in known:
            m.notes.append("se aprende con el instructor (su precio no viene en los datos)")
        return m

    known_by_char: dict[str, set[int]] = {}
    for r in conn.execute("SELECT char_key, recipe_id FROM known_recipes"):
        known_by_char.setdefault(r["char_key"], set()).add(r["recipe_id"])

    learnable = sorted((c for c in a.crafts if c.yours and not c.known and c.complete and c.profit > 0
                        and c.skill_line is not None), key=lambda c: c.profit, reverse=True)
    for c in learnable[:MAX_LEARN_OPTIONS]:
        chars = levels.get(c.skill_line, [])
        who, skill = chars[0] if chars else (None, 1)
        m = _craft_method(c, f"Aprender {c.name}", who)
        methods.append(with_guide(m, c, c.skill_line, max(skill, 1), known_by_char.get(who, set())))

    best_by_profession: dict[int, object] = {}
    for c in a.crafts:
        if not c.yours and c.complete and c.profit > 0 and c.skill_line is not None:
            current = best_by_profession.get(c.skill_line)
            if current is None or c.profit > current.profit:
                best_by_profession[c.skill_line] = c
    others = sorted(best_by_profession.items(), key=lambda kv: kv[1].profit, reverse=True)
    for line, c in others[:MAX_OTHER_PROFESSIONS]:
        free = [char for char, profs in primaries.items() if len(profs) < 2]
        m = _craft_method(c, f"Subir {c.profession} para {c.name}", free[0] if free else None)
        if not free and primaries:
            m.notes.append("todos tus personajes tienen ya dos profesiones: tendrías que dejar una")
        methods.append(with_guide(m, c, line, 1, set()))

    for m in methods:
        _evaluate(m, baseline.per_hour or 0, baseline.per_hour_later, s)
    if baseline not in methods:
        _evaluate(baseline, 0, None, s)
    methods.sort(key=lambda m: (not m.is_baseline, m.gain is None, -(m.gain or 0)))
    return methods, baseline
