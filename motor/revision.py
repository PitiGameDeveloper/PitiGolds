"""Lo que opina el asesor de cada método para tu situación (conocimiento/revision.json).

El motor calcula; el asesor (Claude) revisa de vez en cuando los métodos con tus personajes y
apunta en cada uno una nota del 1 al 10, por qué le parece bueno o malo y los pasos exactos
para hacerlo. En los crafteos apunta además cómo se consigue la receta cuando los datos del
juego no lo dicen. El addon lo enseña al desplegar cada método.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .catalogo import CatalogError

REVIEW_PATH = Path(__file__).resolve().parent.parent / "conocimiento" / "revision.json"

# Cómo se consigue una receta. instructor, vendedor y subasta se compran en un momento;
# botin, reputacion y mision llevan tiempo.
RECIPE_WAYS = ("instructor", "vendedor", "subasta", "botin", "reputacion", "mision")


@dataclass
class Review:
    score: int | None = None
    why: str = ""
    steps: list[str] = field(default_factory=list)
    date: str = ""
    recipe_way: str = ""          # crafteos: cómo se consigue la receta (RECIPE_WAYS)
    recipe_where: str = ""        # quién la vende o dónde cae
    recipe_price: str = ""
    recipe_requirement: str = ""  # reputación, divisas...


@dataclass
class Reviews:
    farms: dict[str, Review] = field(default_factory=dict)
    crafts: dict[int, Review] = field(default_factory=dict)   # por receta (spell id)
    date: str = ""


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{path.name} no es un JSON válido (línea {exc.lineno}: {exc.msg})") from exc
    if not isinstance(data, dict):
        raise CatalogError(f"{path.name} debe ser un objeto {{...}}")
    return data


def _review(raw: dict) -> Review:
    recipe = raw.get("receta") if isinstance(raw.get("receta"), dict) else {}
    score = raw.get("nota")
    return Review(score=score if isinstance(score, int) else None, why=raw.get("por_que", ""),
                  steps=[s for s in raw.get("pasos", []) if isinstance(s, str)], date=raw.get("fecha", ""),
                  recipe_way=recipe.get("como", ""), recipe_where=recipe.get("donde", ""),
                  recipe_price=recipe.get("precio", ""), recipe_requirement=recipe.get("requisito", ""))


def load_reviews(path: Path = REVIEW_PATH) -> Reviews:
    """Las revisiones del asesor (vacías si no hay archivo); CatalogError si el JSON está roto."""
    if not path.is_file():
        return Reviews()
    data = _read(path)
    result = Reviews(date=data.get("fecha", ""))
    for key, raw in (data.get("farmeos") or {}).items():
        if isinstance(raw, dict):
            result.farms[key] = _review(raw)
    for key, raw in (data.get("crafteos") or {}).items():
        if isinstance(raw, dict) and str(key).isdigit():
            result.crafts[int(key)] = _review(raw)
    return result


def review_problems(path: Path = REVIEW_PATH, method_ids: set[str] | None = None) -> list[str]:
    """Lo que está mal en revision.json, en frases. method_ids: los ids del catálogo."""
    if not path.is_file():
        return []
    try:
        data = _read(path)
    except CatalogError as exc:
        return [str(exc)]
    problems = []

    def check(where: str, raw) -> None:
        if not isinstance(raw, dict):
            problems.append(f"{where}: debe ser un objeto {{\"nota\": 7, \"por_que\": ..., \"pasos\": [...]}}")
            return
        score = raw.get("nota")
        if not (isinstance(score, int) and 1 <= score <= 10):
            problems.append(f"{where}: «nota» debe ser un número del 1 al 10")
        if not isinstance(raw.get("pasos", []), list):
            problems.append(f"{where}: «pasos» debe ser una lista de frases")
        if "fecha" in raw and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(raw["fecha"])):
            problems.append(f"{where}: «fecha» debe ser AAAA-MM-DD")
        recipe = raw.get("receta")
        if recipe is not None:
            if not isinstance(recipe, dict):
                problems.append(f"{where}: «receta» es {{\"como\": \"vendedor\", \"donde\": ..., \"precio\": ...}}")
            elif recipe.get("como") not in RECIPE_WAYS:
                problems.append(f"{where}: «receta.como» debe ser uno de: {', '.join(RECIPE_WAYS)}")

    for key, raw in (data.get("farmeos") or {}).items():
        if method_ids is not None and key not in method_ids:
            problems.append(f"farmeo «{key}»: no está en metodos.json")
        check(f"farmeo «{key}»", raw)
    for key, raw in (data.get("crafteos") or {}).items():
        if not str(key).isdigit():
            problems.append(f"crafteo «{key}»: la clave es el número de la receta (sale en datos/panel.md)")
        check(f"crafteo «{key}»", raw)
    return problems
