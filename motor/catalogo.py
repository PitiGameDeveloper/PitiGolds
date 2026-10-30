"""Métodos de tus guías: lo que cuentan guías, vídeos y otras fuentes, cruzado con tus datos.

El catálogo (conocimiento/metodos.json) apunta qué se farmea, dónde, a qué nivel, con qué
profesión y qué objetos dan el dinero. Las cifras de oro por hora de las guías no se usan:
cada servidor es distinto, así que cada método se valora con tus precios:

  - qué valen hoy sus objetos en la subasta (o lo que paga el vendedor por ellos),
  - cuánto se vende de ellos al día (lo máximo que el mercado te deja sacar),
  - si alguno de tus personajes puede hacerlo ya (nivel y profesiones),
  - y, cuando lo mides con /pg farmeo <id>, tu oro por hora de verdad.

Los objetos se buscan por su nombre en inglés o en español en los datos del juego, así que
el catálogo se puede rellenar copiando los nombres de una guía en inglés.
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .business import MARKET_SHARE
from .crafting import CraftResult, profession_levels
from .farming import FarmSummary
from .pricing import ItemPrice

CATALOG_PATH = Path(__file__).resolve().parent.parent / "conocimiento" / "metodos.json"

KINDS = {
    "farmeo": "Farmeos", "pesca": "Pesca", "mazmorra": "Mazmorras", "crafteo": "Crafteos",
    "inversion": "Para invertir", "vendedor": "Vendedores con existencias limitadas", "diario": "Cada día",
}
TIME_KINDS = ("farmeo", "pesca", "mazmorra")   # ocupan tu tiempo: se miden con /pg farmeo


@dataclass
class CatalogEntry:
    id: str
    name: str
    kind: str
    level: int = 0
    zone: str = ""
    professions: list[tuple[int, int]] = field(default_factory=list)   # (profesión, nivel), todas
    any_profession: list[int] = field(default_factory=list)            # basta con una de ellas
    better_with: list[int] = field(default_factory=list)               # ayudan, pero no hacen falta
    items: list[str] = field(default_factory=list)
    item_ids: dict[str, int] = field(default_factory=dict)   # los que el catálogo da con su número
    vendor: str = ""
    quantity: float = 1.0
    requirement: str = ""
    notes: str = ""
    source: str = ""
    added: str = ""


class CatalogError(ValueError):
    """El catálogo no se puede leer (JSON roto)."""


def _read(path: Path) -> list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{path.name} no es un JSON válido (línea {exc.lineno}: {exc.msg})") from exc
    methods = data.get("metodos", []) if isinstance(data, dict) else None
    if not isinstance(methods, list):
        raise CatalogError(f"{path.name} debe tener una lista «metodos»")
    return methods


def catalog_problems(path: Path = CATALOG_PATH, known_lines: set[int] | None = None) -> list[str]:
    """Lo que está mal en el catálogo, en frases (vacío si está bien). known_lines: las
    profesiones que existen según los datos del juego, para comprobar sus números."""
    try:
        methods = _read(path)
    except CatalogError as exc:
        return [str(exc)]
    problems, seen = [], set()

    def check_line(where: str, line) -> None:
        if not isinstance(line, int):
            problems.append(f"{where}: la profesión debe ser un número (393 Desollar, 182 Botánica...)")
        elif known_lines is not None and line not in known_lines:
            problems.append(f"{where}: no existe la profesión {line}")

    for n, m in enumerate(methods, 1):
        if not isinstance(m, dict):
            problems.append(f"método {n}: debe ser un objeto {{...}}")
            continue
        where = f"«{m.get('id') or m.get('nombre') or n}»"
        ident = m.get("id")
        if not ident or not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", ident):
            problems.append(f"{where}: el id debe ser minúsculas, números y guiones (ej. «perla-azul»)")
        elif ident in seen:
            problems.append(f"{where}: id repetido")
        seen.add(ident)
        if not m.get("nombre"):
            problems.append(f"{where}: falta «nombre»")
        if m.get("tipo") not in KINDS:
            problems.append(f"{where}: tipo «{m.get('tipo')}» no vale; usa uno de: {', '.join(KINDS)}")
        if "nivel" in m and not (isinstance(m["nivel"], int) and 0 <= m["nivel"] <= 80):
            problems.append(f"{where}: «nivel» debe ser un número de 0 a 80")
        objects = m.get("objetos", [])
        if not isinstance(objects, list):
            problems.append(f"{where}: «objetos» debe ser una lista")
            objects = []
        for o in objects:
            if isinstance(o, dict):
                if not o.get("nombre") or not isinstance(o.get("id", 0), int):
                    problems.append(f"{where}: un objeto con número debe ser {{\"nombre\": ..., \"id\": 1234}}")
            elif not isinstance(o, str) or not o.strip():
                problems.append(f"{where}: los objetos son nombres o {{\"nombre\", \"id\"}}")
        for p in m.get("profesiones", []):
            if not isinstance(p, dict) or "id" not in p:
                problems.append(f"{where}: cada profesión es {{\"id\": 182, \"nivel\": 70}}")
            else:
                check_line(where, p["id"])
        for line in m.get("profesiones_alguna", []) + m.get("mejor_con", []):
            check_line(where, line)
        if m.get("tipo") == "vendedor" and not m.get("vendedor"):
            problems.append(f"{where}: a un método de vendedor le falta «vendedor»")
        if "fecha" in m and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(m["fecha"])):
            problems.append(f"{where}: «fecha» debe ser AAAA-MM-DD")
        if not m.get("fuente"):
            problems.append(f"{where}: falta «fuente» (de dónde sale)")
    return problems


def load_catalog(path: Path = CATALOG_PATH) -> list[CatalogEntry]:
    """Los métodos del catálogo. Se salta los que no tienen id; CatalogError si el JSON está roto."""
    if not path.is_file():
        return []
    entries = []
    for m in _read(path):
        if not isinstance(m, dict) or not m.get("id"):
            continue
        # Un objeto es un nombre o {"nombre": ..., "id": ...} para los que no salen en los datos
        # del juego (mucho equipo antiguo solo lo conoce el servidor).
        names, ids = [], {}
        for o in m.get("objetos", []):
            if isinstance(o, dict):
                names.append(o["nombre"])
                if o.get("id"):
                    ids[o["nombre"]] = int(o["id"])
            else:
                names.append(o)
        entries.append(CatalogEntry(
            id=m["id"], name=m.get("nombre", m["id"]), kind=m.get("tipo", "farmeo"), level=m.get("nivel", 0),
            zone=m.get("zona", ""),
            professions=[(p["id"], p.get("nivel", 1)) for p in m.get("profesiones", [])],
            any_profession=list(m.get("profesiones_alguna", [])), better_with=list(m.get("mejor_con", [])),
            items=names, item_ids=ids, vendor=m.get("vendedor", ""), quantity=m.get("cantidad", 1),
            requirement=m.get("requisito", ""), notes=m.get("notas", ""), source=m.get("fuente", ""),
            added=m.get("fecha", "")))
    return entries


def normalize(name: str) -> str:
    """Sin tildes, mayúsculas ni apóstrofos tipográficos: «Cardo veloz» = «cardo  veloz»."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return " ".join(plain.replace("’", "'").lower().split())


def item_index(conn: sqlite3.Connection) -> dict[str, int]:
    """Nombre normalizado (inglés o español) -> objeto. Si dos objetos se llaman igual, el de
    número más bajo, que suele ser el original y no una copia de pruebas."""
    index: dict[str, int] = {}

    def add(name: str | None, item_id: int) -> None:
        if name:
            key = normalize(name)
            if key not in index or item_id < index[key]:
                index[key] = item_id

    for r in conn.execute("SELECT item_id, name, name_en FROM gd_items"):
        add(r["name"], r["item_id"])
        add(r["name_en"], r["item_id"])
    for r in conn.execute("SELECT item_id, name FROM items"):
        add(r["name"], r["item_id"])
    return index


def resolve_items(conn: sqlite3.Connection, entries: list[CatalogEntry]) -> tuple[dict[str, int], list[str]]:
    """Objetos del catálogo que se reconocen (nombre -> objeto) y los que no."""
    index = item_index(conn)
    found, missing = {}, []
    for e in entries:
        for name in e.items:
            item_id = e.item_ids.get(name) or index.get(normalize(name))
            if item_id is not None:
                found[name] = item_id
            elif name not in missing:
                missing.append(name)
    return found, missing


@dataclass
class ItemView:
    label: str                      # como lo cita la guía
    item_id: int | None
    price: ItemPrice | None = None
    signals: object | None = None   # market.MarketSignals
    craft: CraftResult | None = None  # la mejor receta que lo fabrica (crafteos)

    @property
    def name(self) -> str:
        return self.price.name if self.price and not self.price.name.startswith("objeto ") else self.label

    @property
    def unit_value(self) -> int | None:
        """Lo que te deja una unidad: en la subasta sin comisión o lo que paga el vendedor."""
        options = [v for v in (self.price.net_sale, self.price.vendor_sell) if v] if self.price else []
        return max(options) if options else None

    @property
    def to_vendor(self) -> bool:
        p = self.price
        return bool(p and p.vendor_sell and (p.net_sale is None or p.vendor_sell >= p.net_sale))

    @property
    def market_day(self) -> int | None:
        """Lo máximo que puedes sacar al día vendiéndolo en la subasta sin hundir el precio."""
        s, p = self.signals, self.price
        if s is None or not s.sales_per_day or p is None or not p.net_sale:
            return None
        return round(s.sales_per_day * MARKET_SHARE * p.net_sale)


@dataclass
class GuideMethod:
    entry: CatalogEntry
    items: list[ItemView] = field(default_factory=list)
    lacking: list[str] = field(default_factory=list)
    have_characters: bool = False
    needs: str = ""                 # profesiones que pide, en texto
    measured: FarmSummary | None = None
    daily_value: int | None = None  # tipo diario: lo que da cada día

    @property
    def feasible(self) -> bool | None:
        """None si todavía no se sabe nada de tus personajes."""
        return not self.lacking if self.have_characters else None

    @property
    def missing_items(self) -> list[str]:
        return [i.label for i in self.items if i.item_id is None]

    @property
    def market_day(self) -> int:
        return sum(i.market_day or 0 for i in self.items)

    @property
    def best_unit(self) -> int:
        return max((i.unit_value or 0 for i in self.items), default=0)

    def sort_key(self):
        measured = self.measured.per_hour if self.measured else 0
        return (self.feasible is False, -measured, -self.market_day, -self.best_unit, self.entry.level)


def _profession_names(conn: sqlite3.Connection) -> dict[int, str]:
    return {r["skill_line"]: r["name"] for r in conn.execute("SELECT skill_line, name FROM gd_skill_lines")}


def evaluate_catalog(conn: sqlite3.Connection, entries: list[CatalogEntry], resolved: dict[str, int],
                     prices: dict[int, ItemPrice], signals: dict, crafts: list[CraftResult],
                     farm_summary: list[FarmSummary]) -> list[GuideMethod]:
    names = _profession_names(conn)
    levels = profession_levels(conn)
    char_levels = [r["level"] or 0 for r in conn.execute("SELECT level FROM characters")]
    top_level = max(char_levels, default=0)

    def prof(line: int) -> str:
        return names.get(line, f"profesión {line}")

    def craft_rank(c: CraftResult):
        return c.complete, c.known, c.profit or 0

    best_craft: dict[int, CraftResult] = {}
    for c in crafts:
        if c.output_item_id:
            current = best_craft.get(c.output_item_id)
            if current is None or craft_rank(c) > craft_rank(current):
                best_craft[c.output_item_id] = c

    measured: dict[str, FarmSummary] = {}
    for g in farm_summary:
        key = normalize(g.activity)
        if key not in measured or g.hours > measured[key].hours:
            measured[key] = g

    result = []
    for e in entries:
        m = GuideMethod(entry=e, have_characters=bool(char_levels))
        for label in e.items:
            item_id = resolved.get(label)
            m.items.append(ItemView(label=label, item_id=item_id, price=prices.get(item_id),
                                    signals=signals.get(item_id), craft=best_craft.get(item_id)))
        parts = [f"{prof(line)} {skill}" if skill > 1 else prof(line) for line, skill in e.professions]
        if e.any_profession:
            parts.append(" o ".join(prof(line) for line in e.any_profession))
        m.needs = ", ".join(parts)
        if e.better_with:
            m.needs += ("; " if m.needs else "") + "mejor con " + ", ".join(prof(line) for line in e.better_with)

        if char_levels:
            if e.level and top_level < e.level:
                m.lacking.append(f"nivel {e.level} (tu máximo: {top_level})")
            for line, skill in e.professions:
                have = levels.get(line, [])
                if not have:
                    m.lacking.append(prof(line))
                elif have[0][1] < skill:
                    m.lacking.append(f"{prof(line)} {skill} (tienes {have[0][1]})")
            if e.any_profession and not any(levels.get(line) for line in e.any_profession):
                m.lacking.append(" o ".join(prof(line) for line in e.any_profession))

        m.measured = measured.get(normalize(e.id)) or measured.get(normalize(e.name))
        if e.kind == "diario":
            values = [i.unit_value for i in m.items if i.unit_value]
            if values:
                m.daily_value = round(e.quantity * statistics.mean(values))
        result.append(m)
    result.sort(key=GuideMethod.sort_key)
    return result
