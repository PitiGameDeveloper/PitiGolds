"""Pasa los datos del archivo SavedVariables del addon a la base de datos."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .db import set_meta
from .luaparse import as_dict, as_list, parse_saved_variables
from .pricing import market_price

WARBAND_KEY = "_warband"
AUCTION_STATUS_ACTIVE = 0  # Enum.AuctionStatus.Active

_MARKUP = [
    (re.compile(r"\|c[0-9a-fA-F]{8}"), ""),
    (re.compile(r"\|r"), ""),
    (re.compile(r"\|T[^|]*\|t"), ""),
    (re.compile(r"\|A[^|]*\|a"), ""),
    (re.compile(r"\|H[^|]*\|h"), ""),
    (re.compile(r"\|h"), ""),
    (re.compile(r"\|n"), "\n"),
]


def plain_text(text: str | None) -> str | None:
    """Quita los códigos de color, iconos y enlaces de un texto de WoW."""
    if text is None:
        return None
    for pattern, repl in _MARKUP:
        text = pattern.sub(repl, text)
    return text.strip()


@dataclass
class IngestReport:
    account: str
    path: Path
    characters: int = 0
    recipes: int = 0
    new_scans: int = 0
    new_prices: int = 0
    farm_buckets: int = 0
    ledger_events: int = 0


def ingest_file(conn: sqlite3.Connection, account: str, path: Path) -> IngestReport:
    data = parse_saved_variables(path.read_text(encoding="utf-8", errors="replace"))
    db = data.get("PitiGoldsDB")
    if not isinstance(db, dict):
        raise ValueError(f"{path} no contiene PitiGoldsDB")
    report = IngestReport(account=account, path=path)
    now = int(time.time())
    with conn:
        for char_key, char in as_dict(db.get("characters")).items():
            _ingest_character(conn, account, str(char_key), char, now)
            report.characters += 1
        _ingest_account(conn, as_dict(db.get("account")))
        report.recipes = _ingest_recipes(conn, db)
        _ingest_vendors(conn, account, as_dict(db.get("vendorItems")))
        _ingest_trainers(conn, as_dict(db.get("trainerRecipes")))
        report.new_scans, report.new_prices = _ingest_scans(conn, account, as_list(db.get("scans")))
        report.farm_buckets = _ingest_farm(conn, as_dict(db.get("farmLog")))
        report.ledger_events = _ingest_ledger(conn, as_list(db.get("ledger")))
        _ingest_misc(conn, account, db, now)
    return report


def _ingest_ledger(conn: sqlite3.Connection, events: list) -> int:
    cur = conn.executemany(
        "INSERT OR IGNORE INTO ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(e.get("key"), e.get("t"), e.get("char"), e.get("type"), e.get("itemID"), e.get("itemName"),
          e.get("qty"), e.get("money"), e.get("unit"), e.get("deposit"), e.get("cut"), e.get("recipeID"),
          e.get("kind"), e.get("seconds"))
         for e in events if isinstance(e, dict) and e.get("key")],
    )
    return cur.rowcount


def _ingest_farm(conn: sqlite3.Connection, log: dict) -> int:
    # Los tramos van creciendo mientras juegas: se reemplazan enteros cada vez.
    for key, b in log.items():
        conn.execute(
            "INSERT OR REPLACE INTO farm_buckets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, b.get("t"), b.get("char"), b.get("zone"), b.get("zoneName"), b.get("label"),
             b.get("money") or 0, b.get("first"), b.get("last")),
        )
        conn.execute("DELETE FROM farm_items WHERE bucket_key = ?", (key,))
        conn.executemany("INSERT INTO farm_items VALUES (?, ?, ?)",
                         [(key, int(i), int(n)) for i, n in as_dict(b.get("items")).items()])
    return len(log)


# Personajes ---------------------------------------------------------------------

def _ingest_character(conn: sqlite3.Connection, account: str, key: str, c: dict, now: int) -> None:
    inv = as_dict(c.get("inventory"))
    mail = as_dict(inv.get("mail"))
    conn.execute(
        """INSERT OR REPLACE INTO characters
           (char_key, account, name, realm, faction, class, race, level, money, mail_money, last_seen, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (key, account, c.get("name"), c.get("realm"), c.get("faction"), c.get("class"), c.get("race"),
         c.get("level"), c.get("money"), mail.get("money"), c.get("lastSeen"), now),
    )

    summary = as_list(c.get("professionSummary"))
    if summary or "professionSummary" in c:
        conn.execute("DELETE FROM profession_summary WHERE char_key = ?", (key,))
        conn.executemany(
            "INSERT OR REPLACE INTO profession_summary VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(key, p.get("skillLine"), p.get("slot"), p.get("name"), p.get("rank"), p.get("maxRank"),
              p.get("modifier")) for p in summary],
        )

    for prof_id, p in as_dict(c.get("professions")).items():
        conn.execute(
            "INSERT OR REPLACE INTO professions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, prof_id, p.get("name"), p.get("parentID"), p.get("parentName"), p.get("skill"),
             p.get("maxSkill"), p.get("modifier"), p.get("total"), p.get("scanned"),
             json.dumps(p.get("info") or {}, ensure_ascii=False)),
        )
        conn.execute("DELETE FROM known_recipes WHERE char_key = ? AND profession_id = ?", (key, prof_id))
        difficulty = as_dict(p.get("difficulty"))
        conn.executemany(
            "INSERT OR REPLACE INTO known_recipes VALUES (?, ?, ?, ?)",
            [(key, rid, prof_id, difficulty.get(rid)) for rid in as_list(p.get("known"))],
        )

    if "currencies" in c:
        conn.execute("DELETE FROM currencies WHERE char_key = ?", (key,))
        conn.executemany(
            "INSERT OR REPLACE INTO currencies VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(key, cid, cur.get("name"), cur.get("quantity"), cur.get("max"), cur.get("earned"),
              1 if cur.get("accountWide") else 0)
             for cid, cur in as_dict(c.get("currencies")).items()],
        )

    if "reputations" in c:
        conn.execute("DELETE FROM reputations WHERE char_key = ?", (key,))
        conn.executemany(
            "INSERT OR REPLACE INTO reputations VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(key, fid, r.get("name"), r.get("standing"), r.get("reaction"), r.get("min"), r.get("max"))
             for fid, r in as_dict(c.get("reputations")).items()],
        )

    for location in ("bags", "bank", "mail"):
        if location in inv:
            block = as_dict(inv[location])
            _replace_inventory(conn, key, location, block.get("items"), block.get("bound"), block.get("updated"))

    # Lo enviado por correo desde otros personajes y aún no recogido.
    incoming: dict[int, int] = {}
    for entry in as_list(inv.get("mailIncoming")):
        for item_id, count in as_dict(entry.get("items")).items():
            incoming[item_id] = incoming.get(item_id, 0) + count
    _replace_inventory(conn, key, "mail_incoming", incoming, None, now)

    if "auctions" in inv:
        auctions = as_dict(inv["auctions"])
        updated = auctions.get("updated")
        listed = as_list(auctions.get("list"))
        conn.execute("DELETE FROM owned_auctions WHERE char_key = ?", (key,))
        conn.executemany(
            "INSERT INTO owned_auctions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(key, a.get("itemID"), a.get("qty"), a.get("buyout"), a.get("bid"), a.get("status"),
              a.get("timeLeft"), updated) for a in listed],
        )
        active: dict[int, int] = {}
        for a in listed:
            if a.get("status") == AUCTION_STATUS_ACTIVE and a.get("itemID"):
                active[a["itemID"]] = active.get(a["itemID"], 0) + (a.get("qty") or 0)
        _replace_inventory(conn, key, "auctions", active, None, updated)


def _replace_inventory(conn, char_key, location, items, bound, updated) -> None:
    conn.execute("DELETE FROM inventory WHERE char_key = ? AND location = ?", (char_key, location))
    rows = [(char_key, location, int(i), 0, int(n), updated) for i, n in as_dict(items).items()]
    rows += [(char_key, location, int(i), 1, int(n), updated) for i, n in as_dict(bound).items()]
    conn.executemany("INSERT OR REPLACE INTO inventory VALUES (?, ?, ?, ?, ?, ?)", rows)


def _ingest_account(conn: sqlite3.Connection, account: dict) -> None:
    if "warbandBank" in account:
        block = as_dict(account["warbandBank"])
        _replace_inventory(conn, WARBAND_KEY, "warband", block.get("items"), block.get("bound"),
                           block.get("updated"))
    if account.get("warbandMoney") is not None:
        set_meta(conn, "warband_money", str(account["warbandMoney"]))


# Recetas ----------------------------------------------------------------------------

def _ingest_recipes(conn: sqlite3.Connection, db: dict) -> int:
    recipes = as_dict(db.get("recipes"))
    for rid, r in recipes.items():
        conn.execute(
            "INSERT OR REPLACE INTO recipes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, r.get("name"), r.get("professionID"), r.get("professionName"), r.get("parentProfessionID"),
             r.get("categoryID"), r.get("output"), r.get("qtyMin"), r.get("qtyMax"), r.get("recipeType"),
             r.get("source"), plain_text(r.get("source")),
             json.dumps(r.get("info") or {}, ensure_ascii=False), r.get("updated")),
        )
        conn.execute("DELETE FROM recipe_reagents WHERE recipe_id = ?", (rid,))
        rows = []
        for slot in as_list(r.get("reagents")):
            # Si la API no dice si es obligatorio se guarda NULL, que se trata como obligatorio.
            required = None if slot.get("required") is None else int(bool(slot["required"]))
            base = (slot.get("qty"), slot.get("type"), required)
            for item_id in as_list(slot.get("items")):
                rows.append((rid, slot.get("slot"), item_id, None, *base))
            for currency_id in as_list(slot.get("currencies")):
                rows.append((rid, slot.get("slot"), None, currency_id, *base))
        conn.executemany("INSERT INTO recipe_reagents VALUES (?, ?, ?, ?, ?, ?, ?)", rows)

    conn.executemany(
        "INSERT OR REPLACE INTO recipe_categories VALUES (?, ?, ?)",
        [(cid, cat.get("name"), cat.get("parent")) for cid, cat in as_dict(db.get("recipeCategories")).items()],
    )
    item_rows = []
    for iid, entry in as_dict(db.get("items")).items():
        if isinstance(entry, str):  # formato de la versión 0.1 del addon: solo el nombre
            item_rows.append((iid, entry, None))
        elif isinstance(entry, dict):
            item_rows.append((iid, entry.get("name"), entry.get("sell")))
    conn.executemany(
        """INSERT INTO items (item_id, name, sell_price) VALUES (?, ?, ?)
           ON CONFLICT(item_id) DO UPDATE SET
             name = COALESCE(excluded.name, items.name),
             sell_price = COALESCE(excluded.sell_price, items.sell_price)""",
        item_rows,
    )

    return len(recipes)


def _ingest_vendors(conn: sqlite3.Connection, account: str, vendors: dict) -> None:
    # El addon guarda la lista completa (y borra lo que un vendedor ya no vende): se reemplaza.
    conn.execute("DELETE FROM vendor_items WHERE account = ? OR account IS NULL", (account,))
    conn.executemany(
        """INSERT OR REPLACE INTO vendor_items
           (item_id, price, limited, vendor, costs_json, updated, account, char_key, zone)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [(iid, v.get("price"), 1 if v.get("limited") else 0, v.get("vendor"),
          json.dumps(as_list(v.get("costs")), ensure_ascii=False) if v.get("costs") else None, v.get("time"),
          account, v.get("char"), v.get("zone"))
         for iid, v in vendors.items()],
    )


def _ingest_trainers(conn: sqlite3.Connection, trainers: dict) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO trainer_recipes VALUES (?, ?, ?, ?, ?, ?)",
        [(skill, name, t.get("rank"), t.get("level"), t.get("cost"), t.get("time"))
         for skill, recipes in trainers.items() for name, t in as_dict(recipes).items()],
    )


# Escaneos de subasta -------------------------------------------------------------------

def _parse_price(entry: str) -> tuple[int, int, int | None, int | None, str | None]:
    """'mínimo,cantidad[,subastas,vendedores][|libro]' -> tupla."""
    head, _, book = entry.partition("|")
    parts = head.split(",")
    min_price = int(float(parts[0]))
    quantity = int(float(parts[1]))
    auctions = int(parts[2]) if len(parts) > 2 else None
    owners = int(parts[3]) if len(parts) > 3 else None
    return min_price, quantity, auctions, owners, (book or None)


def _ingest_scans(conn: sqlite3.Connection, account: str, scans: list) -> tuple[int, int]:
    new_scans = new_prices = 0
    for s in scans:
        scan_time = int(s.get("time") or 0)
        scan_id = f"{scan_time}-{s.get('char')}-{s.get('type')}"
        cur = conn.execute(
            "INSERT OR IGNORE INTO scans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scan_id, s.get("type"), scan_time, s.get("started"), s.get("duration"), s.get("realm"),
             s.get("faction"), s.get("char"), s.get("count"), account),
        )
        if cur.rowcount == 0:
            continue  # ya estaba en la base de datos
        rows = []
        for item_id, entry in as_dict(s.get("items")).items():
            if isinstance(entry, str):
                min_price, quantity, auctions, owners, book = _parse_price(entry)
                rows.append((scan_id, int(item_id), min_price, quantity, auctions, owners, book,
                             market_price(min_price, quantity, book)))
        conn.executemany("INSERT OR REPLACE INTO prices VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
        new_scans += 1
        new_prices += len(rows)
    return new_scans, new_prices


# Resto ------------------------------------------------------------------------------------

def _ingest_misc(conn: sqlite3.Connection, account: str, db: dict, now: int) -> None:
    set_meta(conn, "addon_version", str(db.get("addonVersion")))
    set_meta(conn, "client", json.dumps(db.get("client") or {}, ensure_ascii=False))
    if db.get("discovery"):
        set_meta(conn, "discovery", json.dumps(db["discovery"], ensure_ascii=False))
    set_meta(conn, "last_ingest", str(now))
    conn.executemany(
        "INSERT OR IGNORE INTO addon_log VALUES (?, ?)",
        [(line, account) for line in as_list(db.get("log")) if isinstance(line, str)],
    )
