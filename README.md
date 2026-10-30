# PitiGolds

Addon personal para WoW Forever que ayuda a decidir en qué gastar el tiempo para ganar oro.

- **Fase 0 (hecha):** recoger datos (personajes, profesiones, recetas, inventario, divisas, vendedores y
  subasta) y guardarlos con su histórico en una base de datos.
- **Fase 1 (hecha):** valorar lo que tienes, ver qué crafteos dan beneficio, qué recetas te convendría
  aprender y qué vender, dónde y a qué precio. Los precios salen también en el tooltip de cada objeto.

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
5. Haz doble clic en **`informe.cmd`** para ver qué hacer: crafteos rentables, recetas que te convendría
   aprender y qué vender. Queda guardado también en `datos/informe.md`.
6. Tras el siguiente `/reload`, al pasar el ratón por un objeto verás su precio de mercado y, si sabes
   fabricarlo, cuánto cuesta y cuánto ganas.

**`estado.cmd`** da el resumen general: oro, profesiones, valor del inventario y divisas de Forever.

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
| Lo que vende cada vendedor y a cuánto (también lo que se paga con divisas) | Al hablar con el vendedor |
| Lo que paga un vendedor por cada objeto | Cuando el objeto pasa por tus bolsas, banco o recetas |

## Datos del juego

El juego solo enseña las recetas de tus profesiones. Para conocer las de **todas**, el motor descarga
las tablas del cliente de Forever que publica [wago.tools](https://wago.tools): recetas, materiales, lo que
fabrica cada una, el nivel al que se aprende y al que pasa a amarilla, verde y gris, el objeto con el que
se aprende (diseños, patrones...) y lo que cobra y paga un vendedor por cada objeto.

```
.venv\Scripts\python -m motor datos-juego
```

No hace falta acordarse: `vigilar.cmd` lo comprueba al arrancar y después una vez al día, e
`informe.cmd` cada vez que lo abres. Solo se descarga algo cuando:
- hay una versión nueva del juego (se usa la que tienes instalada), o
- la última descarga tiene más de 7 días: a veces aparecen filas que antes estaban cifradas sin que
  cambie la versión.

Si no hay conexión, se sigue con los datos que haya y se reintenta una hora después. Las tablas
quedan en `datos/juego/` y las de versiones viejas se borran solas.

Lo que el addon ve en partida (recetas al abrir tus profesiones, vendedores, subasta) no depende de
estas tablas y, si un dato está en los dos sitios, manda el del juego.

Lo que **no** traen: qué PNJ vende cada receta, porque eso está en el servidor. Para tus profesiones
lo dice el propio juego al abrir la ventana; para las demás, el informe dice si se aprende con un
objeto (y cuánto cuesta en la subasta), con el instructor o al aprender la profesión.

Con estos datos el informe añade:
- **Recetas de tus profesiones que te convendría aprender**, con el nivel que piden y cómo se aprenden.
- **Profesiones que no tienes**: cuántas recetas darían beneficio con los precios actuales y cuál es la mejor.

## Cómo decide el informe

- **Precio de mercado**: la media del 15 % más barato de las unidades a la venta. Así una sola unidad
  regalada no hunde el precio. Con 3 escaneos o más en los últimos 7 días se usa también la **mediana**,
  y nada se valora por encima de la mediana + 25 %.
- **Coste de un crafteo**: cada material al precio más barato entre la subasta y un vendedor (si no tiene
  límite de existencias). Los materiales opcionales no cuentan. Lo que se paga con divisas (Merchant's
  Favor...) se muestra aparte.
- **Lo que sacas**: precio de mercado de lo fabricado menos el 5 % de comisión, o lo que paga el vendedor
  si es más.
- **Qué hacer con cada objeto** (solo los no ligados):
  - **guardar** si es material de una receta tuya que da beneficio;
  - **vendedor** si el vendedor paga más que la subasta;
  - **esperar** si está un 20 % o más por debajo de su mediana de 7 días;
  - **subastar** en otro caso, 1 cobre por debajo del más barato (nunca por debajo de lo que paga el
    vendedor). Avisa si tienes más de lo que hay a la venta.
- **En la subasta** (columna de crafteos): cuántas unidades de lo fabricado hay a la venta. Si son muy
  pocas, el beneficio es real pero el mercado es pequeño.

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
