"""Base de datos SQLite del motor."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS trainer_recipes (
  skill_name TEXT, name TEXT, rank INTEGER, level INTEGER, cost INTEGER, updated INTEGER,
  PRIMARY KEY (skill_name, name)
);

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

-- sell_price: lo que paga un vendedor por una unidad.
CREATE TABLE IF NOT EXISTS items (item_id INTEGER PRIMARY KEY, name TEXT, sell_price INTEGER);

-- Lo que venden los vendedores que has visto. price: por unidad, NULL si solo se paga con
-- divisas (costs_json). char_key: quién lo vio (el precio puede llevar sus descuentos).
-- zone: dónde estaba el vendedor.
CREATE TABLE IF NOT EXISTS vendor_items (
  item_id INTEGER PRIMARY KEY, price INTEGER, limited INTEGER, vendor TEXT, costs_json TEXT, updated INTEGER,
  account TEXT, char_key TEXT, zone TEXT
);

-- Comprobaciones fuera del juego (Wowhead...) de si algún vendedor vende un objeto (vendors.py).
-- status: vende o nadie; misses: veces seguidas que salió «nadie»; game_build: versión del juego entonces.
CREATE TABLE IF NOT EXISTS vendor_checks (
  item_id INTEGER PRIMARY KEY, status TEXT, detail TEXT, checked_at INTEGER, misses INTEGER, game_build TEXT
);

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
-- market_price: precio medio del 1 % más barato de las unidades (mínimo 5) (ver pricing.py).
CREATE TABLE IF NOT EXISTS prices (
  scan_id TEXT, item_id INTEGER, min_price INTEGER, quantity INTEGER,
  num_auctions INTEGER, num_owners INTEGER, book TEXT, market_price INTEGER,
  PRIMARY KEY (scan_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_prices_item ON prices(item_id);

CREATE TABLE IF NOT EXISTS addon_log (line TEXT PRIMARY KEY, account TEXT);

-- Lo ganado farmeando, en tramos de 5 minutos por personaje, zona y etiqueta (farming.py).
-- first/last: hora de la primera y la última ganancia del tramo.
CREATE TABLE IF NOT EXISTS farm_buckets (
  bucket_key TEXT PRIMARY KEY, t INTEGER, char_key TEXT, zone_id INTEGER, zone_name TEXT,
  label TEXT, money INTEGER, first INTEGER, last INTEGER
);
CREATE INDEX IF NOT EXISTS idx_farm_buckets_t ON farm_buckets(t);
CREATE TABLE IF NOT EXISTS farm_items (
  bucket_key TEXT, item_id INTEGER, count INTEGER, PRIMARY KEY (bucket_key, item_id)
);

-- Contabilidad de subasta y crafteo (business.py). type: buy, post, sale, craft o time.
-- money: lo pagado (buy), el precio de venta bruto (sale); unit_price: precio por unidad puesto (post);
-- deposit: depósito pagado (post) o devuelto (sale); cut: comisión (sale); seconds: tiempo (time).
-- Las ventas y compras por correo solo traen el nombre del objeto (item_name).
CREATE TABLE IF NOT EXISTS ledger (
  event_key TEXT PRIMARY KEY, t INTEGER, char_key TEXT, type TEXT, item_id INTEGER, item_name TEXT,
  quantity INTEGER, money INTEGER, unit_price INTEGER, deposit INTEGER, cut INTEGER,
  recipe_id INTEGER, kind TEXT, seconds INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ledger_t ON ledger(t);

-- Novedades de tus fuentes (fuentes.py). status: nuevo (sin revisar) o visto.
CREATE TABLE IF NOT EXISTS source_items (
  key TEXT PRIMARY KEY, source TEXT, title TEXT, url TEXT, published INTEGER, summary TEXT,
  first_seen INTEGER, status TEXT
);

-- Datos del juego descargados de wago.tools (gamedata.py). Se rehacen en cada importación.
CREATE TABLE IF NOT EXISTS gd_skill_lines (skill_line INTEGER PRIMARY KEY, name TEXT, category INTEGER, parent INTEGER);

-- spell_id es el mismo número que el recipeID del juego.
-- Color al fabricar: naranja hasta yellow, amarilla hasta (yellow+grey)/2, verde hasta grey.
-- cooldown_hours: espera entre fabricaciones; las de la misma cooldown_category la comparten.
CREATE TABLE IF NOT EXISTS gd_recipes (
  spell_id INTEGER PRIMARY KEY, skill_line INTEGER, name TEXT,
  min_skill INTEGER, yellow INTEGER, grey INTEGER, num_skillups INTEGER, acquire INTEGER,
  output_item_id INTEGER, output_qty REAL, learn_item_id INTEGER,
  cooldown_hours REAL, cooldown_category INTEGER
);
CREATE TABLE IF NOT EXISTS gd_reagents (spell_id INTEGER, item_id INTEGER, quantity INTEGER);
CREATE INDEX IF NOT EXISTS idx_gd_reagents_spell ON gd_reagents(spell_id);

-- buy_price: lo que cobra un vendedor por vendor_stack unidades; sell_price: lo que paga por una.
-- name_en: el nombre en inglés, para reconocer los objetos que citan guías y vídeos.
-- min_faction / min_reputation: reputación que pide (4 neutral, 5 amistoso, 6 honorable, 7 reverenciado...).
CREATE TABLE IF NOT EXISTS gd_items (
  item_id INTEGER PRIMARY KEY, name TEXT, quality INTEGER, class_id INTEGER, subclass_id INTEGER,
  buy_price INTEGER, sell_price INTEGER, vendor_stack INTEGER, stackable INTEGER, bonding INTEGER,
  required_skill INTEGER, required_skill_rank INTEGER, name_en TEXT, min_faction INTEGER, min_reputation INTEGER
);
CREATE TABLE IF NOT EXISTS gd_factions (faction_id INTEGER PRIMARY KEY, name TEXT);
-- Nombres de zona: area_id de AreaTable (datos del Classic) y map_id de UiMap (mapas del juego).
CREATE TABLE IF NOT EXISTS gd_areas (area_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS gd_maps (map_id INTEGER PRIMARY KEY, name TEXT);

-- Lo que vende cada vendedor según el addon Merchant Map (merchantmap.py). Se rehace en cada importación.
-- npc: su clave en Merchant Map; faction: A, H o AH (NULL si no se sabe); price: comprobado en Forever,
-- por unidad (NULL si no se ha comprobado o se paga con divisa); verified: 0 si solo sale en la lista
-- del Classic; holiday: vendedor de fiestas.
CREATE TABLE IF NOT EXISTS mm_vendor_items (
  item_id INTEGER, npc TEXT, vendor TEXT, faction TEXT, area_id INTEGER, map_id INTEGER, price INTEGER,
  limited INTEGER, currency INTEGER, verified INTEGER, holiday INTEGER
);
CREATE INDEX IF NOT EXISTS idx_mm_vendor_items_item ON mm_vendor_items(item_id);

-- Dónde aparece cada PNJ (kind 'npc') y cada objeto del mapa (kind 'obj') según QuestieDB
-- (spawns.py). Se rehacen en cada importación. rank: 0 normal, 1 élite, 2 raro élite, 3 jefe, 4 raro
-- (los objetos no tienen nivel). qd_spawns: area_id de AreaTable, x e y en % del mapa de esa zona.
CREATE TABLE IF NOT EXISTS qd_names (
  kind TEXT, id INTEGER, name_en TEXT, name_es TEXT, min_level INTEGER, max_level INTEGER, rank INTEGER,
  PRIMARY KEY (kind, id)
);
CREATE TABLE IF NOT EXISTS qd_spawns (kind TEXT, id INTEGER, area_id INTEGER, x REAL, y REAL);
CREATE INDEX IF NOT EXISTS idx_qd_spawns_area ON qd_spawns(area_id, kind);
"""

# La vista se rehace siempre para que coja las columnas nuevas.
VIEWS = """
DROP VIEW IF EXISTS latest_prices;
CREATE VIEW latest_prices AS
  SELECT item_id, min_price, market_price, quantity, num_auctions, num_owners, time, type, has_book FROM (
    SELECT p.item_id, p.min_price, p.market_price, p.quantity, p.num_auctions, p.num_owners, s.time, s.type,
           (p.book IS NOT NULL AND p.book <> '') AS has_book,
           ROW_NUMBER() OVER (PARTITION BY p.item_id ORDER BY s.time DESC) AS rn
    FROM prices p JOIN scans s ON s.scan_id = p.scan_id
  )
  WHERE rn = 1;
"""

# Columnas añadidas después de la primera versión: se crean en bases de datos antiguas.
ADDED_COLUMNS = {
    "prices": {"market_price": "INTEGER"},
    "items": {"sell_price": "INTEGER"},
    "vendor_items": {"account": "TEXT", "char_key": "TEXT", "zone": "TEXT"},
    "gd_items": {"name_en": "TEXT", "min_faction": "INTEGER", "min_reputation": "INTEGER"},
    "gd_recipes": {"cooldown_hours": "REAL", "cooldown_category": "INTEGER"},
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for table, columns in ADDED_COLUMNS.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, kind in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    conn.executescript(VIEWS)
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
