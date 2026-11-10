"""Ritmo de venta: no poner 100 de golpe si se venden 10 al día, y qué pasa si el precio baja."""

import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.business import Capacity
from motor.crafting import CraftResult
from motor.market import MarketSignals
from motor.pricing import ItemPrice
from motor.report import _craftable_cell, _profit_cell
from motor.selling import advise, sell_plan


def signals(trend=0.0, strength=0.0, sales=10.0, owners=None):
    return MarketSignals(current=100, median=100, quantity=50, points=10, span_days=7, trend_per_day=trend,
                         trend_strength=strength, sales_per_day=sales, owners=owners)


class PlanDeVenta(unittest.TestCase):
    def test_cien_de_algo_que_se_vende_a_diez_al_dia(self):
        plan = sell_plan(100, ItemPrice(item_id=1, name="X", market=100), signals())
        self.assertEqual(plan.per_day, 3)                  # un 30 % de las 10 diarias
        self.assertAlmostEqual(plan.days, 100 / 3)
        self.assertEqual(plan.avg_price, 100)              # precio estable: el de hoy
        self.assertIn("pon unas 3 al día y no todo de golpe (tardarías unos 33 días)", plan.notes[0])

    def test_si_el_precio_baja_se_saca_menos_de_media(self):
        plan = sell_plan(100, ItemPrice(item_id=1, name="X", market=100), signals(trend=-0.03, strength=1.0))
        self.assertLess(plan.avg_price, 85)
        self.assertTrue(any("sacarías de media" in n for n in plan.notes))

    def test_muchos_vendedores_te_rebajaran(self):
        plan = sell_plan(100, ItemPrice(item_id=1, name="X", market=100), signals(owners=8))
        self.assertTrue(any("hay 8 vendedores" in n for n in plan.notes))

    def test_pocas_unidades_no_necesitan_aviso(self):
        plan = sell_plan(2, ItemPrice(item_id=1, name="X", market=100), signals(owners=8))
        self.assertEqual(plan.notes, [])

    def test_sin_ventas_medidas_solo_avisa_si_tienes_mas_que_el_mercado(self):
        p = ItemPrice(item_id=1, name="X", market=100, quantity=35)
        self.assertIn("súbelo poco a poco", sell_plan(65, p, None).notes[0])
        self.assertEqual(sell_plan(10, p, None).notes, [])


class ConsejoConRitmo(unittest.TestCase):
    def test_lo_que_no_se_vende_en_dos_semanas(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = dbmod.connect(Path(tmp) / "p.db")
            conn.execute("INSERT INTO inventory VALUES ('A-R', 'bags', 1, 0, 100, 0)")
            conn.commit()
            prices = {1: ItemPrice(item_id=1, name="Hierba", market=100, min_price=100, quantity=50,
                                   vendor_sell=60, stack_size=20)}
            (a,) = advise(conn, prices, [], {1: signals(trend=-0.03, strength=1.0)})
            conn.close()
        self.assertEqual(a.action, "subastar")
        self.assertEqual(a.pace, "3/día · ~33 días")
        self.assertIn("unas 58", a.reason)                 # 100 menos lo que se vende en 14 días (42)
        self.assertLess(a.total, round(99 * 0.95) * 100)   # el total cuenta con que el precio baja


class CeldasDelInforme(unittest.TestCase):
    def test_beneficio_a_7_dias(self):
        self.assertEqual(_profit_cell(2800, 2700), "28 p 0 c")
        self.assertEqual(_profit_cell(2800, 1000), "28 p 0 c (en 36 horas: 10 p 0 c)")
        self.assertEqual(_profit_cell(2800, -50), "28 p 0 c (en 36 horas: ya no compensa)")

    def test_no_fabricar_mas_de_lo_que_se_vende(self):
        c = CraftResult(recipe_id=1, name="Bolsa", profession="Sastrería", output_item_id=2, craftable_now=40)
        c.capacity = Capacity(units_per_day=3.0, gold_per_day=100, minutes_per_day=1, gold_per_hour=1000)
        self.assertEqual(_craftable_cell(c), "40 (haz unas 3 al día)")
        c.craftable_now = 5
        self.assertEqual(_craftable_cell(c), "5")


if __name__ == "__main__":
    unittest.main()
