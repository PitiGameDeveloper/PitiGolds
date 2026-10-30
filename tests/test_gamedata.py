"""Importación de los datos del juego (formato de wago.tools) y su uso en el informe."""

import csv
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from motor import db as dbmod
from motor import gamedata
from motor.analysis import analyze
from motor.db import set_meta
from motor.gamedata import import_tables, installed_build, pick_build
from motor.report import build_advice_report

TABLES = {
    "SkillLine": (["DisplayName_lang", "ID", "CategoryID", "ParentSkillLineID"], [
        ["Herrería", 164, 11, 0], ["Alquimia", 171, 11, 0], ["Racial orco", 125, 9, 0],
        ["Test Profession [DNT]", 999, 11, 0], ["Escarcha", 6, 7, 0],
    ]),
    "SkillLineAbility": (["ID", "SkillLine", "Spell", "MinSkillLineRank", "TrivialSkillLineRankLow",
                          "TrivialSkillLineRankHigh", "NumSkillUps", "AcquireMethod"], [
        [10, 164, 2738, 1, 60, 100, 1, 0],
        [11, 164, 2662, 90, 120, 160, 1, 0],
        [12, 171, 2330, 1, 55, 95, 1, 1],
        [13, 125, 20572, 1, 1, 1, 0, 0],    # racial: sin materiales
        [14, 999, 5555, 1, 1, 1, 1, 0],     # pruebas de Blizzard
        [15, 171, 7777, 1, 1, 1, 1, 0],     # sin nombre en el cliente
    ]),
    "SpellName": (["ID", "Name_lang"], [
        [2738, "Hacha de cobre"], [2662, "Peto de cobre rúnico"], [2330, "Poción de sanación menor"],
        [20572, "Furia sangrienta"], [5555, "Prueba"],
    ]),
    "SpellEffect": (["ID", "Effect", "EffectItemType", "EffectTriggerSpell", "EffectBasePointsF", "SpellID"], [
        [1, 24, 2845, 0, 1, 2738], [2, 24, 2864, 0, 1, 2662], [3, 24, 118, 0, 1, 2330],
        [4, 36, 0, 2662, 0, 9001],  # el hechizo 9001 enseña el peto
    ]),
    "SpellReagents": (["ID", "SpellID", "Reagent_0", "Reagent_1", "ReagentCount_0", "ReagentCount_1"], [
        [1, 2738, 2840, 2880, 6, 1], [2, 2662, 2840, 3371, 12, 1], [3, 2330, 2447, 765, 1, 1],
        [4, 5555, 2840, 0, 1, 0], [5, 7777, 2840, 0, 1, 0],
    ]),
    "ItemEffect": (["ID", "TriggerType", "SpellID"], [[50, 6, 2738], [51, 0, 9001]]),
    "ItemXItemEffect": (["ID", "ItemEffectID", "ItemID"], [[1, 50, 9100], [2, 51, 2881]]),
    "Item": (["ID", "ClassID", "SubclassID"], [[2840, 7, 7], [9100, 9, 4]]),
    "ItemSparse": (["ID", "Display_lang", "OverallQualityID", "BuyPrice", "SellPrice", "VendorStackCount",
                    "Stackable", "Bonding", "RequiredSkill", "RequiredSkillRank"], [
        [2840, "Lingote de cobre", 1, 40, 10, 1, 20, 0, 0, 0],
        [2880, "Flujo débil", 1, 100, 25, 1, 20, 0, 0, 0],
        [3371, "Vial vacío", 1, 20, 1, 5, 20, 0, 0, 0],
        [2845, "Hacha de cobre", 2, 0, 18, 1, 1, 2, 0, 0],
        [2864, "Peto de cobre rúnico", 2, 0, 200, 1, 1, 2, 0, 0],
        [118, "Poción de sanación menor", 1, 0, 5, 1, 5, 0, 0, 0],
        [2447, "Flor de paz", 1, 0, 10, 1, 20, 0, 0, 0],
        [765, "Hojaplata", 1, 0, 10, 1, 20, 0, 0, 0],
        [9100, "Diseño: hacha de cobre", 2, 500, 125, 1, 1, 2, 164, 1],
        [2881, "Diseño: peto de cobre con runas", 2, 600, 150, 1, 1, 2, 164, 100],
    ]),
}


def write_tables(folder: Path) -> None:
    for name, (header, rows) in TABLES.items():
        with open(folder / f"{name}.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)


class Importacion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name) / "csv"
        folder.mkdir()
        write_tables(folder)
        self.conn = dbmod.connect(Path(self.tmp.name) / "p.db")
        self.report = import_tables(self.conn, folder, "1.60.1.1")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def q(self, sql, *args):
        return self.conn.execute(sql, args).fetchall()

    def test_solo_recetas_de_verdad(self):
        self.assertEqual({r[0] for r in self.q("SELECT spell_id FROM gd_recipes")}, {2738, 2662, 2330})
        self.assertEqual({r[0] for r in self.q("SELECT skill_line FROM gd_skill_lines")}, {164, 171})
        self.assertEqual(self.report.by_profession, {"Herrería": 2, "Alquimia": 1})

    def test_niveles_y_objeto_de_aprendizaje(self):
        row = self.q("SELECT min_skill, yellow, grey, output_item_id, learn_item_id FROM gd_recipes "
                     "WHERE spell_id = 2738")[0]
        self.assertEqual(tuple(row), (1, 60, 100, 2845, 9100))  # el diseño enseña la receta directamente
        self.assertEqual(self.q("SELECT learn_item_id FROM gd_recipes WHERE spell_id = 2662")[0][0], 2881)

    def test_en_el_informe(self):
        c = self.conn
        c.execute("INSERT INTO profession_summary VALUES ('A-R', 164, 'primary1', 'Herrería', 50, 150, 0)")
        c.execute("INSERT INTO scans VALUES ('s', 'full', 1000, 0, 0, 'R', 'Horde', 'A-R', 0, 'X')")
        c.executemany("INSERT INTO prices VALUES ('s', ?, ?, 10, 1, 1, NULL, ?)", [
            (2840, 300, 300), (2845, 5000, 5000), (118, 60, 60), (2447, 20, 20), (765, 30, 30), (9100, 1500, 1500),
        ])
        c.execute("INSERT INTO vendor_items (item_id, price, limited, vendor) VALUES (2880, 100, 0, 'Grimtak')")
        c.commit()

        a = analyze(c)
        crafts = {r.recipe_id: r for r in a.crafts}
        axe, plate, potion = crafts[2738], crafts[2662], crafts[2330]

        self.assertTrue(axe.yours)
        self.assertFalse(axe.known)
        self.assertEqual((axe.cost, axe.value, axe.profit), (1900, 4750, 2850))
        self.assertEqual((axe.yellow, axe.green, axe.grey), (60, 80, 100))
        self.assertEqual(axe.learn_price, 1500)

        self.assertEqual(plate.required_skill, 100)  # lo pide el diseño, aunque la receta diga 90
        self.assertEqual([m.name for m in plate.missing], ["Vial vacío"])

        self.assertFalse(potion.yours)
        self.assertEqual(potion.profit, 57 - 50)
        self.assertEqual(potion.source, "Se aprende al aprender la profesión")

        text = build_advice_report(c, a)
        self.assertIn("Se aprende con «Diseño: hacha de cobre» (15 p 0 c)", text)
        self.assertIn("| Alquimia | 1 | Poción de sanación menor |", text)
        self.assertIn("Vial vacío (si lo vende un vendedor: 4 c)", text)


class Actualizacion(unittest.TestCase):
    """Cuándo se vuelven a bajar las tablas (sin conectarse a wago.tools)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cache = root / "juego"
        self.cache.mkdir()
        self.wow = root / "_forever_"  # sin .build.info: se usa la versión más reciente
        self.conn = dbmod.connect(root / "p.db")
        self.downloads = []

        def fake_download(build, dest, refresh=False):
            self.downloads.append((build, refresh))
            dest.mkdir(parents=True, exist_ok=True)
            write_tables(dest)
            return dest

        self.patch = mock.patch.object(gamedata, "download", fake_download)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.conn.close()
        self.tmp.cleanup()

    def update(self, builds):
        with mock.patch.object(gamedata, "available_builds", return_value=builds):
            return gamedata.update_game_data(self.conn, self.cache, self.wow)

    def test_al_dia_no_descarga(self):
        self.assertEqual(self.update(["1.0.2"]).build, "1.0.2")
        self.assertIsNone(self.update(["1.0.2"]))
        self.assertEqual(self.downloads, [("1.0.2", False)])

    def test_cada_semana_vuelve_a_bajar_la_misma_version(self):
        self.update(["1.0.2"])
        set_meta(self.conn, "game_data_updated", str(int(time.time()) - 8 * 86400))
        self.conn.commit()
        self.assertIsNotNone(self.update(["1.0.2"]))
        self.assertEqual(self.downloads[-1], ("1.0.2", True))

    def test_version_nueva_borra_la_vieja(self):
        self.update(["1.0.2"])
        self.assertEqual(self.update(["1.0.3", "1.0.2"]).build, "1.0.3")
        self.assertEqual(self.downloads[-1], ("1.0.3", False))
        self.assertFalse((self.cache / "1.0.2").exists())
        self.assertTrue((self.cache / "1.0.3").exists())


class Version(unittest.TestCase):
    def test_elige_la_del_cliente_instalado(self):
        self.assertEqual(pick_build(["1.60.1.3", "1.60.1.2"], "1.60.1.2"), "1.60.1.2")
        self.assertEqual(pick_build(["1.60.1.3", "1.60.1.2"], "1.60.1.1"), "1.60.1.3")
        self.assertEqual(pick_build(["1.60.1.3"], None), "1.60.1.3")

    def test_lee_build_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".build.info").write_text(
                "Branch!STRING:0|Active!DEC:1|Version!STRING:0|Product!STRING:0\n"
                "eu|1|12.1.5.70529|wow\n"
                "eu|1|1.60.1.70685|wowf\n", encoding="utf-8")
            self.assertEqual(installed_build(root / "_forever_"), "1.60.1.70685")
            self.assertIsNone(installed_build(root / "otra" / "_forever_"))


if __name__ == "__main__":
    unittest.main()
