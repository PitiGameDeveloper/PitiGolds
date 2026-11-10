"""Escribe Generated.lua, el archivo que el addon carga al hacer /reload.

Lleva:
  ingestedUpTo  hasta qué escaneo ha guardado ya el motor, para que el addon los
                borre de SavedVariables y el archivo no crezca sin parar.
  prices        "mercado,mediana,tendencia,ventas" de tus objetos y de los materiales de tus
                recetas, para el tooltip. Tendencia: b (baja), s (sube) o vacía. Ventas: unidades
                vendidas al día (estimadas), o vacío si no hay datos suficientes.
  craft         coste y beneficio por unidad de lo que sabes fabricar.
  recipes       "coste,ganancia" de cada fabricación de las recetas de tus profesiones, para
                la ventana de profesión. Ganancia vacía si lo fabricado no tiene precio.
  recipeParts   desglose de esas recetas (recipe_parts) para recalcularlas en el juego con lo que
                se acaba de ver en la subasta.
  lastScan      hora del último escaneo de la subasta.
  methods       la ventana de métodos: el mejor farmeo y las pestañas de farmeos y crafteos
                (panel.py).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .analysis import Analysis, analyze
from .panel import Panel, build_panel, panel_export

HEADER = "-- Este archivo lo escribe el motor de PitiGolds (python -m motor). No lo edites a mano."
TREND_CODES = {"baja": "b", "sube": "s"}
FARM_KEEP_SECONDS = 600


def lua_value(value, indent: str = "  ") -> str:
    """Un valor de Python escrito como Lua: dict -> tabla con claves, list -> lista."""
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.4g}" if value == value and abs(value) != float("inf") else "nil"
    if isinstance(value, str):
        text = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")
        return f'"{text}"'
    inner = indent + "  "
    if isinstance(value, dict):
        items = [(k, v) for k, v in value.items() if v is not None]
        if not items:
            return "{}"
        parts = [(f"{k} = " if isinstance(k, str) and k.isidentifier() else f"[{lua_value(k)}] = ")
                 + lua_value(v, inner) for k, v in items]
    else:
        if not value:
            return "{}"
        parts = [lua_value(v, inner) for v in value]
    return "{\n" + "".join(f"{inner}{part},\n" for part in parts) + indent + "}"


def _num(value) -> str:
    """Número para recipeParts: entero si lo es, vacío si no hay."""
    if value is None:
        return ""
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.4g}"
    return str(int(value))


def recipe_parts(c, prices: dict) -> str:
    """Desglose de una receta para que el addon la recalcule con los precios que ve en la subasta:
    "objeto,unidades,valor,venta_vendedor,depósito|material:cantidad:coste:tienda;..."
    valor: lo que el motor cobra por lo fabricado (por fabricación); coste: lo que el motor paga por
    unidad del material; tienda: lo que cuesta a un vendedor sin límite (vacío si no hay)."""
    out = prices.get(c.output_item_id) if c.output_item_id else None
    head = ",".join([
        _num(c.output_item_id), _num(c.output_qty), _num(c.value),
        _num(out.vendor_sell if out else None), _num(round(out.deposit_per_unit, 2) if out else None),
    ])
    parts = []
    for r in c.reagents:
        if r.item_id is None:
            continue
        p = prices.get(r.item_id)
        shop = p.shop_price if p is not None else None
        parts.append(f"{r.item_id}:{r.quantity}:{_num(r.unit_cost)}:{_num(shop)}")
    return head + "|" + ";".join(parts)


def render_generated(ingested_up_to: int, analysis: Analysis, now: int | None = None,
                     farm_ingested_up_to: int = 0, ledger_ingested_up_to: int = 0,
                     panel: Panel | None = None) -> str:
    lines = [
        HEADER,
        "PitiGoldsGenerated = {",
        f"  ingestedUpTo = {int(ingested_up_to)},",
        f"  farmIngestedUpTo = {int(farm_ingested_up_to)},",
        f"  ledgerIngestedUpTo = {int(ledger_ingested_up_to)},",
        f"  generatedAt = {int(now if now is not None else time.time())},",
        "  prices = {",
    ]
    for item_id, p in sorted(analysis.prices.items()):
        if p.market is not None:
            median = p.median if p.has_history else ""
            s = analysis.signals.get(item_id)
            trend = TREND_CODES.get(s.outlook, "") if s is not None and s.confidence != "baja" else ""
            sales = "" if s is None or s.sales_per_day is None else f"{s.sales_per_day:.1f}"
            lines.append(f'    [{item_id}] = "{p.market},{median},{trend},{sales}",')
    lines.append("  },")
    lines.append("  craft = {")
    for item_id, c in sorted(analysis.best_known_craft().items()):
        lines.append(f'    [{item_id}] = "{round(c.cost / c.output_qty)},{round(c.profit / c.output_qty)}",')
    lines.append("  },")
    lines.append("  recipes = {")
    for c in sorted(analysis.crafts, key=lambda c: c.recipe_id):
        if c.yours and c.cost is not None:
            profit = c.profit if c.profit is not None else ""
            lines.append(f'    [{c.recipe_id}] = "{c.cost},{profit}",')
    lines.append("  },")
    lines.append("  recipeParts = {")
    for c in sorted(analysis.crafts, key=lambda c: c.recipe_id):
        if c.yours and c.cost is not None:
            lines.append(f'    [{c.recipe_id}] = "{recipe_parts(c, analysis.prices)}",')
    lines.append("  },")
    if analysis.last_scan:
        lines.append(f"  lastScan = {int(analysis.last_scan)},")
    if panel is not None:
        lines.append(f"  methods = {lua_value(panel_export(panel))},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_generated(conn: sqlite3.Connection, addon_dir: Path, analysis: Analysis | None = None,
                    panel: Panel | None = None) -> Path | None:
    if not addon_dir.is_dir():
        return None
    ingested_up_to = conn.execute("SELECT COALESCE(MAX(time), 0) FROM scans").fetchone()[0]
    # Los tramos de farmeo de los últimos 10 minutos pueden seguir creciendo en el juego:
    # el addon los conserva y se vuelven a leer completos la próxima vez.
    newest_farm = conn.execute("SELECT MAX(t) FROM farm_buckets").fetchone()[0]
    farm_up_to = newest_farm - FARM_KEEP_SECONDS if newest_farm else 0
    ledger_up_to = conn.execute("SELECT COALESCE(MAX(t), 0) FROM ledger").fetchone()[0]
    analysis = analysis if analysis is not None else analyze(conn)
    panel = panel if panel is not None else build_panel(conn, analysis)
    content = render_generated(ingested_up_to, analysis, farm_ingested_up_to=farm_up_to,
                               ledger_ingested_up_to=ledger_up_to, panel=panel)
    target = addon_dir / "Generated.lua"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)
    return target
