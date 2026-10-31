"""Ventana de métodos: oro por hora esperado, colores, quién puede hacerlo, el mejor farmeo y crafteos."""

import json
import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.analysis import Analysis
from motor.business import Capacity
from motor.catalogo import CatalogEntry, catalog_problems, evaluate_catalog, resolve_items
from motor.crafting import CraftResult, Reagent
from motor.farming import FarmSummary
from motor.fuentes import first_link
from motor.generated import lua_value
from motor.market import MarketSignals
from motor.panel import build_panel, panel_export, render_panel
from motor.planner import Settings
from motor.pricing import ItemPrice
from motor.recoleccion import Stretch, gathering_hours
from motor.revision import Review, Reviews, load_reviews, review_problems

G = 10000
ROUTES = {393: [Stretch(1, 150, "Los Baldíos", "Páramos de Poniente", ["Medium Leather"], points_per_hour=75),
                Stretch(150, 300, "Feralas", "Feralas", ["Thick Leather"], points_per_hour=50, char_level=35)]}


def entry(ident, **kw):
    return CatalogEntry(id=ident, name=kw.pop("name", ident.capitalize()), kind=kw.pop("kind", "farmeo"), **kw)


class Panel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = dbmod.connect(Path(self.tmp.name) / "p.db")
        c = self.conn
        c.executemany("INSERT INTO gd_skill_lines VALUES (?, ?, ?, 0)",
                      [(393, "Desollar", 11), (197, "Costura", 11), (182, "Botánica", 11), (185, "Cocina", 9)])
        c.executemany("INSERT INTO gd_items (item_id, name, name_en, sell_price, min_faction, min_reputation) "
                      "VALUES (?, ?, ?, ?, ?, ?)", [
                          (4304, "Cuero grueso", "Thick Leather", 150, None, None),
                          (2319, "Cuero medio", "Medium Leather", 50, None, None),
                          (4611, "Perla azul", "Blue Pearl", 500, None, None),
                          (9001, "Patrón: túnica", "Pattern: Tunic", 0, 529, 6),
                      ])
        c.execute("INSERT INTO gd_factions VALUES (529, 'Alba Argenta')")
        c.executemany("INSERT INTO characters (char_key, name, level, faction) VALUES (?, ?, ?, ?)",
                      [("Grom-R", "Grom", 50, "Horde"), ("Ana-R", "Ana", 20, "Horde")])
        c.executemany("INSERT INTO profession_summary VALUES (?, ?, ?, ?, ?, 300, 0)", [
            ("Grom-R", 393, "primary1", "Desollar", 120), ("Grom-R", 197, "primary2", "Costura", 200)])
        c.execute("INSERT INTO reputations VALUES ('Grom-R', 529, 'Alba Argenta', 0, 5, 0, 0)")
        c.execute("INSERT INTO vendor_items (item_id, price, limited, vendor, zone) VALUES "
                  "(2589, 500, 0, 'Tejedor', 'Orgrimmar')")
        c.commit()
        self.prices = {4304: ItemPrice(4304, "Cuero grueso", market=1 * G, vendor_sell=150),
                       4611: ItemPrice(4611, "Perla azul", market=2 * G, vendor_sell=500),
                       9001: ItemPrice(9001, "Patrón: túnica", market=3 * G)}
        self.signals = {4304: MarketSignals(current=G, median=G, quantity=50, points=6, span_days=3,
                                            sales_per_day=20)}
        self.settings = Settings(hours_per_week=14)   # 2 h al día

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def build(self, entries, crafts=(), farm_summary=(), reviews=None, settings=None):
        resolved, _ = resolve_items(self.conn, entries)
        guide = evaluate_catalog(self.conn, entries, resolved, self.prices, self.signals, list(crafts),
                                 list(farm_summary))
        a = Analysis(prices=self.prices, crafts=list(crafts), sales=[], signals=self.signals,
                     guide_methods=guide, guide_resolved=resolved, farm_summary=list(farm_summary),
                     last_scan=1)
        return build_panel(self.conn, a, settings or self.settings, reviews or Reviews(), ROUTES)

    def pieles(self, **kw):
        return entry("pieles", level=45, professions=[(393, 175)], items=["Thick Leather"],
                     per_hour=[("Thick Leather", 40)], coins_per_hour=2 * G, **kw)

    def test_oro_por_hora_esperado_con_lo_que_absorbe_el_mercado(self):
        panel = self.build([self.pieles()])
        row = panel.farms[0]
        # 20 ventas al día × 30 % / 2 h de juego = 3 por hora a la subasta; las otras 37, al vendedor.
        self.assertEqual(row.per_hour, 2 * G + 3 * 9500 + 37 * 150)
        self.assertFalse(row.measured)
        self.assertTrue(any("el mercado solo se lleva unas 3 por hora" in d for d in row.details))

    def test_lo_medido_manda_y_el_que_falta_algo_dice_que_y_cuanto(self):
        measured = FarmSummary(activity="pieles", zone="Feralas", sessions=2, hours=1.5, value_now=45 * G,
                               value_week=45 * G)
        row = self.build([self.pieles()], farm_summary=[measured]).farms[0]
        self.assertEqual((row.per_hour, row.measured), (30 * G, True))
        self.assertIsNone(row.who)
        self.assertEqual(row.closest, "Grom")
        self.assertEqual(row.lacking, ["Desollar 175 (tiene 120)"])
        self.assertAlmostEqual(row.prep_hours, 30 / 75 + 25 / 50)
        self.assertIn("150-175: Feralas (Cuero grueso); el instructor pide nivel 35", "\n".join(row.details))

    def test_el_mejor_farmeo(self):
        perlas = entry("perlas", level=30, items=["Blue Pearl"], per_hour=[("Blue Pearl", 3)], coins_per_hour=G)
        panel = self.build([self.pieles(), perlas])
        by_key = {r.key: r for r in panel.farms}
        self.assertEqual(by_key["perlas"].who, "Grom")
        # Perlas: 1 o + 3 × 1,9 o = 6,7 o/h y ya las puede hacer; las pieles (5,4 o/h) pasan del 60 %.
        self.assertEqual(panel.verdict.state, "mejor")
        self.assertEqual(panel.verdict.best, "perlas")
        self.assertEqual(by_key["perlas"].color, "verde")
        self.assertEqual(by_key["pieles"].color, "verde")

    def test_preparar_si_lo_que_puedes_hacer_rinde_mucho_menos(self):
        perlas = entry("perlas", level=30, items=["Blue Pearl"], per_hour=[("Blue Pearl", 1)])
        panel = self.build([self.pieles(), perlas])
        self.assertEqual(panel.verdict.state, "preparar")
        text = "\n".join(panel.verdict.lines)
        self.assertIn("Lo mejor que puedes hacer ya: Perlas", text)
        self.assertIn("- Pieles:", text)
        self.assertIn("Grom: le falta Desollar 175 (tiene 120)", text)
        self.assertEqual({r.key: r.color for r in panel.farms}["perlas"], "rojo")   # 1,9 o/h: no llega a 5

    def test_investigar_si_nada_da_dinero(self):
        settings = Settings(hours_per_week=14, min_gold_hour=10)
        panel = self.build([self.pieles()], settings=settings)
        self.assertEqual(panel.verdict.state, "investigar")
        self.assertEqual(panel.farms[0].color, "rojo")
        self.assertIn("«investiga»", "\n".join(panel.verdict.lines))

    def test_sin_datos_y_en_espera(self):
        panel = self.build([entry("nada", level=10, items=["Blue Pearl"])])
        self.assertEqual(panel.verdict.state, "sin_datos")
        dudoso = self.pieles(pending="¿En qué zona?")
        panel = self.build([dudoso])
        self.assertEqual(panel.verdict.state, "sin_datos")   # en espera: no se recomienda
        self.assertIn("En espera, falta un dato: ¿En qué zona?", panel.farms[0].details[0])

    def test_nota_del_asesor(self):
        reviews = Reviews(farms={"pieles": Review(score=8, why="Da mucho y Grom está cerca.",
                                                  steps=["Ve a Feralas.", "Desuella yetis."])})
        row = self.build([self.pieles()], reviews=reviews).farms[0]
        self.assertEqual(row.score, 8)
        self.assertEqual(row.details[:3], ["Asesor (8/10): Da mucho y Grom está cerca.", "1. Ve a Feralas.",
                                           "2. Desuella yetis."])

    def craft(self, rid, required, known=False, learn=None, **kw):
        c = CraftResult(recipe_id=rid, name=f"Receta {rid}", profession="Costura", output_item_id=5000 + rid,
                        output_name=f"Prenda {rid}", skill_line=197, required_skill=required, yours=True,
                        known_by=["Grom-R"] if known else [], cost=1000, value=3000, learn_item_id=learn,
                        reagents=[Reagent("Paño", 2, item_id=2589, unit_cost=500, source="vendedor")], **kw)
        c.capacity = Capacity(units_per_day=4, gold_per_day=8000, minutes_per_day=1, gold_per_hour=G)
        return c

    def test_colores_de_los_crafteos(self):
        crafts = [self.craft(100, 150, known=True), self.craft(101, 210), self.craft(102, 260),
                  self.craft(103, 190, learn=9000), self.craft(104, 190, learn=9001)]
        crafts[3].learn_item_name = "Patrón: chaleco"
        crafts[4].learn_item_name = "Patrón: túnica"
        reviews = Reviews(crafts={103: Review(score=3, recipe_way="botin", recipe_where="Bichos de Feralas")})
        panel = self.build([self.pieles()], crafts, reviews=reviews)
        rows = {r.recipe_id: r for r in panel.crafts}
        self.assertEqual(rows[100].color, "verde")
        self.assertEqual(rows[101].color, "amarillo")   # 10 puntos y la receta es de instructor
        self.assertEqual(rows[102].color, "naranja")    # 60 puntos
        self.assertEqual(rows[103].color, "rojo")       # de botín
        self.assertEqual(rows[104].color, "naranja")    # en la subasta, pero pide honorable (Grom es amistoso)
        self.assertIn("honorable con Alba Argenta (tiene amistoso)", rows[104].recipe.reputation)
        self.assertEqual(rows[101].prep[0], "Grom: le faltan 10 puntos de Costura (200/210).")
        self.assertEqual((rows[100].crafts_day, rows[100].reagents[0].vendor, rows[100].reagents[0].zone),
                         (4, "Tejedor", "Orgrimmar"))
        self.assertEqual([r.recipe_id for r in panel.crafts][:2], [100, 101])
        # El verdict propone hacer antes el crafteo rápido.
        self.assertIn("Antes, fabrica 4 × Prenda 100 con Grom", "\n".join(panel.verdict.lines))

    def test_para_el_addon_y_para_el_asesor(self):
        panel = self.build([self.pieles()], [self.craft(100, 150, known=True)])
        lua = lua_value(panel_export(panel))
        self.assertIn('key = "pieles"', lua)
        self.assertIn('vendor = "Tejedor"', lua)
        text = render_panel(panel)
        self.assertIn("| `pieles` | Pieles |", text)
        self.assertIn("| 100 | Prenda 100 (Costura) |", text)
        self.assertIn("## Sin revisar por el asesor", text)


class Conocimiento(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, data):
        path = self.root / name
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        return path

    def test_revision(self):
        path = self.write("revision.json", {
            "farmeos": {"pieles": {"nota": 8, "por_que": "x", "pasos": ["a"]}, "otro": {"nota": 11}},
            "crafteos": {"100": {"nota": 5, "receta": {"como": "vendedor", "donde": "Qia"}},
                         "camisa": {"nota": 5}, "101": {"nota": 4, "receta": {"como": "regalo"}}}})
        problems = "\n".join(review_problems(path, method_ids={"pieles"}))
        self.assertIn("farmeo «otro»: no está en metodos.json", problems)
        self.assertIn("farmeo «otro»: «nota» debe ser un número del 1 al 10", problems)
        self.assertIn("crafteo «camisa»: la clave es el número de la receta", problems)
        self.assertIn("crafteo «101»: «receta.como» debe ser uno de", problems)
        reviews = load_reviews(path)
        self.assertEqual(reviews.crafts[100].recipe_where, "Qia")
        self.assertEqual(reviews.farms["pieles"].steps, ["a"])

    def test_el_del_proyecto_esta_bien(self):
        self.assertEqual(review_problems(), [])

    def test_por_hora_en_el_catalogo(self):
        path = self.write("metodos.json", {"metodos": [
            {"id": "a", "nombre": "A", "tipo": "farmeo", "fuente": "x", "nivel_minimo": 90,
             "por_hora": [{"objeto": "Thick Leather"}], "oro_hora": "mucho", "enlace": "youtube.com/x"}]})
        problems = "\n".join(catalog_problems(path))
        self.assertIn("«nivel_minimo» debe ser un número de 0 a 80", problems)
        self.assertIn("cada «por_hora» es", problems)
        self.assertIn("«oro_hora» es el oro por hora", problems)
        self.assertIn("«enlace» debe empezar por http", problems)

    def test_rutas_de_recoleccion(self):
        self.assertAlmostEqual(gathering_hours(ROUTES, 393, 100, 200), 50 / 75 + 50 / 50)
        self.assertIsNone(gathering_hours(ROUTES, 186, 1, 50))

    def test_enlace_de_una_transcripcion(self):
        path = self.write("video.txt", "Vídeo: https://www.youtube.com/watch?v=abc123.\nHola, hoy farmeamos...")
        self.assertEqual(first_link(path), "https://www.youtube.com/watch?v=abc123")


if __name__ == "__main__":
    unittest.main()
