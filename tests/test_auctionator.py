"""Los precios de la subasta salen de Auctionator: lo que copia el addon pasa a la base de datos."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.ingest import _ingest_auctionator
from motor.pricing import load_prices

DAY0 = 1577836800
TODAY = 2515
NOW = DAY0 + TODAY * 86400 + 20 * 3600


def export(items, now=NOW, today=TODAY):
    return {"realm": "Dio Horde", "faction": "Horde", "char": "Brujo-Dio", "time": now, "day0": DAY0,
            "today": today, "items": items}


class LecturaDeAuctionator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = dbmod.connect(Path(self.tmp.name) / "p.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def prices(self, item_id):
        return [tuple(r) for r in self.conn.execute(
            "SELECT s.time, p.market_price, p.quantity FROM prices p JOIN scans s ON s.scan_id = p.scan_id "
            "WHERE p.item_id = ? ORDER BY s.time", (item_id,))]

    def test_un_precio_por_dia(self):
        n, when = _ingest_auctionator(self.conn, "A", export({
            2589: f"40|{TODAY - 2}:60:70:10;{TODAY - 1}:45:50:30;{TODAY}:38:41:35",
            2770: f"120|{TODAY - 1}:120:120:20",
        }))
        self.assertEqual((n, when), (2, NOW))
        midday = lambda d: DAY0 + d * 86400 + 43200
        # Cada día, el mínimo más alto; el último día del objeto, su último mínimo.
        self.assertEqual(self.prices(2589), [(midday(TODAY - 2), 70, 10), (midday(TODAY - 1), 50, 30), (NOW, 40, 35)])
        self.assertEqual(self.prices(2770), [(midday(TODAY - 1), 120, 20)])
        p = load_prices(self.conn, [2589])[2589]
        self.assertEqual((p.market, p.seen, p.median, p.history_scans), (40, NOW, 50, 3))

    def test_se_rehacen_hoy_y_ayer_y_no_los_dias_viejos(self):
        _ingest_auctionator(self.conn, "A", export({2589: f"40|{TODAY - 3}:60:70:10;{TODAY}:40:40:35"}))
        # Más tarde: el precio de hoy ha cambiado y Auctionator ya no tiene el día viejo.
        _ingest_auctionator(self.conn, "A", export({2589: f"30|{TODAY}:30:40:50"}, now=NOW + 600))
        self.assertEqual([r[1:] for r in self.prices(2589)], [(70, 10), (30, 50)])
        self.assertEqual(self.prices(2589)[-1][0], NOW + 600)

    def test_sin_copia_no_hace_nada(self):
        self.assertEqual(_ingest_auctionator(self.conn, "A", {}), (0, 0))


class EscaneosDePitiGolds(unittest.TestCase):
    def test_se_borran_una_vez(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.db"
            raw = sqlite3.connect(path)
            raw.executescript(dbmod.SCHEMA)
            raw.execute("INSERT INTO scans (scan_id, type, time) VALUES ('viejo', 'full', 1)")
            raw.execute("INSERT INTO prices (scan_id, item_id, min_price) VALUES ('viejo', 1, 10)")
            raw.commit()
            raw.close()
            conn = dbmod.connect(path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0], 0)
            conn.execute("INSERT INTO scans (scan_id, type, time) VALUES ('otro', 'full', 2)")
            conn.commit()
            conn.close()
            conn = dbmod.connect(path)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 1)
            conn.close()


if __name__ == "__main__":
    unittest.main()
