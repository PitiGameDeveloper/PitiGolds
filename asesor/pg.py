"""Lanza el motor de PitiGolds desde la carpeta del asesor.

    ../.venv/Scripts/python pg.py informe
    ../.venv/Scripts/python pg.py --help      (todos los comandos)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from motor.__main__ import main  # noqa: E402

sys.exit(main())
