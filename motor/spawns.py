"""Dónde está cada bicho y cada cosa del mapa: la base de datos de Questie para Forever (QuestieDB).

QuestieDB (https://github.com/Questie/QuestieDB, de los autores de Questie, GPLv3) trae para cada PNJ
de Forever su nombre en inglés, nivel, rango y puntos de aparición por zona (AreaTable, coordenadas
del mapa de esa zona en %), y lo mismo para los objetos del mapa (almejas, cofres, hierbas de misión).
Aparte, los nombres en español: los de la traducción del Classic y, encima, los que se han visto en
Forever («traces»). Las zonas nuevas de Forever (Clarofluvial) todavía no salen.

El motor lo baja con los datos del juego (qd_names y qd_spawns) y, para cada farmeo del catálogo con
«punto», busca en la zona del punto los bichos («bichos») y las cosas («nodos») cuyo nombre empiece
por alguno de los del catálogo, en español o en inglés. Sus puntos van al addon, que los pinta en el
mapa del juego y lleva la flecha al más cercano. Si el «punto» trae x e y, solo cuentan los que estén
cerca de él (RADIUS); si no, el punto pasa a ser el centro del grupo más denso. Los bichos de nivel
muy por debajo del farmeo no cuentan (comparten nombre con otros de la zona).
"""

from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

from .catalogo import normalize
from .db import get_meta, set_meta
from .gamedata import _get
from .luaparse import _Parser, _tokenize

SOURCE = "https://raw.githubusercontent.com/Questie/QuestieDB/master"
# archivo local -> (ruta en QuestieDB, obligatorio)
FILES = {
    "npcs.lua": ("data/Forever/foreverNpcDB.lua", True),
    "npcs.esES.lua": ("l10n/Forever/lookupNpcs/esES.lua", True),
    "npcs.esES.forever.lua": ("l10n/Forever/traces/lookupNpcs/esES.lua", False),
    "objetos.lua": ("data/Forever/foreverObjectDB.lua", True),
    "objetos.esES.lua": ("l10n/Forever/lookupObjects/esES.lua", True),
    "objetos.esES.forever.lua": ("l10n/Forever/traces/lookupObjects/esES.lua", False),
}
REFRESH_DAYS = 7
RADIUS = 0.12            # con x e y en el catálogo: puntos a menos de esto (12 % del mapa)
CLUSTER = 0.06           # para buscar el grupo más denso
SKIP_RANKS = (2, 3, 4)   # raro élite, jefe y raro: no se farmean
LEVEL_SLACK = 3          # bichos de hasta 3 niveles menos que el farmeo
MAX_POINTS = 400         # por farmeo, para no inflar Generated.lua

NPC, OBJECT = "npc", "obj"
# Campos (QuestieDB.npcKeys / objectKeys), contando desde 1.
NPC_NAME, NPC_MIN_LEVEL, NPC_MAX_LEVEL, NPC_RANK, NPC_SPAWNS = 1, 4, 5, 6, 7
OBJ_NAME, OBJ_SPAWNS = 1, 4


def _lua_table(text: str) -> dict | list:
    """La tabla de «[[return {...}]]», como en los archivos de Questie."""
    start = text.find("return {")
    end = text.rfind("}]]")
    if start < 0 or end < 0:
        raise ValueError("no encuentro la tabla de Questie")
    return _Parser(_tokenize(text[start + len("return "):end + 1])).table()


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {i + 1: v for i, v in enumerate(value)}
    return {}


def parse_db(text: str, kind: str) -> tuple[list[tuple], list[tuple]]:
    """foreverNpcDB.lua o foreverObjectDB.lua -> (filas de qd_names sin nombre español, de qd_spawns)."""
    name_f, spawns_f = (NPC_NAME, NPC_SPAWNS) if kind == NPC else (OBJ_NAME, OBJ_SPAWNS)
    names, spawns = [], []
    for thing_id, row in _as_dict(_lua_table(text)).items():
        r = _as_dict(row)
        if not isinstance(thing_id, int) or not isinstance(r.get(name_f), str):
            continue
        if kind == NPC:
            names.append((kind, thing_id, r[name_f], r.get(NPC_MIN_LEVEL), r.get(NPC_MAX_LEVEL),
                          r.get(NPC_RANK) or 0))
        else:
            names.append((kind, thing_id, r[name_f], None, None, 0))
        for area_id, points in _as_dict(r.get(spawns_f)).items():
            for p in points if isinstance(points, list) else []:
                if (isinstance(p, list) and len(p) >= 2 and all(isinstance(c, (int, float)) for c in p[:2])
                        and p[0] >= 0 and p[1] >= 0):   # {-1, -1}: dentro de una mazmorra
                    spawns.append((kind, thing_id, area_id, float(p[0]), float(p[1])))
    return names, spawns


def parse_names(text: str) -> dict[int, str]:
    """lookupNpcs/esES.lua o lookupObjects/esES.lua -> {id: nombre}."""
    names = {}
    for thing_id, row in _as_dict(_lua_table(text)).items():
        if isinstance(row, str):        # los objetos: [id] = "nombre"
            name = row
        else:                           # los PNJ: [id] = {"nombre", "título"}
            name = _as_dict(row).get(1)
        if isinstance(thing_id, int) and isinstance(name, str) and name:
            names[thing_id] = name
    return names


def _spanish(folder: Path, prefix: str) -> dict[int, str]:
    names = parse_names((folder / f"{prefix}.esES.lua").read_text(encoding="utf-8"))
    forever = folder / f"{prefix}.esES.forever.lua"
    if forever.is_file():
        names.update(parse_names(forever.read_text(encoding="utf-8")))
    return names


def import_files(conn: sqlite3.Connection, folder: Path) -> int:
    rows, spawns = [], []
    for kind, prefix in ((NPC, "npcs"), (OBJECT, "objetos")):
        names, points = parse_db((folder / f"{prefix}.lua").read_text(encoding="utf-8"), kind)
        if not names or not points:  # el formato ha cambiado: mejor quedarse con lo que había
            raise ValueError(f"no entiendo {prefix}.lua de Questie")
        spanish = _spanish(folder, prefix)
        rows += [(n[0], n[1], n[2], spanish.get(n[1]), *n[3:]) for n in names]
        spawns += points
    with conn:
        conn.execute("DELETE FROM qd_names")
        conn.execute("DELETE FROM qd_spawns")
        conn.executemany("INSERT INTO qd_names VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.executemany("INSERT INTO qd_spawns VALUES (?, ?, ?, ?, ?)", spawns)
        set_meta(conn, "questie_updated", str(int(time.time())))
    return len({(s[0], s[1]) for s in spawns})


def update_spawns(conn: sqlite3.Connection, cache_dir: Path, force: bool = False,
                  max_age_days: float = REFRESH_DAYS) -> int | None:
    """Baja e importa los datos si tienen más de max_age_days. PNJ y objetos con sitio, o None si
    ya estaban al día."""
    age = time.time() - int(get_meta(conn, "questie_updated") or 0)
    if not force and age < max_age_days * 86400:
        return None
    folder = cache_dir / "questie"
    folder.mkdir(parents=True, exist_ok=True)
    for name, (path, required) in FILES.items():
        target = folder / name
        tmp = target.with_suffix(".tmp")
        try:
            tmp.write_bytes(_get(f"{SOURCE}/{path}"))
        except OSError:
            if not required:  # sin los nombres vistos en Forever, la traducción del Classic
                continue
            raise
        tmp.replace(target)
    return import_files(conn, folder)


# Consulta ------------------------------------------------------------------------------

@dataclass
class FarmSpawns:
    point: dict                                    # el del catálogo, con x e y si no las traía
    spawns: list[tuple[float, float]] = field(default_factory=list)   # bichos, de 0 a 1 en el mapa
    nodes: list[tuple[float, float]] = field(default_factory=list)    # cosas del mapa
    names: list[str] = field(default_factory=list)                    # lo encontrado, lo más común antes


def has_data(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM qd_spawns LIMIT 1").fetchone() is not None


def map_areas(conn: sqlite3.Connection, map_id: int) -> list[int]:
    """Zonas (AreaTable) de un mapa del juego (UiMap): las que se llaman igual."""
    return [r[0] for r in conn.execute(
        "SELECT a.area_id FROM gd_areas a JOIN gd_maps m ON m.name = a.name WHERE m.map_id = ?", (map_id,))]


def _matches(name: str | None, prefixes: list[str]) -> bool:
    return bool(name) and any(normalize(name).startswith(p) for p in prefixes)


def _densest(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Centro del grupo con más puntos a menos de CLUSTER."""
    best: list[tuple[float, float]] = []
    for x, y in points:
        near = [p for p in points if math.hypot(p[0] - x, p[1] - y) <= CLUSTER]
        if len(near) > len(best):
            best = near
    return sum(p[0] for p in best) / len(best), sum(p[1] for p in best) / len(best)


def _find(conn: sqlite3.Connection, kind: str, areas: list[int], wanted: list[str], point: dict,
          min_level: int, found: dict[str, int]) -> list[tuple[float, float]]:
    prefixes = [normalize(w) for w in wanted]
    marks = ",".join("?" * len(areas))
    points, seen = [], set()
    for r in conn.execute(
            f"SELECT n.name_en, n.name_es, s.x, s.y FROM qd_spawns s "
            f"JOIN qd_names n ON n.kind = s.kind AND n.id = s.id "
            f"WHERE s.kind = ? AND s.area_id IN ({marks}) AND n.rank NOT IN {SKIP_RANKS} "
            f"AND COALESCE(n.max_level, 999) >= ? ORDER BY n.id, s.x, s.y", [kind, *areas, min_level]):
        if not (_matches(r["name_es"], prefixes) or _matches(r["name_en"], prefixes)):
            continue
        x, y = r["x"] / 100, r["y"] / 100
        if "x" in point and math.hypot(x - point["x"], y - point["y"]) > RADIUS:
            continue
        key = (round(x, 3), round(y, 3))
        if key in seen:
            continue
        seen.add(key)
        points.append(key)
        name = r["name_es"] or r["name_en"]
        found[name] = found.get(name, 0) + 1
    if len(points) > MAX_POINTS:
        points = points[::math.ceil(len(points) / MAX_POINTS)]
    return points


def farm_spawns(conn: sqlite3.Connection, point: dict | None, mobs: list[str], nodes: list[str] = (),
                level: int = 0) -> FarmSpawns | None:
    """Dónde están los bichos y las cosas de un farmeo en su mapa, o None si no sale nada."""
    if not point or not point.get("map") or not (mobs or nodes):
        return None
    areas = map_areas(conn, point["map"])
    if not areas:
        return None
    found: dict[str, int] = {}
    min_level = max(0, level - LEVEL_SLACK) if level else 0
    spawns = _find(conn, NPC, areas, list(mobs), point, min_level, found) if mobs else []
    things = _find(conn, OBJECT, areas, list(nodes), point, 0, found) if nodes else []
    if not spawns and not things:
        return None
    new_point = dict(point)
    if "x" not in point:
        x, y = _densest(spawns or things)
        new_point.update(x=round(x, 4), y=round(y, 4))
    return FarmSpawns(point=new_point, spawns=spawns, nodes=things,
                      names=sorted(found, key=lambda n: -found[n]))


def pack(points: list[tuple[float, float]]) -> str:
    """Puntos para el addon en poco sitio: «635,620;640,611» (milésimas del mapa)."""
    return ";".join(f"{round(x * 1000)},{round(y * 1000)}" for x, y in points)


def catalog_warnings(conn: sqlite3.Connection, entries) -> list[str]:
    """Farmeos del catálogo cuyo mapa solo marcaría la zona: sin bichos ni nodos, o con nombres que
    no salen en Questie (mal escritos, de otra zona o de una zona nueva de Forever). En el juego el
    addon apunta dónde los matas, así que no es un error."""
    if not has_data(conn):
        return []
    warnings = []
    for e in entries:
        if not e.point or e.kind not in ("farmeo",):
            continue
        if not e.mobs and not e.nodes:
            warnings.append(f"{e.id}: sin «bichos» ni «nodos», el mapa solo marca la zona")
            continue
        found = farm_spawns(conn, e.point, e.mobs, e.nodes, e.level)
        missing = [n for n in [*e.mobs, *e.nodes]
                   if found is None or not any(normalize(f).startswith(normalize(n)) for f in found.names)]
        if missing:
            warnings.append(f"{e.id}: no encuentro en Questie {', '.join(missing)}"
                            + (" (ni nada más: el mapa solo marca la zona)" if found is None else ""))
    return warnings
