# PitiGolds

Addon personal de Piti para ganar oro en WoW Forever, con un motor en Python que hace las cuentas y
un asesor de Claude Code. El detalle de cómo decide cada cosa está en `README.md` (léelo por secciones).

Todo va en español: textos del juego, código, comentarios, mensajes del motor y commits.

## Carpetas

- `addon/PitiGolds/`: el addon (Lua). Apunta lo que ve en el juego (personajes, profesiones, subasta,
  vendedores, farmeos) en sus SavedVariables. `Generated.lua` lo escribe el motor: no se edita a mano.
- `motor/`: lee esas SavedVariables (`ingest.py`) a `datos/pitigolds.db` y calcula precios, crafteos,
  farmeos, métodos y el informe. Se usa con `python -m motor <comando>` (`--help` para la lista).
- `conocimiento/`: lo que se mantiene a mano: catálogo de métodos, notas de revisión, rutas de
  recolección, cajones saqueados, libranzas y fuentes. Lo valida el motor (`python -m motor metodos`).
- `asesor/`: el asesor de oro. Tiene su propio `CLAUDE.md` y sus comandos.
- `datos/`: salida generada (base de datos, informe, panel, guías, tablas descargadas). No va a git.
- `fuentes/`: guías compradas por Piti. Privadas: no se copian a ningún sitio ni van a git.
- `tests/`: pruebas del motor y del addon.

## De dónde salen los datos

- **El addon**, en partida. Si un dato está en varios sitios, manda lo visto en el juego.
- **wago.tools**: tablas del cliente de Forever (recetas, objetos, precios de vendedor de catálogo,
  zonas). `motor/gamedata.py`.
- **Merchant Map** (addon de terceros, GPLv3; se bajan sus datos de GitHub, no se instala): qué vende
  cada PNJ. El precio de catálogo de wago.tools no dice si alguien vende el objeto; esto sí.
  `motor/merchantmap.py`.

- **QuestieDB** (datos del addon Questie, GPLv3; se bajan de GitHub, no se instala): dónde aparece
  cada PNJ y objeto del mapa en Forever, con su nombre en español, para marcar en el mapa del addon dónde
  están los bichos de cada farmeo. `motor/spawns.py`.

`python -m motor datos-juego` baja las tres últimas y comprueba si hay versión nueva.

## Desarrollo

Solo si trabajas desde la raíz del proyecto. Si vienes de `asesor/`, mandan sus reglas: no se tocan
`addon/`, `motor/` ni `tests/`.

- Python del proyecto: `.venv\Scripts\python`. Tests con unittest (no hay pytest):
  `.venv\Scripts\python -m unittest discover -s tests`. Los del addon necesitan `lupa`
  (`requirements-dev.txt`).
- Dinero siempre en cobre (enteros); `motor/money.py` lo formatea.
- Esquema de la base de datos en `motor/db.py`: tablas nuevas en `SCHEMA`, columnas nuevas en
  `ADDED_COLUMNS` para que se creen en bases antiguas. Las tablas `gd_*`, `mm_*` y `qd_*` se
  rehacen en cada importación.
- Si cambia lo que se importa de wago.tools, sube `FORMAT` en `gamedata.py`.
- El addon llega al juego con WowUp, desde las releases de GitHub: una etiqueta `vX.Y.Z` las crea
  (versión igual en `PitiGolds.toc` y `Core.lua`). Para probar sin publicar: `probar-addon.cmd`.
- Cuando cambie lo que ve Piti (informe, panel, comandos), actualiza `README.md`; si afecta al asesor,
  también `asesor/CLAUDE.md` o su guion en `asesor/comandos/`.
