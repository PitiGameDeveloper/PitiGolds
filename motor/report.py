"""Resumen legible de lo que hay en la base de datos (python -m motor estado)."""

from __future__ import annotations

import json
import sqlite3
import time

from .db import get_meta
from .ingest import WARBAND_KEY

# Divisas y funciones que interesan especialmente en WoW Forever.
HIGHLIGHT = ("favor", "legacy", "legado", "mercader", "comercio")


def format_money(copper: int | None) -> str:
    copper = int(copper or 0)
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    gold, rest = divmod(copper, 10000)
    silver, cop = divmod(rest, 100)
    parts = []
    if gold:
        parts.append(f"{gold:,}".replace(",", ".") + " o")
    if gold or silver:
        parts.append(f"{silver} p")
    parts.append(f"{cop} c")
    return sign + " ".join(parts)


def ago(ts: int | None) -> str:
    if not ts:
        return "nunca"
    minutes = int((time.time() - ts) / 60)
    if minutes < 1:
        return "ahora"
    if minutes < 60:
        return f"hace {minutes} min"
    if minutes < 48 * 60:
        return f"hace {minutes // 60} h"
    return f"hace {minutes // (24 * 60)} días"


def build_report(conn: sqlite3.Connection, top: int = 10) -> str:
    out: list[str] = []
    chars = conn.execute(
        "SELECT * FROM characters WHERE char_key != ? ORDER BY level DESC, char_key", (WARBAND_KEY,)
    ).fetchall()
    if not chars:
        return ("Todavía no hay datos. Entra en el juego con el addon activado, pulsa Exportar "
                "y ejecuta: python -m motor leer")

    out.append(f"PitiGolds: datos leídos {ago(int(get_meta(conn, 'last_ingest') or 0))}")
    out.append("")
    out.append("Personajes")
    total_chars = total_mail = 0
    for c in chars:
        total_chars += c["money"] or 0
        total_mail += c["mail_money"] or 0
        out.append(f"  {c['char_key']:<24} nivel {c['level'] or '?':<3} {c['class'] or '':<12} "
                   f"{format_money(c['money']):>22}   (visto {ago(c['last_seen'])})")
    warband = int(get_meta(conn, "warband_money") or 0)
    out.append(f"  Oro: {format_money(total_chars)} en personajes + {format_money(total_mail)} en el correo"
               + (f" + {format_money(warband)} en el banco de banda" if warband else ""))

    out.append("")
    out.append("Profesiones")
    profs = conn.execute(
        """SELECT p.char_key, p.name, p.skill, p.max_skill,
                  (SELECT COUNT(*) FROM known_recipes k
                    WHERE k.char_key = p.char_key AND k.profession_id = p.profession_id) AS known,
                  p.recipes_total
           FROM professions p ORDER BY p.char_key, p.name"""
    ).fetchall()
    summary = conn.execute(
        "SELECT char_key, name, rank, max_rank FROM profession_summary ORDER BY char_key, name"
    ).fetchall()
    if profs:
        for p in profs:
            out.append(f"  {p['char_key']:<24} {p['name']:<22} {p['skill']}/{p['max_skill']}  "
                       f"{p['known']} recetas conocidas de {p['recipes_total']}")
    for s in summary:
        out.append(f"  {s['char_key']:<24} {s['name']:<22} {s['rank']}/{s['max_rank']}  (libro de hechizos)")
    if not profs and not summary:
        out.append("  Ninguna todavía. Abre la ventana de cada profesión una vez para guardar sus recetas.")

    out.append("")
    out.append("Subasta")
    for kind, label in (("full", "completos"), ("browse", "de materiales")):
        row = conn.execute(
            "SELECT COUNT(*) AS n, MAX(time) AS last FROM scans WHERE type = ?", (kind,)
        ).fetchone()
        out.append(f"  Escaneos {label}: {row['n']} (último {ago(row['last'])})")
    priced = conn.execute("SELECT COUNT(*) FROM latest_prices").fetchone()[0]
    out.append(f"  Objetos con precio: {priced}")

    rows = conn.execute(
        """SELECT i.item_id, COALESCE(it.name, 'objeto ' || i.item_id) AS name, SUM(i.count) AS count,
                  lp.min_price, SUM(i.count) * lp.min_price AS value
           FROM inventory i
           JOIN latest_prices lp ON lp.item_id = i.item_id
           LEFT JOIN items it ON it.item_id = i.item_id
           WHERE i.bound = 0 AND i.location != 'auctions'
           GROUP BY i.item_id ORDER BY value DESC"""
    ).fetchall()
    if rows:
        total_value = sum(r["value"] for r in rows)
        out.append("")
        out.append(f"Tu inventario vendible vale {format_money(total_value)} a precio mínimo de subasta "
                   f"(antes del 5 % de comisión)")
        for r in rows[:top]:
            out.append(f"  {r['name'][:32]:<32} x{r['count']:<6} {format_money(r['min_price']):>20} c/u"
                       f"  = {format_money(r['value'])}")

    currencies = conn.execute(
        "SELECT char_key, name, quantity, max_quantity FROM currencies ORDER BY name, char_key"
    ).fetchall()
    special = [c for c in currencies if any(h in (c["name"] or "").lower() for h in HIGHLIGHT)]
    if special:
        out.append("")
        out.append("Divisas de Forever")
        for c in special:
            cap = f"/{c['max_quantity']}" if c["max_quantity"] else ""
            out.append(f"  {c['char_key']:<24} {c['name']:<28} {c['quantity']}{cap}")

    discovery = json.loads(get_meta(conn, "discovery") or "{}")
    functions = discovery.get("functions") or []
    if isinstance(functions, dict):
        functions = list(functions.values())
    if functions:
        out.append("")
        out.append(f"APIs nuevas encontradas ({len(functions)}): " + ", ".join(functions[:12])
                   + (" ..." if len(functions) > 12 else ""))
    return "\n".join(out)
