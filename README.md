# PitiGolds

Addon personal para WoW Forever que ayuda a decidir en qué gastar el tiempo para ganar oro.
Ahora mismo está en la **Fase 0**: recoger datos (personajes, profesiones, recetas, inventario,
divisas y subasta) y guardarlos con su histórico en una base de datos.

## Partes

| Carpeta | Qué es |
|---|---|
| `addon/PitiGolds/` | El addon. Está enlazado dentro de WoW (`_forever_\Interface\AddOns\PitiGolds`), así que cualquier cambio aquí se ve en el juego tras un `/reload`. |
| `motor/` | Programa en Python, sin IA, que lee lo que guarda el addon y lo pasa a `datos/pitigolds.db` (SQLite). |
| `tests/` | Un WoW simulado para probar el addon fuera del juego. |

## Uso diario

1. Haz doble clic en **`vigilar.cmd`** y deja esa ventana abierta mientras juegas.
2. En el juego verás un panel pequeño, **PitiGolds**, con el botón **Exportar**. Puedes moverlo arrastrándolo.
3. En la casa de subastas aparecen dos botones encima de la ventana:
   - **PG: Materiales**: recorre materiales, consumibles, recetas y gemas. Guarda el precio mínimo y la cantidad total de cada objeto. Se puede repetir cuando quieras.
   - **PG: Completo**: toda la subasta, subasta por subasta, con cantidades por precio y número de vendedores. El servidor solo lo permite **cada 15 minutos**.
4. Pulsa **Exportar** (hace `/reload`). WoW guarda los datos en disco y `vigilar.cmd` los lee en un par de segundos.
5. Haz doble clic en **`estado.cmd`** para ver el resumen: oro, profesiones, valor del inventario y divisas de Forever.

Si `vigilar.cmd` no está abierto, no pasa nada: el addon guarda hasta 5 escaneos pendientes. A partir de ahí borra
los más antiguos, y esos precios se pierden del histórico.

## Qué recoge y cuándo

| Dato | Cuándo se actualiza |
|---|---|
| Nivel, clase, oro | Al entrar y cada vez que cambia |
| Bolsas | Al entrar y cada vez que cambian |
| Banco y banco de banda guerrera | Al abrir el banco |
| Correo | Al abrir el buzón |
| Correo enviado a tus otros personajes | Al enviarlo (cuenta para el destinatario hasta que abra su buzón) |
| Recetas conocidas, materiales y de dónde sale cada receta | Al abrir la ventana de cada profesión |
| Divisas (Merchant's Favor, Legacy...) y reputaciones | Al entrar y cada vez que cambian |
| Tus subastas puestas | Al abrir la subasta |
| Precios de la subasta | Con los botones PG |

Cada personaje queda guardado tal como estaba la última vez que lo usaste.

## Comandos en el chat

| Comando | Qué hace |
|---|---|
| `/pg export` | Igual que el botón Exportar |
| `/pg materiales` | Escaneo de materiales (con la subasta abierta) |
| `/pg completo` | Escaneo completo (con la subasta abierta) |
| `/pg estado` | Qué hay guardado y cuánto hace que lo leyó el motor |
| `/pg log` | Últimas líneas del registro, con los errores si los hay |
| `/pg panel` | Muestra u oculta el panel |

## Primer día de WoW Forever: qué comprobar

El addon está escrito para la API del cliente moderno, pero no se ha podido probar dentro de Forever todavía.

1. En la pantalla de personajes, botón **AddOns**: que PitiGolds esté activado. Si aparece como
   *desactualizado*, marca "Cargar addons desactualizados" y escribe en el chat `/dump select(4, GetBuildInfo())`
   para saber el número de versión correcto.
2. Abre una vez la ventana de cada profesión, el banco y el buzón con cada personaje.
3. Prueba los dos botones de la subasta.
4. Si algo falla, el error sale en el chat (los tres primeros de cada sesión) y queda en `/pg log`.
5. Ejecuta `estado.cmd`. La línea **APIs nuevas encontradas** lista las funciones de Forever relacionadas con
   Legacy, Merchant's Favor, cajas, etc. Con eso se programa la lectura de los Legacy Points.

## Pruebas

```
.venv\Scripts\python -m unittest discover -s tests
```

Cargan el addon en un Lua 5.1 (el mismo que usa WoW) con la API simulada, juegan una sesión completa
y pasan el resultado por el motor.

## Dónde está el addon y cómo reinstalarlo

El código vive en esta carpeta (`addon/PitiGolds/`). En WoW solo hay un **enlace** a ella, así que borrar
o reinstalar el juego no borra el addon. Por precaución, si algún día desinstalas WoW, borra antes
`_forever_\Interface\AddOns\PitiGolds`: es solo el enlace y no toca nada de aquí.

Para volver a ponerlo en el juego (tras reinstalar WoW o al clonar el repositorio en otro PC):

1. Si no existe `.venv`: `python -m venv .venv` y `.venv\Scripts\python -m pip install -r requirements-dev.txt`
   (solo hace falta para las pruebas; el motor funciona con Python a secas).
2. Doble clic en **`instalar.cmd`**.

`datos/` (tu base de datos con el histórico de precios) y `Generated.lua` no se suben a GitHub.
Para no perder el histórico, haz copia de `datos/pitigolds.db` de vez en cuando.

## Configuración

Por defecto se usa `C:\Program Files (x86)\World of Warcraft\_forever_`. Para cambiarlo, crea un
`config.json` en esta carpeta:

```json
{ "wow_dir": "D:/Juegos/World of Warcraft/_forever_" }
```
