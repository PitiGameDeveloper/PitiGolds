"""Uso:
    python -m motor leer       lee los datos del addon una vez
    python -m motor vigilar    los lee cada vez que WoW los guarda (/reload o salir)
    python -m motor estado     resumen de personajes, oro, profesiones y subasta
    python -m motor informe    qué craftear, qué aprender y qué vender
    python -m motor datos-juego  descarga las recetas y objetos del juego (wago.tools)
    python -m motor chollos    posibles chollos de vendedor que toca comprobar fuera del juego
    python -m motor chollo <id> nadie | vende "detalle"   apunta lo que encuentres
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time

from . import db as dbmod
from .analysis import analyze
from .config import Config, load_config
from .gamedata import update_game_data
from .generated import write_generated
from .ingest import ingest_file
from .money import format_money
from .report import build_advice_report, build_report
from .vendors import record_check


def refresh_outputs(conn: sqlite3.Connection, config: Config) -> str:
    """Rehace Generated.lua (para el juego) y datos/informe.md. Devuelve un resumen de una línea."""
    analysis = analyze(conn)
    target = write_generated(conn, config.addon_dir, analysis)
    if target is None:
        print(f"Aviso: no encuentro la carpeta del addon ({config.addon_dir}); no he escrito Generated.lua.")
    report_path = config.db_path.parent / "informe.md"
    report_path.write_text(build_advice_report(conn, analysis), encoding="utf-8")
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
        text = build_advice_report(conn, analyze(conn))
    finally:
        conn.close()
    (config.db_path.parent / "informe.md").write_text(text, encoding="utf-8")
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
    args = parser.parse_args(argv)

    config = load_config()
    if args.cmd == "leer":
        return cmd_leer(config)
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
