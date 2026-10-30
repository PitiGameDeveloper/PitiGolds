"""Fase 4: novedades de las fuentes, validación del catálogo y lanzador del asesor."""

import json
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from motor import db as dbmod
from motor.analysis import analyze
from motor.catalogo import CatalogError, catalog_problems, load_catalog
from motor.fuentes import collect, mark_done, parse_feed, word_text
from motor.report import build_advice_report

NOW = 1_793_000_000  # finales de octubre de 2026
DAY = 86400


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


def rfc(t):
    return time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(t))


YOUTUBE = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
 <title>Canal de oro</title>
 <entry>
  <id>yt:video:abc</id><title>Best Gold Farm in Forever</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=abc"/>
  <published>{iso(NOW - 2 * DAY)}</published>
  <media:group><media:description>Basilisks in STV &amp; skinning, 30g/h</media:description></media:group>
 </entry>
 <entry>
  <id>yt:video:old</id><title>Old video</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v=old"/>
  <published>{iso(NOW - 20 * DAY)}</published>
 </entry>
</feed>""".encode()

WOWHEAD = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Wowhead News</title>
 <item><title>Hotfixes: Mooncloth cooldown changed</title><link>https://www.wowhead.com/news=1</link>
  <guid>https://www.wowhead.com/news=1</guid><pubDate>{rfc(NOW - DAY)}</pubDate>
  <description>&lt;p&gt;Blizzard changed &lt;b&gt;Mooncloth&lt;/b&gt;.&lt;/p&gt;</description></item>
 <item><title>New cinematic short story</title><link>https://www.wowhead.com/news=2</link>
  <guid>https://www.wowhead.com/news=2</guid><pubDate>{rfc(NOW - DAY)}</pubDate>
  <description>A story about World of Warcraft</description></item>
</channel></rss>""".encode()

SOURCES = [
    {"nombre": "YouTube oro", "tipo": "youtube", "channel_id": "UC123"},
    {"nombre": "Wowhead", "tipo": "rss", "url": "https://wowhead.test/rss", "filtro": r"\b(hotfix\w*|gold)\b"},
    {"nombre": "Caída", "tipo": "rss", "url": "https://caida.test/rss"},
]


def fake_fetch(url):
    if "youtube.com/feeds" in url and "UC123" in url:
        return YOUTUBE
    if url == "https://wowhead.test/rss":
        return WOWHEAD
    raise OSError("sin conexión")


class Novedades(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.conn = dbmod.connect(root / "p.db")
        self.folder = root / "fuentes"
        self.folder.mkdir()

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def collect(self, now=NOW):
        return collect(self.conn, SOURCES, 7, now=now, fetch=fake_fetch, folder=self.folder)

    def test_lee_atom_y_rss(self):
        yt = parse_feed(YOUTUBE, "yt")
        self.assertEqual(yt[0].title, "Best Gold Farm in Forever")
        self.assertEqual(yt[0].summary, "Basilisks in STV & skinning, 30g/h")
        self.assertEqual(yt[0].published, NOW - 2 * DAY)
        wh = parse_feed(WOWHEAD, "wh")
        self.assertEqual(wh[0].summary, "Blizzard changed Mooncloth .")
        self.assertEqual(wh[0].url, "https://www.wowhead.com/news=1")

    def test_solo_lo_reciente_filtrado_y_sin_revisar(self):
        rows, errors = self.collect()
        self.assertEqual([r["title"] for r in rows], ["Hotfixes: Mooncloth cooldown changed", "Best Gold Farm in Forever"])
        self.assertEqual(len(errors), 1)
        self.assertIn("Caída", errors[0])
        # Lo que no se ha marcado sigue saliendo; lo marcado ya no.
        self.assertEqual(len(self.collect()[0]), 2)
        self.assertEqual(mark_done(self.conn, [2], now=NOW), 1)
        self.assertEqual([r["title"] for r in self.collect()[0]], ["Hotfixes: Mooncloth cooldown changed"])
        self.assertEqual(mark_done(self.conn), 1)
        self.assertEqual(self.collect()[0], [])

    def test_archivos_nuevos_de_fuentes(self):
        doc = self.folder / "guia.docx"
        with zipfile.ZipFile(doc, "w") as z:
            z.writestr("word/document.xml", (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Perlas</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>Almejas en </w:t></w:r><w:r><w:t>Tuercespina</w:t></w:r></w:p>'
                '</w:body></w:document>'))
        (self.folder / "imagen.png").write_bytes(b"x")
        rows, _ = self.collect(now=time.time())
        self.assertEqual([r["title"] for r in rows if r["source"] == "fuentes/"], ["guia.docx"])
        self.assertEqual(word_text(doc), "## Perlas\nAlmejas en Tuercespina")


class ValidarCatalogo(unittest.TestCase):
    def write(self, data):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "metodos.json"
        path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)
        return path

    def test_el_del_proyecto_esta_bien(self):
        self.assertEqual(catalog_problems(), [])

    def test_errores_tipicos(self):
        path = self.write({"metodos": [
            {"id": "bueno", "nombre": "Bueno", "tipo": "farmeo", "fuente": "x", "objetos": ["Blue Pearl"]},
            {"id": "bueno", "nombre": "Repetido", "tipo": "farmeo", "fuente": "x"},
            {"id": "Con Espacios", "nombre": "Mal id", "tipo": "farmear", "fuente": "x"},
            {"id": "prof", "nombre": "Prof", "tipo": "farmeo", "fuente": "x", "profesiones": [{"id": 999}]},
            {"id": "sin-fuente", "nombre": "Sin fuente", "tipo": "vendedor", "objetos": [{"nombre": "X", "id": "1"}]},
        ]})
        problems = "\n".join(catalog_problems(path, known_lines={182, 393}))
        self.assertIn("«bueno»: id repetido", problems)
        self.assertIn("«Con Espacios»: el id debe ser", problems)
        self.assertIn("tipo «farmear» no vale", problems)
        self.assertIn("«prof»: no existe la profesión 999", problems)
        self.assertIn("«sin-fuente»: falta «fuente»", problems)
        self.assertIn("«sin-fuente»: a un método de vendedor le falta «vendedor»", problems)
        self.assertIn("{\"nombre\": ..., \"id\": 1234}", problems)

    def test_json_roto_no_deja_sin_informe(self):
        path = self.write('{"metodos": [ {"id": "a",, } ]}')
        self.assertIn("no es un JSON válido (línea 1", catalog_problems(path)[0])
        with self.assertRaises(CatalogError):
            load_catalog(path)
        with tempfile.TemporaryDirectory() as tmp:
            conn = dbmod.connect(Path(tmp) / "p.db")
            from unittest import mock
            with mock.patch("motor.analysis.load_catalog", side_effect=CatalogError("metodos.json no es un JSON válido")):
                a = analyze(conn)
            text = build_advice_report(conn, a)
            conn.close()
        self.assertIn("No he podido leer los métodos de tus guías: metodos.json no es un JSON válido", text)


class Lanzador(unittest.TestCase):
    def test_pg_funciona_desde_otra_carpeta(self):
        asesor = Path(__file__).resolve().parent.parent / "asesor"
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run([sys.executable, str(asesor / "pg.py"), "--help"], cwd=tmp,
                                 capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("fuentes", out.stdout)
        self.assertIn("metodos", out.stdout)


if __name__ == "__main__":
    unittest.main()
