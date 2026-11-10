"""Rentabilidad de las recetas: coste de los materiales frente a lo que se saca vendiendo.

Las recetas salen de dos sitios: las que el addon ha visto al abrir tus profesiones
(tabla recipes) y las de los datos del juego (gd_recipes), que incluyen las de
profesiones que no tienes. Si una receta está en los dos, mandan los datos de partida,
y los del juego añaden los niveles de habilidad y el objeto con el que se aprende.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from .pricing import ItemPrice

# Enum.TradeskillRelativeDifficulty: cuánto sube la habilidad al fabricar.
DIFFICULTY = {0: "naranja", 1: "amarilla", 2: "verde", 3: "gris"}
BASIC_REAGENT = 1             # Enum.CraftingReagentType.Basic
ACQUIRE_WITH_PROFESSION = 1   # gd_recipes.acquire: se aprende sola al aprender la profesión


@dataclass
class Reagent:
    name: str
    quantity: int
    item_id: int | None = None
    currency_id: int | None = None
    unit_cost: int | None = None
    source: str | None = None   # subasta, vendedor o divisa
    owned: int = 0


@dataclass
class CraftResult:
    recipe_id: int
    name: str
    profession: str | None
    output_item_id: int | None
    output_name: str | None = None
    output_qty: float = 1.0
    reagents: list[Reagent] = field(default_factory=list)
    known_by: list[str] = field(default_factory=list)
    difficulty: int | None = None
    source: str | None = None      # cómo se aprende
    cost: int | None = None        # materiales comprados al mejor precio
    value: int | None = None       # lo que se cobra vendiendo lo fabricado, ya sin comisión
    missing: list[ItemPrice] = field(default_factory=list)   # materiales sin precio
    currencies: list[str] = field(default_factory=list)
    craftable_now: int = 0         # fabricaciones posibles con lo que ya tienes
    output_listed: int | None = None
    skill_line: int | None = None
    yours: bool = False            # alguno de tus personajes tiene esta profesión
    required_skill: int | None = None
    skill_unknown: bool = False    # de instructor: Forever no publica a qué nivel se aprende (required_skill dice 1)
    trainer_level: int | None = None   # nivel de personaje que pide el instructor, si lo hemos visto
    trainer_cost: int | None = None
    yellow: int | None = None      # nivel al que deja de ser naranja
    grey: int | None = None        # nivel al que deja de dar puntos
    learn_item_id: int | None = None
    learn_item_name: str | None = None
    learn_price: int | None = None  # lo que cuesta el objeto de aprendizaje (subasta o vendedor)
    output_signals: object | None = None  # MarketSignals de lo fabricado (lo rellena analysis)
    capacity: object | None = None        # business.Capacity: cuánto da al día como máximo
    profit_later: int | None = None        # beneficio con el precio previsto a 36 horas
    cooldown_hours: float | None = None   # espera entre fabricaciones (tela lunar, transmutaciones...)
    cooldown_category: int | None = None  # las recetas de la misma categoría comparten la espera

    @property
    def known(self) -> bool:
        return bool(self.known_by)

    @property
    def complete(self) -> bool:
        return self.cost is not None and self.value is not None

    @property
    def profit(self) -> int | None:
        return self.value - self.cost if self.complete else None

    @property
    def margin(self) -> float | None:
        if not self.complete or not self.cost:
            return None
        return self.profit / self.cost

    @property
    def green(self) -> int | None:
        if self.yellow is None or self.grey is None:
            return None
        return (self.yellow + self.grey) // 2

    @property
    def crafts_per_day(self) -> float | None:
        """Fabricaciones al día que permite la espera, contando a todos los que saben hacerla
        (o a uno solo si nadie la sabe todavía). None si no tiene espera."""
        if not self.cooldown_hours:
            return None
        return max(1, len(self.known_by)) * 24 / self.cooldown_hours

    @property
    def difficulty_name(self) -> str | None:
        return DIFFICULTY.get(self.difficulty) if self.difficulty is not None else None


def profession_levels(conn: sqlite3.Connection) -> dict[int, list[tuple[str, int]]]:
    """Por profesión (skill line), qué personajes la tienen y a qué nivel, del más alto al más bajo."""
    levels: dict[int, dict[str, int]] = {}
    for r in conn.execute("SELECT char_key, skill_line, rank FROM profession_summary"):
        levels.setdefault(r["skill_line"], {})[r["char_key"]] = r["rank"] or 0
    for r in conn.execute("SELECT char_key, parent_id, skill FROM professions WHERE parent_id IS NOT NULL"):
        current = levels.setdefault(r["parent_id"], {})
        current[r["char_key"]] = max(current.get(r["char_key"], 0), r["skill"] or 0)
    return {line: sorted(chars.items(), key=lambda kv: -kv[1]) for line, chars in levels.items()}


def recipe_item_ids(conn: sqlite3.Connection) -> set[int]:
    queries = [
        "SELECT item_id FROM recipe_reagents WHERE item_id IS NOT NULL",
        "SELECT output_item_id FROM recipes WHERE output_item_id IS NOT NULL",
        "SELECT item_id FROM gd_reagents",
        "SELECT output_item_id FROM gd_recipes WHERE output_item_id IS NOT NULL",
        "SELECT learn_item_id FROM gd_recipes WHERE learn_item_id IS NOT NULL",
    ]
    return {row[0] for q in queries for row in conn.execute(q)}


def _add_item_reagent(result: CraftResult, options: list[ItemPrice], quantity: int,
                      owned: dict[int, int]) -> None:
    """Añade un material; si el hueco acepta varios objetos, usa el más barato."""
    if not options:
        return
    priced = [p for p in options if p.buy_price is not None]
    best = min(priced, key=lambda p: p.buy_price) if priced else options[0]
    reagent = Reagent(name=best.name, quantity=quantity, item_id=best.item_id, unit_cost=best.buy_price,
                      source=best.buy_source, owned=owned.get(best.item_id, 0))
    result.reagents.append(reagent)
    if reagent.unit_cost is None:
        result.missing.append(best)


def _finish(result: CraftResult, prices: dict[int, ItemPrice]) -> None:
    out_price = prices.get(result.output_item_id) if result.output_item_id else None
    if out_price:
        result.output_name = out_price.name
        result.output_listed = out_price.quantity
        candidates = [v for v in (out_price.net_sale, out_price.vendor_sell) if v]
        if candidates:
            result.value = round(max(candidates) * result.output_qty)
    if not result.missing:
        result.cost = round(sum(r.unit_cost * r.quantity for r in result.reagents if r.unit_cost is not None))
    item_reagents = [r for r in result.reagents if r.item_id is not None]
    if item_reagents:
        result.craftable_now = min(r.owned // r.quantity for r in item_reagents)


def evaluate_recipes(conn: sqlite3.Connection, prices: dict[int, ItemPrice],
                     owned: dict[int, int]) -> list[CraftResult]:
    currency_names = {r["currency_id"]: r["name"]
                      for r in conn.execute("SELECT DISTINCT currency_id, name FROM currencies")}

    crafters: dict[int, list[tuple[str, int | None]]] = defaultdict(list)
    for r in conn.execute("SELECT char_key, recipe_id, difficulty FROM known_recipes"):
        crafters[r["recipe_id"]].append((r["char_key"], r["difficulty"]))

    owned_lines = {r[0] for r in conn.execute(
        "SELECT skill_line FROM profession_summary UNION SELECT parent_id FROM professions "
        "UNION SELECT profession_id FROM professions") if r[0]}

    slots: dict[int, dict[int, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    for r in conn.execute("SELECT * FROM recipe_reagents ORDER BY recipe_id, slot"):
        slots[r["recipe_id"]][r["slot"]].append(r)

    game = {r["spell_id"]: r for r in conn.execute(
        "SELECT r.*, s.name AS line_name FROM gd_recipes r JOIN gd_skill_lines s USING (skill_line)")}
    game_reagents: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for r in conn.execute("SELECT spell_id, item_id, quantity FROM gd_reagents"):
        game_reagents[r["spell_id"]].append((r["item_id"], r["quantity"]))
    learn_rank = {r["item_id"]: r["required_skill_rank"] for r in conn.execute(
        "SELECT item_id, required_skill_rank FROM gd_items "
        "WHERE item_id IN (SELECT learn_item_id FROM gd_recipes)")}
    trainers = {(r["skill_name"], r["name"]): r for r in conn.execute("SELECT * FROM trainer_recipes")}

    def apply_common(result: CraftResult, game_row: sqlite3.Row | None, fallback_line: int | None) -> None:
        crafted_by = crafters.get(result.recipe_id, [])
        result.known_by = sorted(k for k, _ in crafted_by)
        levels = [d for _, d in crafted_by if d is not None]
        result.difficulty = min(levels) if levels else None
        result.skill_line = fallback_line
        if game_row is not None:
            result.skill_line = game_row["skill_line"]
            result.yellow, result.grey = game_row["yellow"], game_row["grey"]
            result.cooldown_hours = game_row["cooldown_hours"]
            result.cooldown_category = game_row["cooldown_category"]
            required = game_row["min_skill"] or 0
            learn_id = game_row["learn_item_id"]
            if learn_id:
                learn = prices.get(learn_id)
                result.learn_item_id = learn_id
                result.learn_item_name = learn.name if learn else None
                result.learn_price = learn.buy_price if learn else None
                required = max(required, learn_rank.get(learn_id) or 0)
            # Lo visto en el instructor manda: es el único dato real de las recetas sin patrón.
            trainer = None if learn_id else (trainers.get((game_row["line_name"], game_row["name"]))
                                             or trainers.get((game_row["line_name"], result.name)))
            if trainer is not None:
                required = max(required, trainer["rank"] or 0)
                result.trainer_level, result.trainer_cost = trainer["level"], trainer["cost"]
            result.required_skill = required or None
            result.skill_unknown = (trainer is None and not learn_id and required <= 1
                                    and game_row["acquire"] != ACQUIRE_WITH_PROFESSION)
            if not result.source:
                if learn_id:
                    result.source = f"Se aprende con «{result.learn_item_name}»"
                elif game_row["acquire"] == ACQUIRE_WITH_PROFESSION:
                    result.source = "Se aprende al aprender la profesión"
                else:
                    result.source = "Instructor de la profesión"
        result.yours = result.known or (result.skill_line in owned_lines)

    results = []
    seen = set()
    for rec in conn.execute("SELECT * FROM recipes"):
        rid = rec["recipe_id"]
        seen.add(rid)
        game_row = game.get(rid)
        result = CraftResult(
            recipe_id=rid, name=rec["name"], profession=rec["profession_name"],
            output_item_id=rec["output_item_id"], source=rec["source_plain"],
            output_qty=((rec["qty_min"] or 1) + (rec["qty_max"] or rec["qty_min"] or 1)) / 2,
        )
        for slot_rows in slots.get(rid, {}).values():
            first = slot_rows[0]
            if first["required"] == 0 and first["reagent_type"] != BASIC_REAGENT:
                continue  # material opcional
            quantity = first["quantity"] or 1
            if first["currency_id"] is not None:
                name = currency_names.get(first["currency_id"], f"divisa {first['currency_id']}")
                result.currencies.append(f"{quantity} {name}")
                result.reagents.append(Reagent(name=name, quantity=quantity,
                                               currency_id=first["currency_id"], source="divisa"))
                continue
            options = [prices[r["item_id"]] for r in slot_rows if r["item_id"] in prices]
            _add_item_reagent(result, options, quantity, owned)
        apply_common(result, game_row, rec["parent_profession_id"])
        _finish(result, prices)
        results.append(result)

    # Recetas que el addon no ha visto: las de profesiones que no tienes o que no has abierto.
    for rid, g in game.items():
        if rid in seen:
            continue
        result = CraftResult(recipe_id=rid, name=g["name"], profession=g["line_name"],
                             output_item_id=g["output_item_id"], output_qty=g["output_qty"] or 1.0)
        for item_id, quantity in game_reagents.get(rid, []):
            _add_item_reagent(result, [prices[item_id]] if item_id in prices else [], quantity, owned)
        apply_common(result, g, None)
        _finish(result, prices)
        results.append(result)
    return results
