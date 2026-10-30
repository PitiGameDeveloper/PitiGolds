"""Prueba el addon en un WoW simulado (Lua 5.1) y pasa sus datos por el motor.

Necesita lupa:  .venv\\Scripts\\python -m pip install -r requirements-dev.txt
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from lupa.lua51 import LuaRuntime

from motor import db as dbmod
from motor.analysis import analyze
from motor.generated import write_generated
from motor.ingest import ingest_file
from motor.report import build_advice_report, build_report

ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = ROOT / "addon" / "PitiGolds"
TESTS_DIR = Path(__file__).resolve().parent


def toc_files() -> list[str]:
    lines = (ADDON_DIR / "PitiGolds.toc").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def lua_path(path: Path) -> str:
    return path.as_posix()


class AddonEnPartidaSimulada(unittest.TestCase):
    """Una sesión completa: entrar, abrir banco, correo, profesión y subasta, y exportar."""

    @classmethod
    def setUpClass(cls):
        cls.lua = lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = lua.globals().Mock
        files = lua.table_from(toc_files())
        mock.LoadAddon(lua_path(ADDON_DIR), files)
        # SavedVariables de una sesión anterior: ya existía un alter.
        lua.execute('PitiGoldsDB = { characters = { ["Alt-Dio"] = { name = "Alt", level = 20, inventory = {} } } }')
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        mock.Advance(10)

        mock.Fire("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", 8)  # banco
        mock.Advance(2)
        mock.Fire("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", 8)

        mock.Fire("MAIL_SHOW")
        mock.Advance(2)
        lua.execute('SendMail("alt", "", "")')
        mock.Fire("MAIL_SEND_SUCCESS")
        mock.Fire("MAIL_CLOSED")

        mock.Fire("MERCHANT_SHOW")
        mock.Advance(1)
        mock.Fire("MERCHANT_CLOSED")

        mock.Fire("TRADE_SKILL_SHOW")
        mock.Advance(3)

        mock.Fire("AUCTION_HOUSE_SHOW")
        mock.Advance(3)
        mock.ClickButton("PG: Materiales")
        mock.Advance(60)
        mock.ClickButton("PG: Completo")
        mock.Advance(30)
        mock.Slash("completo")  # dentro de los 15 minutos: debe negarse
        mock.Advance(1)

        cls.mock = mock
        cls.db = lua.globals().PitiGoldsDB
        cls.char = cls.db.characters["Brujo-Dio"]

    def chat(self) -> str:
        return "\n".join(self.mock.chat.values())

    def test_sin_errores(self):
        log = "\n".join(self.db.log.values())
        self.assertNotIn("ERROR", log)
        self.assertNotIn("error", self.chat())

    def test_personaje_y_oro(self):
        self.assertEqual(self.char.level, 60)
        self.assertEqual(self.char["class"], "WARLOCK")
        self.assertEqual(self.char.money, 1234567)
        self.assertEqual(self.db.account.warbandMoney, 500000)

    def test_bolsas_banco_y_banda(self):
        bags = self.char.inventory.bags
        self.assertEqual(bags["items"][2589], 25)
        self.assertEqual(bags["items"][2770], 15)
        self.assertEqual(bags["bound"][6948], 1)
        self.assertEqual(bags.slots, 26)
        self.assertEqual(self.char.inventory.bank["items"][2589], 40)
        self.assertEqual(self.char.inventory.bank["items"][2840], 10)
        self.assertEqual(self.db.account.warbandBank["items"][818], 3)
        self.assertEqual(self.db["items"][2589].name, "Paño de lino")
        self.assertEqual(self.db["items"][2589].sell, 13)

    def test_vendedor(self):
        vendor = self.db.vendorItems
        self.assertEqual(vendor[2880].price, 100)
        self.assertEqual(vendor[2320].price, 10)  # 30 c el lote de 3
        self.assertEqual(vendor[2880].vendor, "Grimtak")
        self.assertIsNone(vendor[9999].price)
        self.assertEqual(vendor[9999].costs[1].currencyID, 3001)
        self.assertEqual(vendor[9999].costs[1].value, 50)

    def test_correo_sin_contra_reembolso(self):
        mail = self.char.inventory.mail
        self.assertEqual(mail["items"][2592], 20)
        self.assertIsNone(mail["items"][2770])
        self.assertEqual(mail.money, 5000)

    def test_correo_enviado_al_alter(self):
        incoming = self.db.characters["Alt-Dio"].inventory.mailIncoming
        self.assertEqual(incoming[1]["items"][2840], 5)
        self.assertEqual(incoming[1]["from"], "Brujo-Dio")

    def test_divisas_y_reputacion(self):
        cur = self.char.currencies
        self.assertEqual(cur[3001].quantity, 120)
        self.assertTrue(cur[3002].accountWide)
        self.assertIsNone(cur[42])
        self.assertEqual(self.char.reputations[2900].standing, 1500)

    def test_recetas(self):
        prof = self.char.professions[2751]
        self.assertEqual(prof.skill, 75)
        self.assertEqual(sorted(prof.known.values()), [1001, 1002])
        recipe = self.db.recipes[1003]
        self.assertIn("Grimtak", recipe.source)
        self.assertEqual(recipe.reagents[2].currencies[1], 3001)
        self.assertIsNone(recipe.info.learned)  # lo que depende del personaje no va a la ficha común
        self.assertEqual(self.db.recipes[1001].info.maxTrivialLevel, 50)

    def test_escaneos(self):
        scans = self.db.scans
        self.assertEqual(len(scans), 2)
        browse, full = scans[1], scans[2]
        self.assertEqual(browse.type, "browse")
        self.assertEqual(browse.count, 7)
        self.assertEqual(browse["items"][818], "2500,4")
        self.assertEqual(full.type, "full")
        self.assertEqual(full["items"][2589], "40,35,3,2|40:15;45:20")
        self.assertEqual(full["items"][2845], "5000,1,1,1|5000:1")
        self.assertEqual(full["items"][19019], "75000000000,1,1,1|75000000000:1")
        self.assertIsNone(full["items"][2592])  # solo puja, sin precio de compra
        self.assertIn("solo se puede hacer cada 15 minutos", self.chat())

    def test_subastas_propias(self):
        listed = self.char.inventory.auctions.list
        self.assertEqual(listed[1].itemID, 2840)
        self.assertEqual(listed[2].status, 1)


class AddonMasMotor(unittest.TestCase):
    """Lo que guarda el addon se lee en el motor y el addon borra lo ya leído."""

    def test_de_punta_a_punta(self):
        scenario = AddonEnPartidaSimulada
        scenario.setUpClass()
        lua, mock = scenario.lua, scenario.mock
        saved = lua.globals().Mock.Serialize("PitiGoldsDB", lua.globals().PitiGoldsDB)

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            sv = tmp / "WTF" / "Account" / "TEST#1" / "SavedVariables" / "PitiGolds.lua"
            sv.parent.mkdir(parents=True)
            sv.write_text(saved, encoding="utf-8")
            addon_dir = tmp / "addon"
            addon_dir.mkdir()

            conn = dbmod.connect(tmp / "pitigolds.db")
            report = ingest_file(conn, "TEST#1", sv)
            self.assertEqual(report.characters, 2)
            self.assertEqual(report.new_scans, 2)
            again = ingest_file(conn, "TEST#1", sv)
            self.assertEqual(again.new_scans, 0)

            q = lambda sql, *a: conn.execute(sql, a).fetchall()
            self.assertEqual(q("SELECT count FROM inventory WHERE char_key='Brujo-Dio' AND location='bags' "
                               "AND item_id=2589 AND bound=0")[0][0], 25)
            self.assertEqual(q("SELECT count FROM inventory WHERE char_key='_warband' AND item_id=818")[0][0], 3)
            self.assertEqual(q("SELECT count FROM inventory WHERE char_key='Alt-Dio' "
                               "AND location='mail_incoming' AND item_id=2840")[0][0], 5)
            self.assertEqual(q("SELECT count FROM inventory WHERE char_key='Brujo-Dio' "
                               "AND location='auctions' AND item_id=2840")[0][0], 10)
            self.assertEqual(q("SELECT COUNT(*) FROM known_recipes WHERE char_key='Brujo-Dio'")[0][0], 2)
            source = q("SELECT source_plain FROM recipes WHERE recipe_id=1003")[0][0]
            self.assertEqual(source, "Vendedor: Grimtak\nZona: Durotar\nCoste: 5")
            self.assertEqual(q("SELECT currency_id FROM recipe_reagents WHERE recipe_id=1003 AND slot=2")[0][0], 3001)
            row = q("SELECT min_price, quantity, num_auctions, num_owners, book FROM prices p "
                    "JOIN scans s ON s.scan_id = p.scan_id WHERE s.type='full' AND item_id=2589")[0]
            self.assertEqual(tuple(row), (40, 35, 3, 2, "40:15;45:20"))
            self.assertEqual(q("SELECT min_price FROM latest_prices WHERE item_id=19019")[0][0], 75000000000)
            self.assertEqual(q("SELECT sell_price FROM items WHERE item_id=5000")[0][0], 500)
            self.assertEqual(q("SELECT price FROM vendor_items WHERE item_id=2880")[0][0], 100)

            text = build_report(conn)
            self.assertIn("Brujo-Dio", text)
            self.assertIn("Favor del mercader", text)
            self.assertIn("Paño de lino", text)

            a = analyze(conn)
            crafts = {c.recipe_id: c for c in a.crafts}
            smelt, axe, helm = crafts[1001], crafts[1002], crafts[1003]
            self.assertEqual((smelt.cost, smelt.value, smelt.profit), (120, 285, 165))
            self.assertEqual(smelt.craftable_now, 15)
            self.assertEqual(smelt.difficulty_name, "amarilla")
            # 6 barras a 300 en la subasta + flujo a 100 del vendedor; el paño opcional no cuenta.
            self.assertEqual((axe.cost, axe.value, axe.profit), (1900, 4750, 2850))
            self.assertEqual([r.source for r in axe.reagents], ["subasta", "vendedor"])
            self.assertFalse(helm.known)
            self.assertEqual([m.name for m in helm.missing], ["Barra de bronce"])
            self.assertEqual(helm.currencies, ["10 Favor del mercader"])

            sales = {s.item_id: s for s in a.sales}
            self.assertEqual((sales[2589].action, sales[2589].unit_price), ("subastar", 39))
            self.assertIn("poco a poco", sales[2589].reason)  # 65 tuyos frente a 35 a la venta
            self.assertEqual((sales[5000].action, sales[5000].total), ("vendedor", 2000))
            self.assertEqual(sales[2770].action, "guardar")
            self.assertEqual(sales[2840].action, "guardar")
            self.assertIn("correo en camino 5", sales[2840].places)
            self.assertNotIn(6948, sales)  # ligado: no se puede vender

            advice = build_advice_report(conn, a)
            self.assertIn("Hacha de cobre", advice)
            self.assertIn("Profesiones sin abrir todavía", advice)  # minería y cocina

            generated = write_generated(conn, addon_dir, a)
            conn.close()
            content = generated.read_text(encoding="utf-8")
            up_to = int(re.search(r"ingestedUpTo = (\d+)", content).group(1))
            self.assertGreater(up_to, 0)
            self.assertIn('[2589] = "40,",', content)
            self.assertIn('[2845] = "1900,2850",', content)

            # Al recargar, el addon carga Generated.lua y borra lo que el motor ya tiene.
            lua.execute(f'dofile("{generated.as_posix()}")')
            mock.ns.PruneScans()
            self.assertEqual(len(lua.globals().PitiGoldsDB.scans), 0)

            tooltip = mock.Tooltip(2840)
            self.assertIn("PitiGolds subasta = 3p 0c", tooltip)
            self.assertIn("PitiGolds fabricar = 1p 20c  |cff40ff40+1p 65c|r", tooltip)
            self.assertEqual(mock.Tooltip(123456), "")

            mock.ClickButton("Exportar")
            self.assertTrue(mock.reloaded)


if __name__ == "__main__":
    unittest.main()
