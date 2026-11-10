"""Señales de mercado, previsión, ventas estimadas y backtest con historiales inventados."""

import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.analysis import analyze
from motor.market import DAY, Point, backtest, compute_signals, estimate_sales

T0 = 1_762_000_000
H = 3600


def series(prices, quantities=None, owners=None, step=6 * H, kind="browse"):
    # Por defecto un escaneo cada 6 h: la ventana de la previsión es de 36 h.
    n = len(prices)
    quantities = quantities or [100] * n
    owners = owners or [None] * n
    return [Point(T0 + i * step, prices[i], quantities[i], owners[i], None, kind) for i in range(n)]


class VentasEstimadas(unittest.TestCase):
    def test_unidades_que_desaparecen_a_buen_precio(self):
        a = Point(T0, 100, 35, 3, "100:10;110:5;150:20", "full")
        b = Point(T0 + 6 * H, 100, 32, 3, "100:4;110:5;130:3", "full")
        # A 100 faltan 6; a 110 no falta nada; a 150 está por encima de la zona de venta.
        self.assertAlmostEqual(estimate_sales([a, b], [a.time, b.time]), 24.0)

    def test_si_desaparece_de_la_subasta_se_vendio_todo(self):
        a = Point(T0, 100, 15, 2, "100:10;110:5", "full")
        self.assertAlmostEqual(estimate_sales([a], [T0, T0 + 12 * H]), 30.0)

    def test_lo_que_vuelve_mas_barato_no_es_venta(self):
        # Alguien quita sus 24 a 100 y pone 20 a 95: solo faltan 4.
        a = Point(T0, 100, 34, 2, "100:24;105:10", "full")
        b = Point(T0 + 6 * H, 95, 30, 2, "95:20;105:10", "full")
        self.assertAlmostEqual(estimate_sales([a, b], [a.time, b.time]), 16.0)

    def test_lo_que_aparece_mas_caro_no_descuenta(self):
        a = Point(T0, 100, 10, 1, "100:10", "full")
        b = Point(T0 + 6 * H, 110, 8, 1, "110:8", "full")
        self.assertAlmostEqual(estimate_sales([a, b], [a.time, b.time]), 40.0)

    def test_si_lo_recoloca_todo_no_hay_ventas(self):
        a = Point(T0, 100, 24, 1, "100:24", "full")
        b = Point(T0 + 6 * H, 90, 24, 1, "90:24", "full")
        self.assertAlmostEqual(estimate_sales([a, b], [a.time, b.time]), 0.0)

    def test_con_pocos_minutos_no_se_inventa_las_ventas_del_dia(self):
        # 19 minutos entre escaneos: 100 unidades menos no son 7500 vendidas al día.
        a = Point(T0, 100, 100, 1, "100:100", "full")
        b = Point(T0 + 1140, 100, 0, 1, "", "full")
        self.assertIsNone(estimate_sales([a, b], [a.time, b.time]))
        self.assertIsNone(compute_signals([a, b], [a.time, b.time]).days_of_supply)

    def test_escaneos_muy_separados_no_cuentan(self):
        a = Point(T0, 100, 10, 1, "100:10", "full")
        b = Point(T0 + 20 * H, 100, 0, 1, "", "full")
        self.assertIsNone(estimate_sales([a, b], [a.time, b.time]))


class Prevision(unittest.TestCase):
    def test_mercado_que_se_hunde(self):
        pts = series([100, 97, 93, 90, 86, 82, 78, 74],
                     quantities=[100, 110, 125, 140, 150, 165, 185, 200],
                     owners=[5, 5, 6, 7, 7, 8, 9, 10])
        s = compute_signals(pts, [])
        self.assertEqual(s.outlook, "baja")
        self.assertLess(s.forecast, s.current)
        self.assertGreater(s.drop_risk, 50)
        self.assertEqual(s.confidence, "media")
        text = " ".join(s.reasons)
        self.assertIn("precio -", text)
        self.assertIn("de unidades a la venta", text)
        self.assertIn("de vendedores", text)

    def test_mercado_que_sube(self):
        pts = series([50, 53, 57, 61, 66, 70, 75], quantities=[200, 180, 160, 140, 120, 100, 80])
        s = compute_signals(pts, [])
        self.assertEqual(s.outlook, "sube")
        self.assertGreater(s.forecast, s.current)

    def test_mercado_estable(self):
        s = compute_signals(series([100, 102, 99, 101, 100, 98, 101]), [])
        self.assertEqual(s.outlook, "estable")
        self.assertLess(s.drop_risk, 35)

    def test_sin_historial_no_hay_prevision(self):
        s = compute_signals(series([100, 90]), [])
        self.assertEqual(s.outlook, "sin datos")
        self.assertIsNone(s.forecast)

    def test_backtest(self):
        falling = series([round(200 * 0.97 ** i) for i in range(40)], step=DAY // 4)
        result = backtest({1: falling}, [])
        self.assertGreater(result.cases, 5)
        self.assertGreater(result.accuracy, 0.8)      # bajaba y dijo que bajaba
        self.assertLess(result.baseline, result.accuracy)


class ConsejoConTendencia(unittest.TestCase):
    """Algo barato respecto a su mediana se esperaría; si además está cayendo, mejor venderlo ya."""

    def test_si_cae_no_se_espera(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = dbmod.connect(Path(tmp) / "p.db")
            conn.execute("INSERT INTO items VALUES (1, 'Mineral', 1)")
            conn.execute("INSERT INTO gd_items (item_id, name, stackable) VALUES (1, 'Mineral', 20)")
            conn.execute("INSERT INTO inventory VALUES ('A-R', 'bags', 1, 0, 50, 0)")
            for day, price in enumerate([100, 100, 100, 100, 95, 85, 75, 65]):
                scan = f"s{day}"
                conn.execute("INSERT INTO scans VALUES (?, 'browse', ?, 0, 0, 'R', 'Horde', 'A-R', 1, 'X')",
                             (scan, T0 + day * 6 * H))
                conn.execute("INSERT INTO prices VALUES (?, 1, ?, ?, NULL, NULL, NULL, ?)",
                             (scan, price, 100 + day * 20, price))
            conn.commit()
            a = analyze(conn)
            advice = {s.item_id: s for s in a.sales}[1]
            self.assertEqual(a.signals[1].outlook, "baja")
            self.assertEqual(advice.action, "subastar")
            self.assertIn("tiende a bajar", advice.reason)
            conn.close()


if __name__ == "__main__":
    unittest.main()
