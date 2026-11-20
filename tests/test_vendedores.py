"""Qué vende cada vendedor según Merchant Map y cuándo se usa su precio."""

import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor import merchantmap
from motor.pricing import load_prices

T0 = 1_762_000_000


VENDOR_DATA = r'''local _, MM = ...
MM.knownVendors = {
[66]={"Tharynn Bouden","Trade Supplies","A",12,41.82,67.16,{2320,2324,2604}},
[3489]={"Zikkel \"Chispas\"",nil,"H",17,62.0,38.0,{2320,4291}},
[3490]={"Kilxx","Fisherman","AH",17,62.76,38.22,{4603,6256}},
[16015]={"Vi'el",nil,"AH",618,0,0,{8846}},
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
        c.execute("INSERT INTO gd_items (item_id, name, buy_price, vendor_stack, class_id, subclass_id) "
                  "VALUES (8846, 'Gromsanguina', 1000, 1, 7, 9)")
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
        # No está en la subasta: se cuenta comprado al vendedor.
        self.assertEqual((hilo.shop_price, hilo.buy_price, hilo.buy_source), (10, 10, "vendedor"))
        self.assertEqual(hilo.known_vendor.vendors, 2)
        self.assertEqual(prices[2324].shop_price, 5)      # 25 por un lote de 5
        self.assertEqual(prices[2324].known_vendor.where, "Tharynn Bouden (Bosque de Elwynn)")
        self.assertIsNone(prices[4603].shop_price)        # existencias limitadas
        self.assertIsNone(prices[2880].shop_price)        # se paga con divisa
        self.assertTrue(prices[2880].known_vendor.currency)
        self.assertEqual(prices[6256].shop_price, 23)     # sin comprobar: precio de los datos del juego
        self.assertFalse(prices[6256].known_vendor.verified)
        # Hierba solo en la lista del Classic: cuenta como limitada y no se usa para el coste.
        self.assertTrue(prices[8846].known_vendor.limited)
        self.assertIsNone(prices[8846].shop_price)
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

    def test_la_subasta_manda_sobre_el_vendedor(self):
        self.conn.execute("INSERT INTO scans (scan_id, type, time) VALUES ('s1', 'full', ?)", (T0,))
        self.conn.executemany("INSERT INTO prices (scan_id, item_id, min_price, quantity) VALUES ('s1', ?, ?, 50)",
                              [(4603, 1000), (2589, 500), (2324, 26), (2320, 30)])
        prices = load_prices(self.conn)
        # El hilo está en la subasta: se compra allí aunque el vendedor lo tenga a 10.
        self.assertEqual((prices[2320].buy_price, prices[2320].buy_source), (30, "subasta"))
        # 80 comprobado frente a 100 en los datos del juego: se aparta más de un 15 %, manda el comprobado.
        self.assertEqual(prices[4603].known_vendor.price, 80)
        self.assertEqual(prices[4603].known_vendor.where, "Kilxx (Los Baldíos)")


if __name__ == "__main__":
    unittest.main()
