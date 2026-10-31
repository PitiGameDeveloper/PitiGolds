"""Novedades de tus fuentes: lo publicado en los últimos días que el asesor aún no ha revisado.

conocimiento/fuentes.json lista feeds (Wowhead, Reddit...) y canales de YouTube. Además cuenta
cualquier archivo nuevo en fuentes/ (PDF, Word, texto: una guía comprada, mensajes de Discord
copiados a un .txt...).

Solo se listan título, fecha, enlace y un resumen corto. Leer a fondo lo que interese lo hace el
asesor, y así se gastan pocos tokens: cada novedad sale una vez, y cuando el asesor la ha
revisado (fuentes --hecho) ya no vuelve a salir.
"""

from __future__ import annotations

import email.utils
import html
import json
import re
import sqlite3
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree as ET

from .config import PROJECT_ROOT

SOURCES_PATH = PROJECT_ROOT / "conocimiento" / "fuentes.json"
LOCAL_DIR = PROJECT_ROOT / "fuentes"
LOCAL_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".html", ".htm"}
DEFAULT_DAYS = 7
MAX_PER_SOURCE = 15
SUMMARY_CHARS = 300
USER_AGENT = "PitiGolds (addon personal; https://github.com/PitiGameDeveloper)"

ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class Novelty:
    key: str
    source: str
    title: str
    url: str
    published: int
    summary: str = ""


def load_sources(path: Path = SOURCES_PATH) -> list[dict]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("fuentes", [])


def feed_url(source: dict) -> str:
    if source.get("tipo") == "youtube":
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={source['channel_id']}"
    return source["url"]


def _get(url: str, timeout: float = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _plain(text: str | None) -> str:
    """Sin etiquetas HTML ni espacios de más, cortado a SUMMARY_CHARS."""
    if not text:
        return ""
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())
    return text if len(text) <= SUMMARY_CHARS else text[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


def _date(text: str | None) -> int | None:
    if not text:
        return None
    text = text.strip()
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        pass
    try:
        return int(email.utils.parsedate_to_datetime(text).timestamp())
    except (TypeError, ValueError):
        return None


def parse_feed(data: bytes, source: str) -> list[Novelty]:
    """Feeds Atom (YouTube, Reddit) y RSS 2.0 (Wowhead)."""
    root = ET.fromstring(data)
    items = []
    if root.tag == f"{ATOM}feed":
        for entry in root.iter(f"{ATOM}entry"):
            link = next((l.get("href") for l in entry.findall(f"{ATOM}link")
                         if l.get("rel", "alternate") == "alternate"), "")
            summary = (entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content")
                       or entry.findtext(f"{MEDIA}group/{MEDIA}description"))
            published = _date(entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated"))
            ident = entry.findtext(f"{ATOM}id") or link
            items.append(Novelty(key=f"{source}|{ident}", source=source, title=_plain(entry.findtext(f"{ATOM}title")),
                                 url=link, published=published or 0, summary=_plain(summary)))
    else:
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            ident = item.findtext("guid") or link
            items.append(Novelty(key=f"{source}|{ident}", source=source, title=_plain(item.findtext("title")),
                                 url=link, published=_date(item.findtext("pubDate")) or 0,
                                 summary=_plain(item.findtext("description"))))
    return items


def first_link(path: Path) -> str | None:
    """El primer enlace de un archivo de texto o Word: el vídeo de una transcripción, por ejemplo."""
    try:
        if path.suffix.lower() == ".docx":
            text = word_text(path)
        elif path.suffix.lower() == ".pdf":
            return None
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")[:20000]
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError):
        return None
    found = re.search(r"https?://[^\s<>\"')\]]+", text)
    return found.group(0).rstrip(".,;:") if found else None


def local_files(folder: Path = LOCAL_DIR) -> list[Novelty]:
    """Archivos de fuentes/. Si cambias uno, vuelve a salir como novedad. Si dentro hay un enlace
    (el vídeo de una transcripción), sale en el resumen."""
    if not folder.is_dir():
        return []
    items = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in LOCAL_SUFFIXES:
            mtime = int(path.stat().st_mtime)
            link = first_link(path)
            items.append(Novelty(key=f"archivo|{path.name}|{mtime}", source="fuentes/", title=path.name,
                                 url=str(path), published=mtime, summary=f"Enlace: {link}" if link else ""))
    return items


def word_text(path: Path) -> str:
    """Texto de un .docx, con los títulos marcados con # (las imágenes no se pueden leer)."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for paragraph in root.iter(f"{WORD}p"):
        text = "".join(t.text or "" for t in paragraph.iter(f"{WORD}t")).strip()
        if not text:
            continue
        style = paragraph.find(f"{WORD}pPr/{WORD}pStyle")
        name = style.get(f"{WORD}val", "") if style is not None else ""
        if name.lower().startswith("heading") and name[-1:].isdigit():
            text = "#" * int(name[-1]) + " " + text
        lines.append(text)
    return "\n".join(lines)


def collect(conn: sqlite3.Connection, sources: list[dict], days: float = DEFAULT_DAYS, now: float | None = None,
            fetch: Callable[[str], bytes] = _get, folder: Path = LOCAL_DIR) -> tuple[list[sqlite3.Row], list[str]]:
    """Lee las fuentes, guarda lo nuevo y devuelve lo publicado en los últimos `days` días que aún
    no se ha revisado, y los errores (una fuente caída no para las demás)."""
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    found, errors = [], []
    for source in sources:
        name = source.get("nombre") or feed_url(source)
        try:
            items = parse_feed(fetch(feed_url(source)), name)
        except (OSError, ValueError, ET.ParseError, KeyError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        pattern = source.get("filtro")
        if pattern:
            items = [i for i in items if re.search(pattern, f"{i.title} {i.summary}", re.IGNORECASE)]
        recent = sorted((i for i in items if i.published >= cutoff), key=lambda i: -i.published)
        found += recent[:source.get("max", MAX_PER_SOURCE)]
    found += [i for i in local_files(folder) if i.published >= cutoff]
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO source_items VALUES (?, ?, ?, ?, ?, ?, ?, 'nuevo')",
            [(i.key, i.source, i.title, i.url, i.published, i.summary, int(now)) for i in found])
    return pending(conn, days, now), errors


def pending(conn: sqlite3.Connection, days: float = DEFAULT_DAYS, now: float | None = None) -> list[sqlite3.Row]:
    """Lo que queda por revisar, en el mismo orden en que lo lista `fuentes`."""
    cutoff = (time.time() if now is None else now) - days * 86400
    return conn.execute("SELECT * FROM source_items WHERE status = 'nuevo' AND published >= ? "
                        "ORDER BY published DESC, key", (cutoff,)).fetchall()


def mark_done(conn: sqlite3.Connection, numbers: list[int] | None = None, days: float = DEFAULT_DAYS,
              now: float | None = None) -> int:
    """Marca como revisadas las novedades con esos números de la última lista, o todas las
    pendientes si no se dan números. Devuelve cuántas."""
    with conn:
        if not numbers:
            return conn.execute("UPDATE source_items SET status = 'visto' WHERE status = 'nuevo'").rowcount
        rows = pending(conn, days, now)
        keys = [(rows[n - 1]["key"],) for n in numbers if 1 <= n <= len(rows)]
        conn.executemany("UPDATE source_items SET status = 'visto' WHERE key = ?", keys)
        return len(keys)
