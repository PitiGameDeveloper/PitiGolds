"""Métodos de tus guías (catálogo), recetas con espera y el talento de Legacy de subir profesión."""

import json
import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.analysis import Analysis, analyze
from motor.business import craft_capacity
from motor.catalogo import CatalogEntry, evaluate_catalog, load_catalog, normalize, resolve_items
from motor.crafting import CraftResult, Reagent
from motor.farming import FarmSummary
from motor.leveling import plan_leveling, skill_up_chance
from motor.market import MarketSignals
from motor.pricing import ItemPrice
from motor.report import build_advice_report, build_guides_section

G = 10000


class Catalogo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.conn = dbmod.connect(root / "p.db")
        c = self.conn
        c.executemany("INSERT INTO gd_items (item_id, name, name_en, sell_price) VALUES (?, ?, ?, ?)", [
            (4611, "Perla azul", "Blue Pearl", 500),
            (2452, "Cardo veloz", "Swiftthistle", 15),
            (7078, "Esencia de Fuego", "Essence of Fire", 400),
            (7080, "Esencia de agua", "Essence of Water", 400),
            (5000, "Pluma vibrante", "Vibrant Plume", 825),
        ])
        c.execute("INSERT INTO gd_skill_lines VALUES (182, 'Botánica', 11, 0)")
        c.execute("INSERT INTO characters (char_key, name, level) VALUES ('Piti-R', 'Piti', 32)")
        c.execute("INSERT INTO profession_summary VALUES ('Piti-R', 182, 'primary1', 'Botánica', 60, 75, 0)")
        c.commit()
        self.path = root / "metodos.json"
        self.path.write_text(json.dumps({"metodos": [
            {"id": "perla-azul", "nombre": "Almejas", "tipo": "farmeo", "nivel": 30, "objetos": ["Blue Pearl"]},
            {"id": "cardo", "nombre": "Cardo veloz", "tipo": "farmeo", "nivel": 13,
             "profesiones": [{"id": 182, "nivel": 70}], "objetos": ["cardo  VELOZ"]},
            {"id": "arpias", "nombre": "Arpías", "tipo": "farmeo", "nivel": 28, "objetos": ["Vibrant Plume"]},
            {"id": "lejos", "nombre": "Lejos", "tipo": "farmeo", "nivel": 55, "objetos": ["Essence of Fire"]},
            {"id": "twink", "nombre": "Twinks", "tipo": "inversion",
             "objetos": ["Shadowfang", {"nombre": "Staff of Jordan", "id": 873}]},
            {"id": "estudio", "nombre": "Estudio dedicado", "tipo": "diario", "cantidad": 3,
             "requisito": "todo a 300", "objetos": ["Essence of Fire", "Essence of Water"]},
        ]}), encoding="utf-8")
        self.entries = load_catalog(self.path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_nombres_en_ingles_o_espanol(self):
        self.assertEqual(normalize("Botánica  Fácil"), "botanica facil")
        found, missing = resolve_items(self.conn, self.entries)
        self.assertEqual(found["Blue Pearl"], 4611)
        self.assertEqual(found["cardo  VELOZ"], 2452)          # español, con mayúsculas y espacios de más
        self.assertEqual(found["Staff of Jordan"], 873)       # el catálogo da el número
        self.assertEqual(missing, ["Shadowfang"])

    def evaluate(self, farm_summary=()):
        resolved, _ = resolve_items(self.conn, self.entries)
        prices = {4611: ItemPrice(4611, "Perla azul", market=2 * G, vendor_sell=500, stack_size=20),
                  2452: ItemPrice(2452, "Cardo veloz", market=3000, stack_size=20),
                  5000: ItemPrice(5000, "Pluma vibrante", vendor_sell=825, stack_size=20),
                  7078: ItemPrice(7078, "Esencia de Fuego", market=4 * G, stack_size=10),
                  7080: ItemPrice(7080, "Esencia de agua", market=2 * G, stack_size=10)}
        signals = {4611: MarketSignals(current=2 * G, median=2 * G, quantity=40, points=8, span_days=3,
                                       sales_per_day=20)}
        methods = evaluate_catalog(self.conn, self.entries, resolved, prices, signals, [], list(farm_summary))
        return {m.entry.id: m for m in methods}, methods

    def test_lo_que_puedes_hacer_ya(self):
        by_id, ordered = self.evaluate()
        self.assertEqual(by_id["perla-azul"].lacking, [])
        self.assertEqual(by_id["cardo"].lacking, ["Botánica 70 (tienes 60)"])
        self.assertEqual(by_id["lejos"].lacking, ["nivel 55 (tu máximo: 32)"])
        # La perla mueve 20 al día: el 30 % a 1,9 o sin comisión, menos 5 c de depósito (pila de 20).
        self.assertEqual(by_id["perla-azul"].market_day, round(20 * 0.3 * 18995))
        self.assertTrue(by_id["arpias"].items[0].to_vendor)
        timed = [m.entry.id for m in ordered if m.entry.kind == "farmeo"]
        self.assertEqual(timed[:2], ["perla-azul", "arpias"])   # primero lo que puedes hacer, por mercado
        self.assertEqual(set(timed[2:]), {"cardo", "lejos"})

    def test_lo_medido_manda(self):
        by_id, ordered = self.evaluate([FarmSummary("arpias", "Las Mil Agujas", 2, 1.5, 30 * G, 30 * G)])
        self.assertEqual(by_id["arpias"].measured.per_hour, 20 * G)
        self.assertEqual(ordered[0].entry.id, "arpias")

    def test_diario(self):
        by_id, _ = self.evaluate()
        # 3 esencias al azar entre fuego (3,8 o sin comisión) y agua (1,9 o), menos 10 c de depósito
        # (pila de 10).
        self.assertEqual(by_id["estudio"].daily_value, round(3 * (37990 + 18990) / 2))

    def test_en_el_informe(self):
        a = analyze(self.conn, self.entries)
        text = build_advice_report(self.conn, a)
        self.assertIn("## Métodos de tus guías", text)
        self.assertIn("| Arpías (`arpias`) | 28 |", text)
        self.assertIn("### Para más adelante", text)
        self.assertIn("Objetos de tus guías que no salen en los datos del juego (1)", text)
        full = "\n".join(build_guides_section(a, limit=None, heading="#"))
        self.assertIn("# Métodos de tus guías", full)
        self.assertIn("## Estudio dedicado", full)

    def test_el_catalogo_del_proyecto_se_lee(self):
        entries = load_catalog()
        self.assertGreater(len(entries), 50)
        ids = [e.id for e in entries]
        self.assertEqual(len(ids), len(set(ids)), "hay ids repetidos")
        self.assertTrue(all(e.kind in ("farmeo", "pesca", "mazmorra", "crafteo", "inversion", "vendedor", "diario")
                            for e in entries))


def mooncloth(known_by):
    c = CraftResult(recipe_id=18560, name="Tela lunar", profession="Costura", output_item_id=14342,
                    cost=2 * G, value=5 * G, known_by=known_by, cooldown_hours=95, skill_line=197,
                    required_skill=250, yellow=270, grey=290,
                    reagents=[Reagent(name="Tela rúnica", quantity=2, item_id=14047, unit_cost=G)])
    return c


class RecetasConEspera(unittest.TestCase):
    def test_la_espera_limita_lo_que_se_hace_al_dia(self):
        c = mooncloth(["A-R", "B-R"])
        c.output_signals = MarketSignals(current=5 * G, median=5 * G, quantity=40, points=8, span_days=3,
                                         sales_per_day=30)
        cap = craft_capacity(c)
        self.assertTrue(cap.by_cooldown)
        self.assertAlmostEqual(cap.units_per_day, 2 * 24 / 95)   # una cada 95 h por personaje
        self.assertEqual(cap.gold_per_day, round(3 * G * 2 * 24 / 95))

    def test_sin_datos_de_ventas_basta_la_espera(self):
        cap = craft_capacity(mooncloth([]))
        self.assertAlmostEqual(cap.units_per_day, 24 / 95)          # si la aprendes, en un personaje

    def test_en_el_informe(self):
        c = mooncloth(["A-R", "B-R"])
        c.capacity = craft_capacity(c)
        with tempfile.TemporaryDirectory() as tmp:
            conn = dbmod.connect(Path(tmp) / "p.db")
            text = build_advice_report(conn, Analysis(prices={}, crafts=[c], sales=[]))
            conn.close()
        self.assertIn("(espera: 1 cada 4 días por personaje, 2 personajes)", text)

    def test_no_sirve_para_subir(self):
        prices = {14047: ItemPrice(14047, "Tela rúnica", market=G)}
        plan = plan_leveling([mooncloth(["A-R"])], prices, {}, 197, 250, 260)
        self.assertEqual(plan.steps, [])
        self.assertEqual(plan.gaps, [(250, 260)])


class TalentoDeSubida(unittest.TestCase):
    def test_multiplica_amarillas_y_verdes(self):
        self.assertAlmostEqual(skill_up_chance(47, 25, 70, 0.2), 23 / 45 * 1.2)
        self.assertEqual(skill_up_chance(30, 25, 70, 0.5), 1.0)       # nunca más del 100 %
        self.assertEqual(skill_up_chance(70, 25, 70, 0.5), 0.0)       # la gris sigue sin dar

    def test_la_subida_sale_mas_barata(self):
        recipe = CraftResult(recipe_id=1, name="Barra", profession="Herrería", output_item_id=None, skill_line=164,
                             required_skill=1, yellow=10, grey=60, cost=100, value=100,
                             reagents=[Reagent(name="Mineral", quantity=1, item_id=10, unit_cost=100)])
        prices = {10: ItemPrice(10, "Mineral", market=100)}
        plain = plan_leveling([recipe], prices, {}, 164, 1, 50)
        talented = plan_leveling([recipe], prices, {}, 164, 1, 50, bonus=0.25)
        self.assertLess(talented.crafts, plain.crafts)
        self.assertLess(talented.materials_cost, plain.materials_cost)
        self.assertEqual(talented.bonus, 0.25)


if __name__ == "__main__":
    unittest.main()
