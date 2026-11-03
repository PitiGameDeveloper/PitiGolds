"""Datos del juego: las tablas del cliente de WoW Forever que publica wago.tools.

Traen todas las recetas de todas las profesiones (también de las que no tienes), con
el nivel al que se aprenden y al que pasan a amarilla, verde y gris, sus materiales, lo
que fabrican, el objeto con el que se aprenden, la espera de las que tienen (tela lunar,
transmutaciones...) y lo que cobra y paga un vendedor por cada objeto. Los nombres de los
objetos se bajan también en inglés, para reconocer lo que citan guías y vídeos, y los nombres de
las zonas. No traen qué PNJ vende cada cosa: eso vive en el servidor (ver merchantmap.py).
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .db import get_meta, set_meta

WAGO = "https://wago.tools"
PRODUCT = "wowf"
LOCALE = "esES"
USER_AGENT = "PitiGolds (addon personal; https://github.com/PitiGameDeveloper)"
TABLES = ["SkillLine", "SkillLineAbility", "SpellName", "SpellEffect", "SpellReagents",
          "ItemSparse", "Item", "ItemEffect", "ItemXItemEffect", "SpellCooldowns", "SpellCategories", "Faction",
          "AreaTable", "UiMap"]
ENGLISH_TABLES = ["ItemSparse"]  # se bajan también en inglés: <tabla>.enUS.csv
FORMAT = 4  # sube cuando se importan datos nuevos: obliga a reimportar aunque la versión no cambie

PROFESSION_CATEGORIES = {9, 11}  # SkillLine.CategoryID: secundarias (cocina, pesca...) y principales
EFFECT_CREATE_ITEM = 24
EFFECT_LEARN_SPELL = 36
TRIGGER_LEARN_SPELL = 6  # ItemEffect.TriggerType: usar el objeto enseña el hechizo
MAX_REAGENTS = 8
REFRESH_DAYS = 7         # se vuelven a bajar aunque la versión no cambie
_BUILD_NAME = re.compile(r"\d+(\.\d+)+")


def _get(url: str, timeout: float = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def available_builds(product: str = PRODUCT) -> list[str]:
    builds = json.loads(_get(f"{WAGO}/api/builds", timeout=20))
    return [b["version"] for b in builds.get(product, [])]


def installed_build(wow_dir: Path) -> str | None:
    """Versión del cliente instalado según el .build.info de Battle.net."""
    info = wow_dir.parent / ".build.info"
    if not info.is_file():
        return None
    lines = info.read_text(encoding="utf-8", errors="replace").splitlines()
    header = [h.split("!")[0] for h in lines[0].split("|")]
    for line in lines[1:]:
        values = dict(zip(header, line.split("|")))
        if values.get("Product") == PRODUCT and values.get("Version"):
            return values["Version"]
    return None


def pick_build(builds: list[str], installed: str | None) -> str:
    """La versión del cliente instalado si wago.tools la tiene; si no, la más reciente."""
    if installed and installed in builds:
        return installed
    return builds[0]


def download(build: str, dest: Path, refresh: bool = False) -> Path:
    """Baja las tablas a dest. Sin refresh, las que ya estén descargadas no se vuelven a pedir."""
    dest.mkdir(parents=True, exist_ok=True)
    wanted = [(t, LOCALE, f"{t}.csv") for t in TABLES] + [(t, "enUS", f"{t}.enUS.csv") for t in ENGLISH_TABLES]
    for table, locale, filename in wanted:
        target = dest / filename
        if refresh or not target.is_file():
            data = _get(f"{WAGO}/db2/{table}/csv?build={build}&locale={locale}")
            tmp = target.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
    return dest


# Importación ---------------------------------------------------------------------------

def _rows(folder: Path, table: str):
    path = folder / f"{table}.csv"
    if not path.is_file():  # tablas añadidas después: la importación sigue sin ellas
        return
    with open(path, encoding="utf-8", newline="") as f:
        yield from csv.DictReader(f)


def _int(value: str | None) -> int:
    try:
        return int(float(value)) if value not in (None, "") else 0
    except ValueError:
        return 0


@dataclass
class ImportReport:
    build: str
    recipes: int = 0
    items: int = 0
    by_profession: dict[str, int] = field(default_factory=dict)


def import_tables(conn: sqlite3.Connection, folder: Path, build: str) -> ImportReport:
    report = ImportReport(build=build)

    skill_lines = {}
    for r in _rows(folder, "SkillLine"):
        if _int(r["CategoryID"]) in PROFESSION_CATEGORIES:
            skill_lines[_int(r["ID"])] = (r["DisplayName_lang"], _int(r["CategoryID"]), _int(r["ParentSkillLineID"]))

    spell_names = {_int(r["ID"]): r["Name_lang"] for r in _rows(folder, "SpellName")}

    outputs: dict[int, tuple[int, float]] = {}
    learns: dict[int, int] = {}  # hechizo «aprender» -> receta que enseña
    for r in _rows(folder, "SpellEffect"):
        effect, spell = _int(r["Effect"]), _int(r["SpellID"])
        if effect == EFFECT_CREATE_ITEM and spell not in outputs and _int(r["EffectItemType"]):
            outputs[spell] = (_int(r["EffectItemType"]), max(1.0, float(r["EffectBasePointsF"] or 1)))
        elif effect == EFFECT_LEARN_SPELL and _int(r["EffectTriggerSpell"]):
            learns.setdefault(spell, _int(r["EffectTriggerSpell"]))

    # Objeto con el que se aprende cada receta (diseños, patrones, recetas...). El efecto del
    # objeto enseña la receta directamente (TriggerType 6) o lanza un hechizo que la enseña.
    taught_by_effect: dict[int, int] = {}
    for r in _rows(folder, "ItemEffect"):
        spell = _int(r["SpellID"])
        recipe = spell if _int(r["TriggerType"]) == TRIGGER_LEARN_SPELL else learns.get(spell)
        if recipe:
            taught_by_effect[_int(r["ID"])] = recipe
    learn_item: dict[int, int] = {}
    for r in _rows(folder, "ItemXItemEffect"):
        recipe = taught_by_effect.get(_int(r["ItemEffectID"]))
        item = _int(r["ItemID"])
        if recipe and (recipe not in learn_item or item < learn_item[recipe]):
            learn_item[recipe] = item

    # Espera entre fabricaciones (en milisegundos): la propia o la de su categoría, que
    # comparten varias recetas (todas las transmutaciones, por ejemplo).
    cooldowns: dict[int, float] = {}
    for r in _rows(folder, "SpellCooldowns"):
        ms = max(_int(r["CategoryRecoveryTime"]), _int(r["RecoveryTime"]))
        if ms > 0 and _int(r["DifficultyID"]) == 0:
            cooldowns[_int(r["SpellID"])] = ms / 3_600_000
    categories = {_int(r["SpellID"]): _int(r["Category"]) for r in _rows(folder, "SpellCategories")
                  if _int(r["Category"]) and _int(r["DifficultyID"]) == 0}

    recipes = {}
    for r in _rows(folder, "SkillLineAbility"):
        line, spell = _int(r["SkillLine"]), _int(r["Spell"])
        if line not in skill_lines or spell in recipes:
            continue
        output = outputs.get(spell, (None, 1.0))
        cooldown = cooldowns.get(spell)
        recipes[spell] = (spell, line, spell_names.get(spell), _int(r["MinSkillLineRank"]),
                          _int(r["TrivialSkillLineRankLow"]), _int(r["TrivialSkillLineRankHigh"]),
                          _int(r["NumSkillUps"]), _int(r["AcquireMethod"]), output[0], output[1],
                          learn_item.get(spell), cooldown, categories.get(spell) if cooldown else None)

    reagents = []
    for r in _rows(folder, "SpellReagents"):
        spell = _int(r["SpellID"])
        if spell in recipes:
            for i in range(MAX_REAGENTS):
                item, qty = _int(r.get(f"Reagent_{i}")), _int(r.get(f"ReagentCount_{i}"))
                if item > 0 and qty > 0:
                    reagents.append((spell, item, qty))

    # Solo cuentan las recetas con nombre y materiales: fuera los rangos de habilidad, las
    # líneas raciales o de equitación y las de pruebas de Blizzard ([DNT]).
    with_reagents = {spell for spell, _, _ in reagents}
    recipes = {s: r for s, r in recipes.items()
               if s in with_reagents and r[2] and "[DNT]" not in skill_lines[r[1]][0]}
    reagents = [g for g in reagents if g[0] in recipes]
    used_lines = {r[1] for r in recipes.values()}
    skill_lines = {k: v for k, v in skill_lines.items() if k in used_lines}

    classes = {_int(r["ID"]): (_int(r["ClassID"]), _int(r["SubclassID"])) for r in _rows(folder, "Item")}
    english = {_int(r["ID"]): r["Display_lang"] for r in _rows(folder, "ItemSparse.enUS")}
    items = []
    for r in _rows(folder, "ItemSparse"):
        item = _int(r["ID"])
        cls = classes.get(item, (None, None))
        items.append((item, r["Display_lang"], _int(r["OverallQualityID"]), cls[0], cls[1],
                      _int(r["BuyPrice"]), _int(r["SellPrice"]), max(1, _int(r["VendorStackCount"])),
                      _int(r["Stackable"]), _int(r["Bonding"]), _int(r["RequiredSkill"]),
                      _int(r["RequiredSkillRank"]), english.get(item),
                      _int(r.get("MinFactionID")) or None, _int(r.get("MinReputation")) or None))
    factions = [(_int(r["ID"]), r["Name_lang"]) for r in _rows(folder, "Faction") if r.get("Name_lang")]
    areas = [(_int(r["ID"]), r["AreaName_lang"]) for r in _rows(folder, "AreaTable") if r.get("AreaName_lang")]
    maps = [(_int(r["ID"]), r["Name_lang"]) for r in _rows(folder, "UiMap") if r.get("Name_lang")]

    with conn:
        for table in ("gd_skill_lines", "gd_recipes", "gd_reagents", "gd_items", "gd_factions", "gd_areas",
                      "gd_maps"):
            conn.execute(f"DELETE FROM {table}")
        conn.executemany("INSERT INTO gd_skill_lines VALUES (?, ?, ?, ?)",
                         [(k, *v) for k, v in skill_lines.items()])
        conn.executemany(
            "INSERT INTO gd_recipes (spell_id, skill_line, name, min_skill, yellow, grey, num_skillups, acquire, "
            "output_item_id, output_qty, learn_item_id, cooldown_hours, cooldown_category) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", recipes.values())
        conn.executemany("INSERT INTO gd_reagents VALUES (?, ?, ?)", reagents)
        conn.executemany(
            "INSERT INTO gd_items (item_id, name, quality, class_id, subclass_id, buy_price, sell_price, "
            "vendor_stack, stackable, bonding, required_skill, required_skill_rank, name_en, min_faction, "
            "min_reputation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", items)
        conn.executemany("INSERT INTO gd_factions VALUES (?, ?)", factions)
        conn.executemany("INSERT INTO gd_areas VALUES (?, ?)", areas)
        conn.executemany("INSERT INTO gd_maps VALUES (?, ?)", maps)
        set_meta(conn, "game_data_build", build)
        set_meta(conn, "game_data_updated", str(int(time.time())))
        set_meta(conn, "game_data_format", str(FORMAT))

    report.recipes = len(recipes)
    report.items = len(items)
    for _, line, *_ in recipes.values():
        name = skill_lines[line][0]
        report.by_profession[name] = report.by_profession.get(name, 0) + 1
    return report


def _remove_old_builds(cache_dir: Path, keep: str) -> None:
    for folder in cache_dir.iterdir():
        if folder.is_dir() and folder.name != keep and _BUILD_NAME.fullmatch(folder.name):
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()


def update_game_data(conn: sqlite3.Connection, cache_dir: Path, wow_dir: Path,
                     force: bool = False, max_age_days: float = REFRESH_DAYS) -> ImportReport | None:
    """Descarga e importa las tablas si hay una versión nueva del juego, o las vuelve a bajar si
    la última importación tiene más de max_age_days (wago.tools puede añadir filas que antes
    estaban cifradas sin que cambie la versión). None si ya estaban al día."""
    build = pick_build(available_builds(), installed_build(wow_dir))
    same_build = get_meta(conn, "game_data_build") == build
    stale = time.time() - int(get_meta(conn, "game_data_updated") or 0) >= max_age_days * 86400
    old_format = get_meta(conn, "game_data_format") != str(FORMAT)
    if not force and same_build and not stale and not old_format:
        return None
    # Con un formato nuevo basta con bajar las tablas que falten.
    folder = download(build, cache_dir / build, refresh=force or (same_build and stale))
    report = import_tables(conn, folder, build)
    _remove_old_builds(cache_dir, keep=build)
    return report
