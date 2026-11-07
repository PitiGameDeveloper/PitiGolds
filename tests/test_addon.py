"""Prueba el addon en un WoW simulado (Lua 5.1) y pasa sus datos por el motor.

Necesita lupa:  .venv\\Scripts\\python -m pip install -r requirements-dev.txt
"""

from __future__ import annotations

import math
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
from motor.panel import build_panel
from motor.revision import Reviews
from motor.report import build_advice_report, build_report

ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = ROOT / "addon" / "PitiGolds"
TESTS_DIR = Path(__file__).resolve().parent


def toc_files() -> list[str]:
    lines = (ADDON_DIR / "PitiGolds.toc").read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def lua_path(path: Path) -> str:
    return path.as_posix()


class VersionDelAddon(unittest.TestCase):
    def test_el_toc_y_core_dicen_la_misma(self):
        # Si no coinciden, GitHub rechaza la publicación de la release.
        toc = (ADDON_DIR / "PitiGolds.toc").read_text(encoding="utf-8")
        core = (ADDON_DIR / "Core.lua").read_text(encoding="utf-8")
        self.assertEqual(re.search(r"^## Version: *(\S+)", toc, re.M).group(1),
                         re.search(r'^ns\.VERSION = "(.*?)"', core, re.M).group(1))


class FormatoDelDinero(unittest.TestCase):
    def test_las_perdidas_llevan_signo(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        for copper, text in ((-2, "-2c"), (-32, "-32c"), (-175, "-1p 75c"), (-12345, "-1o 23p 45c"), (175, "1p 75c")):
            self.assertEqual(mock.ns.Money(copper), text)


class OroAlSalir(unittest.TestCase):
    def test_salir_no_machaca_el_oro_guardado(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.player.money = 12345
        mock.Fire("PLAYER_LOGIN")
        char = lua.globals().PitiGoldsDB.characters["Brujo-Dio"]
        self.assertEqual(char.money, 12345)

        mock.AddMoney(55)
        self.assertEqual(char.money, 12400)

        mock.player.money = 0  # lo que da GetMoney() mientras se sale del juego
        mock.Fire("PLAYER_LOGOUT")
        self.assertEqual(char.money, 12400)


class AddonEnPartidaSimulada(unittest.TestCase):
    """Una sesión completa: entrar, abrir banco, correo, profesión y subasta, y recargar."""

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

            # Cuántos caben en cada pila (de los datos del juego): el depósito de la subasta es por pila.
            conn.executemany("INSERT INTO gd_items (item_id, stackable) VALUES (?, ?)",
                             [(i, 20) for i in (2589, 2592, 2770, 2840, 2880, 818, 5000)] + [(2845, 1)])
            a = analyze(conn)
            crafts = {c.recipe_id: c for c in a.crafts}
            smelt, axe, helm = crafts[1001], crafts[1002], crafts[1003]
            # La barra a 300 en la subasta: menos la comisión (285) y 5 c de depósito (pila de 20).
            self.assertEqual((smelt.cost, smelt.value, smelt.profit), (120, 280, 160))
            self.assertEqual(smelt.craftable_now, 15)
            self.assertEqual(smelt.difficulty_name, "amarilla")
            # 6 barras a 300 en la subasta + flujo a 100 del vendedor; el paño opcional no cuenta. El hacha
            # no se apila: pierde la plata entera de depósito.
            self.assertEqual((axe.cost, axe.value, axe.profit), (1900, 4650, 2750))
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

            panel = build_panel(conn, a, reviews=Reviews(), routes={})
            generated = write_generated(conn, addon_dir, a, panel)
            conn.close()
            content = generated.read_text(encoding="utf-8")
            up_to = int(re.search(r"ingestedUpTo = (\d+)", content).group(1))
            self.assertGreater(up_to, 0)
            self.assertIn('[2589] = "40,,",', content)
            self.assertIn('[2845] = "1900,2750",', content)

            # Al recargar, el addon carga Generated.lua y borra lo que el motor ya tiene.
            lua.execute(f'dofile("{generated.as_posix()}")')
            mock.ns.PruneScans()
            self.assertEqual(len(lua.globals().PitiGoldsDB.scans), 0)

            tooltip = mock.Tooltip(2840)
            self.assertIn("PitiGolds subasta = 3p 0c", tooltip)
            self.assertIn("PitiGolds fabricar = 1p 20c  |cff40ff40+1p 60c|r", tooltip)
            self.assertEqual(mock.Tooltip(123456), "")

            # Ventana de métodos: el hacha ya la sabe hacer, así que salen los pasos con lo que tiene.
            self.assertIn("vendor = \"Grimtak\"", content)
            mock.ClickButton("Mejor farmeo")
            methods = mock.ns.Methods
            methods.Open("crafts")
            names = [c.name for c in panel.crafts]
            methods.Select(names.index("Hacha de cobre") + 1)
            detail = methods.DetailText()
            self.assertIn("Hoy: 1 × Hacha de cobre con Brujo", detail)
            self.assertIn("Viaja a Durotar, habla con Grimtak y compra x1 Flujo débil", detail)
            self.assertNotIn("Barra de cobre (", detail)   # las 6 barras ya están en su banco
            self.assertIn("Fabrica x1 Hacha de cobre con Brujo.", detail)
            self.assertIn("Ponlo en la subasta: x1 a", detail)

            # Una receta sin aprender: primero cómo conseguirla; al aprenderla, los pasos para hacerla.
            lua.execute('''
              TestRow = { recipe = 7777, name = "Yelmo de cobre", prof = "Herrería", line = 164, who = "Alt-Dio",
                skill = 40, craftsDay = 2, outputQty = 1, sellPrice = 5000,
                prep = { "Alt: le faltan 10 puntos de Herrería (40/50)." },
                learn = { way = "vendedor", vendor = "Grimtak", zone = "Orgrimmar", itemName = "Diseño: yelmo",
                          price = 500 },
                reagents = { { id = 2840, name = "Barra de cobre", qty = 4, price = 300, src = "subasta" } } }
            ''')
            steps, known = methods.CraftSteps(lua.globals().TestRow)
            text = "\n".join(steps.values())
            self.assertFalse(known)
            self.assertIn("Conéctate con Alt (Herrería 40), viaja a Orgrimmar y cómprale «Diseño: yelmo» a Grimtak",
                          text)
            self.assertIn("pulsa Actualizar", text)
            lua.execute('PitiGoldsDB.characters["Alt-Dio"].professions = { [164] = { skill = 50, known = { 7777 } } }')
            steps, known = methods.CraftSteps(lua.globals().TestRow)
            text = "\n".join(steps.values())
            self.assertTrue(known)
            # 8 barras: 5 le llegan por correo; 3 se las manda Brujo, que tiene 10 en el banco.
            self.assertIn("Envía por correo a Alt: x3 Barra de cobre", text)
            self.assertIn("Conéctate con Alt.", text)
            self.assertIn("Fabrica x2 Yelmo de cobre con Alt.", text)


if __name__ == "__main__":
    unittest.main()


class Farmeo(unittest.TestCase):
    """Lo que entra en las bolsas farmeando se apunta; lo que se recoge del correo, no."""

    @classmethod
    def setUpClass(cls):
        cls.lua = lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = cls.mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        lua.execute("PitiGoldsDB = nil")
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        mock.Advance(10)

        mock.Slash("farmeo Cobre en Durotar")
        mock.Loot(0, 10, 2770, 3)
        mock.AddMoney(250)
        mock.Advance(60)
        mock.Loot(0, 10, 2770, 2)
        mock.Advance(1)
        # Lo que se recoge del correo no es farmeado.
        mock.Fire("MAIL_SHOW")
        mock.Loot(0, 11, 2592, 20)
        mock.AddMoney(5000)
        mock.Advance(2)
        mock.Fire("MAIL_CLOSED")
        mock.Advance(1)
        # Sigue en otra zona.
        lua.execute("Mock.mapID = 1413")
        mock.Loot(0, 10, 2770, 1)
        mock.Advance(1)
        cls.buckets = list(lua.globals().PitiGoldsDB.farmLog.values())

    def total(self, zone, item_id=None):
        found = [b for b in self.buckets if b.zoneName == zone]
        if item_id is None:
            return sum(b.money for b in found)
        return sum((b["items"][item_id] or 0) for b in found)

    def test_cuenta_lo_farmeado(self):
        self.assertEqual(self.total("Durotar", 2770), 5)
        self.assertEqual(self.total("Durotar"), 250)
        self.assertEqual(self.total("Los Baldíos", 2770), 1)
        self.assertTrue(all(b.label == "Cobre en Durotar" for b in self.buckets))

    def test_no_cuenta_el_correo(self):
        self.assertEqual(sum((b["items"][2592] or 0) for b in self.buckets), 0)
        self.assertEqual(self.total("Durotar") + self.total("Los Baldíos"), 250)

    def test_oro_por_hora_en_el_juego(self):
        per_hour = self.lua.eval("Mock.ns.FarmLastHour()")
        per_hour = per_hour[0] if isinstance(per_hour, tuple) else per_hour
        self.assertGreater(per_hour, 0)

    def test_sesiones_en_el_motor(self):
        saved = self.mock.Serialize("PitiGoldsDB", self.lua.globals().PitiGoldsDB)
        with tempfile.TemporaryDirectory() as tmp:
            sv = Path(tmp) / "PitiGolds.lua"
            sv.write_text(saved, encoding="utf-8")
            conn = dbmod.connect(Path(tmp) / "p.db")
            report = ingest_file(conn, "TEST#1", sv)
            self.assertGreater(report.farm_buckets, 0)
            ingest_file(conn, "TEST#1", sv)  # leerlo dos veces no duplica nada
            a = analyze(conn)
            sessions = {s.zone: s for s in a.farms}
            self.assertEqual(sessions["Durotar"].items, {2770: 5})
            self.assertEqual(sessions["Durotar"].money, 250)
            self.assertEqual(sessions["Durotar"].activity, "Cobre en Durotar")
            self.assertEqual(sessions["Los Baldíos"].items, {2770: 1})
            self.assertIn("Tus farmeos", build_advice_report(conn, a))
            conn.close()


class SesionEnVivo(unittest.TestCase):
    """El panel y la ventana de sesión se ponen al día al lootear, con el precio más reciente."""

    @classmethod
    def setUpClass(cls):
        cls.lua = lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = cls.mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        lua.execute('PitiGoldsDB = nil; PitiGoldsGenerated = { prices = { [2770] = "200,," } }')
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        mock.Advance(10)
        cls.ns = lua.globals().Mock.ns

        mock.Loot(0, 10, 2770, 3)
        mock.AddMoney(250)
        mock.Advance(1)
        mock.Fire("MAIL_SHOW")
        mock.Loot(0, 11, 2592, 20)
        mock.AddMoney(5000)
        mock.Advance(2)
        mock.Fire("MAIL_CLOSED")
        mock.Advance(1)
        session = lua.globals().PitiGoldsDB.characters["Brujo-Dio"].session
        cls.items = dict(session["items"].items())
        cls.money = session.money
        cls.panel = cls.ns.PanelText()

    def value(self, item_id):
        unit, source = self.lua.eval(f"Mock.ns.ItemValue({item_id})")
        return unit, source

    def test_cuenta_lo_farmeado_y_no_el_correo(self):
        self.assertEqual(self.items, {2770: 3})
        self.assertEqual(self.money, 250)
        # 250 c sueltos + 3 minerales a 185 c (200 en la subasta menos la comisión y 5 c de depósito,
        # 1 plata por pila de 20).
        self.assertIn("Sesión (0 min): 8p 5c", self.panel)

    def test_el_panel_cambia_en_cuanto_looteas(self):
        before = self.ns.PanelText()
        self.mock.Loot(0, 12, 818, 1)   # Ojo de tigre: 150 c en el vendedor
        self.mock.Advance(1)            # menos que el reloj del panel (60 s)
        after = self.ns.PanelText()
        self.assertNotEqual(before, after)
        self.assertIn("Sesión (", after)
        self.assertIn("Última hora:", after)

    def test_precio_del_escaneo_que_el_motor_no_ha_leido(self):
        self.assertEqual(self.value(2770), (185, "subasta"))
        self.assertEqual(self.value(818), (150, "vendedor"))
        # Escaneo completo: el mercado es la media del 15 % más barato (2 de 10 a 100 c).
        self.lua.execute('Mock.ns.AddScan({ time = time(), items = { [2770] = "100,10,2,2|100:2;120:8" } })')
        self.assertEqual(self.value(2770), (90, "escaneo"))
        self.mock.Advance(5)
        self.lua.execute('Mock.ns.AddScan({ time = time(), items = { [2770] = "300,5" } })')
        self.assertEqual(self.value(2770), (280, "escaneo"))   # manda el más reciente
        self.lua.execute('Mock.ns.AddScan({ time = time(), items = { [818] = "100,4" } })')
        self.assertEqual(self.value(818), (150, "vendedor"))   # el vendedor paga más

    def test_el_precio_del_vendedor_se_pone_al_dia(self):
        # Guardado en otra sesión a 1 p 10 c; desde entonces Blizzard la dejó en 1 c.
        self.lua.execute('Mock.itemNames[11287] = "Varita mágica inferior"; Mock.sellPrices[11287] = 1;'
                         'PitiGoldsDB.items[11287] = { name = "Varita mágica inferior", sell = 110 }')
        self.assertEqual(self.value(11287), (110, "vendedor"))
        self.ns.NoteItem(11287)
        self.assertEqual(self.lua.eval("PitiGoldsDB.items[11287].sell"), 1)
        self.assertEqual(self.value(11287), (1, "vendedor"))

    def test_ventana_y_reiniciar(self):
        S = self.ns.Session
        S.Reset()
        self.mock.Loot(0, 10, 2770, 2)
        self.mock.Advance(1)
        self.assertTrue(self.mock.ClickButton("Sesión"))
        self.assertIn("Mineral de cobre ×2", S.RowTexts())
        self.assertIn("Llevas 0 min:", S.SummaryText())
        self.mock.Loot(0, 10, 2770, 1)   # con la ventana abierta, también al momento
        self.mock.Advance(1)
        self.assertIn("Mineral de cobre ×3", S.RowTexts())
        self.assertTrue(self.mock.ClickButton("Reiniciar"))
        self.assertIn("Aún no has farmeado nada", S.RowTexts())

    def test_sigue_tras_un_reload_y_empieza_otra_al_rato(self):
        S = self.ns.Session
        S.Reset()
        self.mock.Loot(0, 10, 2770, 1)
        self.mock.Advance(1)
        session = self.lua.globals().PitiGoldsDB.characters["Brujo-Dio"].session
        session.seen = session.seen - 120   # dos minutos fuera (un /reload, otro personaje)
        S.OnLogin()
        session = self.lua.globals().PitiGoldsDB.characters["Brujo-Dio"].session
        self.assertEqual(session["items"][2770], 1)
        self.assertGreaterEqual(session.away, 120)   # el rato fuera no cuenta
        session.seen = session.seen - 3600
        S.OnLogin()
        session = self.lua.globals().PitiGoldsDB.characters["Brujo-Dio"].session
        self.assertIsNone(session["items"][2770])


ACTIVE_METHODS = """
PitiGoldsDB = nil
PitiGoldsGenerated = {
  prices = { [2770] = "200,,", [2589] = "40,," },
  methods = {
    verdict = { state = "mejor", title = "Arpías", lines = {}, best = "baldios-arpias" },
    farms = {
      { key = "baldios-arpias", name = "Arpías", kind = "farmeo", gph = 20000, items = { 2589 }, coins = true,
        point = { map = 1413, x = 0.5, y = 0.5 }, mobs = { "Arpía" }, zone = "Los Baldíos", details = {}, req = "" },
      { key = "cobre", name = "Cobre en Durotar", kind = "farmeo", items = { 2770 }, coins = false,
        point = { map = 1411 }, mobs = {}, details = {}, req = "" },
    },
    crafts = {
      { recipe = 1002, name = "Hacha de cobre", prof = "Herrería", craftsDay = 2, profit = 500, outputQty = 1,
        color = "verde", knownBy = {}, details = {}, reagents = {
          { id = 2840, name = "Barra de cobre", qty = 6, src = "subasta" },
          { id = 2880, name = "Flujo débil", qty = 1, src = "vendedor" } } },
    },
  },
}
"""


class FarmeosActivos(unittest.TestCase):
    """Elegir farmeos en la ventana de métodos, su recuadro con reloj, el macro, las marcas y la flecha."""

    @classmethod
    def setUpClass(cls):
        cls.lua = lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = cls.mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        lua.execute(ACTIVE_METHODS)
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        mock.Advance(10)
        cls.ns = mock.ns
        cls.T = mock.ns.Tracker

    def setUp(self):
        self.lua.execute("""
          PitiGoldsDB.characters["Brujo-Dio"].activeFarms = {}
          Mock.macros = {}
          for unit in pairs(Mock.plates) do Mock.RemovePlate(unit) end
          Mock.units = {}
          Mock.loot = {}
        """)
        self.T.Changed()

    def farm(self, key):
        return self.T.Find(key)[0]

    def activate_from_window(self, tab, index):
        self.ns.Methods.Open(tab)
        self.ns.Methods.Select(index)
        label = "Craftear este" if tab == "crafts" else "Farmear este"
        self.assertTrue(self.mock.ClickButton(label))

    def test_activar_desde_la_ventana_de_metodos(self):
        self.activate_from_window("farms", 1)
        self.assertTrue(self.T.IsActive("baldios-arpias"))
        self.assertTrue(self.T.IsShown())
        self.assertIn("Empieza solo con el primer botín", self.T.BoxTexts())
        self.assertIn("Paño de lino ×0", self.T.BoxTexts())
        # El macro se crea con el bicho del catálogo y el botón cambia.
        self.assertEqual(self.mock.macros[1].name, "PG Objetivo")
        self.assertEqual(self.mock.macros[1].body, "/cleartarget\n/tar Arpía\n/cleartarget [dead]")
        self.assertTrue(self.mock.ClickButton("Quitar de activos"))
        self.assertFalse(self.T.IsActive("baldios-arpias"))
        self.assertEqual(self.mock.macros[1].body, "/pg objetivo")

    def test_el_primer_botin_pone_en_marcha_el_reloj_y_cuenta_lo_suyo(self):
        self.activate_from_window("farms", 1)
        self.mock.Loot(0, 10, 2589, 3)     # paño de lino: es de las arpías
        self.mock.Loot(0, 11, 2770, 2)     # mineral de cobre: no
        self.mock.AddMoney(250)            # monedas: este farmeo las da
        self.mock.Advance(1)
        f = self.farm("baldios-arpias")
        self.assertIsNotNone(f.started)
        self.assertEqual(dict(f["items"].items()), {2589: 3})
        self.assertEqual(f.money, 250)
        texts = self.T.BoxTexts()
        self.assertIn("Paño de lino ×3", texts)
        self.assertNotIn("Mineral de cobre", texts)
        # Lo farmeado queda apuntado con su id para que el motor lo mida.
        labels = {b.label for b in self.lua.globals().PitiGoldsDB.farmLog.values()}
        self.assertIn("baldios-arpias", labels)

    def test_parar_reiniciar_y_acabar(self):
        self.activate_from_window("farms", 1)
        self.T.StartStop("baldios-arpias")
        self.mock.Advance(90)
        self.T.StartStop("baldios-arpias")   # parado
        self.mock.Advance(600)
        f = self.farm("baldios-arpias")
        self.assertEqual(self.T.Elapsed(f), 90)
        self.mock.Loot(0, 10, 2589, 1)       # en pausa no cuenta
        self.mock.Advance(1)
        self.assertIsNone(f["items"][2589])
        self.T.StartStop("baldios-arpias")
        self.mock.Loot(0, 10, 2589, 4)
        self.mock.Advance(1)
        self.T.Reset("baldios-arpias")
        self.assertEqual((self.T.Elapsed(f), f["items"][2589]), (0, None))
        self.mock.Loot(0, 10, 2589, 2)
        self.mock.Advance(60)
        self.T.Finish("baldios-arpias")
        self.assertFalse(self.T.IsActive("baldios-arpias"))
        self.assertIn("Arpías: ", self.mock.chat[len(self.mock.chat)])

    def test_sigue_tras_un_reload_sin_contar_el_rato_fuera(self):
        self.activate_from_window("farms", 1)
        self.T.StartStop("baldios-arpias")
        self.mock.Advance(100)
        self.T.OnLogout()
        self.mock.Advance(50)
        self.T.OnLogin()
        f = self.farm("baldios-arpias")
        self.assertIsNotNone(f.started)
        self.mock.Advance(10)
        self.assertEqual(self.T.Elapsed(f), 110)
        self.T.OnLogout()
        self.mock.Advance(3600)              # una hora fuera: queda en pausa
        self.T.OnLogin()
        self.assertIsNone(f.started)
        self.assertEqual(self.T.Elapsed(f), 110)

    def test_crafteo_con_los_materiales_que_tienes(self):
        self.activate_from_window("crafts", 1)
        texts = self.T.BoxTexts()
        self.assertIn("Puedes fabricar |cffffd1000|r de 2", texts)
        self.assertIn("Barra de cobre |cffff40400/12|r", texts)   # 10 en el banco no valen
        self.assertIn("Flujo débil |cffff40400/2|r", texts)
        self.mock.Loot(0, 12, 2840, 12)
        self.mock.Loot(0, 13, 2880, 1)
        self.mock.Advance(1)
        texts = self.T.BoxTexts()
        self.assertIn("Barra de cobre |cff33dd3312/12|r", texts)
        self.assertIn("Flujo débil |cffffd11a1/2|r", texts)
        self.assertIn("Puedes fabricar |cffffd1001|r de 2", texts)
        self.T.ToggleOpen("receta:1002")
        self.assertIn("En el banco: Barra de cobre ×10", self.T.BoxTexts())
        self.T.SetCrafts("receta:1002", 1)
        self.assertIn("Barra de cobre |cffffd11a12/18|r", self.T.BoxTexts())
        self.lua.execute("Mock.bags[0][12] = nil; Mock.bags[0][13] = nil")

    def test_calavera_sobre_los_bichos_del_farmeo(self):
        self.activate_from_window("farms", 1)
        self.mock.AddPlate("nameplate1", self.lua.eval('{ name = "Arpía Alabruja", guid = "Creature-0-1-0-1-3276-01" }'))
        self.mock.AddPlate("nameplate2", self.lua.eval('{ name = "Jabalí", guid = "Creature-0-1-0-1-3099-02" }'))
        self.assertEqual(self.mock.MarkedPlates(), 1)
        self.mock.RemovePlate("nameplate1")
        self.assertEqual(self.mock.MarkedPlates(), 0)

    def test_aprende_el_bicho_al_lootear_y_lo_anade_al_macro(self):
        self.activate_from_window("farms", 1)    # arpías
        self.activate_from_window("farms", 2)    # cobre: sin bichos en el catálogo
        self.T.StartStop("cobre")
        self.lua.execute("""
          Mock.units.target = { name = "Peón de Ventura", guid = "Creature-0-1-0-1-3284-0002" }
          Mock.loot = { { itemID = 2770, sources = { "Creature-0-1-0-1-3284-0002", 1 } } }
        """)
        self.mock.Fire("LOOT_OPENED")
        self.assertEqual(self.farm("cobre").mobs[3284], "Peón de Ventura")
        self.assertEqual(self.mock.macros[1].body,
                         "/cleartarget\n/tar Arpía\n/tar [noexists] Peón de Ventura\n/cleartarget [dead]")
        # Si el de la segunda línea está a la vista, va primero.
        self.mock.AddPlate("nameplate3", self.lua.eval('{ name = "Peón de Ventura", guid = "Creature-0-1-0-1-3284-0003" }'))
        self.mock.Advance(2)
        self.assertTrue(self.mock.macros[1].body.startswith("/cleartarget\n/tar Peón de Ventura\n"))
        # Lo que suelta otro bicho que empieza como uno del catálogo no hace falta apuntarlo.
        self.lua.execute("""
          Mock.units.target = { name = "Arpía Alabruja", guid = "Creature-0-1-0-1-3276-0004" }
          Mock.loot = { { itemID = 2589, sources = { "Creature-0-1-0-1-3276-0004", 1 } } }
        """)
        self.T.StartStop("baldios-arpias")
        self.mock.Fire("LOOT_OPENED")
        self.assertIsNone(self.farm("baldios-arpias").mobs[3276])

    def test_anadir_y_quitar_el_objetivo(self):
        self.activate_from_window("farms", 2)
        self.lua.execute('Mock.units.target = { name = "Kobold", guid = "Creature-0-1-0-1-40-0001" }')
        self.T.ToggleOpen("cobre")
        self.assertTrue(self.mock.ClickButton("Añadir objetivo"))
        self.assertEqual(self.farm("cobre").mobs[40], "Kobold")
        self.assertIn("Bichos: Kobold", self.T.BoxTexts())
        self.assertTrue(self.mock.ClickButton("Quitar objetivo"))
        self.assertIsNone(self.farm("cobre").mobs[40])

    def test_flecha(self):
        A = self.ns.Arrow
        self.activate_from_window("farms", 1)
        # El centro de Los Baldíos está 1000 m al sur: mirando al norte, la flecha apunta atrás.
        state = A.Compute(self.lua.eval("{ map = 1413, x = 0.5, y = 0.5 }"))
        self.assertAlmostEqual(state.distance, 1000)
        self.assertAlmostEqual(state.angle, math.pi)
        self.lua.execute("Mock.facing = math.pi")
        state = A.Compute(self.lua.eval("{ map = 1413, x = 0.5, y = 0.5 }"))
        self.assertAlmostEqual(state.angle, 0)
        self.lua.execute("Mock.facing = math.pi / 2")    # mirando al oeste: el sur queda a la izquierda
        state = A.Compute(self.lua.eval("{ map = 1413, x = 0.5, y = 0.5 }"))
        self.assertAlmostEqual(state.angle, math.pi / 2)
        self.lua.execute("Mock.facing = 0")
        self.assertIn("Arpías\n1000 m", A.Text())
        # Solo la zona: dentro de ella, avisa.
        self.assertEqual(A.Compute(self.lua.eval("{ map = 1411 }")).text, "Estás en Durotar")


class Contabilidad(unittest.TestCase):
    """Comprar lingotes, fabricar hachas, ponerlas a la venta y cobrar: todo queda apuntado."""

    @classmethod
    def setUpClass(cls):
        cls.lua = lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = cls.mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        lua.execute("PitiGoldsDB = nil; Mock.commodityPrices[2840] = 300")
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        mock.Advance(10)
        mock.Fire("MERCHANT_SHOW")  # el flujo débil cuesta 100 en el vendedor
        mock.Advance(1)
        mock.Fire("MERCHANT_CLOSED")

        mock.Fire("AUCTION_HOUSE_SHOW")
        lua.execute("C_AuctionHouse.StartCommoditiesPurchase(2840, 12)")
        mock.Advance(1)
        lua.execute("C_AuctionHouse.ConfirmCommoditiesPurchase(2840, 12)")
        mock.Advance(119)
        mock.Fire("AUCTION_HOUSE_CLOSED")

        mock.Fire("TRADE_SKILL_SHOW")
        mock.Advance(3)
        for _ in range(2):
            mock.Fire("UNIT_SPELLCAST_SUCCEEDED", "player", "guid", 1002)
        mock.Fire("UNIT_SPELLCAST_SUCCEEDED", "target", "guid", 1002)  # no es tuyo
        mock.Advance(57)
        mock.Fire("TRADE_SKILL_CLOSE")

        mock.Fire("AUCTION_HOUSE_SHOW")
        lua.execute("C_AuctionHouse.PostItem({ itemID = 2845 }, 1, 1, 0, 5000)")
        lua.execute("C_AuctionHouse.PostItem({ itemID = 2845 }, 1, 1, 0, 5000)")
        mock.Advance(30)
        mock.Fire("AUCTION_HOUSE_CLOSED")

        lua.execute('Mock.inbox = { { sender = "Casa de subastas", subject = "Subasta exitosa", money = 4800, '
                    'invoice = { type = "seller", itemName = "Hacha de cobre", bid = 5000, deposit = 50, '
                    'cut = 250, count = 1 } } }')
        mock.Fire("MAIL_SHOW")
        mock.Advance(2)
        lua.execute("TakeInboxMoney(1); AutoLootMailItem(1)")  # el mismo correo: una sola venta
        mock.Advance(28)
        mock.Fire("MAIL_CLOSED")
        cls.events = list(lua.globals().PitiGoldsDB.ledger.values())

    def of(self, kind):
        return [e for e in self.events if e.type == kind]

    def test_compra_de_materiales(self):
        (buy,) = self.of("buy")
        self.assertEqual((buy.itemID, buy.qty, buy.money), (2840, 12, 3600))

    def test_crafteos_y_lo_puesto_a_la_venta(self):
        crafts = self.of("craft")
        self.assertEqual([(c.recipeID, c.itemID) for c in crafts], [(1002, 2845), (1002, 2845)])
        posts = self.of("post")
        self.assertEqual([(p.itemID, p.qty, p.unit, p.deposit) for p in posts], [(2845, 1, 5000, 50)] * 2)

    def test_venta_por_correo_una_sola_vez(self):
        (sale,) = self.of("sale")
        self.assertEqual((sale.itemName, sale.money, sale.cut, sale.deposit), ("Hacha de cobre", 5000, 250, 50))

    def test_tiempo_de_gestion(self):
        seconds = {}
        for e in self.of("time"):
            seconds[e.kind] = seconds.get(e.kind, 0) + e.seconds
        self.assertEqual(seconds, {"subasta": 150, "profesion": 60, "correo": 30})

    def test_beneficio_en_el_motor(self):
        saved = self.mock.Serialize("PitiGoldsDB", self.lua.globals().PitiGoldsDB)
        with tempfile.TemporaryDirectory() as tmp:
            sv = Path(tmp) / "PitiGolds.lua"
            sv.write_text(saved, encoding="utf-8")
            conn = dbmod.connect(Path(tmp) / "p.db")
            self.assertEqual(ingest_file(conn, "TEST#1", sv).ledger_events, len(self.events))
            self.assertEqual(ingest_file(conn, "TEST#1", sv).ledger_events, 0)  # no se duplica
            a = analyze(conn)
            items = {e.name: e for e in a.business.items}
            axe = items["Hacha de cobre"]
            self.assertEqual(axe.origin, "fabricado")
            self.assertEqual((axe.crafted, axe.posted, axe.sold), (2, 2, 1))
            # 6 lingotes a lo que te costaron (300) + flujo del vendedor (100).
            self.assertEqual(axe.unit_cost, 1900)
            self.assertEqual(axe.deposits_lost, 50)
            self.assertEqual(axe.profit, 5000 - 250 - 1900 - 50)
            self.assertEqual(items["Barra de cobre"].origin, "material")
            self.assertAlmostEqual(axe.seconds, 240)  # todo el tiempo de gestión es del hacha
            self.assertEqual(a.business.per_hour, round(2800 / (240 / 3600)))
            self.assertIn("Tu negocio en la subasta", build_advice_report(conn, a))
            conn.close()


class VendedorQueCambia(unittest.TestCase):
    """Si un vendedor deja de vender algo, se borra; lo de otros vendedores se queda."""

    def test_se_borra_lo_que_ya_no_vende(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        lua.execute("PitiGoldsDB = nil")
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        mock.Advance(10)

        def visit(npc, items_lua):
            lua.execute(f'Mock.merchant.npc = "{npc}"; Mock.merchant.items = {items_lua}')
            mock.Fire("MERCHANT_SHOW")
            mock.Advance(1)
            mock.Fire("MERCHANT_CLOSED")

        visit("Grimtak", '{ { itemID = 2880, name = "Flujo débil", price = 100 }, '
                         '{ itemID = 2320, name = "Hilo grueso", price = 10 } }')
        visit("Otro", '{ { itemID = 2321, name = "Hilo fino", price = 50 } }')
        visit("Grimtak", '{ { itemID = 2880, name = "Flujo débil", price = 100 } }')  # tras un parche

        vendor = lua.globals().PitiGoldsDB.vendorItems
        self.assertEqual(vendor[2880].vendor, "Grimtak")
        self.assertIsNone(vendor[2320])
        self.assertEqual(vendor[2321].vendor, "Otro")
        self.assertEqual(vendor[2880].char, "Brujo-Dio")
