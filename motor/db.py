"""Base de datos SQLite del motor."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS characters (
  char_key TEXT PRIMARY KEY, account TEXT, name TEXT, realm TEXT, faction TEXT,
  class TEXT, race TEXT, level INTEGER, money INTEGER, mail_money INTEGER,
  last_seen INTEGER, ingested_at INTEGER
);

-- Lo que muestra el libro de hechizos (sin abrir la ventana de la profesión).
CREATE TABLE IF NOT EXISTS profession_summary (
  char_key TEXT, skill_line INTEGER, slot TEXT, name TEXT,
  rank INTEGER, max_rank INTEGER, modifier INTEGER,
  PRIMARY KEY (char_key, skill_line)
);

-- Lo que se ve al abrir la ventana de la profesión.
CREATE TABLE IF NOT EXISTS professions (
  char_key TEXT, profession_id INTEGER, name TEXT, parent_id INTEGER, parent_name TEXT,
  skill INTEGER, max_skill INTEGER, modifier INTEGER, recipes_total INTEGER, scanned INTEGER,
  info_json TEXT,
  PRIMARY KEY (char_key, profession_id)
);

CREATE TABLE IF NOT EXISTS known_recipes (
  char_key TEXT, recipe_id INTEGER, profession_id INTEGER, difficulty INTEGER,
  PRIMARY KEY (char_key, recipe_id)
);

CREATE TABLE IF NOT EXISTS recipes (
  recipe_id INTEGER PRIMARY KEY, name TEXT, profession_id INTEGER, profession_name TEXT,
  parent_profession_id INTEGER, category_id INTEGER, output_item_id INTEGER,
  qty_min REAL, qty_max REAL, recipe_type INTEGER,
  source_text TEXT, source_plain TEXT, info_json TEXT, updated INTEGER
);

-- Un mismo hueco (slot) puede aceptar varios objetos alternativos.
CREATE TABLE IF NOT EXISTS recipe_reagents (
  recipe_id INTEGER, slot INTEGER, item_id INTEGER, currency_id INTEGER,
  quantity INTEGER, reagent_type INTEGER, required INTEGER
);
CREATE INDEX IF NOT EXISTS idx_reagents_recipe ON recipe_reagents(recipe_id);
CREATE INDEX IF NOT EXISTS idx_reagents_item ON recipe_reagents(item_id);

CREATE TABLE IF NOT EXISTS recipe_categories (category_id INTEGER PRIMARY KEY, name TEXT, parent_id INTEGER);

CREATE TABLE IF NOT EXISTS items (item_id INTEGER PRIMARY KEY, name TEXT);

CREATE TABLE IF NOT EXISTS currencies (
  char_key TEXT, currency_id INTEGER, name TEXT, quantity INTEGER, max_quantity INTEGER,
  total_earned INTEGER, account_wide INTEGER,
  PRIMARY KEY (char_key, currency_id)
);

CREATE TABLE IF NOT EXISTS reputations (
  char_key TEXT, faction_id INTEGER, name TEXT, standing INTEGER, reaction INTEGER,
  threshold_min INTEGER, threshold_max INTEGER,
  PRIMARY KEY (char_key, faction_id)
);

-- location: bags, bank, mail, mail_incoming, auctions, warband (char_key '_warband').
CREATE TABLE IF NOT EXISTS inventory (
  char_key TEXT, location TEXT, item_id INTEGER, bound INTEGER, count INTEGER, updated INTEGER,
  PRIMARY KEY (char_key, location, item_id, bound)
);
CREATE INDEX IF NOT EXISTS idx_inventory_item ON inventory(item_id);

CREATE TABLE IF NOT EXISTS owned_auctions (
  char_key TEXT, item_id INTEGER, quantity INTEGER, buyout INTEGER, bid INTEGER,
  status INTEGER, time_left INTEGER, updated INTEGER
);

-- type: full (subasta completa, una por una) o browse (materiales: mínimo y cantidad).
CREATE TABLE IF NOT EXISTS scans (
  scan_id TEXT PRIMARY KEY, type TEXT, time INTEGER, started INTEGER, duration INTEGER,
  realm TEXT, faction TEXT, char_key TEXT, item_count INTEGER, account TEXT
);
CREATE INDEX IF NOT EXISTS idx_scans_time ON scans(time);

-- book: "precio:cantidad;precio:cantidad" con los niveles de precio más baratos.
CREATE TABLE IF NOT EXISTS prices (
  scan_id TEXT, item_id INTEGER, min_price INTEGER, quantity INTEGER,
  num_auctions INTEGER, num_owners INTEGER, book TEXT,
  PRIMARY KEY (scan_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_prices_item ON prices(item_id);

CREATE TABLE IF NOT EXISTS addon_log (line TEXT PRIMARY KEY, account TEXT);

CREATE VIEW IF NOT EXISTS latest_prices AS
  SELECT item_id, min_price, quantity, num_auctions, num_owners, time, type FROM (
    SELECT p.item_id, p.min_price, p.quantity, p.num_auctions, p.num_owners, s.time, s.type,
           ROW_NUMBER() OVER (PARTITION BY p.item_id ORDER BY s.time DESC) AS rn
    FROM prices p JOIN scans s ON s.scan_id = p.scan_id
  )
  WHERE rn = 1;
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
    )
    conn.commit()
    return conn


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
