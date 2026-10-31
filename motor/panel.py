"""La ventana de métodos del addon: la pestaña de farmeos, la de crafteos y el mejor farmeo.

Se calcula sin IA cada vez que el motor lee los datos del addon, así que cada método guardado
se vuelve a comprobar con los precios del último escaneo.

Farmeos (farmeos, pesca y mazmorras del catálogo, más los que has medido tú):
  - oro por hora: el medido si lo has medido; si no, el esperado: lo que da en una hora según
    la investigación (`por_hora` del catálogo) valorado con tus precios. De cada objeto solo va
    a la subasta lo que el mercado absorbe en tus horas de juego; el resto, al vendedor.
  - para ordenarlos cuenta lo menor entre hoy y lo previsto a 7 días: un farmeo cuyos objetos
    van a bajar vale lo que valdrán.
  - color: verde si da al menos el 60 % del mejor, amarillo si llega al mínimo (5 oro/h por
    defecto, `ajustes --minimo-hora`), rojo si no llega.
  - quién puede hacerlo ya; si nadie, al que menos le falta y cuánto le cuesta prepararlo
    (horas de recolección por la ruta de recoleccion.json, o la guía de subida de un crafteo).
Crafteos: beneficio por unidad, cuántas absorbe el mercado al día y lo cerca que estás de
poder hacerlo: verde (ya puedes), amarillo (te faltan 25 puntos o menos y la receta se compra
en un momento), naranja (te faltan hasta 75 puntos, un poco de reputación o de divisas, o no
se sabe de dónde sale la receta) y rojo (falta mucho, o la receta es de botín).

El mejor farmeo:
  - «mejor»: el que ya puedes hacer, llega al mínimo y rinde al menos el 60 % del mejor de todos;
  - «preparar»: lo que puedes hacer ya rinde mucho menos que otros que piden preparación;
  - «investigar»: ningún método guardado llega al mínimo: toca buscar métodos nuevos;
  - «sin datos»: faltan precios o estimaciones para decidir.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field

from .analysis import Analysis
from .business import MARKET_SHARE
from .catalogo import TIME_KINDS, CatalogEntry, CatalogError, normalize
from .crafting import CraftResult
from .leveling import plan_leveling
from .money import format_money
from .planner import Settings, load_settings
from .pricing import AH_CUT
from .recoleccion import GATHERING, Stretch, gathering_hours, load_routes, route_lines
from .revision import Review, Reviews, load_reviews

GREEN_SHARE = 0.6
CLOSE_GAP = 25          # puntos de profesión que se suben en un rato
FAR_GAP = 75
MAX_CRAFT_ROWS = 40
HOURS_PER_LEVEL = 1.0   # solo para elegir al personaje más cercano cuando le falta nivel
PRIMARY_CATEGORY = 11   # gd_skill_lines.category de las profesiones principales
STANDINGS = {1: "odiado", 2: "hostil", 3: "adverso", 4: "neutral", 5: "amistoso", 6: "honorable",
             7: "reverenciado", 8: "exaltado"}
COLOR_RANK = {"verde": 0, "amarillo": 1, "naranja": 2, "rojo": 3}


@dataclass
class Character:
    key: str
    name: str
    level: int
    faction: str | None
    skills: dict[int, int] = field(default_factory=dict)
    primaries: set[int] = field(default_factory=set)
    reputation: dict[int, int] = field(default_factory=dict)   # facción -> reaction (4 neutral...)
    currencies: dict[int, int] = field(default_factory=dict)

    def free_slot(self, line: int, primary_lines: set[int]) -> bool:
        return line not in primary_lines or line in self.primaries or len(self.primaries) < 2


@dataclass
class FarmRow:
    key: str                     # id del catálogo, o «medido:<actividad>|<zona>»
    name: str
    kind: str = "farmeo"
    zone: str = ""
    score: int | None = None
    per_hour: int | None = None
    per_hour_week: int | None = None
    measured: bool = False
    color: str | None = None
    who: str | None = None       # personaje que ya puede hacerlo
    requirement: str = ""        # lo que pide, en corto
    closest: str | None = None   # si nadie puede: al que menos le falta
    lacking: list[str] = field(default_factory=list)
    prep_gold: int = 0
    prep_hours: float = 0.0
    level: int = 0
    min_level: int = 0
    pending: str = ""
    details: list[str] = field(default_factory=list)

    @property
    def value(self) -> int | None:
        """Lo que cuenta para ordenar: lo menor entre hoy y dentro de 7 días."""
        if self.per_hour is None:
            return None
        if self.per_hour_week is None:
            return self.per_hour
        return min(self.per_hour, self.per_hour_week)

    @property
    def ready(self) -> bool:
        return self.who is not None and not self.pending


@dataclass
class ReagentRow:
    item_id: int | None
    name: str
    quantity: int
    unit_price: int | None
    source: str | None           # subasta, vendedor o divisa
    vendor: str | None = None
    zone: str | None = None


@dataclass
class RecipeSource:
    way: str                     # aprendida, instructor, profesion, vendedor, subasta, botin, reputacion, mision, desconocida
    text: str
    item_id: int | None = None
    item_name: str | None = None
    price: int | None = None
    vendor: str | None = None
    zone: str | None = None
    reputation: str = ""         # «honorable con el Alba Argenta (tienes amistoso)»
    rep_gap: int = 0
    currency_short: str = ""     # «te faltan 3 Merchant's Favor»


@dataclass
class CraftRow:
    recipe_id: int
    name: str
    profession: str
    skill_line: int | None
    score: int | None = None
    profit_item: int | None = None
    approx: bool = False
    approx_why: str = ""
    per_day: float | None = None       # unidades que absorbe el mercado al día
    gold_day: int | None = None
    minutes_day: float | None = None
    crafts_day: int = 1
    color: str = "rojo"
    who: str | None = None             # quién la fabrica, o el que está más cerca
    who_name: str | None = None
    who_skill: int = 0
    required: int = 0
    gap: int = 0
    known_by: list[str] = field(default_factory=list)
    recipe: RecipeSource | None = None
    reagents: list[ReagentRow] = field(default_factory=list)
    output_id: int | None = None
    output_qty: float = 1.0
    sell_price: int | None = None      # a cuánto ponerlo en la subasta (antes de comisión)
    cooldown_hours: float | None = None
    prep: list[str] = field(default_factory=list)   # qué le falta, en frases
    details: list[str] = field(default_factory=list)


@dataclass
class Verdict:
    state: str                   # mejor, preparar, investigar, sin_datos
    title: str
    lines: list[str] = field(default_factory=list)
    best: str | None = None      # key del farmeo recomendado


@dataclass
class Panel:
    farms: list[FarmRow] = field(default_factory=list)
    crafts: list[CraftRow] = field(default_factory=list)
    verdict: Verdict = field(default_factory=lambda: Verdict("sin_datos", "Aún no hay datos"))
    unreviewed: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)   # archivos de conocimiento rotos


# Personajes ---------------------------------------------------------------------------

def load_characters(conn: sqlite3.Connection) -> list[Character]:
    chars = {r["char_key"]: Character(key=r["char_key"], name=r["name"] or r["char_key"].split("-")[0],
                                      level=r["level"] or 0, faction=r["faction"])
             for r in conn.execute("SELECT char_key, name, level, faction FROM characters")}
    for r in conn.execute("SELECT char_key, skill_line, slot, rank FROM profession_summary"):
        c = chars.get(r["char_key"])
        if c is not None:
            c.skills[r["skill_line"]] = max(c.skills.get(r["skill_line"], 0), r["rank"] or 0)
            if (r["slot"] or "").startswith("primary"):
                c.primaries.add(r["skill_line"])
    for r in conn.execute("SELECT char_key, parent_id, skill FROM professions WHERE parent_id IS NOT NULL"):
        c = chars.get(r["char_key"])
        if c is not None:
            c.skills[r["parent_id"]] = max(c.skills.get(r["parent_id"], 0), r["skill"] or 0)
    for r in conn.execute("SELECT char_key, faction_id, reaction FROM reputations"):
        if r["char_key"] in chars and r["reaction"] is not None:
            chars[r["char_key"]].reputation[r["faction_id"]] = r["reaction"]
    for r in conn.execute("SELECT char_key, currency_id, quantity FROM currencies"):
        if r["char_key"] in chars:
            chars[r["char_key"]].currencies[r["currency_id"]] = r["quantity"] or 0
    return sorted(chars.values(), key=lambda c: -c.level)


@dataclass
class _Context:
    conn: sqlite3.Connection
    a: Analysis
    settings: Settings
    chars: list[Character]
    names: dict[int, str]              # profesión -> nombre
    primary_lines: set[int]
    routes: dict[int, list[Stretch]]
    english: dict[str, str]            # nombre inglés normalizado -> nombre en el juego
    known_by_char: dict[str, set[int]]
    factions: dict[int, str]

    def prof(self, line: int) -> str:
        return self.names.get(line, f"profesión {line}")


def _context(conn: sqlite3.Connection, a: Analysis, settings: Settings,
             routes: dict[int, list[Stretch]]) -> _Context:
    names, primary = {}, set()
    for r in conn.execute("SELECT skill_line, name, category FROM gd_skill_lines"):
        names[r["skill_line"]] = r["name"]
        if r["category"] == PRIMARY_CATEGORY:
            primary.add(r["skill_line"])
    english = {}
    for r in conn.execute("SELECT name, name_en FROM gd_items WHERE name_en IS NOT NULL AND name IS NOT NULL"):
        english.setdefault(normalize(r["name_en"]), r["name"])
    known: dict[str, set[int]] = {}
    for r in conn.execute("SELECT char_key, recipe_id FROM known_recipes"):
        known.setdefault(r["char_key"], set()).add(r["recipe_id"])
    factions = {r["faction_id"]: r["name"] for r in conn.execute("SELECT faction_id, name FROM gd_factions")}
    return _Context(conn=conn, a=a, settings=settings, chars=load_characters(conn), names=names,
                    primary_lines=primary, routes=routes, english=english, known_by_char=known, factions=factions)


# Preparar un método: subir nivel o profesión ---------------------------------------------

@dataclass
class _Prep:
    char: Character
    lacking: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    gold: int = 0
    hours: float = 0.0
    blocked: bool = False        # sin hueco de profesión

    @property
    def cost(self) -> float:
        return self.hours + (1000 if self.blocked else 0)


def _profession_prep(ctx: _Context, prep: _Prep, line: int, target: int) -> None:
    ch = prep.char
    have = ch.skills.get(line, 0)
    if have >= target:
        return
    name = ctx.prof(line)
    if line not in ch.skills:
        if not ch.free_slot(line, ctx.primary_lines):
            prep.blocked = True
            dropped = " o ".join(ctx.prof(p) for p in sorted(ch.primaries))
            prep.lacking.append(f"{name} {target} (tendría que dejar {dropped})")
        else:
            prep.lacking.append(f"{name} {target} (no la tiene)")
        prep.lines.append(f"Aprende {name} con el instructor.")
    else:
        prep.lacking.append(f"{name} {target} (tiene {have})")
    start = max(have, 1)
    if line in GATHERING:
        hours = gathering_hours(ctx.routes, line, start, target)
        if hours is not None:
            prep.hours += hours
            prep.lines.append(f"Sube {name} de {start} a {target} recolectando (~{_hours(hours)}):")
            prep.lines += ["  " + t for t in route_lines(ctx.routes, line, start, target, ch.faction, ctx.english)]
        else:
            prep.hours += (target - start) / 40
            prep.lines.append(f"Sube {name} de {start} a {target}.")
        return
    plan = plan_leveling(ctx.a.crafts, ctx.a.prices, ctx.a.owned, line, start, target,
                         ctx.known_by_char.get(ch.key, set()), ctx.settings.skillup_bonus)
    prep.gold += plan.cash_needed
    prep.hours += plan.hours
    text = f"Sube {name} de {start} a {target}: ~{format_money(plan.cash_needed)} y ~{_hours(plan.hours)}"
    if plan.gaps:
        text += " (faltan precios de algún tramo: costará más)"
    prep.lines.append(text + f". Guía: python -m motor guia {normalize(name)}")


def _hours(hours: float) -> str:
    return f"{hours * 60:.0f} min" if hours < 1 else f"{hours:.1f} h".replace(".0 h", " h")


def _farm_prep(ctx: _Context, e: CatalogEntry, ch: Character) -> _Prep:
    prep = _Prep(char=ch)
    need_level = e.min_level or e.level
    if need_level and ch.level < need_level:
        prep.lacking.append(f"nivel {need_level} (tiene {ch.level})")
        prep.lines.append(f"Sube a {ch.name} a nivel {need_level}.")
        prep.hours += (need_level - ch.level) * HOURS_PER_LEVEL
    for line, skill in e.professions:
        _profession_prep(ctx, prep, line, max(skill, 1))
    if e.any_profession and not any(ch.skills.get(line) for line in e.any_profession):
        options = sorted(e.any_profession, key=lambda line: line not in GATHERING)
        _profession_prep(ctx, prep, options[0], 1)
    return prep


# Farmeos ------------------------------------------------------------------------------

def _expected(ctx: _Context, e: CatalogEntry, resolved: dict[str, int]) -> tuple[int | None, int | None, list[str]]:
    """Oro por hora esperado (hoy y a 7 días) según `por_hora`, y su desglose en frases."""
    if not e.per_hour and not e.coins_per_hour:
        return None, None, []
    hours_day = max(ctx.settings.hours_per_day, 0.5)
    now = week = float(e.coins_per_hour)
    lines, priced = [], bool(e.coins_per_hour)
    if e.coins_per_hour:
        lines.append(f"Monedas y basura: ~{format_money(e.coins_per_hour)}/h")
    for label, qty in e.per_hour:
        item_id = resolved.get(label)
        p = ctx.a.prices.get(item_id) if item_id else None
        name = p.name if p and not p.name.startswith("objeto ") else label
        ah = (p.net_sale or 0) if p else 0
        vendor = (p.vendor_sell or 0) if p else 0
        if not ah and not vendor:
            lines.append(f"{qty:g} {name}/h: sin precio todavía (escanea la subasta)")
            continue
        priced = True
        if ah <= vendor:
            now += qty * vendor
            week += qty * vendor
            lines.append(f"{qty:g} {name}/h al vendedor a {format_money(vendor)}")
            continue
        s = ctx.a.signals.get(item_id)
        cap = s.sales_per_day * MARKET_SHARE / hours_day if s is not None and s.sales_per_day else None
        to_ah = qty if cap is None else min(qty, cap)
        rest = qty - to_ah
        ah_week = round(s.forecast_7d * (1 - AH_CUT)) if s is not None and s.forecast_7d else ah
        now += to_ah * ah + rest * vendor
        week += to_ah * max(ah_week, vendor) + rest * vendor
        text = f"{qty:g} {name}/h a {format_money(ah)} en la subasta"
        if rest > 0:
            text += (f"; el mercado solo se lleva unas {cap:.0f} por hora de juego, el resto "
                     + (f"al vendedor ({format_money(vendor)})" if vendor else "no se vende"))
        elif cap is None:
            text += " (aún no sé cuántas se venden al día)"
        lines.append(text)
    if not priced:
        return None, None, lines
    return round(now), round(week), lines


def _farm_rows(ctx: _Context, reviews: Reviews) -> list[FarmRow]:
    a = ctx.a
    resolved = a.guide_resolved
    rows, linked = [], set()
    for m in a.guide_methods:
        e = m.entry
        if e.kind not in TIME_KINDS:
            continue
        row = FarmRow(key=e.id, name=e.name, kind=e.kind, zone=e.zone, level=e.level,
                      min_level=e.min_level, pending=e.pending)
        parts = [f"{ctx.prof(line)} {skill}" if skill > 1 else ctx.prof(line) for line, skill in e.professions]
        if e.any_profession:
            parts.append(" o ".join(ctx.prof(line) for line in e.any_profession))
        if e.min_level or e.level:
            parts.append(f"nivel {e.min_level or e.level}")
        row.requirement = ", ".join(parts)

        now, week, value_lines = _expected(ctx, e, resolved)
        if m.measured is not None and m.measured.hours > 0:
            g = m.measured
            linked.add((g.activity, g.zone))
            row.per_hour, row.per_hour_week, row.measured = g.per_hour, g.per_hour_week, True
            row.details.append(f"Medido: {format_money(g.per_hour)}/h en {_hours(g.hours)} "
                               f"({g.sessions} sesión{'es' if g.sessions != 1 else ''}).")
            if now is not None:
                row.details.append(f"La investigación esperaba ~{format_money(now)}/h.")
        else:
            row.per_hour, row.per_hour_week = now, week
            if now is not None:
                row.details.append(f"Esperado con tus precios: ~{format_money(now)}/h (sin medir: mídelo con "
                                   f"/pg farmeo {e.id}).")
            elif not e.per_hour:
                row.details.append("Aún no hay estimación de cuánto da por hora: pídesela al asesor.")
        row.details += ["  " + t for t in value_lines]
        if row.per_hour and row.per_hour_week is not None:
            change = row.per_hour_week / row.per_hour - 1 if row.per_hour else 0
            if change <= -0.1:
                row.details.append(f"Sus objetos van a bajar: en 7 días daría ~{format_money(row.per_hour_week)}/h.")
            elif change >= 0.1:
                row.details.append(f"Sus objetos van a subir: en 7 días daría ~{format_money(row.per_hour_week)}/h.")

        preps = [_farm_prep(ctx, e, ch) for ch in ctx.chars]
        ready = [p for p in preps if not p.lacking]
        if ready:
            row.who = ready[0].char.name
            others = ", ".join(p.char.name for p in ready[1:])
            row.details.append(f"Lo puede hacer ya: {row.who}" + (f" (y {others})" if others else "") + ".")
        elif preps:
            best = min(preps, key=lambda p: p.cost)
            row.closest = best.char.name
            row.lacking = best.lacking
            row.prep_gold, row.prep_hours = best.gold, best.hours
            row.details.append(f"Nadie puede todavía. Al que menos le falta: {best.char.name} "
                               f"({'; '.join(best.lacking)}).")
            row.details += best.lines
        _add_catalog_details(row, e, reviews.farms.get(e.id))
        rows.append(row)

    for g in a.farm_summary:
        if (g.activity, g.zone) in linked or not g.hours:
            continue
        row = FarmRow(key=f"medido:{g.activity}|{g.zone}", name=f"{g.activity} en {g.zone}", zone=g.zone,
                      per_hour=g.per_hour, per_hour_week=g.per_hour_week, measured=True,
                      who="tú", requirement="lo has medido tú")
        row.details.append(f"Medido: {format_money(g.per_hour)}/h en {_hours(g.hours)} ({g.sessions} sesiones). "
                           "No está en el catálogo: el asesor puede añadirlo.")
        rows.append(row)
    return rows


def _add_catalog_details(row: FarmRow, e: CatalogEntry, review: Review | None) -> None:
    head = []
    if e.pending:
        head.append(f"En espera, falta un dato: {e.pending}")
    if review is not None:
        row.score = review.score
        if review.why:
            head.append(f"Asesor ({review.score}/10): {review.why}")
        head += [f"{n}. {step}" for n, step in enumerate(review.steps, 1)]
    row.details[:0] = head
    if e.zone:
        row.details.append(f"Zona: {e.zone}.")
    if e.notes:
        row.details.append(e.notes)
    source = f"Fuente: {e.source}" if e.source else ""
    if e.link:
        source += f" ({e.link})"
    if source:
        row.details.append(source + ".")


def _color_farms(rows: list[FarmRow], floor: int) -> int | None:
    values = [r.value for r in rows if r.value is not None and not r.pending]
    best = max(values, default=None)
    for r in rows:
        v = r.value
        if v is None:
            r.color = None
        elif v < floor:
            r.color = "rojo"
        elif best and v >= GREEN_SHARE * best:
            r.color = "verde"
        else:
            r.color = "amarillo"
    return best


# Crafteos -----------------------------------------------------------------------------

def _vendor_rows(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {r["item_id"]: r for r in conn.execute("SELECT * FROM vendor_items")}


def _recipe_source(ctx: _Context, c: CraftResult, ch: Character | None, vendors: dict, checks: dict,
                   review: Review | None, item_info: dict) -> RecipeSource:
    if c.known:
        return RecipeSource(way="aprendida", text="Ya la sabe " + ", ".join(k.split("-")[0] for k in c.known_by))
    learn = c.learn_item_id
    if not learn:
        if c.source == "Se aprende al aprender la profesión":
            return RecipeSource(way="profesion", text="Se aprende al aprender la profesión.")
        return RecipeSource(way="instructor", text=f"Se aprende con el instructor de {c.profession}.")
    name = c.learn_item_name or f"objeto {learn}"
    src = RecipeSource(way="desconocida", text="", item_id=learn, item_name=name)
    v = vendors.get(learn)
    p = ctx.a.prices.get(learn)
    if v is not None:
        src.way, src.vendor, src.zone, src.price = "vendedor", v["vendor"], v["zone"], v["price"]
        src.text = f"La vende {v['vendor']}" + (f" en {v['zone']}" if v["zone"] else "")
        if v["price"]:
            src.text += f" por {format_money(v['price'])}"
        if v["costs_json"] and ch is not None:
            short = []
            for cost in json.loads(v["costs_json"]):
                cid, need = cost.get("currencyID"), cost.get("value") or 0
                if cid and ch.currencies.get(cid, 0) < need:
                    short.append(f"{need - ch.currencies.get(cid, 0)} {cost.get('name') or 'divisa'}")
            if short:
                src.currency_short = "le faltan " + ", ".join(short)
    elif checks.get(learn) is not None and checks[learn]["status"] == "vende":
        src.way = "vendedor"
        src.text = "La vende un vendedor" + (f": {checks[learn]['detail']}" if checks[learn]["detail"] else "")
    elif p is not None and p.market:
        src.way, src.price = "subasta", p.market
        src.text = f"Está en la subasta por {format_money(p.market)}"
    elif review is not None and review.recipe_way:
        src.way = review.recipe_way
        src.text = f"{review.recipe_way.capitalize()}: {review.recipe_where}".rstrip(": ")
        if review.recipe_price:
            src.text += f" ({review.recipe_price})"
        if review.recipe_requirement:
            src.text += f"; pide {review.recipe_requirement}"
    else:
        src.text = (f"No sé dónde se consigue «{name}»: pídele al asesor que lo mire "
                    "(o escanea la subasta por si alguien la vende)")
    faction, standing = item_info.get(learn, (None, None))
    if faction and standing:
        fname = ctx.factions.get(faction, f"la facción {faction}")
        have = ch.reputation.get(faction, 4) if ch is not None else 4
        src.reputation = f"{STANDINGS.get(standing, standing)} con {fname}"
        if have < standing:
            src.rep_gap = standing - have
            src.reputation += f" (tiene {STANDINGS.get(have, have)})"
    return src


def _status(ctx: _Context, c: CraftResult, ch: Character | None, src: RecipeSource) -> tuple[str, int, list[str]]:
    """Color, puntos que faltan y por qué no es verde, para un personaje."""
    if c.known:
        return "verde", 0, []
    line = c.skill_line
    required = c.required_skill or 1
    have = ch.skills.get(line, 0) if ch is not None and line is not None else 0
    gap = max(0, required - have)
    rank, why = 1, []
    if ch is not None and line is not None and line not in ch.skills:
        if not ch.free_slot(line, ctx.primary_lines):
            return "rojo", gap, [f"no tiene hueco para {c.profession}"]
        rank = 2
        why.append(f"no tiene {c.profession}")
    if gap > FAR_GAP:
        rank = 3
    elif gap > CLOSE_GAP:
        rank = max(rank, 2)
    if gap:
        why.append(f"le faltan {gap} puntos de {c.profession} ({have}/{required})")
    if src.way in ("botin", "mision"):
        rank = 3
        why.append("la receta lleva tiempo conseguirla" + (f" ({src.text})" if src.text else ""))
    elif src.way in ("desconocida", "reputacion"):
        rank = max(rank, 2)
        why.append("no sé dónde se consigue la receta" if src.way == "desconocida" else src.text)
    if src.rep_gap:
        rank = max(rank, 3 if src.rep_gap >= 2 else 2)
        why.append(f"pide {src.reputation}")
    if src.currency_short:
        rank = max(rank, 2)
        why.append(src.currency_short)
    if not why:
        why.append(f"solo falta aprender la receta ({src.text})")
    return ("amarillo", "naranja", "rojo")[rank - 1], gap, why


def _craft_candidates(ctx: _Context, reviews: Reviews) -> list[CraftResult]:
    a = ctx.a
    catalog_outputs = set()
    for m in a.guide_methods:
        if m.entry.kind == "crafteo":
            catalog_outputs.update(i.item_id for i in m.items if i.item_id)
    best: dict[int, CraftResult] = {}
    for c in a.crafts:
        if not c.complete or not c.output_item_id:
            continue
        s = c.output_signals
        wanted = c.recipe_id in reviews.crafts or c.output_item_id in catalog_outputs
        if c.profit <= 0 and not wanted:
            continue
        if s is not None and s.sales_per_day == 0 and not (c.known or wanted):
            continue
        current = best.get(c.output_item_id)
        rank = (c.known, c.recipe_id in reviews.crafts, c.profit)
        if current is None or rank > (current.known, current.recipe_id in reviews.crafts, current.profit):
            best[c.output_item_id] = c

    def day_value(c: CraftResult) -> float:
        cap = c.capacity
        return cap.gold_per_day if cap is not None else c.profit / 10

    must = [c for c in best.values() if c.known or c.recipe_id in reviews.crafts
            or c.output_item_id in catalog_outputs]
    rest = sorted((c for c in best.values() if c not in must), key=day_value, reverse=True)
    mine = [c for c in rest if c.yours]
    others: dict[int, list[CraftResult]] = {}
    for c in rest:
        if not c.yours and c.skill_line is not None:
            others.setdefault(c.skill_line, []).append(c)
    extra = [c for group in others.values() for c in group[:3]]
    chosen = must + mine + sorted(extra, key=day_value, reverse=True)
    return chosen[:max(MAX_CRAFT_ROWS, len(must))]


def _craft_rows(ctx: _Context, reviews: Reviews) -> list[CraftRow]:
    a, conn = ctx.a, ctx.conn
    vendors = _vendor_rows(conn)
    checks = {r["item_id"]: r for r in conn.execute("SELECT item_id, status, detail FROM vendor_checks")}
    item_info = {r["item_id"]: (r["min_faction"], r["min_reputation"]) for r in conn.execute(
        "SELECT item_id, min_faction, min_reputation FROM gd_items WHERE min_faction IS NOT NULL")}
    by_key = {ch.key: ch for ch in ctx.chars}
    rows = []
    for c in _craft_candidates(ctx, reviews):
        review = reviews.crafts.get(c.recipe_id)
        row = CraftRow(recipe_id=c.recipe_id, name=c.output_name or c.name, profession=c.profession or "?",
                       skill_line=c.skill_line, required=c.required_skill or 0, known_by=list(c.known_by),
                       output_id=c.output_item_id, output_qty=c.output_qty, cooldown_hours=c.cooldown_hours)
        row.score = review.score if review else None
        row.profit_item = round(c.profit / c.output_qty)
        out = a.prices.get(c.output_item_id)
        row.sell_price = out.sale_price if out else None
        approx = []
        if out is None or not out.has_history:
            approx.append("el precio de venta es de pocos escaneos")
        for r in c.reagents:
            p = a.prices.get(r.item_id) if r.item_id else None
            if r.source == "subasta" and (p is None or not p.has_history):
                approx.append("algún material tiene precio de pocos escaneos")
                break
        row.approx, row.approx_why = bool(approx), "; ".join(approx)
        cap = c.capacity
        if cap is not None:
            row.per_day, row.gold_day, row.minutes_day = cap.units_per_day, cap.gold_per_day, cap.minutes_per_day
            row.crafts_day = max(1, math.floor(cap.units_per_day / max(c.output_qty, 1)))
        for r in c.reagents:
            v = vendors.get(r.item_id) if r.item_id else None
            row.reagents.append(ReagentRow(item_id=r.item_id, name=r.name, quantity=r.quantity,
                                           unit_price=r.unit_cost, source=r.source,
                                           vendor=v["vendor"] if v is not None and r.source == "vendedor" else None,
                                           zone=v["zone"] if v is not None and r.source == "vendedor" else None))

        if c.known:
            crafter = by_key.get(c.known_by[0])
            row.color, row.who = "verde", c.known_by[0]
            row.who_name = crafter.name if crafter else c.known_by[0].split("-")[0]
            row.who_skill = crafter.skills.get(c.skill_line, 0) if crafter and c.skill_line else 0
            row.recipe = _recipe_source(ctx, c, crafter, vendors, checks, review, item_info)
        else:
            options = []
            for ch in ctx.chars or [None]:
                src = _recipe_source(ctx, c, ch, vendors, checks, review, item_info)
                color, gap, why = _status(ctx, c, ch, src)
                options.append((COLOR_RANK[color], gap, -(ch.level if ch else 0), color, ch, src, why))
            options.sort(key=lambda o: o[:3])
            _, gap, _, color, ch, src, why = options[0]
            row.color, row.gap, row.recipe = color, gap, src
            if ch is not None:
                row.who, row.who_name = ch.key, ch.name
                row.who_skill = ch.skills.get(c.skill_line, 0) if c.skill_line else 0
                if gap and c.skill_line is not None:
                    prep = _Prep(char=ch)
                    _profession_prep(ctx, prep, c.skill_line, row.required)
                    row.prep = prep.lines
            row.prep[:0] = [f"{(row.who_name or 'Tu personaje')}: {w}." for w in why]
        _craft_details(row, c, review)
        rows.append(row)
    rows.sort(key=lambda r: (COLOR_RANK[r.color], -(r.gold_day or 0), -(r.profit_item or 0)))
    return rows


def _craft_details(row: CraftRow, c: CraftResult, review: Review | None) -> None:
    d = row.details
    if review is not None:
        if review.why:
            d.append(f"Asesor ({review.score}/10): {review.why}")
        d += [f"{n}. {step}" for n, step in enumerate(review.steps, 1)]
    d.append(f"Beneficio: {format_money(row.profit_item)} por unidad (se vende a {format_money(row.sell_price)}, "
             f"materiales {format_money(round(c.cost / c.output_qty))})"
             + (f". Aproximado: {row.approx_why}" if row.approx else "") + ".")
    if row.per_day is not None:
        cap = c.capacity
        limit = "su espera" if cap.by_cooldown else "el mercado"
        d.append(f"Por {limit}: unas {row.per_day:.1f} al día, ~{format_money(row.gold_day)} en "
                 f"~{row.minutes_day:.0f} min.")
    else:
        d.append("Aún no sé cuántas se venden al día: empieza con pocas.")
    if row.cooldown_hours:
        d.append(f"Tiene una espera de {_hours(row.cooldown_hours)} entre fabricaciones.")
    if row.recipe is not None and row.recipe.way != "aprendida":
        d.append(f"Receta: {row.recipe.text}" + (f"; pide {row.recipe.reputation}" if row.recipe.reputation else "")
                 + ".")


# El mejor farmeo ------------------------------------------------------------------------

def _verdict(farms: list[FarmRow], crafts: list[CraftRow], best_value: int | None, floor: int,
             a: Analysis, has_chars: bool = True) -> Verdict:
    usable = [r for r in farms if r.value is not None and not r.pending]
    if not usable:
        lines = []
        if not a.last_scan:
            lines.append("Escanea la subasta (botón «PG: Completo»).")
        if not any(r.per_hour is not None for r in farms):
            lines.append("Los métodos guardados aún no tienen estimación por hora: pídele al asesor que los revise.")
        return Verdict("sin_datos", "Aún no puedo decirte el mejor farmeo", lines)
    if not has_chars:
        lines = ["Entra con cada personaje (sus datos se guardan al cambiar de uno a otro): así sabré quién "
                 "puede hacer cada farmeo."]
        if not a.last_scan:
            lines.append("Escanea también la subasta (botón «PG: Completo»): sin ella solo cuento lo que paga el vendedor.")
        lines.append("Mientras, los que más rinden sobre el papel:")
        for r in sorted(usable, key=lambda r: -r.value)[:3]:
            lines.append(f"- {r.name}: ~{format_money(r.per_hour)}/h" + (f" ({r.requirement})." if r.requirement else "."))
        return Verdict("sin_datos", "Aún no conozco tus personajes", lines)
    if best_value is None or best_value < floor:
        return Verdict("investigar", "Ningún método guardado da dinero ahora",
                       [f"Ninguno llega a {format_money(floor)}/h con tus precios: o se han saturado o ya no funcionan.",
                        "Toca investigar: abre el asesor y dile «investiga»."])
    quick = [c for c in crafts if c.color == "verde" and c.gold_day and c.gold_day > 0][:3]
    quick_lines = [f"Antes, fabrica {c.crafts_day} × {c.name} con {c.who_name}: ~{format_money(c.gold_day)} "
                   f"en ~{c.minutes_day:.0f} min." for c in quick]
    ready = sorted((r for r in usable if r.ready), key=lambda r: -r.value)
    top = ready[0] if ready else None
    if top is not None and top.value >= max(floor, GREEN_SHARE * best_value):
        star = "" if top.measured else " (estimado)"
        lines = [f"{format_money(top.per_hour)}/h{star} con {top.who}" + (f", en {top.zone}" if top.zone else "") + "."]
        return Verdict("mejor", f"Mejor farmeo: {top.name}", lines + quick_lines, best=top.key)
    lines = []
    if top is not None:
        lines.append(f"Lo mejor que puedes hacer ya: {top.name}, ~{format_money(top.per_hour)}/h.")
    else:
        lines.append("Ninguno de los que dan dinero lo puedes hacer todavía.")
    lines.append("Rinden más, si te preparas:")
    better = sorted((r for r in usable if not r.ready and (top is None or r.value > top.value)),
                    key=lambda r: -r.value)[:3]
    for r in better:
        cost = f"~{_hours(r.prep_hours)}" + (f" y ~{format_money(r.prep_gold)}" if r.prep_gold else "")
        if r.closest:
            lines.append(f"- {r.name}: ~{format_money(r.per_hour)}/h. {r.closest}: le falta {'; '.join(r.lacking)} ({cost}).")
        else:
            lines.append(f"- {r.name}: ~{format_money(r.per_hour)}/h. Pide {r.requirement or 'algo que no tiene nadie'}.")
    return Verdict("preparar", "Lo que ya puedes hacer rinde poco", lines + quick_lines,
                   best=top.key if top is not None else None)


def build_panel(conn: sqlite3.Connection, a: Analysis, settings: Settings | None = None,
                reviews: Reviews | None = None, routes: dict[int, list[Stretch]] | None = None) -> Panel:
    settings = settings or load_settings(conn)
    panel = Panel()
    if reviews is None:
        try:
            reviews = load_reviews()
        except CatalogError as exc:
            reviews = Reviews()
            panel.problems.append(str(exc))
    if routes is None:
        try:
            routes = load_routes()
        except (CatalogError, KeyError, TypeError, ValueError) as exc:
            routes = {}
            panel.problems.append(f"recoleccion.json: {exc}")
    ctx = _context(conn, a, settings, routes)
    floor = round(settings.min_gold_hour * 10000)
    panel.farms = _farm_rows(ctx, reviews)
    best = _color_farms(panel.farms, floor)
    panel.farms.sort(key=lambda r: (r.pending != "", r.value is None, -(r.value or 0)))
    panel.crafts = _craft_rows(ctx, reviews)
    panel.verdict = _verdict(panel.farms, panel.crafts, best, floor, a, has_chars=bool(ctx.chars))
    panel.unreviewed = ([r.key for r in panel.farms if r.score is None and not r.key.startswith("medido:")]
                        + [str(c.recipe_id) for c in panel.crafts if c.score is None])
    return panel


# Para el addon y para el asesor ----------------------------------------------------------

def _money_or(value: int | None, star: bool = False) -> str:
    return "?" if value is None else format_money(value) + ("*" if star else "")


def panel_export(panel: Panel) -> dict:
    """La ventana de métodos en tablas sencillas, para escribirlas en Generated.lua."""
    v = panel.verdict
    farms = [{
        "key": r.key, "name": r.name, "kind": r.kind, "score": r.score, "color": r.color,
        "gph": r.per_hour, "gphWeek": r.per_hour_week, "measured": r.measured, "who": r.who,
        "req": r.requirement, "closest": r.closest, "lacking": "; ".join(r.lacking),
        "level": r.level or None, "minLevel": r.min_level or None, "pending": bool(r.pending),
        "details": r.details,
    } for r in panel.farms]
    crafts = []
    for c in panel.crafts:
        src = c.recipe
        crafts.append({
            "recipe": c.recipe_id, "name": c.name, "prof": c.profession, "line": c.skill_line,
            "score": c.score, "profit": c.profit_item, "approx": c.approx,
            "perDay": round(c.per_day, 1) if c.per_day is not None else None, "goldDay": c.gold_day,
            "minutes": round(c.minutes_day) if c.minutes_day is not None else None, "craftsDay": c.crafts_day,
            "color": c.color, "who": c.who, "whoName": c.who_name, "skill": c.who_skill,
            "required": c.required, "gap": c.gap, "knownBy": c.known_by,
            "learn": None if src is None else {
                "way": src.way, "text": src.text, "item": src.item_id, "itemName": src.item_name,
                "price": src.price, "vendor": src.vendor, "zone": src.zone, "rep": src.reputation},
            "reagents": [{"id": r.item_id, "name": r.name, "qty": r.quantity, "price": r.unit_price,
                          "src": r.source, "vendor": r.vendor, "zone": r.zone} for r in c.reagents],
            "output": c.output_id, "outputQty": c.output_qty, "sellPrice": c.sell_price,
            "cooldown": c.cooldown_hours, "prep": c.prep, "details": c.details,
        })
    return {"verdict": {"state": v.state, "title": v.title, "lines": v.lines, "best": v.best},
            "farms": farms, "crafts": crafts}


def render_panel(panel: Panel) -> str:
    """datos/panel.md: lo mismo que la ventana del addon, para leerlo en el PC o que lo revise el asesor."""
    v = panel.verdict
    out = ["# Métodos", "", "Lo mismo que enseña la ventana de métodos del addon. * = estimado, sin medir.", "",
           f"## {v.title}", ""]
    out += v.lines + [""]
    for p in panel.problems:
        out += [f"**Aviso:** {p}", ""]
    out += ["## Farmeos", "", "| id | Método | Nota | Color | Oro/h | Quién puede | Requisito | Nivel |",
            "|---|---|---|---|---|---|---|---|"]
    for r in panel.farms:
        who = r.who or (f"nadie ({r.closest}: {'; '.join(r.lacking)})" if r.closest else "nadie")
        level = f"{r.level}" + (f" (desde {r.min_level})" if r.min_level and r.min_level != r.level else "")
        out.append(f"| `{r.key}` | {r.name}{' (en espera)' if r.pending else ''} | {r.score or ''} | "
                   f"{r.color or 'sin datos'} | {_money_or(r.per_hour, not r.measured)} | {who} | {r.requirement} | "
                   f"{level if r.level else ''} |")
    out += ["", "## Crafteos", "", "| Receta | Objeto | Nota | Beneficio/u | Al día | Color | Quién | Qué falta |",
            "|---|---|---|---|---|---|---|---|"]
    for c in panel.crafts:
        per_day = f"{c.per_day:.1f}" if c.per_day is not None else "?"
        missing = "; ".join(c.prep[:2]) if c.color != "verde" else ""
        out.append(f"| {c.recipe_id} | {c.name} ({c.profession}) | {c.score or ''} | "
                   f"{_money_or(c.profit_item, c.approx)} | {per_day} | {c.color} | {c.who_name or ''} | {missing} |")
    if panel.unreviewed:
        out += ["", "## Sin revisar por el asesor", "", ", ".join(f"`{k}`" for k in panel.unreviewed)]
    out += ["", "## Detalle", ""]
    for r in panel.farms:
        out += [f"### {r.name} (`{r.key}`)", ""] + [f"- {d}" for d in r.details] + [""]
    for c in panel.crafts:
        out += [f"### {c.name} (receta {c.recipe_id})", ""] + [f"- {d}" for d in c.prep + c.details] + [""]
    return "\n".join(out).rstrip() + "\n"
