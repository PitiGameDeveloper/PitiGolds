"""Libranzas del artesano: qué zonas sale más barato hacer.

Cada misión se coge con la libranza (se compra en la subasta) y se entrega con el objeto que pide
(también de la subasta). Lo que cuesta una misión es la libranza más el objeto. Las zonas pegadas se
agrupan para hacerlas en el mismo viaje. Qué pide cada una, dónde se entrega y los grupos están en
conocimiento/libranzas.json; las cuentas las hace el addon en la subasta, con lo que ves en ella
(Writs.lua). Solo cuentan los precios de la subasta.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

WRITS_PATH = Path(__file__).resolve().parent.parent / "conocimiento" / "libranzas.json"


@dataclass
class Writ:
    item_id: int              # la libranza
    target_id: int            # el objeto que se entrega
    quantity: int = 1
    name: str = ""            # el del objeto
    profession: str = ""
    zone: str = ""
    npc: str = ""
    level: str = ""


@dataclass
class WritBook:
    writs: list[Writ] = field(default_factory=list)
    groups: list[list[str]] = field(default_factory=list)   # zonas pegadas


def load_writs(path: Path = WRITS_PATH) -> WritBook:
    if not path.exists():
        return WritBook()
    data = json.loads(path.read_text(encoding="utf-8"))
    writs = [Writ(item_id=int(w["libranza"]), target_id=int(w["objeto"]), quantity=int(w.get("cantidad", 1)),
                  name=w.get("nombre", ""), profession=w.get("profesion", ""), zone=w.get("zona", ""),
                  npc=w.get("pnj", ""), level=w.get("nivel", ""))
             for w in data.get("libranzas", [])]
    groups = [[str(z) for z in g] for g in data.get("grupos", [])]
    return WritBook(writs, groups)


def writ_problems(conn: sqlite3.Connection | None = None, path: Path = WRITS_PATH) -> list[str]:
    """Lo que está mal en libranzas.json. Con conn, comprueba también que los objetos existen."""
    if not path.exists():
        return []
    try:
        book = load_writs(path)
    except (ValueError, KeyError, TypeError) as exc:
        return [f"{path.name}: no se puede leer ({exc})"]
    known = None
    if conn is not None:
        known = {r[0] for r in conn.execute("SELECT item_id FROM gd_items")} or None
    problems, seen = [], set()
    zones = {w.zone for w in book.writs}
    for w in book.writs:
        label = w.name or str(w.item_id)
        if w.item_id in seen:
            problems.append(f"{label}: libranza repetida")
        seen.add(w.item_id)
        if not w.zone:
            problems.append(f"{label}: falta la zona de entrega")
        if w.quantity <= 0:
            problems.append(f"{label}: la cantidad tiene que ser mayor que 0")
        if known is not None:
            for item_id in (w.item_id, w.target_id):
                if item_id not in known:
                    problems.append(f"{label}: el objeto {item_id} no sale en los datos del juego")
    grouped = set()
    for g in book.groups:
        for z in g:
            if z not in zones:
                problems.append(f"grupos: «{z}» no es la zona de ninguna libranza")
            if z in grouped:
                problems.append(f"grupos: «{z}» está en dos grupos")
            grouped.add(z)
    return problems


def writ_item_ids(book: WritBook) -> set[int]:
    ids = set()
    for w in book.writs:
        ids.update((w.item_id, w.target_id))
    return ids


def writs_export(book: WritBook) -> dict:
    """Para Generated.lua: list = { [libranza] = { objeto, cantidad, nombre, profesión, zona, PNJ }, ... },
    groups = { { zona, zona }, ... }. Los nombres, por si el juego aún no tiene el objeto en la caché;
    los precios van en prices, como los del resto de objetos."""
    items = {w.item_id: [w.target_id, w.quantity, w.name, w.profession, w.zone, w.npc] for w in book.writs}
    return {"list": items, "groups": book.groups}
