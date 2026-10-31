---
description: Pone nota del 1 al 10 a los farmeos y crafteos según los personajes de Piti, con el porqué y los pasos exactos
argument-hint: "[todo | ids o números de receta]"
---
Qué revisar: $ARGUMENTS (si no dice nada: lo que está «Sin revisar» en el panel y lo que se revisó hace
más de 7 días; con «todo», todo).

1. `../.venv/Scripts/python pg.py metodos` para rehacer el panel con los datos de hoy, y lee
   `../datos/panel.md`: el mejor farmeo, las dos tablas, «Sin revisar» y, de «Detalle», solo los métodos
   que vas a revisar. Para saber qué personajes tiene Piti: `pg.py estado`.
2. Por cada método, decide con los datos del panel y la situación de Piti (nivel y profesiones de cada
   personaje, lo que le falta, el oro que tiene):
   - **nota del 1 al 10**: cuánto le conviene ahora. Pesa el oro por hora (o al día en los crafteos),
     si lo puede hacer ya o cuánto le cuesta prepararlo, si sus objetos van a bajar, si el mercado es
     pequeño o con muchos vendedores, y lo fiable del dato (estimado frente a medido). Un 10 es «hazlo
     hoy»; un 1, «olvídalo».
   - **por qué**: una o dos frases con la cifra que más pesa («24 o/h estimados y ya lo puede hacer tu
     Brujo; el cuero grueso lleva una semana bajando»).
   - **pasos**: exactos y en orden, para que Piti no tenga que pensar.
     - Farmeos: con qué personaje, adónde ir (zona y punto conocido), qué matar o recoger y la ruta,
       qué guardar y qué vender al vendedor, y que lo mida con «Medir este farmeo».
     - Crafteos: solo lo que el addon no sabe calcular: dónde está la receta si los datos no lo dicen
       (vendedor y zona, reputación, botín) y trucos de la receta. La lista de la compra y el correo
       entre personajes ya los calcula el addon.
   - **receta** (crafteos con «no sé dónde se consigue»): búscalo en Wowhead (WebFetch) y apúntalo en
     `receta`: `{"como": "vendedor", "donde": "Qia (Cuna del Invierno)", "precio": "4 o", "requisito": ""}`.
3. Escríbelo en `../conocimiento/revision.json`: los farmeos por su id y los crafteos por su número de
   receta, con `nota`, `por_que`, `pasos`, `fecha` (hoy) y, si toca, `receta`. Pon también `fecha` arriba.
4. `pg.py metodos` otra vez: valida lo que has escrito y deja el addon al día.
5. Resume a Piti: el mejor farmeo para él ahora y por qué, los dos o tres crafteos que más le convienen,
   y que haga `/reload` para verlo en el addon.

No te inventes cifras: salen del panel. Si un método no tiene `por_hora` (no sale oro/h), estímalo en
`../conocimiento/metodos.json` como dice `comandos/buscar-metodos.md` antes de ponerle nota.
