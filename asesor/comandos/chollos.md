---
description: Comprueba fuera del juego si algún vendedor vende los posibles chollos y lo apunta
---
1. `../.venv/Scripts/python pg.py chollos`. Lista los objetos de crafteos o farmeos rentables que
   saldrían más baratos comprados a un vendedor, si alguno los vendiera, y que toca comprobar. Si
   dice que los datos de Merchant Map ya dicen quién vende cada cosa, no hay nada que mirar: díselo a
   Piti y que mire «Comprar a vendedores y revender» en el informe.
2. Para cada uno (como mucho 10 por vez), mira en Wowhead si algún PNJ lo vende (pestaña «Sold by»).
   Usa el número del objeto: primero la base de datos de Forever si Wowhead la tiene, si no la de
   Classic (`https://www.wowhead.com/classic/item=<id>`), y di cuál has usado.
3. Apunta lo que encuentres:
   - nadie lo vende: `pg.py chollo <id> nadie`;
   - alguien lo vende: `pg.py chollo <id> vende "PNJ (zona), reputación o existencias limitadas si las hay"`.
4. Resume a Piti: los que sí vende algún PNJ, lo que ganaría por unidad (sale en la lista del paso 1) y
   que pase por ese PNJ y abra su ventana para que el addon apunte el precio y las existencias de
   verdad. Hasta entonces el motor no lo cuenta como reventa.
