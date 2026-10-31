"""Precios de mercado, historial de 7 días y consejos de venta sobre una base de datos inventada."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.analysis import analyze
from motor.pricing import load_prices, market_price

DAY = 86400
T0 = 1_762_000_000


class PrecioDeMercado(unittest.TestCase):
    def test_una_unidad_regalada_no_hunde_el_precio(self):
        # 100 unidades: el 15 % son 15. Una a 10 c y catorce a 100 c -> (10 + 1400) / 15 = 94
        self.assertEqual(market_price(10, 100, "10:1;100:99"), 94)

    def test_sin_libro_usa_el_minimo(self):
        self.assertEqual(market_price(50, 10, None), 50)

    def test_libro_mas_corto_que_el_15_por_ciento(self):
        # Solo se conocen 3 unidades del libro; se usa la media de esas.
        self.assertEqual(market_price(10, 1000, "10:1;20:2"), 17)


class HistorialYConsejos(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = dbmod.connect(Path(self.tmp.name) / "p.db")
        c = self.conn
        c.executemany("INSERT INTO items VALUES (?, ?, ?)", [(1, "Hundido", 5), (2, "Disparado", 5)])
        c.executemany("INSERT INTO gd_items (item_id, name, stackable) VALUES (?, ?, 20)",
                      [(1, "Hundido"), (2, "Disparado")])
        # Cuatro días a 100 y hoy: el 1 cae a 70 y el 2 sube a 200.
        history = [(100, 100)] * 4 + [(70, 200)]
        for day, (p1, p2) in enumerate(history):
            scan = f"s{day}"
            c.execute("INSERT INTO scans VALUES (?, 'browse', ?, 0, 0, 'R', 'Horde', 'A-R', 2, 'X')",
                      (scan, T0 + day * DAY))
            c.executemany("INSERT INTO prices VALUES (?, ?, ?, 50, NULL, NULL, NULL, ?)",
                          [(scan, 1, p1, p1), (scan, 2, p2, p2)])
        # Un escaneo de hace más de 7 días no cuenta para la mediana.
        c.execute("INSERT INTO scans VALUES ('viejo', 'browse', ?, 0, 0, 'R', 'Horde', 'A-R', 1, 'X')",
                  (T0 - 10 * DAY,))
        c.execute("INSERT INTO prices VALUES ('viejo', 1, 9999, 1, NULL, NULL, NULL, 9999)")
        c.executemany("INSERT INTO inventory VALUES ('A-R', 'bags', ?, 0, ?, 0)", [(1, 10), (2, 5)])
        c.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_mediana_de_7_dias(self):
        p = load_prices(self.conn)[1]
        self.assertEqual(p.market, 70)
        self.assertEqual(p.median, 100)
        self.assertEqual(p.history_scans, 5)
        self.assertAlmostEqual(p.deviation, -0.3)

    def test_un_pico_no_infla_el_valor(self):
        p = load_prices(self.conn)[2]
        self.assertEqual(p.sale_price, 125)  # mediana 100 + 25 %

    def test_consejos(self):
        sales = {s.item_id: s for s in analyze(self.conn).sales}
        self.assertEqual(sales[1].action, "esperar")
        self.assertEqual(sales[1].unit_price, 100)
        self.assertIn("30 %", sales[1].reason)
        self.assertEqual(sales[2].action, "subastar")
        self.assertEqual(sales[2].unit_price, 199)
        self.assertIn("buen momento", sales[2].reason)


class BaseDeDatosAntigua(unittest.TestCase):
    def test_se_anaden_las_columnas_nuevas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vieja.db"
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE prices (scan_id TEXT, item_id INTEGER, min_price INTEGER, quantity INTEGER, "
                        "num_auctions INTEGER, num_owners INTEGER, book TEXT, PRIMARY KEY (scan_id, item_id))")
            old.execute("CREATE TABLE items (item_id INTEGER PRIMARY KEY, name TEXT)")
            old.commit()
            old.close()
            conn = dbmod.connect(path)
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(prices)")}
            self.assertIn("market_price", columns)
            self.assertIn("sell_price", {r["name"] for r in conn.execute("PRAGMA table_info(items)")})
            conn.execute("SELECT market_price FROM latest_prices").fetchall()
            conn.close()


if __name__ == "__main__":
    unittest.main()
