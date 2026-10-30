"""Formato de cantidades de oro y de tiempos para los textos del motor."""

from __future__ import annotations

import time


def format_money(copper: int | float | None) -> str:
    if copper is None:
        return "?"
    copper = int(round(copper))
    sign = "-" if copper < 0 else ""
    copper = abs(copper)
    gold, rest = divmod(copper, 10000)
    silver, cop = divmod(rest, 100)
    parts = []
    if gold:
        parts.append(f"{gold:,}".replace(",", ".") + " o")
    if gold or silver:
        parts.append(f"{silver} p")
    parts.append(f"{cop} c")
    return sign + " ".join(parts)


def format_pct(fraction: float) -> str:
    """0.3 -> '30 %'"""
    return f"{fraction * 100:.0f} %"


def ago(ts: int | None) -> str:
    if not ts:
        return "nunca"
    minutes = int((time.time() - ts) / 60)
    if minutes < 1:
        return "ahora"
    if minutes < 60:
        return f"hace {minutes} min"
    if minutes < 48 * 60:
        return f"hace {minutes // 60} h"
    return f"hace {minutes // (24 * 60)} días"
