"""Uso:
    python -m motor leer       lee los datos del addon una vez
    python -m motor vigilar    los lee cada vez que WoW los guarda (/reload o salir)
    python -m motor estado     resumen de personajes, oro, profesiones y subasta
"""

from __future__ import annotations

import argparse
import sys
import time

from . import db as dbmod
from .config import Config, load_config
from .generated import write_generated
from .ingest import ingest_file
from .report import build_report


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
        target = write_generated(conn, config.addon_dir)
        if target is None:
            print(f"Aviso: no encuentro la carpeta del addon ({config.addon_dir}); no he escrito Generated.lua.")
    finally:
        conn.close()
    return 0


def cmd_vigilar(config: Config, interval: float) -> int:
    print("Vigilando los datos del addon. Cada /reload o salida del juego se leerá solo. Ctrl+C para parar.")
    seen: dict[str, float] = {}
    while True:
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


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m motor", description="Motor de PitiGolds")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("leer", help="lee los datos del addon y los guarda en la base de datos")
    watch = sub.add_parser("vigilar", help="lee los datos cada vez que WoW los guarde")
    watch.add_argument("--intervalo", type=float, default=2.0, help="segundos entre comprobaciones")
    sub.add_parser("estado", help="resumen de personajes, oro, profesiones y subasta")
    args = parser.parse_args(argv)

    config = load_config()
    if args.cmd == "leer":
        return cmd_leer(config)
    if args.cmd == "vigilar":
        try:
            return cmd_vigilar(config, args.intervalo)
        except KeyboardInterrupt:
            return 0
    return cmd_estado(config)


if __name__ == "__main__":
    sys.exit(main())
