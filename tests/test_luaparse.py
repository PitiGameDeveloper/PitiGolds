import unittest

from motor.luaparse import LuaParseError, as_dict, as_list, parse_saved_variables


class LectorSavedVariables(unittest.TestCase):
    def test_formato_de_wow(self):
        text = '''
PitiGoldsDB = {
\t["characters"] = {
\t\t["Brujo-Dio"] = {
\t\t\t["money"] = 1234567,
\t\t\t["ratio"] = 0.5,
\t\t\t["vivo"] = true,
\t\t},
\t},
\t["scans"] = {
\t\t{
\t\t\t["type"] = "full",
\t\t}, -- [1]
\t\t{
\t\t\t["type"] = "browse",
\t\t}, -- [2]
\t},
\t["vacio"] = {
\t},
\t[2589] = "40,35",
}
OtraVariable = nil
'''
        data = parse_saved_variables(text)
        db = data["PitiGoldsDB"]
        self.assertEqual(db["characters"]["Brujo-Dio"]["money"], 1234567)
        self.assertEqual(db["characters"]["Brujo-Dio"]["ratio"], 0.5)
        self.assertIs(db["characters"]["Brujo-Dio"]["vivo"], True)
        self.assertEqual([s["type"] for s in db["scans"]], ["full", "browse"])
        self.assertEqual(db["vacio"], {})
        self.assertEqual(db[2589], "40,35")
        self.assertIsNone(data["OtraVariable"])

    def test_escapes_y_acentos(self):
        data = parse_saved_variables('X = { "Paño \\"bueno\\"", "línea\\\nnueva", "\\124cff", "a\\\\b" }')
        self.assertEqual(data["X"], ['Paño "bueno"', "línea\nnueva", "|cff", "a\\b"])

    def test_numeros(self):
        data = parse_saved_variables("X = { -5, 1e3, 75000000000, 0x10 }")
        self.assertEqual(data["X"], [-5, 1000.0, 75000000000, 16])

    def test_claves_enteras_con_huecos(self):
        data = parse_saved_variables("X = { [3] = 'a', [10] = 'b' }")
        self.assertEqual(data["X"], {3: "a", 10: "b"})
        self.assertEqual(as_list(data["X"]), ["a", "b"])
        self.assertEqual(as_dict(["a", "b"]), {1: "a", 2: "b"})

    def test_error_claro(self):
        with self.assertRaises(LuaParseError):
            parse_saved_variables("X = { ")


if __name__ == "__main__":
    unittest.main()
