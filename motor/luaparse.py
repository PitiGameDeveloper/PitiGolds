"""Lector de archivos SavedVariables de WoW.

WoW guarda las variables de los addons como asignaciones Lua del tipo
``Nombre = { ["clave"] = valor, ... }``. Este módulo convierte ese texto en
diccionarios y listas de Python sin ejecutar nada.
"""

from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(
    r"""
      (?P<ws>\s+|--[^\n]*)
    | (?P<str>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
    | (?P<num>-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)|-?inf\b|-?nan(?:\(ind\))?)
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<op>[{}\[\]=,;])
    """,
    re.VERBOSE | re.DOTALL,
)

_SIMPLE_ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
    "\\": "\\", '"': '"', "'": "'", "\n": "\n",
}

_LITERALS = {"true": True, "false": False, "nil": None}

_INTEGER = re.compile(r"-?\d+")


class LuaParseError(ValueError):
    pass


def _unescape(body: str) -> str:
    if "\\" not in body:
        return body
    out = bytearray()
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch != "\\":
            out += ch.encode("utf-8")
            i += 1
            continue
        nxt = body[i + 1] if i + 1 < n else ""
        if nxt.isdigit():
            digits = re.match(r"\d{1,3}", body[i + 1:]).group()
            out.append(int(digits) & 0xFF)
            i += 1 + len(digits)
        else:
            out += _SIMPLE_ESCAPES.get(nxt, nxt).encode("utf-8")
            i += 2
    return out.decode("utf-8", errors="replace")


def _number(text: str) -> int | float:
    if _INTEGER.fullmatch(text):
        return int(text)
    lowered = text.lower()
    if "inf" in lowered:
        return float("-inf") if lowered.startswith("-") else float("inf")
    if "nan" in lowered:
        return float("nan")
    if "0x" in lowered:
        return int(text, 16)
    return float(text)


def _tokenize(text: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    pos = 0
    for m in _TOKEN.finditer(text):
        if m.start() != pos:
            raise LuaParseError(f"carácter inesperado en la posición {pos}: {text[pos:pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        raw = m.group()
        if kind == "str":
            tokens.append(("value", _unescape(raw[1:-1])))
        elif kind == "num":
            tokens.append(("value", _number(raw)))
        elif kind == "name" and raw in _LITERALS:
            tokens.append(("value", _LITERALS[raw]))
        else:
            tokens.append((kind, raw))
    if pos != len(text):
        raise LuaParseError(f"carácter inesperado en la posición {pos}: {text[pos:pos + 20]!r}")
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, Any]]):
        self.tokens = tokens
        self.i = 0

    def peek(self, offset: int = 0) -> tuple[str, Any] | None:
        j = self.i + offset
        return self.tokens[j] if j < len(self.tokens) else None

    def take(self) -> tuple[str, Any]:
        tok = self.peek()
        if tok is None:
            raise LuaParseError("el archivo termina antes de tiempo")
        self.i += 1
        return tok

    def is_op(self, op: str, offset: int = 0) -> bool:
        tok = self.peek(offset)
        return tok is not None and tok[0] == "op" and tok[1] == op

    def expect_op(self, op: str) -> None:
        tok = self.take()
        if tok != ("op", op):
            raise LuaParseError(f"se esperaba {op!r} y llegó {tok[1]!r} (token {self.i})")

    def value(self) -> Any:
        if self.is_op("{"):
            return self.table()
        kind, val = self.take()
        if kind != "value":
            raise LuaParseError(f"se esperaba un valor y llegó {val!r} (token {self.i})")
        return val

    def table(self) -> dict | list:
        self.expect_op("{")
        entries: dict[Any, Any] = {}
        next_index = 1
        while not self.is_op("}"):
            if self.is_op("["):
                self.take()
                key = self.value()
                self.expect_op("]")
                self.expect_op("=")
                entries[key] = self.value()
            elif self.peek() is not None and self.peek()[0] == "name" and self.is_op("=", 1):
                key = self.take()[1]
                self.take()
                entries[key] = self.value()
            else:
                entries[next_index] = self.value()
                next_index += 1
            if self.is_op(",") or self.is_op(";"):
                self.take()
            else:
                break
        self.expect_op("}")
        return _as_list_if_sequence(entries)


def _as_list_if_sequence(entries: dict[Any, Any]) -> dict | list:
    n = len(entries)
    if n and all(isinstance(k, int) and not isinstance(k, bool) for k in entries):
        if min(entries) == 1 and max(entries) == n:
            return [entries[i] for i in range(1, n + 1)]
    return entries


def parse_saved_variables(text: str) -> dict[str, Any]:
    """Devuelve {nombre_de_variable: valor} para cada asignación del archivo."""
    parser = _Parser(_tokenize(text))
    result: dict[str, Any] = {}
    while parser.peek() is not None:
        kind, name = parser.take()
        if kind != "name":
            raise LuaParseError(f"se esperaba un nombre de variable y llegó {name!r}")
        parser.expect_op("=")
        result[name] = parser.value()
        if parser.is_op(";"):
            parser.take()
    return result


def as_list(value: Any) -> list:
    """Las tablas Lua vacías o con huecos llegan como dict; esto las trata como lista."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value[k] for k in sorted(k for k in value if isinstance(k, int))]
    return []


def as_dict(value: Any) -> dict:
    """Las tablas Lua con claves 1..n llegan como lista; esto las trata como dict."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {i + 1: v for i, v in enumerate(value)}
    return {}
