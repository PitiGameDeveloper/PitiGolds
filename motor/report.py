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


def _week_cell(profit: int, week: int | None) -> str:
    if week is None:
        return ""
    if week <= 0:
        return "ya no compensa"
    return format_money(week)


def _profit_cell(profit: int, week: int | None) -> str:
    """Beneficio de hoy y, si va a cambiar mucho, el previsto a 7 días."""
    text = format_money(profit)
    if week is not None and abs(week - profit) > abs(profit) * 0.1:
        text += " (en 7 días: " + ("ya no compensa" if week <= 0 else format_money(week)) + ")"
    return text


def _craftable_cell(c) -> str:
    """Cuántas puedes hacer con lo que tienes; si son más de las que se venden, cuántas hacer al día."""
    if not c.craftable_now:
        return ""
    cap = c.capacity
    if cap is not None and c.craftable_now > cap.units_per_day * 2:
        return f"{c.craftable_now} (haz unas {max(1, int(cap.units_per_day))} al día)"
    return str(c.craftable_now)


def _capacity_cell(cap) -> str:
    if cap is None:
        return ""
    return f"{format_money(cap.gold_per_day)} ({cap.units_per_day:.0f} uds, {cap.minutes_per_day:.0f} min)"


def _business_section(a: Analysis, limit: int) -> list[str]:
    b = a.business
    out = ["", "## Tu negocio en la subasta (últimos 14 días)", ""]
    if not b.items and not b.seconds:
        out.append("Todavía no hay movimientos. Se apuntan solos: compras de materiales, crafteos, lo que "
                   "pones a la venta y las ventas al recoger el dinero del correo.")
        return out
    trading = b.trading
    if trading:
        per_hour = format_money(b.per_hour) if b.per_hour is not None else "?"
        out.append(f"Beneficio de lo que fabricas o revendes: {format_money(b.profit)} en "
                   f"{_duration(b.trading_hours)} de gestión = {per_hour} por hora.")
    if b.farmed_sales:
        out.append(f"Ventas de lo farmeado (ya cuentan en tus farmeos): {format_money(b.farmed_sales)}.")
    out.append(f"Tiempo total con la subasta, la profesión o el correo abiertos: {_duration(b.hours)}.")
    if trading:
        out.append("")
        out += _table(["Objeto", "Origen", "Fabricados", "Comprados", "Puestos", "Vendidos", "Precio medio",
                       "Coste por unidad", "Depósitos sin recuperar", "Beneficio", "Oro/h"],
                      [[e.name, e.origin, f"{e.crafted:.0f}" if e.crafted else "", e.bought or "", e.posted or "",
                        e.sold or "", format_money(e.avg_sale) if e.avg_sale else "",
                        format_money(e.unit_cost) if e.unit_cost is not None else "?",
                        format_money(e.deposits_lost) if e.deposits_lost else "",
                        format_money(e.profit) if e.profit is not None else "?",
                        format_money(e.per_hour) if e.per_hour is not None else ""]
                       for e in trading[:limit]])
    return out


def _vendor_sections(a: Analysis, limit: int) -> list[str]:
    out = []
    if a.vendor_flips:
        out += ["", "## Comprar a vendedores y revender", "",
                "Vendedores que has visto que venden por debajo de lo que pagan en la subasta.", ""]
        out += _table(["Objeto", "Vendedor", "Compras a", "Vendes por", "Ganas por unidad", "En 7 días",
                       "Como mucho al día",
                       "Existencias"],
                      [[f.name, f.vendor, format_money(f.buy), format_money(f.sell), format_money(f.profit),
                        _week_cell(f.profit, f.profit_week),
                        format_money(f.gold_per_day) if f.gold_per_day is not None else "",
                        "limitadas" if f.limited else "sin límite"] for f in a.vendor_flips[:limit]])
    candidates = a.vendor_candidates
    if candidates:
        due = sum(1 for c in candidates if c.due)
        out += ["", "## Posibles chollos de vendedor", "",
                "Objetos de tus crafteos o farmeos que en la subasta (ya sin comisión) se pagan al menos un 30 % más "
                "de lo que costaría comprárselos a un vendedor. No se sabe si alguno lo vende: hay que mirarlo fuera del juego. Los materiales de "
                "botín (tela, mineral, hierbas...) y lo que farmeas se miran una vez y después solo con versiones "
                "nuevas del juego.",
                "",
                f"Toca comprobar {due}. Lista: python -m motor chollos. Para apuntar lo que encuentres: "
                "python -m motor chollo <id> nadie, o python -m motor chollo <id> vende \"vendedor, zona y condiciones\".",
                ""]
        out += _table(["Objeto", "ID", "Por qué importa", "Si lo vende alguien, ganarías", "Resultado",
                       "Siguiente comprobación"],
                      [[c.name, c.item_id, c.why, f"{format_money(c.gain)} por unidad",
                        c.status + (f": {c.detail}" if c.detail else ""), c.next_check]
                       for c in candidates[:limit]])
    return out


def _duration(hours: float) -> str:
    if hours < 1:
        return f"{hours * 60:.0f} min"
    return f"{hours:.1f} h".replace(".", ",")


def _market_cell(listed: int | None, s) -> str:
    parts = []
    if listed is not None:
        parts.append(f"{listed} en venta")
    if s is not None and s.sales_per_day:
        parts.append(f"~{s.sales_per_day:.0f}/día")
    if s is not None and s.outlook in ("baja", "sube"):
        parts.append(s.outlook)
    return " · ".join(parts)


def _accuracy_line(a: Analysis) -> str:
    b = a.accuracy
    if b.cases < 20:
        return ("Acierto de la previsión: todavía no hay historial para medirlo "
                f"({b.cases} casos; hacen falta 20).")
    return (f"Acierto de la previsión a 3 días: {format_pct(b.accuracy)} en {b.cases} casos "
            f"(decir siempre «estable» acertaría el {format_pct(b.baseline)}).")


def _moving_items(a: Analysis) -> list[list]:
    """Objetos que te afectan y cuyo precio se espera que cambie."""
    rows = []
    for item_id in a.relevant_items():
        s = a.signals.get(item_id)
        if s is None or s.outlook not in ("baja", "sube"):
            continue
        p = a.prices.get(item_id)
        sales = f"~{s.sales_per_day:.1f}" if s.sales_per_day else ""
        rows.append((abs(s.week_change or 0), [
            p.name if p else f"objeto {item_id}", format_money(s.current),
            f"{format_money(s.forecast_7d)} ({s.outlook})", s.quantity, sales, s.drop_risk, s.confidence,
            "; ".join(s.reasons)]))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [row for _, row in rows]


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
            rows.append([c.name, ", ".join(c.known_by), format_money(c.cost), format_money(c.value),
                         _profit_cell(c.profit, c.profit_week), _craftable_cell(c), skill,
                         _market_cell(c.output_listed, c.output_signals), _capacity_cell(c.capacity)])
        out += _table(["Receta", "Quién", "Coste", "Vendes por", "Beneficio", "Ya puedes hacer",
                       "Sube habilidad", "Mercado", "Como mucho al día"], rows)
        out.append("")
        out.append("«Como mucho al día»: beneficio si vendes el 30 % de lo que se vende al día (más hunde el "
                   "precio), y el tiempo que te lleva fabricarlo y ponerlo a la venta.")
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

    out += ["", "## Mercado: lo que se mueve", ""]
    out.append(_accuracy_line(a))
    moving = _moving_items(a)
    if moving:
        out.append("")
        out += _table(["Objeto", "Ahora", "En 7 días", "A la venta", "Ventas al día", "Riesgo de bajada",
                       "Confianza", "Por qué"], moving[:limit])
    else:
        out.append("")
        out.append("Nada que destacar: hacen falta al menos 3 escaneos repartidos en más de un día.")

    useful = [s for s in a.sales if s.action != "sin precio"]
    out += ["", "## Qué hacer con lo que tienes", ""]
    if useful:
        out += _table(["Objeto", "Cantidad", "Dónde", "Qué hacer", "Precio", "Total", "Ritmo", "Por qué"],
                      [[s.name, s.count, s.places, s.action, format_money(s.unit_price),
                        format_money(s.total), s.pace, s.reason] for s in useful[:limit * 2]])
    else:
        out.append("Nada todavía: hace falta saber qué tienes y haber escaneado la subasta.")

    out += ["", "## Tus farmeos (últimos 14 días)", ""]
    if a.farms:
        out.append("Oro por hora real: lo ganado (objetos a precio de mercado sin comisión, más el oro) "
                   "entre la primera y la última ganancia de cada sesión, valorado con los precios de hoy "
                   "y con los previstos dentro de 7 días.")
        out.append("")
        out += _table(["Actividad", "Zona", "Sesiones", "Tiempo", "Oro/h hoy", "Oro/h en 7 días"],
                      [[g.activity, g.zone, g.sessions, _duration(g.hours), format_money(g.per_hour),
                        format_money(g.per_hour_week)] for g in a.farm_summary[:limit]])
        recent = sorted(a.farms, key=lambda s: s.start, reverse=True)[:10]
        out += ["", "Últimas sesiones:", ""]
        out += _table(["Cuándo", "Quién", "Zona", "Actividad", "Duración", "Oro/h", "Lo principal"],
                      [[ago(s.end), s.char_key, s.zone, s.activity, _duration(s.hours),
                        format_money(s.per_hour), ", ".join(s.top_items)] for s in recent])
    else:
        out.append("Todavía no hay farmeos registrados. Se apuntan solos mientras juegas; "
                   "ponles nombre con /pg farmeo <nombre>.")

    out += _business_section(a, limit)
    out += _vendor_sections(a, limit)

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
