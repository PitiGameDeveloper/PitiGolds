"""Escribe Generated.lua, el archivo que el addon carga al hacer /reload.

De momento solo le dice al addon hasta qué escaneo ha guardado ya el motor, para
que los borre de SavedVariables y el archivo no crezca sin parar.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

TEMPLATE = """-- Este archivo lo escribe el motor de PitiGolds (python -m motor). No lo edites a mano.
PitiGoldsGenerated = {{
  ingestedUpTo = {ingested_up_to},
  generatedAt = {generated_at},
}}
"""


def write_generated(conn: sqlite3.Connection, addon_dir: Path) -> Path | None:
    if not addon_dir.is_dir():
        return None
    ingested_up_to = conn.execute("SELECT COALESCE(MAX(time), 0) FROM scans").fetchone()[0]
    content = TEMPLATE.format(ingested_up_to=int(ingested_up_to), generated_at=int(time.time()))
    target = addon_dir / "Generated.lua"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)
    return target
