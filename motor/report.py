"""Textos para leer: el resumen (python -m motor estado) y el informe de qué hacer
(python -m motor informe)."""

from __future__ import annotations

import json
import sqlite3
import time

from .analysis import Analysis
from .db import get_meta
from .ingest import WARBAND_KEY
from .money import ago, format_money, format_pct

# Divisas y funciones que interesan especialmente en WoW Forever.
HIGHLIGHT = ("favor", "legacy", "legado", "mercader", "comercio")

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
                  COALESCE(lp.market_price, lp.min_price) AS min_price,
                  SUM(i.count) * COALESCE(lp.market_price, lp.min_price) AS value
           FROM inventory i
           JOIN latest_prices lp ON lp.item_id = i.item_id
           LEFT JOIN items it ON it.item_id = i.item_id
           WHERE i.bound = 0 AND i.location != 'auctions'
           GROUP BY i.item_id ORDER BY value DESC"""
    ).fetchall()
    if rows:
        total_value = sum(r["value"] for r in rows)
        out.append("")
        out.append(f"Tu inventario vendible vale {format_money(total_value)} a precio de mercado "
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


# Informe de qué hacer ----------------------------------------------------------------

def _cell(text) -> str:
    return str(text).replace("|", "/").replace("\n", " · ")


def _table(headers: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines


def _missing_professions(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """SELECT s.char_key, s.name FROM profession_summary s
           WHERE NOT EXISTS (SELECT 1 FROM professions p WHERE p.char_key = s.char_key
                             AND (p.parent_id = s.skill_line OR p.profession_id = s.skill_line))
           ORDER BY s.char_key, s.name"""
    ).fetchall()
    return [f"{r['char_key']}: {r['name']}" for r in rows]


def _how_to_learn(c) -> str:
    text = c.source or "?"
    if c.learn_price:
        text += f" ({format_money(c.learn_price)})"
    return text


def _missing_hint(p) -> str:
    # El precio de catálogo solo sirve si algún vendedor lo vende: se da como pista.
    if p.catalog_buy:
        return f"{p.name} (si lo vende un vendedor: {format_money(p.catalog_buy)})"
    return p.name


def _other_professions(a: Analysis) -> list[list]:
    by_profession = {}
    for c in a.crafts:
        if not c.yours and c.complete and c.profit > 0 and c.profession:
            by_profession.setdefault(c.profession, []).append(c)
    rows = []
    for profession, crafts in by_profession.items():
        crafts.sort(key=lambda c: c.profit, reverse=True)
        best = crafts[0]
        rows.append((best.profit, [profession, len(crafts), best.name, best.required_skill or "",
                                   format_money(best.profit), ", ".join(c.name for c in crafts[1:4])]))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [row for _, row in rows]


def build_advice_report(conn: sqlite3.Connection, a: Analysis, limit: int = 15) -> str:
    out = ["# PitiGolds: qué hacer", ""]
    priced = sum(1 for p in a.prices.values() if p.market is not None)
    out.append(f"Último escaneo de subasta: {ago(a.last_scan)}. Objetos tuyos o de tus recetas con precio: {priced}.")
    out.append("Precios de mercado: media del 15 % más barato de lo que hay a la venta. "
               "Lo que vendes ya tiene descontado el 5 % de comisión.")

    known = sorted((c for c in a.crafts if c.known and c.complete and c.profit > 0),
                   key=lambda c: c.profit, reverse=True)
    out += ["", "## Crafteos rentables que ya sabes hacer", ""]
    if known:
        rows = []
        for c in known[:limit]:
            skill = c.difficulty_name if c.difficulty is not None and c.difficulty < 3 else ""
            listed = "" if c.output_listed is None else c.output_listed
            rows.append([c.name, ", ".join(c.known_by), format_money(c.cost), format_money(c.value),
                         format_money(c.profit), format_pct(c.margin) if c.margin is not None else "",
                         c.craftable_now or "", skill, listed])
        out += _table(["Receta", "Quién", "Coste", "Vendes por", "Beneficio", "Margen",
                       "Ya puedes hacer", "Sube habilidad", "En la subasta"], rows)
    else:
        out.append("Ninguno todavía. Hace falta abrir la ventana de tus profesiones y un escaneo de materiales.")

    learn = sorted((c for c in a.crafts if c.yours and not c.known and c.complete and c.profit > 0),
                   key=lambda c: c.profit, reverse=True)
    if learn:
        out += ["", "## Recetas de tus profesiones que te convendría aprender", ""]
        out += _table(["Receta", "Profesión", "Nivel", "Beneficio", "Cómo se aprende"],
                      [[c.name, c.profession or "", c.required_skill or "", format_money(c.profit),
                        _how_to_learn(c)] for c in learn[:limit]])

    others = _other_professions(a)
    if others:
        out += ["", "## Profesiones que no tienes", "",
                "Recetas que ya darían beneficio con los precios actuales. Cuánto costaría subir la "
                "profesión hasta ellas llegará con la guía de subida.", ""]
        out += _table(["Profesión", "Recetas con beneficio", "La mejor", "Nivel", "Beneficio", "Otras buenas"],
                      others[:limit])

    useful = [s for s in a.sales if s.action != "sin precio"]
    out += ["", "## Qué hacer con lo que tienes", ""]
    if useful:
        out += _table(["Objeto", "Cantidad", "Dónde", "Qué hacer", "Precio", "Total", "Por qué"],
                      [[s.name, s.count, s.places, s.action, format_money(s.unit_price),
                        format_money(s.total), s.reason] for s in useful[:limit * 2]])
    else:
        out.append("Nada todavía: hace falta saber qué tienes y haber escaneado la subasta.")

    notes = []
    no_price = [s.name for s in a.sales if s.action == "sin precio"]
    if no_price:
        notes.append(f"Objetos tuyos sin precio ({len(no_price)}): {', '.join(no_price[:10])}"
                     + (" ..." if len(no_price) > 10 else ""))
    blocked = {m.item_id: m for c in a.crafts if c.yours for m in c.missing}
    if blocked:
        names = [_missing_hint(m) for m in sorted(blocked.values(), key=lambda m: m.name)]
        notes.append(f"Materiales sin precio que impiden calcular recetas de tus profesiones: {', '.join(names[:10])}"
                     + (" ..." if len(names) > 10 else ""))
    game_build = get_meta(conn, "game_data_build")
    client = json.loads(get_meta(conn, "client") or "{}")
    client_build = f"{client['version']}.{client['build']}" if client.get("version") and client.get("build") else None
    if not game_build:
        notes.append("Faltan los datos del juego (recetas de todas las profesiones): python -m motor datos-juego")
    elif client_build and client_build != game_build:
        notes.append(f"Los datos del juego son de la versión {game_build} y tu cliente es la {client_build}: "
                     "python -m motor datos-juego")
    unscanned = _missing_professions(conn)
    if unscanned:
        notes.append("Profesiones sin abrir todavía (ábrelas una vez): " + "; ".join(unscanned))
    if a.last_scan and time.time() - a.last_scan > 24 * 3600:
        notes.append(f"El último escaneo de subasta es de {ago(a.last_scan)}: los precios pueden haber cambiado.")
    if notes:
        out += ["", "## Faltan datos", ""] + [f"- {n}" for n in notes]
    return "\n".join(out) + "\n"
