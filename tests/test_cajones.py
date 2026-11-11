"""Cajones saqueados: el favor de mercader más barato, en el motor y en la pestaña de la subasta."""

from __future__ import annotations

import unittest

from motor.cajones import Crate, CrateOption, crate_problems, crates_export, evaluate_crates, load_crates
from motor.generated import lua_value
from motor.pricing import ItemPrice

try:
    from lupa.lua51 import LuaRuntime
except ImportError:  # las del addon necesitan lupa (requirements-dev.txt)
    LuaRuntime = None


def crates() -> list[Crate]:
    return [
        Crate(1001, "Cajón saqueado: polvos", 5, options=[CrateOption(2001, 20, "Polvo"), CrateOption(2002, 4, "Esencia")]),
        Crate(1002, "Cajón saqueado: piezas", 20, estimated=True, options=[CrateOption(2003, 10, "Pieza")]),
        Crate(1003, "Cajón saqueado: sin precio", 10, options=[CrateOption(2001, 20, "Polvo")]),
    ]


def prices() -> dict[int, ItemPrice]:
    return {
        1001: ItemPrice(1001, "A", market=100),
        1002: ItemPrice(1002, "B", market=1000),
        2001: ItemPrice(2001, "Polvo", market=50),
        2002: ItemPrice(2002, "Esencia", market=200),
        2003: ItemPrice(2003, "Pieza", market=100, vendor_buy=50),
    }


class CajonesEnElMotor(unittest.TestCase):
    def test_elige_el_lote_mas_barato_por_su_cantidad_y_ordena_por_favor(self):
        result = evaluate_crates(crates(), prices())
        self.assertEqual([r.crate.item_id for r in result], [1002, 1001, 1003])
        piezas, polvos, sin_precio = result
        # 10 piezas a 1 p en la subasta (el vendedor no cuenta) + el cajón: 20 p entre 20 de favor.
        self.assertEqual((piezas.option.item_id, piezas.fill_cost, piezas.total, piezas.per_favor),
                         (2003, 1000, 2000, 100))
        # 4 esencias (8 p) salen más baratas que 20 polvos (10 p) aunque cada polvo cueste menos.
        self.assertEqual((polvos.option.item_id, polvos.fill_cost, polvos.per_favor), (2002, 800, 180))
        # Todos sus lotes, por lo que cuesta la cantidad que pide.
        self.assertEqual([(o.item_id, cost) for o, cost in polvos.options], [(2002, 800), (2001, 1000)])
        self.assertIsNone(sin_precio.per_favor)

    def test_exporta_los_lotes(self):
        out = crates_export(crates())
        self.assertEqual(out[1002], {"name": "Cajón saqueado: piezas", "favor": 20, "est": True,
                                     "opts": [[2003, 10, "Pieza"]]})
        self.assertIsNone(out[1001]["est"])
        self.assertIn("[1001] = {", lua_value(out))

    def test_el_conocimiento_de_cajones_esta_bien(self):
        self.assertEqual(crate_problems(), [])
        real = load_crates()
        self.assertEqual(len(real), 30)
        self.assertTrue(all(c.estimated for c in real if "artesano" in c.name))
        self.assertFalse(any(c.estimated for c in real if "artesano" not in c.name))
        curiosidades = next(c for c in real if c.item_id == 248685)
        self.assertEqual([(o.item_id, o.quantity) for o in curiosidades.options],
                         [(10940, 20), (10939, 4), (10978, 6), (11084, 2)])


@unittest.skipIf(LuaRuntime is None, "falta lupa")
class PestanaCajones(unittest.TestCase):
    def setUp(self):
        from tests.test_addon import ADDON_DIR, TESTS_DIR, lua_path, toc_files
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "wow_mock.lua")}")')
        lua.execute(f'dofile("{lua_path(TESTS_DIR / "escenario.lua")}")')
        mock = lua.globals().Mock
        lua.execute('''
          AuctionHouseFrame = {
            GetFrameLevel = function() return 1 end,
            SetDisplayMode = function(self, mode) Mock.displayMode = mode end,
            CommoditiesBuyFrame = {
              SetItemIDAndPrice = function() end,
              IsShown = function() return true end,
              BuyDisplay = { SetQuantitySelected = function(_, q) Mock.buyQuantity = q end },
            },
          }''')
        mock.LoadAddon(lua_path(ADDON_DIR), lua.table_from(toc_files()))
        mock.Fire("ADDON_LOADED", "PitiGolds")
        mock.Fire("PLAYER_LOGIN")
        lua.execute(f'PitiGoldsGenerated = {lua_value({"prices": {}, "crates": crates_export(crates())})}')
        lua.execute('''
          PitiGoldsGenerated.prices = { [1001] = "100,,", [1002] = "1000,,", [2001] = "50,,", [2002] = "200,,",
                                        [2003] = "100,," }''')
        self.lua, self.mock = lua, mock

    def chat(self) -> str:
        return "\n".join(self.mock.chat.values())

    def test_lista_del_favor_mas_barato(self):
        rows = self.mock.ns.Crates.Rows()
        self.assertEqual([rows[i]["id"] for i in (1, 2, 3)], [1002, 1001, 1003])
        self.assertEqual(self.mock.ns.Crates.Line(rows[1]),
                         "1p 0c/favor  Cajón saqueado: piezas (20? de favor): cajón 10p 0c + 10 × Pieza 10p 0c = 20p 0c")
        self.assertEqual(self.mock.ns.Crates.Line(rows[2]),
                         "1p 80c/favor  Cajón saqueado: polvos (5 de favor): cajón 1p 0c + 4 × Esencia 8p 0c = 9p 0c")
        self.assertEqual(self.mock.ns.Crates.Line(rows[3]),
                         "Cajón saqueado: sin precio (10 de favor): sin precio del cajón")

    def test_cada_cajon_con_sus_lotes_debajo(self):
        crates_ns = self.mock.ns.Crates
        lines = crates_ns.Lines()
        shape = [(lines[i]["row"]["id"], lines[i]["opt"] and lines[i]["opt"]["id"]) for i in range(1, len(lines) + 1)]
        # El cajón y debajo sus lotes, del más barato (4 esencias, 8 p) al más caro (20 polvos, 10 p).
        self.assertEqual(shape, [(1002, None), (1002, 2003), (1001, None), (1001, 2002), (1001, 2001),
                                 (1003, None), (1003, 2001)])
        cajon = list(crates_ns.Cells(lines[3]).values())
        # Con mayúscula y fondo propio; los lotes, filas alternas.
        self.assertEqual(cajon[0], "|cffffffffPolvos|r")
        self.assertIsNotNone(crates_ns.Background(lines[3]))
        self.assertIsNone(crates_ns.Background(lines[4]))
        self.assertEqual(cajon[1:], ["5", "1p 0c", "", "9p 0c", "|cff40ff401p 80c|r"])
        barato = list(crates_ns.Cells(lines[4]).values())
        self.assertEqual(barato, ["      |cff40ff404 × Esencia|r", "", "", "|cff40ff408p 0c|r",
                                  "|cff40ff409p 0c|r", "|cff40ff401p 80c|r"])
        caro = list(crates_ns.Cells(lines[5]).values())
        self.assertEqual(caro, ["      |cffbbbbbb20 × Polvo|r", "", "", "|cffbbbbbb10p 0c|r",
                                "|cffbbbbbb11p 0c|r", "|cffbbbbbb2p 20c|r"])

    def test_al_pulsar_un_lote_busca_ese(self):
        mock = self.mock
        mock.Fire("AUCTION_HOUSE_SHOW")
        mock.ns.Crates.Buy(1001, 2001)
        searches = self.lua.eval("Mock.itemKeySearches")
        last = searches[len(searches)]
        self.assertEqual([last[1], last[2]], [1001, 2001])
        self.assertEqual(mock.ns.ShoppingQuantity(2001), (20, 0))
        self.assertIsNone(mock.ns.ShoppingQuantity(2002))

    def test_al_pulsar_busca_el_cajon_y_su_lote(self):
        mock = self.mock
        mock.Fire("AUCTION_HOUSE_SHOW")
        mock.ns.Crates.Buy(1001)
        searches = self.lua.eval("Mock.itemKeySearches")
        last = searches[len(searches)]
        self.assertEqual([last[1], last[2]], [1001, 2002])
        self.assertEqual(mock.ns.ShoppingQuantity(2002), (4, 0))
        self.assertEqual(mock.ns.ShoppingQuantity(1001), (1, 0))
        mock.ns.SetCraftCount(3)
        self.assertEqual(mock.ns.ShoppingQuantity(2002), (12, 0))
        self.lua.execute("AuctionHouseFrame.CommoditiesBuyFrame:SetItemIDAndPrice(2002, 200)")
        mock.Advance(1)
        self.assertEqual(self.lua.eval("Mock.buyQuantity"), 12)
        self.assertIn("Esencia: marcados 12 para 3 cajones.", self.chat())

    def test_la_pestana_se_abre_y_se_cierra_con_las_de_blizzard(self):
        mock = self.mock
        mock.Fire("AUCTION_HOUSE_SHOW")
        crates_ns = mock.ns.Crates
        self.assertFalse(crates_ns.IsShown())
        self.assertTrue(mock.ClickButton("Cajones"))
        self.assertTrue(crates_ns.IsShown())
        self.lua.execute("AuctionHouseFrame:SetDisplayMode('buy')")
        self.assertFalse(crates_ns.IsShown())
        # Al pulsar un cajón se pasa a Comprar para ver los resultados.
        self.assertTrue(mock.ClickButton("Cajones"))
        crates_ns.Buy(1001)
        self.assertFalse(crates_ns.IsShown())

    def test_la_pestana_va_junto_a_la_ultima_de_blizzard_sin_entrar_en_su_lista(self):
        # Como en el juego: la plantilla de pestaña se apunta sola en la lista Tabs de su padre.
        lua = self.lua
        lua.execute('''
          Mock.blizzardTab = Mock.NewFrame("AuctionHouseFrameAuctionsTab")
          AuctionHouseFrame.Tabs = { Mock.blizzardTab }
          local create = CreateFrame
          CreateFrame = function(kind, name, parent, template)
            local f = create(kind, name, parent, template)
            if template == "PanelTabButtonTemplate" and parent then
              parent.Tabs = parent.Tabs or {}
              table.insert(parent.Tabs, f)
            end
            return f
          end''')
        self.mock.Fire("AUCTION_HOUSE_SHOW")
        self.assertEqual(lua.eval("#AuctionHouseFrame.Tabs"), 1)
        self.assertTrue(lua.eval("PitiGoldsCratesTab.point[2] == Mock.blizzardTab"))
        self.assertEqual(self.chat(), "")

    def test_al_comprar_sube_el_precio_al_momento(self):
        lua, mock = self.lua, self.mock
        lua.execute('''
          Mock.commodity = { [2002] = { { unitPrice = 200, quantity = 4 }, { unitPrice = 230, quantity = 10 } } }
          C_AuctionHouse.GetNumCommoditySearchResults = function(id) return #(Mock.commodity[id] or {}) end
          C_AuctionHouse.GetCommoditySearchResultInfo = function(id, i) return Mock.commodity[id][i] end
          Mock.requeried = {}
          C_AuctionHouse.SendSearchQuery = function(key) table.insert(Mock.requeried, key.itemID) end''')
        mock.Fire("AUCTION_HOUSE_SHOW")
        mock.Fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2002)
        mock.Advance(1)
        scan = lua.eval("PitiGoldsDB.scans[#PitiGoldsDB.scans]")
        self.assertEqual(scan["items"][2002], "200,14,2|200:4;230:10")
        # Te llevas las 4 a 2 p: lo que queda empieza en 2 p 30 c.
        lua.execute("C_AuctionHouse.ConfirmCommoditiesPurchase(2002, 4)")
        mock.Advance(1)
        self.assertEqual(scan["items"][2002], "230,10,2|230:10")
        self.assertEqual(list(lua.eval("Mock.requeried").values()), [2002])
        polvos = next(r for r in mock.ns.Crates.Rows().values() if r["id"] == 1001)
        esencia = next(o for o in polvos["options"].values() if o["id"] == 2002)
        self.assertEqual(esencia["cost"], 4 * 230)
        # Cuando llega la lista nueva del servidor, manda ella.
        lua.execute("Mock.commodity[2002] = { { unitPrice = 240, quantity = 10 } }")
        mock.Fire("COMMODITY_SEARCH_RESULTS_UPDATED", 2002)
        mock.Advance(1)
        self.assertEqual(scan["items"][2002], "240,10,1|240:10")

    def test_comando_del_chat(self):
        self.mock.Slash("cajones")
        self.assertIn("1p 0c/favor  Cajón saqueado: piezas", self.chat())


if __name__ == "__main__":
    unittest.main()
