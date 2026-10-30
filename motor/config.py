"""Rutas del motor. Se pueden cambiar con un config.json en la raíz del proyecto."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / "config.json"
DEFAULT_WOW_DIR = Path(r"C:\Program Files (x86)\World of Warcraft\_forever_")
ADDON_NAME = "PitiGolds"


@dataclass(frozen=True)
class Config:
    wow_dir: Path
    db_path: Path
    addon_dir: Path

    def saved_variables(self) -> list[tuple[str, Path]]:
        """Archivos PitiGolds.lua de cada cuenta: [(cuenta, ruta)]."""
        accounts = self.wow_dir / "WTF" / "Account"
        found = []
        if accounts.is_dir():
            for account in sorted(accounts.iterdir()):
                sv = account / "SavedVariables" / f"{ADDON_NAME}.lua"
                if sv.is_file():
                    found.append((account.name, sv))
        return found


def load_config(path: Path = CONFIG_FILE) -> Config:
    raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    wow_dir = Path(raw.get("wow_dir", DEFAULT_WOW_DIR))
    db_path = Path(raw.get("db_path", PROJECT_ROOT / "datos" / "pitigolds.db"))
    installed = wow_dir / "Interface" / "AddOns" / ADDON_NAME
    default_addon = installed if installed.is_dir() else PROJECT_ROOT / "addon" / ADDON_NAME
    addon_dir = Path(raw.get("addon_dir", default_addon))
    return Config(wow_dir=wow_dir, db_path=db_path, addon_dir=addon_dir)
