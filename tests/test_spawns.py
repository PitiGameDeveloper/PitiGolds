"""Dónde salen los bichos y las cosas de cada farmeo: la base de datos de Questie (spawns.py)."""

import tempfile
import time
import unittest
from pathlib import Path

from motor import db as dbmod
from motor import spawns
from motor.catalogo import CatalogEntry
from motor.spawns import catalog_warnings, farm_spawns, import_files, pack

# Recortes con el formato de QuestieDB (data/Forever/*.lua y l10n/Forever/*/esES.lua).
NPCS = """QuestieDB.npcData = [[return {
[2372] = {'Mudsnout Gnoll',788,840,26,27,0,{[267]={{63.57,65.06},{64.65,65.64},{62.47,62.67}}},nil,267,nil,nil,95,nil,nil,0},
[2373] = {'Mudsnout Shaman',665,702,27,28,0,{[267]={{62.96,63.71},{20.0,20.0}}},nil,267,nil,nil,95,nil,nil,0},
[2374] = {'Torn Fin Muckdweller',665,702,10,11,0,{[267]={{30.0,30.0}}},nil,267,nil,nil,95,nil,nil,0},
[2375] = {'Gnoll Rarísimo',665,702,27,27,4,{[267]={{63.0,63.0}}},nil,267,nil,nil,95,nil,nil,0},
[2376] = {'Old Gnoll',665,702,8,9,0,{[267]={{40.0,40.0}}},nil,267,nil,nil,95,nil,nil,0},
}]]
"""
NPCS_ES = """l10n.npcNameLookup["esES"] = loadstring([[return {
[2372] = {"Gnoll Fangorroca",nil},
[2373] = {"Chamán Fangorroca",nil},
[2376] = {"Gnoll viejo",nil},
}]])
"""
NPCS_FOREVER = """l10n.npcNameLookup["esES"] = loadstring([[return {
[2373] = {"Chamán Fangorroca de Forever","Título"},
}]])
"""
OBJECTS = """QuestieDB.objectData = [[return {
[2744] = {"Giant Clam",nil,nil,{[267]={{24.38,27.99},{25.77,28.31}},[719]={{-1,-1}}},267},
}]]
"""
OBJECTS_ES = """l10n.objectLookup["esES"] = loadstring([[return {
[2744] = "Almeja gigante",
}]])
"""


class BaseDeQuestie(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name) / "questie"
        folder.mkdir()
        for name, text in {"npcs.lua": NPCS, "npcs.esES.lua": NPCS_ES, "npcs.esES.forever.lua": NPCS_FOREVER,
                           "objetos.lua": OBJECTS, "objetos.esES.lua": OBJECTS_ES}.items():
            (folder / name).write_text(text, encoding="utf-8")
        self.conn = c = dbmod.connect(Path(self.tmp.name) / "p.db")
        c.execute("INSERT INTO gd_areas VALUES (267, 'Laderas de Trabalomas')")
        c.execute("INSERT INTO gd_maps VALUES (1424, 'Laderas de Trabalomas')")
        c.commit()
        self.placed = import_files(c, folder)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_importa_pnj_y_objetos_con_su_nombre_en_espanol(self):
        self.assertEqual(self.placed, 6)   # 5 PNJ y la almeja
        names = {r["id"]: r["name_es"] for r in self.conn.execute("SELECT id, name_es FROM qd_names")}
        self.assertEqual(names[2372], "Gnoll Fangorroca")
        self.assertEqual(names[2373], "Chamán Fangorroca de Forever")   # lo visto en Forever manda
        self.assertIsNone(names[2374])
        self.assertEqual(names[2744], "Almeja gigante")
        # Los puntos {-1, -1} son de dentro de una mazmorra: no cuentan.
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM qd_spawns WHERE kind = 'obj'").fetchone()[0], 2)

    def test_sitios_de_los_bichos_del_farmeo(self):
        found = farm_spawns(self.conn, {"map": 1424}, ["Gnoll Fangorroca", "Chamán"], level=26)
        self.assertEqual(found.names, ["Gnoll Fangorroca", "Chamán Fangorroca de Forever"])
        self.assertEqual(len(found.spawns), 5)
        # Sin x/y, el punto va al grupo más denso (el chamán suelto de 20,20 no lo mueve).
        self.assertAlmostEqual(found.point["x"], 0.634, places=2)
        self.assertAlmostEqual(found.point["y"], 0.643, places=2)

    def test_con_sitio_en_el_catalogo_solo_cuentan_los_de_cerca(self):
        found = farm_spawns(self.conn, {"map": 1424, "x": 0.2, "y": 0.2}, ["Chamán Fangorroca"])
        self.assertEqual(found.spawns, [(0.2, 0.2)])
        self.assertEqual(found.point, {"map": 1424, "x": 0.2, "y": 0.2})

    def test_nombre_en_ingles_raros_y_nivel(self):
        # En inglés también vale; el raro (rango 4) no se farmea.
        found = farm_spawns(self.conn, {"map": 1424}, ["Mudsnout"])
        self.assertEqual(len(found.spawns), 5)
        self.assertEqual(len(farm_spawns(self.conn, {"map": 1424}, ["Gnoll"]).spawns), 4)
        # Los de nivel muy por debajo del farmeo comparten nombre con otros de la zona: fuera.
        self.assertEqual(len(farm_spawns(self.conn, {"map": 1424}, ["Gnoll"], level=26).spawns), 3)

    def test_cosas_del_mapa(self):
        found = farm_spawns(self.conn, {"map": 1424}, [], ["Almeja gigante"])
        self.assertEqual(found.spawns, [])
        self.assertEqual(found.nodes, [(0.244, 0.28), (0.258, 0.283)])
        self.assertEqual(pack(found.nodes), "244,280;258,283")

    def test_sin_nada(self):
        self.assertIsNone(farm_spawns(self.conn, {"map": 1424}, ["Kóbold"]))
        self.assertIsNone(farm_spawns(self.conn, {"map": 9999}, ["Gnoll"]))
        self.assertIsNone(farm_spawns(self.conn, None, ["Gnoll"]))

    def test_avisos_del_catalogo(self):
        def entry(id_, mobs=(), nodes=(), point=None):
            return CatalogEntry(id=id_, name=id_, kind="farmeo", level=26, zone="", professions=[],
                                items=[], point=point or {"map": 1424}, mobs=list(mobs), nodes=list(nodes))
        warnings = catalog_warnings(self.conn, [
            entry("bien", ["Gnoll Fangorroca"]),
            entry("vacio"),
            entry("mal", ["Gnoll Fangorroca", "Hociclodo"]),
            entry("nada", ["Hociclodo"]),
        ])
        self.assertEqual(warnings, [
            "vacio: sin «bichos» ni «nodos», el mapa solo marca la zona",
            "mal: no encuentro en Questie Hociclodo",
            "nada: no encuentro en Questie Hociclodo (ni nada más: el mapa solo marca la zona)",
        ])

    def test_no_se_vuelve_a_bajar_si_esta_al_dia(self):
        self.assertIsNone(spawns.update_spawns(self.conn, Path(self.tmp.name)))
        self.assertGreater(int(dbmod.get_meta(self.conn, "questie_updated")), time.time() - 60)

    def test_formato_roto_no_borra_lo_que_habia(self):
        folder = Path(self.tmp.name) / "questie"
        (folder / "npcs.lua").write_text("nada", encoding="utf-8")
        with self.assertRaises(ValueError):
            import_files(self.conn, folder)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM qd_names").fetchone()[0], 6)


if __name__ == "__main__":
    unittest.main()
