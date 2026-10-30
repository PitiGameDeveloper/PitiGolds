"""Guía de subida de profesión: qué fabricar en cada tramo para subir lo más barato posible.

Probabilidad de subir un punto al fabricar una receta, según su color a tu nivel:
  naranja (por debajo de `yellow`): siempre;
  amarilla y verde: (gris - nivel) / (gris - amarilla), de 1 en el paso a amarilla a 0 en gris;
  gris: nunca.
El talento de Legacy que sube la probabilidad multiplica la de las amarillas y verdes (sin
pasar de 1): con un +20 %, una receta al 50 % pasa al 60 %. Cuánto da exactamente está por
confirmar en el juego; se ajusta con python -m motor ajustes --legado-subida N.
Las recetas con espera de una hora o más (tela lunar, transmutaciones) no sirven para subir.
En cada nivel se elige la receta con menor coste esperado por punto:
  (coste de los materiales - lo que recuperas vendiendo lo fabricado) / probabilidad.
Como cada nivel se decide por separado, la suma es el coste esperado mínimo (sin contar lo que
cobra el instructor por enseñar las recetas, que no viene en los datos del juego).

Lo recuperado se cuenta a lo que paga un vendedor, que es seguro; venderlo en la subasta puede
dar más, pero fabricar 40 piezas iguales no se vende en un día.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .crafting import CraftResult
from .pricing import ItemPrice

CRAFT_SECONDS = 3.5        # lo que tarda cada fabricación
BUY_SECONDS = 30           # buscar y comprar cada material distinto en la subasta
MAX_COOLDOWN_HOURS = 1     # con una espera de una hora o más, la receta no sirve para subir


def skill_up_chance(skill: int, yellow: int | None, grey: int | None, bonus: float = 0.0) -> float:
    """bonus: lo que suma el talento de Legacy (0.2 = +20 %)."""
    if yellow is None or grey is None:
        return 1.0
    if skill >= grey:
        return 0.0
    if skill < yellow or grey <= yellow:
        return 1.0
    return min(1.0, (grey - skill) / (grey - yellow) * (1 + bonus))


@dataclass
class LevelStep:
    recipe: CraftResult
    start: int
    end: int                  # nivel al que llegas
    crafts: float             # fabricaciones esperadas
    cost: int                 # materiales al precio de compra
    recovered: int            # lo que paga un vendedor por lo fabricado

    @property
    def crafts_rounded(self) -> int:
        return math.ceil(self.crafts - 1e-9)


@dataclass
class ShoppingItem:
    item_id: int
    name: str
    needed: int
    owned: int
    unit_cost: int | None
    source: str | None

    @property
    def to_buy(self) -> int:
        return max(0, self.needed - self.owned)

    @property
    def cash(self) -> int | None:
        return None if self.unit_cost is None else self.to_buy * self.unit_cost


@dataclass
class LevelingPlan:
    profession: str
    skill_line: int | None
    start: int
    target: int
    bonus: float = 0.0        # talento de Legacy que sube la probabilidad
    steps: list[LevelStep] = field(default_factory=list)
    gaps: list[tuple[int, int]] = field(default_factory=list)   # tramos sin receta con precio
    shopping: list[ShoppingItem] = field(default_factory=list)
    learn: list[tuple[str, int | None]] = field(default_factory=list)  # (objeto de aprendizaje, precio)

    @property
    def complete(self) -> bool:
        return not self.gaps and bool(self.steps or self.start >= self.target)

    @property
    def crafts(self) -> int:
        return sum(s.crafts_rounded for s in self.steps)

    @property
    def materials_cost(self) -> int:
        return sum(s.cost for s in self.steps)

    @property
    def recovered(self) -> int:
        return sum(s.recovered for s in self.steps)

    @property
    def learn_cost(self) -> int:
        return sum(price or 0 for _, price in self.learn)

    @property
    def cash_needed(self) -> int:
        """Oro que tienes que gastar: lo que te falta comprar más los objetos de aprendizaje."""
        return sum(i.cash or 0 for i in self.shopping) + self.learn_cost

    @property
    def net_cost(self) -> int:
        """Coste real: todos los materiales (también los tuyos, que podrías vender) menos lo recuperado."""
        return self.materials_cost - self.recovered + self.learn_cost

    @property
    def hours(self) -> float:
        buys = sum(1 for i in self.shopping if i.to_buy)
        return (self.crafts * CRAFT_SECONDS + buys * BUY_SECONDS) / 3600


def plan_leveling(crafts: list[CraftResult], prices: dict[int, ItemPrice], owned: dict[int, int],
                  skill_line: int, start: int, target: int, known: set[int] | None = None,
                  bonus: float = 0.0) -> LevelingPlan:
    """Camino más barato de `start` a `target` con las recetas de una profesión.
    `known`: recetas que ya sabe el personaje (no hay que pagar por aprenderlas).
    `bonus`: talento de Legacy que sube la probabilidad (0.2 = +20 %)."""
    known = known or set()
    options = [c for c in crafts if c.skill_line == skill_line and c.cost is not None
               and c.required_skill is not None and c.grey is not None
               and (c.cooldown_hours or 0) < MAX_COOLDOWN_HOURS]
    profession = next((c.profession for c in crafts if c.skill_line == skill_line and c.profession), "?")
    plan = LevelingPlan(profession=profession, skill_line=skill_line, start=start, target=target, bonus=bonus)

    def recovery(c: CraftResult) -> int:
        p = prices.get(c.output_item_id) if c.output_item_id else None
        return round((p.vendor_sell or 0) * c.output_qty) if p else 0

    def per_point(c: CraftResult, skill: int) -> float | None:
        chance = skill_up_chance(skill, c.yellow, c.grey, bonus)
        if chance <= 0 or c.required_skill > max(skill, 1):
            return None
        learn = 0 if c.recipe_id in known or c.learn_price is None else c.learn_price
        # El objeto de aprendizaje se reparte entre los niveles que le quedan a la receta.
        return (c.cost - recovery(c)) / chance + learn / max(1, c.grey - skill)

    gap_start = None
    for skill in range(start, target):
        scored = [(per_point(c, skill), c) for c in options]
        scored = [(v, c) for v, c in scored if v is not None]
        if not scored:
            gap_start = skill if gap_start is None else gap_start
            continue
        if gap_start is not None:
            plan.gaps.append((gap_start, skill))
            gap_start = None
        _, best = min(scored, key=lambda vc: (vc[0], vc[1].recipe_id))
        crafts = 1 / skill_up_chance(skill, best.yellow, best.grey, bonus)
        last = plan.steps[-1] if plan.steps else None
        if last is not None and last.recipe.recipe_id == best.recipe_id and last.end == skill:
            last.end = skill + 1
            last.crafts += crafts
        else:
            last = LevelStep(recipe=best, start=skill, end=skill + 1, crafts=crafts, cost=0, recovered=0)
            plan.steps.append(last)
    if gap_start is not None:
        plan.gaps.append((gap_start, target))

    needed: dict[int, int] = {}
    for step in plan.steps:
        n = step.crafts_rounded
        step.cost = step.recipe.cost * n
        step.recovered = recovery(step.recipe) * n
        for r in step.recipe.reagents:
            if r.item_id is not None:
                needed[r.item_id] = needed.get(r.item_id, 0) + r.quantity * n
        if step.recipe.recipe_id not in known and step.recipe.learn_item_name:
            entry = (step.recipe.learn_item_name, step.recipe.learn_price)
            if entry not in plan.learn:
                plan.learn.append(entry)
    for item_id, n in sorted(needed.items(), key=lambda kv: -kv[1]):
        p = prices.get(item_id)
        plan.shopping.append(ShoppingItem(item_id=item_id, name=p.name if p else f"objeto {item_id}", needed=n,
                                          owned=owned.get(item_id, 0), unit_cost=p.buy_price if p else None,
                                          source=p.buy_source if p else None))
    return plan
