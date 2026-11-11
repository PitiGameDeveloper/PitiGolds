"""Libranzas del artesano: el conocimiento del motor y la pestaña de la subasta."""

from __future__ import annotations

import unittest

from motor.generated import lua_value
from motor.libranzas import Writ, WritBook, load_writs, writ_item_ids, writ_problems, writs_export

try:
    from lupa.lua51 import LuaRuntime
except ImportError:  # las del addon necesitan lupa (requirements-dev.txt)
    LuaRuntime = None


def book() -> WritBook:
    # Zonas A y B pegadas; C suelta. Precios (libranza + objeto):
    #   A: 3001 (1 p + 2 × 1 p = 3 p), 3002 (10 p + 5 p = 15 p)
    #   B: 3003 (1 p + 1 p = 2 p)
    #   C: 3004 (4 p + 1 p = 5 p), 3005 (sin precio de la libranza)
    return WritBook(
        writs=[
            Writ(3001, 4001, 2, "Daga", "Herrería", "A", "Pepe"),
            Writ(3002, 4002, 1, "Capa", "Sastrería", "A", "Pepe"),
            Writ(3003, 4003, 1, "Poción", "Alquimia", "B", "Ana"),
            Writ(3004, 4004, 1, "Bomba", "Ingeniería", "C", "Luis"),
            Writ(3005, 4005, 1, "Guantes", "Peletería", "C", "Luis"),
        ],
        groups=[["A", "B"]],
    )


class LibranzasEnElMotor(unittest.TestCase):
    def test_exporta_misiones_y_grupos(self):
        out = writs_export(book())
        self.assertEqual(out["list"][3001], [4001, 2, "Daga", "Herrería", "A", "Pepe"])
        self.assertEqual(out["groups"], [["A", "B"]])
        self.assertIn("[3001] = {", lua_value(out))
        self.assertEqual(writ_item_ids(book()), {3001, 3002, 3003, 3004, 3005, 4001, 4002, 4003, 4004, 4005})

    def test_el_conocimiento_de_libranzas_esta_bien(self):
        self.assertEqual(writ_problems(), [])
        real = load_writs()
        self.assertEqual(len(real.writs), 46)
        zones = {w.zone for w in real.writs}
        for group in real.groups:
            self.assertTrue(set(group) <= zones)


@unittest.skipIf(LuaRuntime is None, "falta lupa")
class PestanaLibranzas(unittest.TestCase):
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
        lua.execute(f'PitiGoldsGenerated = {lua_value({"prices": {}, "writs": writs_export(book())})}')
        lua.execute('''
          PitiGoldsGenerated.prices = { [3001] = "100,,", [4001] = "100,,", [3002] = "1000,,", [4002] = "500,,",
                                        [3003] = "100,,", [4003] = "100,,", [3004] = "400,,", [4004] = "100,,",
                                        [4005] = "50,," }''')
        self.lua, self.mock = lua, mock

    def chat(self) -> str:
        return "\n".join(self.mock.chat.values())

    def shape(self, sort):
        lines = self.mock.ns.Writs.Lines(sort)
        out = []
        for i in range(1, len(lines) + 1):
            line = lines[i]
            kind = line["kind"]
            if kind in ("group", "zone"):
                out.append((kind, line["name"], line["sum"]))
            else:
                out.append((kind, line["quest"]["id"]))
        return out

    def test_por_zonas_grupo_zona_y_misiones(self):
        # A+B: 20 p (B 2 p, A 18 p). C sola: 5 p y una sin precio. Grupos de más barato a más caro.
        self.assertEqual(self.shape("zonas"), [
            ("zone", "C", 500), ("writ", 3004), ("item", 3004), ("writ", 3005), ("item", 3005),
            ("group", "B y A", 2000),
            ("zone", "B", 200), ("writ", 3003), ("item", 3003),
            ("zone", "A", 1800), ("writ", 3001), ("item", 3001), ("writ", 3002), ("item", 3002),
        ])

    def test_por_zonas_manda_la_media_por_mision_no_el_total(self):
        # C pasa a 15 p 50 c por 2 misiones (7 p 75 c de media); B y A, 20 p por 3 (6 p 67 c de media):
        # el grupo va antes aunque en total cueste más.
        self.lua.execute('PitiGoldsGenerated.prices[3005] = "1000,,"')
        shape = self.shape("zonas")
        self.assertEqual(shape[0], ("group", "B y A", 2000))
        self.assertEqual(shape[-5], ("zone", "C", 1550))
        # Dentro del grupo, también por la media: B (2 p) antes que A (9 p).
        self.assertEqual([s[1] for s in shape if s[0] == "zone"], ["B", "A", "C"])

    def test_mas_baratas_juntando_las_seguidas_de_la_misma_zona(self):
        # 3003 (B, 2 p), 3001 (A, 3 p), 3004 (C, 5 p), 3002 (A, 15 p), 3005 (C, sin precio): la última
        # de C no va con la otra de C porque entre medias hay una de A.
        self.assertEqual(self.shape("baratas"), [
            ("zone", "B", 200), ("writ", 3003), ("item", 3003),
            ("zone", "A", 300), ("writ", 3001), ("item", 3001),
            ("zone", "C", 500), ("writ", 3004), ("item", 3004),
            ("zone", "A", 1500), ("writ", 3002), ("item", 3002),
            ("zone", "C", 0), ("writ", 3005), ("item", 3005),
        ])
        # Si dos seguidas son de la misma zona, van juntas.
        self.lua.execute('PitiGoldsGenerated.prices[3002] = "150,,"')  # 3002: 6 p 50 c, detrás de 3004
        self.lua.execute('PitiGoldsGenerated.prices[3004] = "50,,"')   # 3004: 1 p 50 c, la más barata
        self.assertEqual(self.shape("baratas")[:6], [
            ("zone", "C", 150), ("writ", 3004), ("item", 3004),
            ("zone", "B", 200), ("writ", 3003), ("item", 3003),
        ])
        self.assertEqual(self.shape("baratas")[6:11], [
            ("zone", "A", 950), ("writ", 3001), ("item", 3001), ("writ", 3002), ("item", 3002),
        ])

    def test_celdas(self):
        writs = self.mock.ns.Writs
        lines = writs.Lines("zonas")
        zona_c = list(writs.Cells(lines[1]).values())
        # La media, solo de las misiones con precio.
        self.assertEqual(zona_c, ["|cffffffffC|r", "", "", "≥ 5p 0c", "|cff40ff405p 0c|r", "2"])
        libranza = list(writs.Cells(lines[2]).values())
        self.assertEqual(libranza[1:], ["Ingeniería", "4p 0c", "|cff40ff405p 0c|r", "", ""])
        objeto = list(writs.Cells(lines[3]).values())
        self.assertEqual(objeto, ["    |cffbbbbbb  Entregar: Bomba|r", "", "|cffbbbbbb1p 0c|r", "", "", ""])
        sin_precio = list(writs.Cells(lines[4]).values())
        self.assertEqual(sin_precio[2], "|cff999999sin precio|r")
        grupo = list(writs.Cells(lines[6]).values())
        self.assertEqual(grupo, ["|cffffd100B y A|r", "", "", "20p 0c", "|cff40ff406p 67c|r", "3"])
        # Grupos y zonas con fondo propio; las misiones, filas alternas.
        self.assertEqual(list(writs.Background(lines[6]).values()), [0.40, 0.30, 0.05, 0.75])
        self.assertEqual(list(writs.Background(lines[1]).values()), [0.10, 0.22, 0.38, 0.75])
        self.assertIsNone(writs.Background(lines[2]))
        daga = list(writs.Cells(lines[12]).values())
        self.assertIn("Entregar: 2 × Daga", daga[0])

    def test_al_pulsar_una_mision_busca_libranza_y_objeto(self):
        mock = self.mock
        mock.Fire("AUCTION_HOUSE_SHOW")
        writs = mock.ns.Writs
        lines = writs.Lines("zonas")
        writs.Buy(lines[12]["quests"])  # la libranza de la Daga
        searches = self.lua.eval("Mock.itemKeySearches")
        last = searches[len(searches)]
        self.assertEqual([last[1], last[2]], [3001, 4001])
        self.assertEqual(mock.ns.ShoppingQuantity(4001), (2, 0))
        self.assertEqual(mock.ns.ShoppingQuantity(3001), (1, 0))
        self.assertEqual(mock.ns.CraftCountLabel(), "Veces x")

    def test_al_pulsar_un_grupo_busca_todas_sus_misiones(self):
        mock = self.mock
        mock.Fire("AUCTION_HOUSE_SHOW")
        writs = mock.ns.Writs
        writs.Buy(writs.Lines("zonas")[6]["quests"])  # B y A
        searches = self.lua.eval("Mock.itemKeySearches")
        last = searches[len(searches)]
        self.assertEqual(sorted(last.values()), [3001, 3002, 3003, 4001, 4002, 4003])

    def test_botones_de_orden_y_pestana(self):
        mock = self.mock
        mock.Fire("AUCTION_HOUSE_SHOW")
        writs = mock.ns.Writs
        self.assertEqual(writs.Sort(), "zonas")
        self.assertTrue(mock.ClickButton("Libranzas"))
        self.assertTrue(writs.IsShown())
        self.assertTrue(mock.ClickButton("Más baratas"))
        self.assertEqual(writs.Sort(), "baratas")
        self.assertEqual(self.lua.eval("PitiGoldsDB.writSort"), "baratas")
        # Una pestaña nuestra cierra la otra.
        self.assertTrue(mock.ClickButton("Cajones"))
        self.assertFalse(writs.IsShown())
        self.assertTrue(mock.ClickButton("Libranzas"))
        self.assertFalse(mock.ns.Crates.IsShown())
        self.lua.execute("AuctionHouseFrame:SetDisplayMode('buy')")
        self.assertFalse(writs.IsShown())
        self.assertTrue(self.lua.eval("PitiGoldsWritsTab.point[2] == PitiGoldsCratesTab"))
        self.assertEqual(self.chat(), "")

    def item_results(self, browse_min, rows, item_id=4001):
        """Abre en la subasta un objeto suelto: la lista de resultados (si browse_min) y sus filas."""
        lua, mock = self.lua, self.mock
        lua.execute(f'''
          Mock.itemRows = {lua_value([{"buyoutAmount": p, "quantity": q} for p, q in rows])}
          C_AuctionHouse.GetNumItemSearchResults = function() return #Mock.itemRows end
          C_AuctionHouse.GetItemSearchResultInfo = function(_, i) return Mock.itemRows[i] end
          C_AuctionHouse.GetBrowseResults = function()
            if not {lua_value(browse_min)} then return {{}} end
            return {{ {{ itemKey = {{ itemID = {item_id}, battlePetSpeciesID = 0 }}, minPrice = {lua_value(browse_min)},
                       totalQuantity = 1 }} }}
          end''')
        mock.Fire("AUCTION_HOUSE_SHOW")
        if browse_min:
            mock.Fire("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED")
            mock.Advance(1)
        lua.execute(f"Mock.Fire('ITEM_SEARCH_RESULTS_UPDATED', {{ itemID = {item_id} }})")
        mock.Advance(1)
        scan = lua.eval("PitiGoldsDB.scans[#PitiGoldsDB.scans]")
        return scan["items"][item_id] if scan and scan["type"] == "search" else None

    def test_filas_que_juntan_subastas_iguales_no_hunden_el_precio(self):
        # Como la Cerradura de prácticas en Forever: una fila «702 a 1 p», y no 702 por 1 p en total.
        self.assertEqual(self.item_results(100, [(100, 702), (400, 5)]), "100,707,2|100:702;400:5")
        self.assertEqual(self.mock.ns.MarketPrice(4001), (100, True))

    def test_un_monton_de_verdad_se_divide(self):
        # Una subasta de 20 por 20 p: 1 p cada una, que es lo que dice la lista de resultados.
        self.assertEqual(self.item_results(100, [(2000, 20)]), "100,20,1|100:20")

    def test_sin_lista_de_resultados_y_filas_de_varios_no_se_apunta(self):
        self.assertIsNone(self.item_results(None, [(100, 702)]))
        # Si cada fila es una subasta de una unidad, no hay duda.
        self.assertEqual(self.item_results(None, [(3500, 1), (4100, 1)]), "3500,2,2|3500:1;4100:1")

    def test_comando_del_chat(self):
        self.mock.Slash("libranzas")
        self.assertIn("2p 0c  Poción (B): libranza 1p 0c + objeto 1p 0c", self.chat())
        self.assertIn("Guantes (C): sin precio de la libranza", self.chat())


if __name__ == "__main__":
    unittest.main()
