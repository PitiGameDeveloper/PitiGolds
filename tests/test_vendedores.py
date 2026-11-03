"""Reventa desde vendedores, posibles chollos y cuándo toca volver a comprobarlos."""

import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor import merchantmap
from motor.crafting import CraftResult, Reagent
from motor.db import set_meta
from motor.farming import FarmSession
from motor.market import MarketSignals
from motor.pricing import ItemPrice, load_prices
from motor.vendors import record_check, vendor_candidates, vendor_flips

T0 = 1_762_000_000
DAY = 86400


class Vendedores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = c = dbmod.connect(Path(self.tmp.name) / "p.db")
        set_meta(c, "game_data_build", "1.60.1.1")
        # 2: tinte (comerciable «otros»); 3: paño de lana (tela, material de botín).
        c.executemany("INSERT INTO gd_items (item_id, name, class_id, subclass_id) VALUES (?, ?, ?, ?)",
                      [(2, "Tinte azul", 7, 11), (3, "Paño de lana", 7, 5)])
        c.execute("INSERT INTO vendor_items (item_id, price, limited, vendor) VALUES (1, 100, 0, 'Grimtak')")
        c.commit()
        self.prices = {
            1: ItemPrice(item_id=1, name="Especia", market=200, min_price=200, stack_size=20),
            2: ItemPrice(item_id=2, name="Tinte azul", market=100, min_price=100, catalog_buy=10, stack_size=20),
            3: ItemPrice(item_id=3, name="Paño de lana", market=200, min_price=200, catalog_buy=44, stack_size=20),
            4: ItemPrice(item_id=4, name="Pocion", market=100, min_price=100, catalog_buy=90,  # poca diferencia
                         stack_size=20),
        }
        self.crafts = [CraftResult(recipe_id=9, name="Bolsa", profession="Sastrería", output_item_id=5,
                                   cost=100, value=500, yours=True,
                                   reagents=[Reagent(name="Tinte azul", quantity=1, item_id=2),
                                             Reagent(name="Pocion", quantity=1, item_id=4)])]
        self.farms = [FarmSession(char_key="A-R", zone="Durotar", label=None, start=T0, end=T0 + 3600,
                                  items={3: 20}, value_now=3800)]

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def candidates(self, now):
        return {c.item_id: c for c in vendor_candidates(self.conn, self.prices, self.crafts, self.farms, now=now)}

    def test_reventa_desde_un_vendedor_visto(self):
        signals = {1: MarketSignals(current=200, median=200, quantity=30, points=10, span_days=3, sales_per_day=10)}
        (flip,) = vendor_flips(self.conn, self.prices, signals)
        # 200 sin comisión (190) ni 5 c de depósito (1 plata por pila de 20).
        self.assertEqual((flip.buy, flip.sell, flip.profit), (100, 185, 85))
        self.assertEqual(flip.gold_per_day, round(85 * 10 * 0.3))

    def test_solo_objetos_de_crafteos_y_farmeos_con_diferencia(self):
        c = self.candidates(T0)
        self.assertEqual(set(c), {2, 3})          # la poción apenas gana nada; la especia ya la viste
        self.assertEqual(c[2].why, "material de Bolsa")
        self.assertEqual(c[3].why, "lo farmeas en Durotar")
        self.assertTrue(c[3].loot)
        self.assertTrue(all(x.due for x in c.values()))

    def test_espera_creciente_si_no_lo_vende_nadie(self):
        record_check(self.conn, 2, sold=False, now=T0)
        self.assertFalse(self.candidates(T0 + 6 * DAY)[2].due)
        self.assertTrue(self.candidates(T0 + 7 * DAY)[2].due)
        record_check(self.conn, 2, sold=False, now=T0 + 7 * DAY)
        self.assertFalse(self.candidates(T0 + 20 * DAY)[2].due)    # ahora toca a los 14 días
        record_check(self.conn, 2, sold=False, now=T0 + 21 * DAY)
        record_check(self.conn, 2, sold=False, now=T0 + 49 * DAY)
        self.assertFalse(self.candidates(T0 + 400 * DAY)[2].due)   # ya solo con versiones nuevas
        set_meta(self.conn, "game_data_build", "1.61.0.1")
        self.assertTrue(self.candidates(T0 + 400 * DAY)[2].due)

    def test_el_pano_de_lana_no_se_mira_cada_semana(self):
        record_check(self.conn, 3, sold=False, now=T0)
        self.assertFalse(self.candidates(T0 + 60 * DAY)[3].due)
        self.assertEqual(self.candidates(T0 + 60 * DAY)[3].next_check, "con la próxima versión del juego")
        set_meta(self.conn, "game_data_build", "1.61.0.1")
        self.assertTrue(self.candidates(T0 + 60 * DAY)[3].due)

    def test_si_lo_vende_alguien_se_guarda_el_detalle(self):
        record_check(self.conn, 2, sold=True, detail="Grimtak (Ratchet), Honorable", now=T0)
        c = self.candidates(T0 + 30 * DAY)[2]
        self.assertEqual((c.status, c.detail, c.due), ("vende", "Grimtak (Ratchet), Honorable", False))


VENDOR_DATA = r'''local _, MM = ...
MM.knownVendors = {
[66]={"Tharynn Bouden","Trade Supplies","A",12,41.82,67.16,{2320,2324,2604}},
[3489]={"Zikkel \"Chispas\"",nil,"H",17,62.0,38.0,{2320,4291}},
[3490]={"Kilxx","Fisherman","AH",17,62.76,38.22,{4603,6256}},
[13418]={"Duende festivo",nil,"AH",1637,53.33,66.49,{17201}},
}

MM.knownItemNames = {
}

MM.holidaySpots = {
[13418]={{"Feast of Winter Veil",1637,53.33,66.49}},
}
'''

VERIFIED_DATA = r'''local _, MM = ...
MM.shippedVendors = {
    [66] = { "Tharynn Bouden", 1429, 0.4182, 0.6716, 1790000000, { [2320] = { 9 }, [2324] = { 25 }, [2880] = { 0, "30 |T135725:0|t" } }, nil, { 2604 } },
    [3490] = { "Kilxx", 1413, 0.6276, 0.3822, 1790634351, { [4603] = { 80, nil, true } }, nil, {  } },
}

MM.shippedServices = {
}
'''


class MerchantMap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = c = dbmod.connect(Path(self.tmp.name) / "p.db")
        folder = Path(self.tmp.name) / "mm"
        folder.mkdir()
        (folder / "VendorData.lua").write_text(VENDOR_DATA, encoding="utf-8")
        (folder / "VerifiedData.lua").write_text(VERIFIED_DATA, encoding="utf-8")
        merchantmap.import_files(c, folder)
        # buy_price: lo que cobra el vendedor por vendor_stack unidades.
        c.executemany("INSERT INTO gd_items (item_id, name, buy_price, vendor_stack) VALUES (?, ?, ?, ?)",
                      [(2320, "Hilo burdo", 10, 1), (2324, "Lejía", 25, 5), (2604, "Tinte rojo", 50, 1),
                       (4291, "Hilo de seda", 500, 1), (4603, "Pez", 100, 1), (6256, "Caña", 23, 1),
                       (2880, "Flujo", 100, 1), (17201, "Galleta", 10, 1), (2589, "Paño de lino", 55, 1)])
        c.executemany("INSERT INTO gd_maps VALUES (?, ?)", [(1429, "Bosque de Elwynn"), (1413, "Los Baldíos")])
        c.execute("INSERT INTO gd_areas VALUES (17, 'Los Baldíos')")
        c.commit()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def offers(self, item_id):
        return [dict(r) for r in self.conn.execute("SELECT * FROM mm_vendor_items WHERE item_id = ?", (item_id,))]

    def test_lee_las_dos_listas(self):
        classic, holidays = merchantmap.parse_classic(VENDOR_DATA)
        self.assertEqual(classic[3489].name, 'Zikkel "Chispas"')
        self.assertEqual((classic[66].faction, classic[66].area_id, classic[66].items), ("A", 12, [2320, 2324, 2604]))
        self.assertEqual(holidays, {13418})
        verified = merchantmap.parse_verified(VERIFIED_DATA)
        self.assertEqual(verified["66"].stock, {2320: (9, False, False), 2324: (25, False, False),
                                                2880: (None, True, False)})
        self.assertEqual(verified["66"].not_seen, {2604})
        self.assertEqual(verified["3490"].stock[4603], (80, False, True))

    def test_lo_comprobado_manda_sobre_el_classic(self):
        (hilo,) = [o for o in self.offers(2320) if o["npc"] == "66"]
        self.assertEqual((hilo["price"], hilo["verified"], hilo["map_id"]), (9, 1, 1429))
        self.assertEqual(self.offers(2604), [])          # no estaba en la tienda al comprobarla
        (cana,) = self.offers(6256)                       # del Classic, en un vendedor comprobado
        self.assertEqual((cana["price"], cana["verified"]), (None, 0))

    def test_precios_vendedor_y_zona(self):
        prices = load_prices(self.conn)
        hilo = prices[2320]
        # 9 es el precio con descuento de quien lo vio: a ±15 % manda el de los datos del juego.
        self.assertEqual((hilo.shop_price, hilo.buy_price, hilo.buy_source), (10, 10, "vendedor"))
        self.assertEqual(hilo.known_vendor.vendors, 2)
        self.assertEqual(prices[2324].shop_price, 5)      # 25 por un lote de 5
        self.assertEqual(prices[2324].known_vendor.where, "Tharynn Bouden (Bosque de Elwynn)")
        self.assertIsNone(prices[4603].shop_price)        # existencias limitadas
        self.assertIsNone(prices[2880].shop_price)        # se paga con divisa
        self.assertTrue(prices[2880].known_vendor.currency)
        self.assertEqual(prices[6256].shop_price, 23)     # sin comprobar: precio de los datos del juego
        self.assertFalse(prices[6256].known_vendor.verified)
        self.assertIsNone(prices[17201].known_vendor)     # solo en fiestas
        lino = prices[2589]
        self.assertTrue(lino.vendors_known)
        self.assertIsNone(lino.known_vendor)              # no lo vende nadie
        self.assertIsNone(lino.buy_price)

    def test_solo_vendedores_de_tu_faccion(self):
        self.conn.execute("INSERT INTO characters (char_key, faction) VALUES ('Piti-R', 'Alliance')")
        prices = load_prices(self.conn)
        self.assertIsNone(prices[4291].known_vendor)      # solo lo vende Zikkel, de la Horda
        self.assertEqual(prices[2320].known_vendor.vendors, 1)
        self.assertEqual(prices[6256].known_vendor.vendor, "Kilxx")   # neutral

    def test_reventa_y_chollos(self):
        self.conn.execute("INSERT INTO scans (scan_id, type, time) VALUES ('s1', 'full', ?)", (T0,))
        self.conn.executemany("INSERT INTO prices (scan_id, item_id, min_price, quantity) VALUES ('s1', ?, ?, 50)",
                              [(4603, 1000), (2589, 500), (2324, 26)])
        prices = load_prices(self.conn)
        flips = {f.item_id: f for f in vendor_flips(self.conn, prices, {})}
        self.assertEqual(set(flips), {4603})              # la lejía apenas deja nada
        # 80 comprobado frente a 100 en los datos del juego: se aparta más de un 15 %, manda el comprobado.
        self.assertEqual((flips[4603].buy, flips[4603].limited, flips[4603].source), (80, True, "Merchant Map"))
        self.assertEqual(flips[4603].vendor, "Kilxx (Los Baldíos)")
        crafts = [CraftResult(recipe_id=9, name="Venda", profession="Primeros auxilios", output_item_id=5,
                              cost=100, value=500, yours=True,
                              reagents=[Reagent(name="Paño de lino", quantity=1, item_id=2589)])]
        # Merchant Map ya dice que el paño de lino no lo vende nadie: no hay que mirarlo fuera.
        self.assertEqual(vendor_candidates(self.conn, prices, crafts, [], now=T0), [])


if __name__ == "__main__":
    unittest.main()
