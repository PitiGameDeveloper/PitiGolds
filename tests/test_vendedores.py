"""Reventa desde vendedores, posibles chollos y cuándo toca volver a comprobarlos."""

import tempfile
import unittest
from pathlib import Path

from motor import db as dbmod
from motor.crafting import CraftResult, Reagent
from motor.db import set_meta
from motor.farming import FarmSession
from motor.market import MarketSignals
from motor.pricing import ItemPrice
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
            1: ItemPrice(item_id=1, name="Especia", market=200, min_price=200),
            2: ItemPrice(item_id=2, name="Tinte azul", market=100, min_price=100, catalog_buy=10),
            3: ItemPrice(item_id=3, name="Paño de lana", market=200, min_price=200, catalog_buy=44),
            4: ItemPrice(item_id=4, name="Pocion", market=100, min_price=100, catalog_buy=90),  # poca diferencia
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
        self.assertEqual((flip.buy, flip.sell, flip.profit), (100, 190, 90))
        self.assertEqual(flip.gold_per_day, round(90 * 10 * 0.3))

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


if __name__ == "__main__":
    unittest.main()
