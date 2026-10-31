"""Subir profesiones de recolección (conocimiento/recoleccion.json).

Botánica, Minería, Desollar y Pesca no se suben con recetas sino recolectando, así que no
cuestan oro: cuestan horas. Cada profesión tiene una ruta por tramos (dónde ir según tu nivel
de profesión y tu facción) con los puntos que se suben en una hora, que son aproximados.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .catalogo import CatalogError, normalize

ROUTES_PATH = Path(__file__).resolve().parent.parent / "conocimiento" / "recoleccion.json"
GATHERING = {182, 186, 393, 356}   # Botánica, Minería, Desollar, Pesca


@dataclass
class Stretch:
    start: int
    end: int
    horde: str
    alliance: str
    what: list[str] = field(default_factory=list)   # en inglés, como en el juego
    note: str = ""
    points_per_hour: float = 40.0
    char_level: int = 0


def load_routes(path: Path = ROUTES_PATH) -> dict[int, list[Stretch]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CatalogError(f"{path.name} no es un JSON válido (línea {exc.lineno}: {exc.msg})") from exc
    routes = {}
    for key, value in data.items():
        if not key.isdigit() or not isinstance(value, dict):
            continue
        routes[int(key)] = [
            Stretch(start=t["desde"], end=t["hasta"], horde=t.get("horda", ""), alliance=t.get("alianza", ""),
                    what=list(t.get("que", [])), note=t.get("nota", ""),
                    points_per_hour=float(t.get("puntos_hora", 40)), char_level=t.get("nivel_personaje", 0))
            for t in value.get("tramos", [])]
    return routes


def gathering_hours(routes: dict[int, list[Stretch]], line: int, start: int, target: int) -> float | None:
    """Horas aproximadas para subir de start a target. None si no hay ruta para esa profesión."""
    stretches = routes.get(line)
    if not stretches:
        return None
    hours, covered = 0.0, start
    for t in stretches:
        low, high = max(start, t.start), min(target, t.end)
        if high > low:
            hours += (high - low) / t.points_per_hour
            covered = max(covered, high)
    if covered < target:   # más allá de la ruta: al ritmo del último tramo
        hours += (target - covered) / stretches[-1].points_per_hour
    return hours


def route_lines(routes: dict[int, list[Stretch]], line: int, start: int, target: int, faction: str | None,
                names: dict[str, str] | None = None) -> list[str]:
    """La ruta de start a target en frases: «115-170: Sierra Espolón... (Hierba cardenal...)».
    names: nombre inglés normalizado -> nombre en el juego, para traducir lo que se recoge."""
    lines = []
    for t in routes.get(line, []):
        low, high = max(start, t.start), min(target, t.end)
        if high <= low:
            continue
        where = t.alliance if (faction or "").lower().startswith("alli") else t.horde
        what = [(names or {}).get(normalize(w), w) for w in t.what]
        text = f"{low}-{high}: {where}"
        if what:
            text += f" ({', '.join(what)})"
        if t.char_level:
            text += f"; el instructor pide nivel {t.char_level}"
        if t.note:
            text += f". {t.note}"
        lines.append(text)
    return lines


def route_problems(path: Path = ROUTES_PATH) -> list[str]:
    try:
        routes = load_routes(path)
    except CatalogError as exc:
        return [str(exc)]
    except (KeyError, TypeError, ValueError) as exc:
        return [f"{path.name}: cada tramo necesita «desde» y «hasta» ({exc})"]
    problems = []
    for line, stretches in routes.items():
        for t in stretches:
            if t.end <= t.start or t.points_per_hour <= 0:
                problems.append(f"{path.name}, profesión {line}: el tramo {t.start}-{t.end} está mal")
    return problems
