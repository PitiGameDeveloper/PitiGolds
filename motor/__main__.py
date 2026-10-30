"""Uso:
    python -m motor leer       lee los datos del addon una vez
    python -m motor vigilar    los lee cada vez que WoW los guarda (/reload o salir)
    python -m motor estado     resumen de personajes, oro, profesiones y subasta
    python -m motor informe    qué craftear, qué aprender y qué vender
    python -m motor datos-juego  descarga las recetas y objetos del juego (wago.tools)
    python -m motor chollos    posibles chollos de vendedor que toca comprobar fuera del juego
    python -m motor chollo <id> nadie | vende "detalle"   apunta lo que encuentres
    python -m motor ajustes --horas-semana 10 --semanas 4 --legado-subida 0   para comparar métodos
    python -m motor guia herreria [--desde 50] [--hasta 150]  guía de subida con su coste
    python -m motor metodos    los métodos de tus guías (conocimiento/metodos.json) con tus precios
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
import unicodedata

from . import db as dbmod
from .analysis import analyze
from .catalogo import CATALOG_PATH, load_catalog
from .config import Config, load_config
from .gamedata import update_game_data
from .generated import write_generated
from .ingest import ingest_file
from .leveling import plan_leveling
from .money import format_money
from .planner import build_methods, load_settings, save_settings
from .report import build_advice_report, build_guides_section, build_report, guide_filename, render_guide
from .vendors import record_check


def write_report(conn: sqlite3.Connection, config: Config, analysis=None) -> str:
    """Escribe datos/informe.md, datos/metodos.md (todos los métodos de tus guías) y las guías
    de subida en datos/guias/. Devuelve el informe."""
    analysis = analysis if analysis is not None else analyze(conn)
    settings = load_settings(conn)
    methods, baseline = build_methods(conn, analysis, settings)
    text = build_advice_report(conn, analysis, plan=(methods, baseline, settings))
    folder = config.db_path.parent
    (folder / "informe.md").write_text(text, encoding="utf-8")
    guides_text = "\n".join(build_guides_section(analysis, limit=None, heading="#")).strip()
    if guides_text:
        (folder / "metodos.md").write_text(guides_text + "\n", encoding="utf-8")
    guides = folder / "guias"
    for m in methods:
        if m.guide is not None and m.guide.steps:
            guides.mkdir(exist_ok=True)
            (guides / guide_filename(m.guide)).write_text(render_guide(m.guide), encoding="utf-8")
    return text


def refresh_outputs(conn: sqlite3.Connection, config: Config) -> str:
    """Rehace Generated.lua (para el juego), el informe y las guías. Devuelve un resumen de una línea."""
    analysis = analyze(conn)
    target = write_generated(conn, config.addon_dir, analysis)
    if target is None:
        print(f"Aviso: no encuentro la carpeta del addon ({config.addon_dir}); no he escrito Generated.lua.")
    write_report(conn, config, analysis)
    crafts = sum(1 for c in analysis.crafts if c.known and c.complete and c.profit > 0)
    to_sell = sum(1 for s in analysis.sales if s.action in ("subastar", "vendedor"))
    return f"{crafts} crafteos rentables, {to_sell} cosas para vender. Detalle: python -m motor informe"


def cmd_leer(config: Config) -> int:
    files = config.saved_variables()
    if not files:
        print(f"No encuentro PitiGolds.lua en {config.wow_dir / 'WTF' / 'Account'}.")
        print("Entra en el juego con el addon activado y pulsa Exportar (o sal del juego).")
        return 1
    conn = dbmod.connect(config.db_path)
    try:
        for account, path in files:
            r = ingest_file(conn, account, path)
            print(f"[{time.strftime('%H:%M:%S')}] {account}: {r.characters} personajes, {r.recipes} recetas, "
                  f"{r.new_scans} escaneos nuevos ({r.new_prices} precios)")
        print("  " + refresh_outputs(conn, config))
    finally:
        conn.close()
    return 0


def cmd_datos_juego(config: Config, force: bool) -> int:
    conn = dbmod.connect(config.db_path)
    try:
        report = update_game_data(conn, config.db_path.parent / "juego", config.wow_dir, force=force)
        if report is None:
            print(f"Los datos del juego ya están al día (versión {dbmod.get_meta(conn, 'game_data_build')}).")
            return 0
        print(f"Datos del juego {report.build}: {report.recipes} recetas y {report.items} objetos.")
        for name, n in sorted(report.by_profession.items(), key=lambda kv: -kv[1]):
            print(f"  {name:<24} {n} recetas")
    except (OSError, ValueError) as exc:
        print(f"No he podido descargar los datos del juego: {exc}")
        return 1
    finally:
        conn.close()
    return 0


def cmd_informe(config: Config) -> int:
    if not config.db_path.exists():
        print("Todavía no hay base de datos. Ejecuta antes: python -m motor leer")
        return 1
    conn = dbmod.connect(config.db_path)
    try:
        text = write_report(conn, config)
    finally:
        conn.close()
    print(text)
    return 0


def cmd_ajustes(config: Config, hours: float | None, weeks: float | None, skillup: float | None) -> int:
    conn = dbmod.connect(config.db_path)
    try:
        settings = load_settings(conn)
        if hours is not None:
            settings.hours_per_week = hours
        if weeks is not None:
            settings.horizon_weeks = weeks
        if skillup is not None:
            settings.legacy_skillup = skillup
        if hours is not None or weeks is not None or skillup is not None:
            save_settings(conn, settings)
    finally:
        conn.close()
    print(f"Juegas {settings.hours_per_week:g} h a la semana; los métodos se comparan a "
          f"{settings.horizon_weeks:g} semanas.")
    print(f"Talento de Legacy para subir profesiones: +{settings.legacy_skillup:g} % de probabilidad"
          + (" (sin él)" if not settings.legacy_skillup else "") + ".")
    return 0


def cmd_metodos(config: Config) -> int:
    entries = load_catalog()
    if not entries:
        print(f"No hay métodos en {CATALOG_PATH}.")
        return 1
    conn = dbmod.connect(config.db_path)
    try:
        analysis = analyze(conn, entries)
        write_report(conn, config, analysis)
    finally:
        conn.close()
    kinds: dict[str, int] = {}
    for e in entries:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    print(f"{len(entries)} métodos en {CATALOG_PATH.name}: " + ", ".join(f"{n} {k}" for k, n in kinds.items()) + ".")
    unknown = analysis.guide_unknown_items
    if unknown:
        print(f"{len(unknown)} objetos que no salen en los datos del juego: {', '.join(unknown)}.")
    print(f"Todos, con tus precios: {config.db_path.parent / 'metodos.md'}")
    return 0


def _plain(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def cmd_guia(config: Config, profession: str, start: int | None, target: int | None) -> int:
    conn = dbmod.connect(config.db_path)
    try:
        lines = [(r["skill_line"], r["name"]) for r in conn.execute("SELECT skill_line, name FROM gd_skill_lines")]
        matches = [(line, name) for line, name in lines if _plain(profession) in _plain(name)]
        if not matches:
            print("No conozco esa profesión. Las que hay: " + ", ".join(sorted(n for _, n in lines))
                  if lines else "Faltan los datos del juego: python -m motor datos-juego")
            return 1
        line, name = matches[0]
        analysis = analyze(conn)
        current = conn.execute("SELECT MAX(rank) FROM profession_summary WHERE skill_line = ?", (line,)).fetchone()[0]
        start = start or max(1, current or 1)
        if target is None:
            target = max((c.required_skill or 0 for c in analysis.crafts if c.skill_line == line), default=start)
        known = {r[0] for r in conn.execute("SELECT recipe_id FROM known_recipes")}
        plan = plan_leveling(analysis.crafts, analysis.prices, analysis.owned, line, start, target, known,
                             load_settings(conn).skillup_bonus)
    finally:
        conn.close()
    text = render_guide(plan)
    guides = config.db_path.parent / "guias"
    guides.mkdir(exist_ok=True)
    (guides / guide_filename(plan)).write_text(text, encoding="utf-8")
    print(text)
    return 0


GAME_DATA_CHECK_SECONDS = 24 * 3600
GAME_DATA_RETRY_SECONDS = 3600


def check_game_data(config: Config) -> bool:
    """Comprobación para vigilar: solo dice algo si hay datos nuevos. True si los ha importado."""
    conn = dbmod.connect(config.db_path)
    try:
        report = update_game_data(conn, config.db_path.parent / "juego", config.wow_dir)
        if report is None:
            return False
        print(f"[{time.strftime('%H:%M:%S')}] Datos del juego actualizados: versión {report.build}, "
              f"{report.recipes} recetas.")
        print("  " + refresh_outputs(conn, config))
        return True
    finally:
        conn.close()


def cmd_vigilar(config: Config, interval: float) -> int:
    print("Vigilando los datos del addon. Cada /reload o salida del juego se leerá solo. Ctrl+C para parar.")
    print("Una vez al día se comprueba también si hay datos nuevos del juego.")
    seen: dict[str, float] = {}
    next_game_check = 0.0
    while True:
        if time.time() >= next_game_check:
            try:
                check_game_data(config)
                next_game_check = time.time() + GAME_DATA_CHECK_SECONDS
            except (OSError, ValueError) as exc:  # sin conexión o wago.tools caído
                print(f"No he podido comprobar los datos del juego; lo reintento en una hora ({exc}).")
                next_game_check = time.time() + GAME_DATA_RETRY_SECONDS
        changed = False
        for _, path in config.saved_variables():
            mtime = path.stat().st_mtime
            if seen.get(str(path)) != mtime:
                seen[str(path)] = mtime
                changed = True
        if changed:
            time.sleep(1)  # WoW puede estar terminando de escribir
            try:
                cmd_leer(config)
            except Exception as exc:  # un archivo a medio escribir no debe parar la vigilancia
                print(f"Error al leer los datos: {exc}")
        time.sleep(interval)


def cmd_estado(config: Config) -> int:
    if not config.db_path.exists():
        print("Todavía no hay base de datos. Ejecuta antes: python -m motor leer")
        return 1
    conn = dbmod.connect(config.db_path)
    try:
        print(build_report(conn))
    finally:
        conn.close()
    return 0


def cmd_chollos(config: Config, show_all: bool) -> int:
    if not config.db_path.exists():
        print("Todavía no hay base de datos. Ejecuta antes: python -m motor leer")
        return 1
    conn = dbmod.connect(config.db_path)
    try:
        candidates = analyze(conn).vendor_candidates
    finally:
        conn.close()
    shown = candidates if show_all else [c for c in candidates if c.due]
    if not shown:
        print("No toca comprobar ninguno." if candidates else "No hay posibles chollos de vendedor.")
        return 0
    print("Mira si algún vendedor los vende (en Wowhead, la pestaña «Vendido por»)\n"
          "y apúntalo con: python -m motor chollo <id> nadie | vende \"vendedor, zona y condiciones\"\n")
    for c in shown:
        print(f"{c.item_id:>7}  {c.name:<32} {c.why:<34} si lo vende alguien: +{format_money(c.gain)}/ud"
              + (f"  [{c.status}{': ' + c.detail if c.detail else ''}]" if c.status != "sin comprobar" else ""))
    return 0


def cmd_chollo(config: Config, item_id: int, result: str, detail: str | None) -> int:
    conn = dbmod.connect(config.db_path)
    try:
        record_check(conn, item_id, sold=(result == "vende"), detail=detail)
    finally:
        conn.close()
    print(f"Apuntado: {item_id} {result}" + (f" ({detail})" if detail else "") + ".")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m motor", description="Motor de PitiGolds")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("leer", help="lee los datos del addon y los guarda en la base de datos")
    watch = sub.add_parser("vigilar", help="lee los datos cada vez que WoW los guarde")
    watch.add_argument("--intervalo", type=float, default=2.0, help="segundos entre comprobaciones")
    sub.add_parser("estado", help="resumen de personajes, oro, profesiones y subasta")
    sub.add_parser("informe", help="qué craftear, qué recetas aprender y qué vender")
    game = sub.add_parser("datos-juego", help="descarga las recetas y objetos del juego de wago.tools")
    game.add_argument("--forzar", action="store_true", help="vuelve a importarlos aunque estén al día")
    deals = sub.add_parser("chollos", help="posibles chollos de vendedor que toca comprobar fuera del juego")
    deals.add_argument("--todos", action="store_true", help="también los que no toca comprobar todavía")
    deal = sub.add_parser("chollo", help="apunta si algún vendedor vende un objeto")
    deal.add_argument("item_id", type=int)
    deal.add_argument("resultado", choices=["nadie", "vende"])
    deal.add_argument("detalle", nargs="?", help="vendedor, zona y condiciones (si lo vende alguien)")
    settings = sub.add_parser("ajustes", help="horas que juegas a la semana y semanas a comparar")
    settings.add_argument("--horas-semana", type=float)
    settings.add_argument("--semanas", type=float)
    settings.add_argument("--legado-subida", type=float,
                          help="%% que suma tu talento de Legacy a la probabilidad de subir profesión")
    guide = sub.add_parser("guia", help="guía de subida de una profesión con su coste")
    guide.add_argument("profesion")
    guide.add_argument("--desde", type=int)
    guide.add_argument("--hasta", type=int)
    sub.add_parser("metodos", help="los métodos de tus guías con tus precios (datos/metodos.md)")
    args = parser.parse_args(argv)

    config = load_config()
    if args.cmd == "leer":
        return cmd_leer(config)
    if args.cmd == "ajustes":
        return cmd_ajustes(config, args.horas_semana, args.semanas, args.legado_subida)
    if args.cmd == "metodos":
        return cmd_metodos(config)
    if args.cmd == "guia":
        return cmd_guia(config, args.profesion, args.desde, args.hasta)
    if args.cmd == "chollos":
        return cmd_chollos(config, args.todos)
    if args.cmd == "chollo":
        return cmd_chollo(config, args.item_id, args.resultado, args.detalle)
    if args.cmd == "informe":
        return cmd_informe(config)
    if args.cmd == "datos-juego":
        return cmd_datos_juego(config, args.forzar)
    if args.cmd == "vigilar":
        try:
            return cmd_vigilar(config, args.intervalo)
        except KeyboardInterrupt:
            return 0
    return cmd_estado(config)


if __name__ == "__main__":
    sys.exit(main())
