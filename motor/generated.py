"""Escribe Generated.lua, el archivo que el addon carga al hacer /reload.

Lleva:
  ingestedUpTo  hasta qué escaneo ha guardado ya el motor, para que el addon los
                borre de SavedVariables y el archivo no crezca sin parar.
  prices        precio de mercado y mediana de 7 días de tus objetos y de los
                materiales de tus recetas, para el tooltip.
  craft         coste y beneficio por unidad de lo que sabes fabricar.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .analysis import Analysis, analyze

HEADER = "-- Este archivo lo escribe el motor de PitiGolds (python -m motor). No lo edites a mano."


def render_generated(ingested_up_to: int, analysis: Analysis, now: int | None = None) -> str:
    lines = [
        HEADER,
        "PitiGoldsGenerated = {",
        f"  ingestedUpTo = {int(ingested_up_to)},",
        f"  generatedAt = {int(now if now is not None else time.time())},",
        "  prices = {",
    ]
    for item_id, p in sorted(analysis.prices.items()):
        if p.market is not None:
            median = p.median if p.has_history else ""
            lines.append(f'    [{item_id}] = "{p.market},{median}",')
    lines.append("  },")
    lines.append("  craft = {")
    for item_id, c in sorted(analysis.best_known_craft().items()):
        lines.append(f'    [{item_id}] = "{round(c.cost / c.output_qty)},{round(c.profit / c.output_qty)}",')
    lines.append("  },")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_generated(conn: sqlite3.Connection, addon_dir: Path, analysis: Analysis | None = None) -> Path | None:
    if not addon_dir.is_dir():
        return None
    ingested_up_to = conn.execute("SELECT COALESCE(MAX(time), 0) FROM scans").fetchone()[0]
    content = render_generated(ingested_up_to, analysis if analysis is not None else analyze(conn))
    target = addon_dir / "Generated.lua"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)
    return target
