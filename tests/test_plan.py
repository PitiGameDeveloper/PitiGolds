"""Fase 3: guía de subida, comparador de métodos y recuperación de la inversión."""

import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.analysis import Analysis
from motor.business import Capacity
from motor.crafting import CraftResult, Reagent
from motor.farming import FarmSummary
from motor.leveling import plan_leveling, skill_up_chance
from motor.planner import Method, Settings, _evaluate, build_methods, time_value
from motor.pricing import ItemPrice
from motor.report import build_plan_section, render_guide

G = 10000  # una moneda de oro en cobre


class ProbabilidadDeSubir(unittest.TestCase):
    def test_colores(self):
        self.assertEqual(skill_up_chance(10, 25, 70), 1.0)     # naranja
        self.assertEqual(skill_up_chance(25, 25, 70), 1.0)     # justo al pasar a amarilla
        self.assertAlmostEqual(skill_up_chance(47, 25, 70), 23 / 45)
        self.assertEqual(skill_up_chance(70, 25, 70), 0.0)     # gris


def recipe(rid, name, required, yellow, grey, cost, reagent_id, qty, unit, output=None):
    return CraftResult(recipe_id=rid, name=name, profession="Herrería", output_item_id=output, skill_line=164,
                       required_skill=required, yellow=yellow, grey=grey, cost=cost, value=cost,
                       reagents=[Reagent(name=f"material {reagent_id}", quantity=qty, item_id=reagent_id,
                                         unit_cost=unit, source="subasta")])


class GuiaDeSubida(unittest.TestCase):
    def setUp(self):
        self.crafts = [
            recipe(1, "Barra", 1, 30, 60, 100, reagent_id=10, qty=2, unit=50, output=100),
            recipe(2, "Hacha", 25, 50, 80, 300, reagent_id=11, qty=3, unit=100),
        ]
        self.prices = {10: ItemPrice(item_id=10, name="Mineral", market=50),
                       11: ItemPrice(item_id=11, name="Lingote", market=100),
                       100: ItemPrice(item_id=100, name="Barra", vendor_sell=20)}

    def test_camino_mas_barato(self):
        plan = plan_leveling(self.crafts, self.prices, {10: 30}, 164, 1, 70)
        self.assertEqual(plan.steps[0].recipe.name, "Barra")
        self.assertEqual(plan.steps[0].start, 1)
        self.assertEqual(plan.steps[-1].recipe.name, "Hacha")   # cuando la barra ya casi no sube, el hacha
        self.assertEqual(plan.steps[-1].end, 70)
        self.assertEqual(plan.gaps, [])
        # Barra: (100 - 20 que paga el vendedor) / probabilidad; mientras es naranja, 1 por punto.
        self.assertEqual(plan.steps[0].recovered, 20 * plan.steps[0].crafts_rounded)

    def test_lista_de_la_compra_con_lo_que_tienes(self):
        plan = plan_leveling(self.crafts, self.prices, {10: 30}, 164, 1, 70)
        ore = next(i for i in plan.shopping if i.item_id == 10)
        bars = sum(s.crafts_rounded for s in plan.steps if s.recipe.name == "Barra")
        self.assertEqual(ore.needed, 2 * bars)
        self.assertEqual(ore.to_buy, 2 * bars - 30)
        self.assertEqual(plan.cash_needed, sum(i.cash for i in plan.shopping))
        self.assertLess(plan.cash_needed, plan.materials_cost)   # parte ya lo tienes

    def test_tramos_sin_receta(self):
        plan = plan_leveling(self.crafts, self.prices, {}, 164, 1, 90)
        self.assertEqual(plan.gaps, [(80, 90)])                  # todo es gris a partir de 80
        self.assertFalse(plan.complete)
        self.assertIn("Entre 80 y 90", render_guide(plan))


class RecuperacionDeLaInversion(unittest.TestCase):
    """Tu ejemplo: farmeas a 10 o/h y otro farmeo da 12 o/h, pero hay que prepararlo."""

    def setUp(self):
        self.s = Settings(hours_per_week=10, horizon_weeks=4)

    def farm(self, setup_gold, setup_hours):
        return Method(name="nuevo", kind="farmeo", per_hour=12 * G, setup_gold=setup_gold * G,
                      setup_hours=setup_hours)

    def test_referencia(self):
        self.assertAlmostEqual(time_value(10 * G, None, self.s), 400 * G)   # 40 h a 10 o/h

    def test_dos_dias_de_preparacion_no_compensan(self):
        m = self.farm(300, 8)
        _evaluate(m, 10 * G, None, self.s)
        self.assertAlmostEqual(m.gain, (32 * 12 - 300 - 400) * G, delta=G)
        self.assertEqual(m.verdict, "no compensa en 4 semanas")
        self.assertIn("198 h de juego", m.payback)              # (300 + 8×10) / 2 + 8

    def test_poca_preparacion_si(self):
        m = self.farm(50, 2)
        _evaluate(m, 10 * G, None, self.s)
        self.assertGreater(m.gain, 0)
        self.assertEqual(m.verdict, "compensa")

    def test_si_lo_tuyo_va_a_bajar_cambia_la_cuenta(self):
        steady, falling = self.farm(150, 4), self.farm(150, 4)
        _evaluate(steady, 10 * G, None, self.s)
        _evaluate(falling, 10 * G, 6 * G, self.s)               # tu farmeo bajará a 6 o/h en una semana
        self.assertLess(steady.gain, 0)
        self.assertGreater(falling.gain, 0)
        self.assertEqual(falling.verdict, "compensa")

    def test_un_crafteo_se_suma_a_farmear(self):
        m = Method(name="bolsas", kind="crafteo", per_day_cap=30 * G, minutes_per_day=5,
                   setup_gold=100 * G, setup_hours=1)
        _evaluate(m, 10 * G, None, self.s)
        daily = 30 * G - 5 / 60 * 10 * G
        self.assertAlmostEqual(m.gain, 27 * daily - 110 * G, delta=G)
        self.assertEqual(m.payback, "~5 días")
        self.assertEqual(m.verdict, "compensa")


class Comparador(unittest.TestCase):
    def test_tabla_de_metodos(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = dbmod.connect(Path(tmp) / "p.db")
            bags = CraftResult(recipe_id=5, name="Bolsa", profession="Sastrería", output_item_id=6, cost=300,
                               value=900, known_by=["A-R"])
            bags.capacity = Capacity(units_per_day=6, gold_per_day=3600, minutes_per_day=1, gold_per_hour=216000)
            a = Analysis(prices={}, crafts=[bags], sales=[], farm_summary=[
                FarmSummary("Minería", "Durotar", 3, 2.0, 24 * G, 20 * G),
                FarmSummary("Tela", "Los Baldíos", 1, 1.0, 8 * G, 8 * G),
            ])
            s = Settings()
            methods, baseline = build_methods(conn, a, s)
            conn.close()
        self.assertEqual(baseline.name, "Minería en Durotar")
        by_name = {m.name: m for m in methods}
        self.assertEqual(by_name["Minería en Durotar"].verdict, "tu referencia")
        self.assertEqual(by_name["Tela en Los Baldíos"].verdict, "rinde menos que tu referencia")
        self.assertEqual(by_name["Fabricar Bolsa"].verdict, "hazlo además de farmear")
        text = "\n".join(build_plan_section(methods, baseline, s))
        self.assertIn("Tu referencia: Minería en Durotar", text)
        self.assertIn("| Fabricar Bolsa | crafteo |", text)


if __name__ == "__main__":
    unittest.main()
