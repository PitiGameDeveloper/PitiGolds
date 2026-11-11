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
# Lo que tiene el personaje del escenario de Barra de cobre: 10 en el banco.
TIENES = "Tienes: = 10 |cffcccccc(banco)|r"
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


class PasosDeUnCrafteoConPerdida(unittest.TestCase):
    def test_avisa_de_la_perdida(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        steps = lua.eval('''(function()
          local base = { name = "Madeja", recipe = 1, knownBy = { "Brujo-Dio" }, reagents = {} }
          local loss = setmetatable({ profit = -2 }, { __index = base })
          local gain = setmetatable({ profit = 2 }, { __index = base })
          return { (Mock.ns.Methods.CraftSteps(loss))[1], (Mock.ns.Methods.CraftSteps(gain))[1] }
        end)()''')
        self.assertEqual(steps[1], "Ahora mismo da pérdida (-2c por unidad): no lo fabriques para vender.")
        self.assertTrue(steps[2].startswith("Hoy: 1 × Madeja"))


class TooltipVentaYSubasta(unittest.TestCase):
    def setUp(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        self.mock = lua.globals().Mock
        self.lua = lua
        self.mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        # Barra de cobre: 3p en subasta y 10c en el vendedor. Ojo de tigre: 1p 40c y 1p 50c.
        lua.execute('PitiGoldsGenerated = { prices = { [2840] = "300,,", [818] = "140,140," } }')

    def test_quita_la_linea_del_juego_y_pone_venta(self):
        tooltip = self.mock.Tooltip(2840, 1, 10)
        self.assertNotIn("Precio de venta", tooltip)
        self.assertEqual(tooltip.split("\n"), ["Venta: = 10c", "[verde] Subasta: = 3p 0c", TIENES])

    def test_por_unidad_y_por_el_monton(self):
        tooltip = self.mock.Tooltip(2840, 5, 50)
        self.assertIn("Venta: = 50c |cffcccccc(10c)|r", tooltip)
        self.assertIn("[verde] Subasta: = 15p 0c |cffcccccc(3p 0c)|r", tooltip)

    def test_el_monton_sale_del_precio_del_juego(self):
        tooltip = self.mock.Tooltip(2840, None, 70)
        self.assertIn("21p 0c |cffcccccc(3p 0c)|r", tooltip)

    def test_verde_al_vendedor_si_la_subasta_deja_menos(self):
        # 1p 40c menos el 5 % de comisión no llega al 1p 50c del vendedor.
        tooltip = self.mock.Tooltip(818, 1, 150)
        self.assertEqual(tooltip.split("\n"), ["[verde] Venta: = 1p 50c", "Subasta: = 1p 40c"])

    def test_sin_precio_de_venta_solo_subasta(self):
        self.assertEqual(self.mock.Tooltip(2840, 3), "Subasta: = 9p 0c |cffcccccc(3p 0c)|r\n" + TIENES)

    def test_muestra_las_ventas_diarias_si_el_motor_las_tiene(self):
        self.lua.execute('PitiGoldsGenerated = { prices = { [2840] = "300,,,4.5", [818] = "140,140,s," } }')
        self.assertIn("|cffccccccventas/día: 4.5|r", self.mock.Tooltip(2840, 1, 10))
        # Sin ventas en el dato no sale la línea.
        self.assertNotIn("ventas/día", self.mock.Tooltip(818, 1, 150))

    def test_sale_aunque_el_cliente_no_llame_a_los_post_calls(self):
        tooltip = self.mock.Tooltip(2840, 1, 10, True)
        self.assertEqual(tooltip.split("\n"), ["Venta: = 10c", "[verde] Subasta: = 3p 0c", TIENES])

    def test_pasar_el_raton_otra_vez_no_repite_ni_pierde_lineas(self):
        for _ in range(3):
            self.assertEqual(self.mock.Tooltip(2840, 1, 10).split("\n"), ["Venta: = 10c", "[verde] Subasta: = 3p 0c", TIENES])
            self.assertEqual(self.mock.Tooltip(2840, 3), "Subasta: = 9p 0c |cffcccccc(3p 0c)|r\n" + TIENES)
            self.assertEqual(self.mock.Tooltip(2840, 3), "Subasta: = 9p 0c |cffcccccc(3p 0c)|r\n" + TIENES)


class IconosDeMoneda(unittest.TestCase):
    def test_en_el_juego_salen_los_iconos(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        lua.execute("Mock.ns.coinIcons = nil")
        mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        text = mock.ns.Money(12345)
        self.assertTrue(text.startswith("1|TInterface\\MoneyFrame\\UI-GoldIcon"), text)
        self.assertIn("23|TInterface\\MoneyFrame\\UI-SilverIcon", text)
        self.assertIn("45|TInterface\\MoneyFrame\\UI-CopperIcon", text)


class SubastaEnVivoYCompra(unittest.TestCase):
    """Lo que ves buscando en la subasta, la lista de la compra y lo nuevo del tooltip."""

    def setUp(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        lua.execute('''
          PitiGoldsGenerated = {
            prices = { [2840] = "300,,", [2845] = "5000,,", [10940] = "10,,", [10939] = "200,,", [10978] = "500,," },
            recipes = { [1002] = "1900,2750" },
            recipeParts = { [1002] = "2845,1,4650,18,100|2840:6:300:;2880:1:100:100" },
          }
          Mock.commodity = { [2840] = { { unitPrice = 400, quantity = 30 }, { unitPrice = 450, quantity = 20 } } }
          C_AuctionHouse.GetNumCommoditySearchResults = function(id) return #(Mock.commodity[id] or {}) end
          C_AuctionHouse.GetCommoditySearchResultInfo = function(id, i) return Mock.commodity[id][i] end
          AuctionHouseFrame = { CommoditiesBuyFrame = {
            SetItemIDAndPrice = function() end,
            IsShown = function() return true end,
            BuyDisplay = { SetQuantitySelected = function(_, q) Mock.buyQuantity = q end },
          } }''')
        self.lua, self.mock = lua, mock

    def last_scan(self):
        return self.lua.eval("PitiGoldsDB.scans[#PitiGoldsDB.scans]")

    def test_apunta_lo_que_buscas_y_lo_usa_al_momento(self):
        mock = self.mock
        mock.Fire("AUCTION_HOUSE_SHOW")
        mock.Fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2840)
        mock.Advance(1)
        scan = self.last_scan()
        self.assertEqual(scan["type"], "search")
        self.assertEqual(scan["items"][2840], "400,50,2|400:30;450:20")
        # El tooltip ya enseña el precio nuevo (media del 15 % más barato: 400).
        self.assertIn("Subasta: = 4p 0c", mock.Tooltip(2840, 1, 10))
        # Y la receta se recalcula: 6 × 4p + 1p de flujo = 25p; 46p 50c - 25p = 21p 50c.
        self.assertEqual(mock.ns.CraftInfoText(1002),
                         "Fabricar: |cffffffff25p 0c|r\nGanancia: |cff40ff4021p 50c|r"
                         "\n|cff999999con lo que acabas de ver en la subasta|r")
        # Una lista de resultados después no pisa la lista entera del objeto.
        self.lua.execute('''Mock.browseData[99] = { { itemKey = { itemID = 2840 }, minPrice = 100, totalQuantity = 5 },
                                                    { itemKey = { itemID = 2880 }, minPrice = 90, totalQuantity = 7 } }
                            C_AuctionHouse.SendBrowseQuery({ itemClassFilters = { { classID = 99 } } })''')
        mock.Advance(2)
        scan = self.last_scan()
        self.assertEqual(scan["items"][2840], "400,50,2|400:30;450:20")
        self.assertEqual(scan["items"][2880], "90,7")
        # Una visita, un escaneo de búsquedas.
        self.assertEqual(self.lua.eval('(function() local n = 0 for _, s in ipairs(PitiGoldsDB.scans) do '
                                       'if s.type == "search" then n = n + 1 end end return n end)()'), 1)

    def test_sin_nada_nuevo_la_receta_es_la_del_motor(self):
        self.assertEqual(self.mock.ns.CraftInfoText(1002),
                         "Fabricar: |cffffffff19p 0c|r\nGanancia: |cff40ff4027p 50c|r")

    def test_marca_lo_que_falta_por_el_multiplicador(self):
        mock = self.mock
        mock.Fire("AUCTION_HOUSE_SHOW")
        mock.ns.SearchRecipeReagents(1002)
        # 6 barras por hacha y ya tiene 10 en el banco.
        self.assertEqual(mock.ns.ShoppingQuantity(2840), (0, 10))
        mock.ns.SetCraftCount(3)
        self.assertEqual(mock.ns.ShoppingQuantity(2840), (8, 10))
        self.assertEqual(mock.ns.ShoppingQuantity(2880), (3, 0))
        self.assertIsNone(mock.ns.ShoppingQuantity(2589))  # opcional: no se compra
        self.lua.execute("AuctionHouseFrame.CommoditiesBuyFrame:SetItemIDAndPrice(2880, 100)")
        mock.Advance(1)
        self.assertEqual(self.lua.eval("Mock.buyQuantity"), 3)
        mock.ns.SetCraftCount(5)
        self.assertEqual(self.lua.eval("Mock.buyQuantity"), 5)
        self.assertIn("Flujo débil: marcados 5 para 5 fabricaciones.", "\n".join(mock.chat.values()))

    def test_cuantos_tienes_y_tus_otros_personajes(self):
        self.lua.execute('''
          local key = "Alter-" .. Mock.ns.charKey:match("%-(.+)$")
          PitiGoldsDB.characters[key] = { name = "Alter", inventory = {
            bags = { items = { [2840] = 4 } }, mail = { items = { [2840] = 1 } } } }''')
        lines = self.mock.Tooltip(2840).split("\n")
        self.assertEqual(lines[-3:], ["Tienes: = 15", "   Banco = 10", "   Alter = 5"])

    def test_valor_de_desencantar(self):
        self.lua.execute('''
          local getInfo = C_Item.GetItemInfo
          C_Item.GetItemInfo = function(id)
            if id == 7000 then return "Botas verdes", nil, 2, 20, 15, nil, nil, 1, "INVTYPE_FEET", nil, 50, 4 end
            return getInfo(id)
          end''')
        lines = self.mock.Tooltip(7000).split("\n")
        # 75 % × 2,5 × 10c + 20 % × 1,5 × 2p + 5 % × 5p = 1p 3,75c
        self.assertEqual(lines[0], "Desencantar: = ~1p 4c")
        self.assertEqual(lines[1], "   objeto 10940 x2-3 |cff999999(75 %)|r = 10c")
        self.assertEqual(lines[2], "   objeto 10939 x1-2 |cff999999(20 %)|r = 2p 0c")
        self.assertEqual(lines[3], "   objeto 10978 x1 |cff999999(5 %)|r = 5p 0c")
        # Lo que no es arma ni armadura no se desencanta.
        self.assertNotIn("Desencantar", self.mock.Tooltip(2840))

    def test_oro_de_la_cuenta(self):
        self.lua.execute('''
          local key = "Alter-" .. Mock.ns.charKey:match("%-(.+)$")
          PitiGoldsDB.characters[key] = { name = "Alter", money = 20000 }
          Mock.goldLines = {}
          Mock.ns.AddGoldLines({ AddDoubleLine = function(_, l, r) table.insert(Mock.goldLines, l .. " = " .. r) end })''')
        lines = list(self.lua.eval("Mock.goldLines").values())
        me = self.mock.ns.charKey.split("-")[0]
        money = self.lua.eval("GetMoney()")
        total = money + 20000 + 500000
        self.assertEqual(lines[0], "Oro de la cuenta = " + self.mock.ns.Money(total))
        self.assertIn("   Alter = 2o 0p 0c", lines)
        self.assertIn(f"   {me} = " + self.mock.ns.Money(money), lines)
        self.assertEqual(lines[-1], "   Banco de banda = 50o 0p 0c")


class FiltroDeProfesiones(unittest.TestCase):
    CRAFTS = """PitiGoldsGenerated = { methods = { farms = {}, crafts = {
      { recipe = 1, name = "Camisa", prof = "Costura", profit = 50, reagents = {}, output = 10, color = "verde" },
      { recipe = 2, name = "Hacha", prof = "Herrería", profit = -5, reagents = {}, output = 20, color = "rojo" },
      { recipe = 3, name = "Encantar capa", prof = "Encantamiento", reagents = {}, color = "rojo" },
      { recipe = 4, name = "Pantalón", prof = "Costura", reagents = {}, output = 40, color = "rojo" },
    } } }"""

    def setUp(self):
        self.lua = lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        self.mock = mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        lua.execute(self.CRAFTS)
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        self.methods = mock.ns.Methods
        self.methods.Open("crafts")

    def char(self):
        return self.lua.globals().PitiGoldsDB.characters["Brujo-Dio"]

    def test_sin_registro_salen_todas(self):
        self.assertEqual(self.methods.RowCount(), 4)
        self.assertIsNone(self.char().craftFilter["Costura"])

    def test_un_boton_por_profesion(self):
        self.assertEqual(list(self.methods.Professions().values()), ["Costura", "Encantamiento", "Herrería"])
        self.assertTrue(self.mock.ClickButton("Costura"))
        self.assertEqual(self.methods.RowCount(), 2)
        self.assertTrue(self.char().craftFilter["Costura"])
        self.assertTrue(self.mock.ClickButton("Costura"))
        self.assertEqual(self.methods.RowCount(), 4)
        self.assertIsNone(self.char().craftFilter["Costura"])

    def test_todas_y_ninguna(self):
        self.assertTrue(self.mock.ClickButton("Ninguna"))
        self.assertEqual(self.methods.RowCount(), 0)
        self.assertTrue(self.mock.ClickButton("Herrería"))
        self.assertEqual(self.methods.RowCount(), 1)
        self.assertTrue(self.mock.ClickButton("Todas"))
        self.assertEqual(self.methods.RowCount(), 4)

    def test_cada_personaje_recuerda_lo_suyo(self):
        self.mock.ClickButton("Herrería")
        self.lua.execute('PitiGoldsDB.characters["Otro-Dio"] = { craftFilter = { Costura = true } }')
        # Otro personaje: su filtro es el suyo, y al volver sigue el primero.
        self.lua.execute('Mock.ns.charKey = "Otro-Dio"')
        self.methods.Open("crafts")
        self.assertEqual(self.methods.RowCount(), 2)
        self.lua.execute('Mock.ns.charKey = "Brujo-Dio"')
        self.methods.Open("crafts")
        self.assertEqual(self.methods.RowCount(), 3)

    def test_las_recetas_sin_precio_van_al_final_al_ordenar(self):
        self.lua.execute('''for i, row in ipairs(PitiGoldsGenerated.methods.crafts) do row.details = { "D" .. i } end
          for _, f in ipairs(Mock.frames) do
            if f.key == "profit" and f.scripts.OnClick then f.scripts.OnClick(f) end
          end''')
        order = []
        for index in range(1, 5):
            self.methods.Select(index)
            order.append(self.methods.DetailText().rsplit("\n", 1)[-1])
        self.assertEqual(order[:2], ["D1", "D2"])          # 50 c y -5 c
        self.assertEqual(sorted(order[2:]), ["D3", "D4"])  # sin precio

    def test_lo_que_no_fabrica_un_objeto_no_se_pone_en_la_subasta(self):
        steps = self.lua.eval('''(function()
          local row = PitiGoldsGenerated.methods.crafts[3]
          row.knownBy = { "Brujo-Dio" }
          local list = Mock.ns.Methods.CraftSteps(row)
          return list[#list]
        end)()''')
        self.assertEqual(steps, "Fabrica x1 Encantar capa con Brujo.")


class Instructores(unittest.TestCase):
    def setUp(self):
        self.lua = lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        self.mock = mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        lua.execute('''Mock.trainer.services = {
          { name = "Sastrería", kind = "header" },
          { name = "Camisa", kind = "unavailable", skill = "Costura", rank = 150, level = 20, cost = 5000 },
          { name = "Toga", kind = "available", skill = "Costura", rank = 75, level = 10, cost = 900 },
          { name = "Trapo", kind = "available", level = 5, cost = 10 },
        }''')

    def test_apunta_tambien_lo_que_aun_no_puedes_aprender(self):
        self.mock.Fire("TRAINER_SHOW")
        self.mock.Advance(1)
        costura = self.lua.globals().PitiGoldsDB.trainerRecipes["Costura"]
        self.assertEqual((costura["Camisa"].rank, costura["Camisa"].level, costura["Camisa"].cost), (150, 20, 5000))
        self.assertEqual(costura["Toga"].rank, 75)
        self.assertEqual(costura["Trapo"].rank, 0)        # no pide nivel de profesión
        self.assertIsNone(costura["Sastrería"])
        # La ventana se queda con los filtros que tenía.
        self.assertFalse(self.mock.trainer.filters["unavailable"])

    def test_llega_al_motor(self):
        self.mock.Fire("TRAINER_SHOW")
        self.mock.Advance(1)
        saved = self.mock.Serialize("PitiGoldsDB", self.lua.globals().PitiGoldsDB)
        with tempfile.TemporaryDirectory() as tmp:
            sv = Path(tmp) / "PitiGolds.lua"
            sv.write_text(saved, encoding="utf-8")
            conn = dbmod.connect(Path(tmp) / "p.db")
            ingest_file(conn, "CUENTA", sv)
            row = conn.execute("SELECT rank, level, cost FROM trainer_recipes "
                               "WHERE skill_name = 'Costura' AND name = 'Camisa'").fetchone()
            self.assertEqual(tuple(row), (150, 20, 5000))
            conn.close()


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
            self.assertIn('[2589] = "40,,,"', content)
            self.assertIn('[2845] = "1900,2750",', content)

            # Al recargar, el addon carga Generated.lua y borra lo que el motor ya tiene.
            lua.execute(f'dofile("{generated.as_posix()}")')
            mock.ns.PruneScans()
            self.assertEqual(len(lua.globals().PitiGoldsDB.scans), 0)

            tooltip = mock.Tooltip(2840)
            self.assertIn("Subasta: = 3p 0c", tooltip)
            self.assertIn("PitiGolds fabricar = 1p 20c  |cff40ff40+1p 60c|r", tooltip)
            self.assertEqual(mock.Tooltip(123456), "")

            # Ventana de profesión: coste y ganancia de la receta elegida, bajo los materiales.
            self.assertIn('[1002] = "1900,2750",', content)
            # Y su desglose, para recalcularla en el juego con lo que se vea en la subasta.
            self.assertIn('[1002] = "2845,1,4650,18,100|2840:6:300:;2880:1:100:100",', content)
            lua.execute('''
              local form = Mock.NewFrame()
              form.Reagents = Mock.NewFrame()
              form.Init = function(self, recipe) self.recipe = recipe end
              form.GetRecipeInfo = function(self) return self.recipe end
              form.CreateFontString = function(self) self.info = Mock.NewFrame(); return self.info end
              ProfessionsFrame = { CraftingPage = { SchematicForm = form } }
              Mock.form = form''')
            mock.Fire("ADDON_LOADED", "Blizzard_Professions")
            lua.execute("Mock.form:Init({ recipeID = 1002 })")
            info = mock.form.info
            self.assertTrue(info.shown, "\n".join(mock.chat.values()))
            self.assertEqual(info.text, "Fabricar: |cffffffff19p 0c|r\nGanancia: |cff40ff4027p 50c|r")
            self.assertTrue(lua.eval("Mock.form.info.point[2] == Mock.form.Reagents"))

            # Buscar con la subasta cerrada: se queda preparado y se lanza al abrirla.
            mock.Fire("AUCTION_HOUSE_CLOSED")
            self.assertTrue(mock.ClickButton("Buscar"))
            self.assertIn("abre la subasta y buscaré Hacha de cobre, Barra de cobre, Flujo débil.", "\n".join(mock.chat.values()))
            self.assertEqual(len(mock.itemKeySearches), 0)
            mock.Fire("AUCTION_HOUSE_SHOW")
            mock.Advance(1)
            self.assertEqual(list(mock.itemKeySearches[1].values()), [2845, 2840, 2880])
            self.assertTrue(mock.ClickButton("Buscar"))  # con la subasta abierta, al momento
            self.assertEqual(len(mock.itemKeySearches), 2)
            mock.Fire("AUCTION_HOUSE_CLOSED")

            lua.execute("Mock.form:Init({ recipeID = 999999 })")
            self.assertFalse(info.shown)

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
        mock.Advance(3)   # pasado el margen tras cerrar el correo
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
        mock.Advance(3)   # pasado el margen tras cerrar el correo
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
        # Escaneo completo: el mercado es la media del 1 % más barato, mínimo 5 unidades
        # (2 a 100 c y 3 a 120 c: 112 c, que se quedan en 101 sin comisión ni depósito).
        self.lua.execute('Mock.ns.AddScan({ time = time(), items = { [2770] = "100,10,2,2|100:2;120:8" } })')
        self.assertEqual(self.value(2770), (101, "escaneo"))
        self.mock.Advance(5)
        # Un mínimo suelto más barato justo después no rebaja el escaneo completo: puede ser cebo.
        self.lua.execute('Mock.ns.AddScan({ time = time(), items = { [2770] = "50,5" } })')
        self.assertEqual(self.value(2770), (101, "escaneo"))
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


class SesionSinComprasNiConjuros(unittest.TestCase):
    """No cuenta lo comprado que llega tras cerrar el vendedor ni lo que crea un hechizo de clase."""

    def setUp(self):
        self.lua = lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = self.mock = lua.globals().Mock
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        lua.execute("PitiGoldsDB = nil")
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        mock.Advance(10)

    def session(self):
        s = self.lua.globals().PitiGoldsDB.characters["Brujo-Dio"].session
        return dict(s["items"].items()), s.money

    def test_compra_que_llega_tras_cerrar_el_vendedor(self):
        self.mock.Fire("MERCHANT_SHOW")
        self.mock.Advance(1)
        self.mock.Fire("MERCHANT_CLOSED")
        self.mock.Loot(0, 5, 1708, 20)   # el néctar llega justo después de cerrar
        self.mock.AddMoney(300)          # y lo vendido, también
        self.mock.Advance(3)
        self.mock.Loot(0, 6, 2770, 2)    # pasado el margen, lo looteado sí cuenta
        self.mock.AddMoney(50)
        self.mock.Advance(1)
        self.assertEqual(self.session(), ({2770: 2}, 50))

    def test_lo_que_crea_el_brujo_no_es_botin(self):
        self.mock.Loot(0, 5, 6265, 3)    # Fragmento de alma
        self.mock.Loot(0, 6, 5511, 1)    # Piedra de salud inferior
        self.mock.Loot(0, 7, 2770, 1)
        self.mock.Advance(1)
        self.assertEqual(self.session()[0], {2770: 1})


ACTIVE_METHODS = """
PitiGoldsDB = nil
Mock.NewWorldMap()
PitiGoldsGenerated = {
  prices = { [2770] = "200,,", [2589] = "40,," },
  methods = {
    verdict = { state = "mejor", title = "Arpías", lines = {}, best = "baldios-arpias" },
    farms = {
      { key = "baldios-arpias", name = "Arpías", kind = "farmeo", gph = 20000, items = { 2589 }, coins = true,
        point = { map = 1413, x = 0.5, y = 0.5 }, mobs = { "Arpía" }, zone = "Los Baldíos", details = {}, req = "",
        spawns = "500,500;500,600", nodes = "250,750" },
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

    def unfold(self, key):
        """Despliega el recuadro de un farmeo (se queda como estaba en otras pruebas)."""
        texts = "\n" + self.T.BoxTexts()
        if f"\n+ {self.farm(key).name}\n" in texts:
            self.T.ToggleOpen(key)

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
        self.activate_from_window("farms", 1)    # arpías: de bichos (da monedas)
        self.activate_from_window("farms", 2)    # cobre: de recolectar
        self.mock.Loot(0, 10, 2589, 3)     # paño de lino: de las arpías
        self.mock.Loot(0, 11, 2770, 2)     # mineral de cobre: del cobre, y también cuenta en las arpías
        self.mock.AddMoney(250)            # monedas: solo las arpías las dan
        self.mock.Advance(1)
        # Un farmeo de bichos cuenta todo lo que sueltan (verdes, otra tela...), como la sesión.
        f = self.farm("baldios-arpias")
        self.assertIsNotNone(f.started)
        self.assertEqual(dict(f["items"].items()), {2589: 3, 2770: 2})
        self.assertEqual(f.money, 250)
        # Uno de recolectar, solo lo suyo.
        cobre = self.farm("cobre")
        self.assertEqual(dict(cobre["items"].items()), {2770: 2})
        self.assertEqual(cobre.money, 0)
        texts = self.T.BoxTexts()
        self.assertIn("Paño de lino ×3", texts)
        self.assertIn("Mineral de cobre ×2", texts)
        # Lo farmeado queda apuntado con sus ids (los dos van en marcha) para que el motor lo mida.
        labels = {b.label for b in self.lua.globals().PitiGoldsDB.farmLog.values()}
        self.assertIn("baldios-arpias+cobre", labels)

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

    def test_mapa_con_los_sitios_de_los_bichos(self):
        M = self.ns.Map
        self.lua.execute("PitiGoldsDB.spots = nil; WorldMapFrame.shown = true; WorldMapFrame.mapID = 1413")
        self.activate_from_window("farms", 1)    # arpías: dos sitios de bichos y una almeja
        pins = sorted((p.texture[-1], round(p.x), round(p.y)) for p in self.mock.MapPins().values())
        self.assertEqual(pins, [("3", 250, -750), ("8", 500, -600), ("8", 500, -500)])
        self.unfold("baldios-arpias")
        self.assertIn("En el mapa (M): 2 sitios de bichos, 1 de cosas del mapa", self.T.BoxTexts())
        # En el mapa del continente, Los Baldíos ocupan la mitad de abajo.
        self.lua.execute("WorldMapFrame.mapID = 1414")
        self.assertEqual(M.Refresh(), 3)
        ys = sorted(round(p.y) for p in self.mock.MapPins().values())
        self.assertEqual(ys, [-875, -800, -750])
        # En otro mapa no sale nada; con el mapa cerrado, tampoco.
        self.lua.execute("WorldMapFrame.mapID = 1411")
        self.assertEqual(M.Refresh(), 0)
        self.lua.execute("WorldMapFrame.shown = false; WorldMapFrame.mapID = 1413")
        self.assertEqual(M.Refresh(), 0)
        # La flecha lleva al sitio más cercano: estás en Durotar, 1000 m al norte del primero.
        f = self.farm("baldios-arpias")
        nearest = M.Nearest(f, self.T.Data(f))
        self.assertEqual((nearest.x, nearest.y, nearest.kind), (0.5, 0.5, "spawn"))

    def test_apunta_donde_matas_los_bichos_del_farmeo(self):
        M = self.ns.Map
        self.lua.execute("PitiGoldsDB.spots = nil; WorldMapFrame.shown = true; WorldMapFrame.mapID = 1413")
        self.activate_from_window("farms", 2)    # cobre: sin sitios de bichos
        self.unfold("cobre")
        self.assertIn("|cff999999En el mapa: solo la zona; apunto dónde matas sus bichos al lootearlos.|r",
                      self.T.BoxTexts())
        self.T.StartStop("cobre")
        self.addCleanup(self.lua.execute, "Mock.position = { 500, 4500 }; Mock.mapID = 1411; Mock.loot = {}")
        self.lua.execute("""
          Mock.mapID = 1413
          Mock.position = { -300, 4800 }    -- en Los Baldíos, en 0.2, 0.3
          Mock.units.target = { name = "Peón de Ventura", guid = "Creature-0-1-0-1-3284-0002" }
          Mock.loot = { { itemID = 2770, sources = { "Creature-0-1-0-1-3284-0002", 1 } } }
        """)
        self.mock.Fire("LOOT_OPENED")    # aprende el bicho y apunta el sitio
        spots = self.lua.eval("PitiGoldsDB.spots.cobre")
        self.assertEqual(len(spots), 1)
        self.assertEqual((spots[1].map, spots[1].x, spots[1].y), (1413, 0.2, 0.3))
        self.mock.Fire("LOOT_OPENED")    # el mismo sitio no se repite
        self.assertEqual(len(self.lua.eval("PitiGoldsDB.spots.cobre")), 1)
        # Un bicho que no es del farmeo no cuenta.
        self.lua.execute("""
          Mock.position = { -600, 4800 }
          Mock.units.target = { name = "Jabalí", guid = "Creature-0-1-0-1-3099-0003" }
          Mock.loot = { { sources = { "Creature-0-1-0-1-3099-0003", 1 } } }
        """)
        self.mock.Fire("LOOT_OPENED")
        self.assertEqual(len(self.lua.eval("PitiGoldsDB.spots.cobre")), 1)
        self.assertEqual([p.texture[-1] for p in self.mock.MapPins().values()], ["4"])
        self.assertIn("En el mapa (M): 1 donde has matado tú", self.T.BoxTexts())
        # La flecha lleva a ese sitio; /pg olvidar lo borra.
        f = self.farm("cobre")
        self.assertEqual(M.Nearest(f, self.T.Data(f)).kind, "seen")
        self.mock.Slash("olvidar cobre")
        self.assertIsNone(self.lua.eval("PitiGoldsDB.spots.cobre"))


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
