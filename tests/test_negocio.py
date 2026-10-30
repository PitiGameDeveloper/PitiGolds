"""Contabilidad del negocio en la subasta y capacidad de cada crafteo."""

import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.business import MARKET_SHARE, compute_business, craft_capacity
from motor.crafting import CraftResult, Reagent
from motor.market import MarketSignals

T0 = 1_762_000_000


class Negocio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = c = dbmod.connect(Path(self.tmp.name) / "p.db")
        c.executemany("INSERT INTO items (item_id, name) VALUES (?, ?)",
                      [(10, "Paño de lana"), (20, "Bolsa de lana"), (30, "Gema"), (40, "Piel")])
        rows = [
            # Reventa: 10 gemas a 100 y se venden a 150 (comisión del 5 %).
            ("b1", T0, "buy", 30, None, 10, 1000, None, None, None, None, None, None),
            ("p1", T0 + 10, "post", 30, None, 10, None, 150, 30, None, None, None, None),
            ("s1", T0 + 20, "sale", None, "Gema", 10, 1500, None, 30, 75, None, None, None),
            # Lo farmeado que vendes no es negocio.
            ("s2", T0 + 30, "sale", None, "Piel", 5, 500, None, 0, 25, None, None, None),
            # Bolsas: paños comprados, 4 bolsas fabricadas, 3 vendidas.
            ("b2", T0 + 40, "buy", 10, None, 12, 1200, None, None, None, None, None, None),
            ("c1", T0 + 50, "craft", 20, None, 4, None, None, None, None, 777, None, None),
            ("p2", T0 + 60, "post", 20, None, 4, None, 900, 40, None, None, None, None),
            ("s3", T0 + 70, "sale", None, "Bolsa de lana", 3, 2700, None, 30, 135, None, None, None),
            ("t1", T0, "time", None, None, None, None, None, None, None, None, "subasta", 1800),
        ]
        c.executemany("INSERT INTO ledger VALUES (?, ?, 'A-R', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        c.commit()
        # La bolsa lleva 3 paños; en el mercado están a 120, pero tú los pagaste a 100.
        self.bag = CraftResult(recipe_id=777, name="Bolsa de lana", profession="Sastrería", output_item_id=20,
                               reagents=[Reagent(name="Paño de lana", quantity=3, item_id=10, unit_cost=120)])

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_cuentas(self):
        b = compute_business(self.conn, {}, [self.bag])
        items = {e.name: e for e in b.items}
        gem, bag, cloth, hide = items["Gema"], items["Bolsa de lana"], items["Paño de lana"], items["Piel"]
        self.assertEqual(gem.origin, "reventa")
        self.assertEqual(gem.profit, 1500 - 75 - 1000)          # el depósito se devolvió entero
        self.assertEqual(bag.origin, "fabricado")
        self.assertEqual(bag.unit_cost, 300)                    # 3 paños a lo que te costaron (100)
        self.assertEqual(bag.deposits_lost, 10)
        self.assertEqual(bag.profit, 2700 - 135 - 3 * 300 - 10)
        self.assertEqual(cloth.origin, "material")
        self.assertEqual(hide.origin, "farmeado")
        self.assertEqual(b.farmed_sales, 475)
        self.assertEqual(b.profit, gem.profit + bag.profit)
        # La media hora se reparte; la compra de paños cuenta como tiempo de las bolsas.
        self.assertEqual(cloth.seconds, 0)
        self.assertAlmostEqual(gem.seconds + bag.seconds + hide.seconds, 1800)
        self.assertGreater(b.per_hour, 0)

    def test_capacidad_de_un_crafteo(self):
        craft = CraftResult(recipe_id=1, name="Bolsa", profession="Sastrería", output_item_id=20,
                            cost=300, value=855)
        craft.output_signals = MarketSignals(current=900, median=900, quantity=40, points=10, span_days=3,
                                             sales_per_day=20)
        cap = craft_capacity(craft)
        self.assertAlmostEqual(cap.units_per_day, 20 * MARKET_SHARE)
        self.assertEqual(cap.gold_per_day, round(555 * 6))
        self.assertAlmostEqual(cap.minutes_per_day, 1.0)       # 6 unidades a 10 s
        self.assertEqual(cap.gold_per_hour, 555 * 360)
        craft.output_signals.sales_per_day = None
        self.assertIsNone(craft_capacity(craft))               # sin ventas medidas no se inventa nada


if __name__ == "__main__":
    unittest.main()
