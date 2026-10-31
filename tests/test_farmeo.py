"""Sesiones de farmeo: cómo se unen los tramos y cuánto se gana por hora."""

import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.farming import farm_item_ids, load_sessions, summarize, value_sessions
from motor.market import MarketSignals
from motor.pricing import load_prices

T0 = 1_762_000_000
MIN = 60


class Sesiones(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = c = dbmod.connect(Path(self.tmp.name) / "p.db")
        # Mineral (metal y piedra) y una hierba; el mineral vale 100 en la subasta.
        c.executemany("INSERT INTO gd_items (item_id, name, class_id, subclass_id, sell_price, stackable) "
                      "VALUES (?, ?, 7, ?, ?, 20)",
                      [(1, "Mineral", 7, 5), (2, "Hierba", 9, 3)])
        c.execute("INSERT INTO scans VALUES ('s', 'browse', ?, 0, 0, 'R', 'Horde', 'A-R', 2, 'X')", (T0,))
        c.executemany("INSERT INTO prices VALUES ('s', ?, ?, 10, NULL, NULL, NULL, ?)", [(1, 100, 100), (2, 40, 40)])

        def bucket(key, t, zone, label, money, first, last, items):
            c.execute("INSERT INTO farm_buckets VALUES (?, ?, 'A-R', 1, ?, ?, ?, ?, ?)",
                      (key, t, zone, label, money, first, last))
            c.executemany("INSERT INTO farm_items VALUES (?, ?, ?)", [(key, i, n) for i, n in items.items()])

        # Minando 24 minutos en Durotar: tres tramos, con un hueco de 11 minutos que no corta...
        bucket("a", T0, "Durotar", None, 0, T0, T0 + 4 * MIN, {1: 20})
        bucket("b", T0 + 5 * MIN, "Durotar", None, 500, T0 + 5 * MIN, T0 + 9 * MIN, {1: 20})
        bucket("c", T0 + 20 * MIN, "Durotar", None, 0, T0 + 20 * MIN, T0 + 24 * MIN, {1: 20})
        # ...una pausa larga de 2 horas corta la sesión...
        bucket("d", T0 + 160 * MIN, "Durotar", None, 0, T0 + 160 * MIN, T0 + 190 * MIN, {2: 30})
        # ...y cambiar de zona también.
        bucket("e", T0 + 195 * MIN, "Los Baldíos", "Hierbas", 0, T0 + 195 * MIN, T0 + 225 * MIN, {2: 30})
        c.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def sessions(self, signals=None):
        sessions = load_sessions(self.conn)
        prices = load_prices(self.conn, farm_item_ids(self.conn))
        value_sessions(self.conn, sessions, prices, signals or {})
        return sessions

    def test_union_y_cortes(self):
        s = self.sessions()
        self.assertEqual([x.zone for x in s], ["Durotar", "Durotar", "Los Baldíos"])
        self.assertEqual((s[0].start, s[0].end), (T0, T0 + 24 * MIN))

    def test_oro_por_hora(self):
        s = self.sessions()
        mining = s[0]
        self.assertEqual(mining.items, {1: 60})
        self.assertEqual(mining.money, 500)
        # 100 menos el 5 % de comisión y 5 de depósito (1 plata por pila de 20).
        self.assertEqual(mining.value_now, 60 * 90 + 500)
        self.assertEqual(mining.hours, 24 * MIN / 3600)
        self.assertEqual(mining.per_hour, round((60 * 90 + 500) / 0.4))
        self.assertEqual(mining.activity, "Minería")
        self.assertEqual(s[-1].activity, "Hierbas")  # la etiqueta manda

    def test_prevision_a_7_dias(self):
        falling = MarketSignals(current=100, median=100, quantity=10, points=8, span_days=7, forecast_7d=60)
        mining = self.sessions({1: falling})[0]
        self.assertEqual(mining.value_week, 60 * 52 + 500)
        self.assertLess(mining.per_hour_week, mining.per_hour)

    def test_resumen_por_actividad_y_zona(self):
        summary = summarize(self.sessions())
        self.assertEqual(summary[0].activity, "Minería")
        self.assertEqual(sum(g.sessions for g in summary), 3)


if __name__ == "__main__":
    unittest.main()
