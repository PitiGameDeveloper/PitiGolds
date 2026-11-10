"""Precios de mercado, historial de 36 horas y consejos de venta sobre una base de datos inventada."""

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
        # 100 unidades: el 1 % es 1, pero se cogen al menos 5. Una a 10 c y cuatro a 100 c -> 82
        self.assertEqual(market_price(10, 100, "10:1;100:99"), 82)

    def test_el_1_por_ciento_de_mucha_oferta(self):
        # 24000 unidades: el 1 % son 240. Una de cebo a 89 c y el resto a 190 c -> 190.
        self.assertEqual(market_price(89, 24000, "89:1;190:23999"), 190)

    def test_sin_libro_usa_el_minimo(self):
        self.assertEqual(market_price(50, 10, None), 50)

    def test_libro_mas_corto_que_lo_que_se_coge(self):
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
        # Cuatro escaneos a 100 y uno último (6 h después): el 1 cae a 70 y el 2 sube a 200.
        history = [(100, 100)] * 4 + [(70, 200)]
        for day, (p1, p2) in enumerate(history):
            scan = f"s{day}"
            c.execute("INSERT INTO scans VALUES (?, 'browse', ?, 0, 0, 'R', 'Horde', 'A-R', 2, 'X')",
                      (scan, T0 + day * 6 * 3600))
            c.executemany("INSERT INTO prices VALUES (?, ?, ?, 50, NULL, NULL, NULL, ?)",
                          [(scan, 1, p1, p1), (scan, 2, p2, p2)])
        # Un escaneo de hace más de 36 horas no cuenta para la mediana.
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


class MinimoSuelto(unittest.TestCase):
    """Lo que pasó con el Paño de seda: escaneo completo a 1 p 90 c y, 2 minutos después, el de
    materiales con un mínimo de 89 c que se comía el precio."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = dbmod.connect(Path(self.tmp.name) / "p.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def scan(self, name, t, item_id, min_price, book=None):
        self.conn.execute("INSERT INTO scans VALUES (?, 'x', ?, 0, 0, 'R', 'Horde', 'A-R', 1, 'X')", (name, t))
        self.conn.execute("INSERT INTO prices VALUES (?, ?, ?, 1000, NULL, NULL, ?, ?)",
                          (name, item_id, min_price, book, market_price(min_price, 1000, book)))

    def test_un_minimo_mas_barato_no_rebaja_el_escaneo_completo(self):
        self.scan("full", T0, 1, 190, "190:500;200:500")
        self.scan("browse", T0 + 120, 1, 89)
        self.assertEqual(load_prices(self.conn)[1].market, 190)

    def test_un_minimo_mas_caro_si_manda(self):
        self.scan("full", T0, 1, 190, "190:500;200:500")
        self.scan("browse", T0 + 120, 1, 250)
        self.assertEqual(load_prices(self.conn)[1].market, 250)

    def test_un_escaneo_completo_viejo_ya_no_manda(self):
        self.scan("full", T0, 1, 190, "190:500;200:500")
        self.scan("browse", T0 + 7 * 3600, 1, 89)
        self.assertEqual(load_prices(self.conn)[1].market, 89)

    def test_los_precios_guardados_se_recalculan(self):
        self.scan("full", T0, 1, 10, "10:1;100:999")
        self.conn.execute("UPDATE prices SET market_price = 94")
        self.conn.execute("UPDATE meta SET value = 'vieja' WHERE key = 'market_formula'")
        # 1000 unidades: el 1 % son 10. Una a 10 c y nueve a 100 c -> 91.
        self.assertEqual(load_prices(self.conn)[1].market, 91)


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
