# PitiGolds

Addon personal para WoW Forever que ayuda a decidir en qué gastar el tiempo para ganar oro.

- **Fase 0 (hecha):** recoger datos (personajes, profesiones, recetas, inventario, divisas, vendedores y
  subasta) y guardarlos con su histórico en una base de datos.
- **Fase 1 (hecha):** valorar lo que tienes, ver qué crafteos dan beneficio, qué recetas te convendría
  aprender y qué vender, dónde y a qué precio. Los precios salen también en el tooltip de cada objeto.
- **Fase 2 (hecha):** señales de mercado y previsión a 7 días (con su acierto medido sobre el propio
  historial), y registro de tus farmeos con tu oro por hora real.
- **Fase 3 (hecha):** comparador de métodos, guía de subida de profesión con su coste y cuándo se
  recupera la inversión según las horas que juegas. Además, los métodos de tus guías valorados con
  tus precios y tus personajes, las esperas de las recetas y el talento de Legacy de subir profesión.
- **Fase 4 (hecha):** el asesor de Claude Code (`asesor/`), que te dice qué hacer cada sesión y busca
  métodos nuevos en lo publicado los últimos 7 días.
- **Fase 5 (hecha):** la ventana de métodos del addon: el mejor farmeo para ti, la pestaña de farmeos y
  la de crafteos, con lo que te falta para cada uno y los pasos exactos.

## La ventana de métodos (Fase 5)

En el panel pequeño del juego, **Mejor farmeo** (o `/pg metodos`) abre la ventana de métodos. Arriba te
dice qué hacer, y debajo hay dos pestañas. Se calcula sin IA cada vez que el motor lee tus datos, así que
cada método guardado se vuelve a comprobar con tus últimos precios. Lo nuevo se ve tras un `/reload`.

**Arriba, el mejor farmeo para ti ahora mismo:**
- **Mejor farmeo: X**: el que ya puedes hacer con algún personaje, llega al mínimo de oro por hora y da al
  menos el 60 % del mejor de todos. Si hay crafteos en verde, te dice que los hagas antes (son pocos
  minutos al día porque el mercado no absorbe más).
- **Lo que ya puedes hacer rinde poco**: los que rinden más piden prepararse. Salen los tres mejores, con
  lo que le falta al personaje más cercano y lo que cuesta (horas y oro).
- **Ningún método guardado da dinero ahora**: se han saturado o ya no funcionan. Toca una sesión de
  investigación con el asesor (dile «investiga»).

**Pestaña Farmeos** (farmeos, pesca y mazmorras, más los que has medido tú):

| Columna | Qué es |
|---|---|
| Farmeo | El método. «En espera» si el asesor tiene una pregunta pendiente para ti: no se recomienda hasta que la contestes. |
| Nota | Del 1 al 10, la que le pone el asesor según tus personajes (`/revisar`). |
| Rinde | Verde: da al menos el 60 % del mejor. Amarillo: llega al mínimo (5 oro/h; `ajustes --minimo-hora`). Rojo: no da dinero. |
| Oro/h | Medido si lo has medido; si no, el esperado (con *): lo que da en una hora según la investigación, valorado con tus precios. De cada objeto solo va a la subasta lo que el mercado absorbe en tus horas de juego; el resto, al vendedor. Si sus objetos van a bajar, cuenta lo que valdrán dentro de 7 días. |
| ¿Puedo? | Sí, con qué personaje, o no; entre paréntesis lo que pide (nivel, profesión). |
| Nivel | El recomendado y, entre paréntesis, desde cuál ya se puede aunque rinda menos. |

**Pestaña Crafteos:**

| Columna | Qué es |
|---|---|
| Crafteo | Lo que se fabrica y su profesión. |
| Nota | La del asesor. |
| Beneficio/u | Por unidad, ya sin materiales ni comisión (* si los precios son de pocos escaneos). |
| Al día | Las que absorbe el mercado al día sin hundir el precio (o las que deja la espera de la receta). |
| ¿Puedo? | Verde: ya la sabe hacer un personaje. Amarillo: casi (le faltan 25 puntos o menos y la receta se compra en un momento). Naranja: le falta algo (hasta 75 puntos, un poco de reputación o de divisas, o no se sabe de dónde sale la receta). Rojo: falta mucho (más puntos, receta de botín, mucha reputación o ninguna profesión libre). |

**Al pulsar un método** se despliega lo que se sabe de él: la opinión del asesor y sus pasos, de dónde
sale el oro, quién puede hacerlo y, si nadie, qué le falta al más cercano y cómo prepararlo. Para subir
Botánica, Minería, Desollar o Pesca, la ruta por zonas según tu facción (`conocimiento/recoleccion.json`).
**Farmear este** (o **Craftear este** en los crafteos) lo pasa a la ventana de farmeos activos; los
activos llevan » delante y el botón cambia a **Quitar de activos**. Puedes tener varios a la vez, de las
dos pestañas.

En los crafteos salen los pasos exactos con tus personajes:
- **Si nadie sabe la receta**: «Conéctate con tu Mago (Sastrería 235), viaja a X y cómprale la receta
  a Y». Cuando la aprendas, pulsa **Actualizar**.
- **Si ya la sabes**, la lista de la compra con lo que tienes, contando bolsas, banco, buzón y banco de
  banda de todos tus personajes: qué le tiene que enviar cada personaje por correo al que fabrica, qué
  comprar a qué vendedor (y en qué zona) y en la subasta, cuántas fabricar y a qué precio ponerlas.

La zona de cada vendedor se apunta al abrir su ventana. `datos/panel.md` tiene lo mismo que la ventana,
para leerlo en el PC.

## Farmeos activos

Una ventana pequeña para tenerla abierta mientras juegas, como la lista de misiones: se arrastra por el
título, cambia de tamaño con la esquina de abajo a la derecha y se cierra con la X (la vuelve a abrir el
botón **Farmeos activos** del panel o `/pg activos`). Cada farmeo activo va en su recuadro, uno debajo
de otro:
- **Farmeos**: lo que llevas de sus objetos (por ejemplo, las pieles) con lo que vale cada uno, el total
  y el oro por hora. Solo cuenta lo suyo: sus objetos y, si da monedas, el oro suelto y la basura gris.
  Si el catálogo no dice qué da (o es uno que mediste tú), cuenta todo.
- **Crafteos**: los materiales que tienes en las bolsas de los que hacen falta (5/8, en verde si ya
  llega) para las que absorbe el mercado en un día, y cuántas puedes fabricar ya.

Cada recuadro tiene su reloj con **Empezar/Parar**, **Reiniciar** (reloj y cuenta a cero) y **Acabar**
(dice en el chat cuánto has sacado y lo quita). El reloj se pone en marcha solo con el primer botín del
farmeo, y solo cuenta lo que entra mientras corre. Tras un `/reload` o un cambio rápido de personaje
sigue en marcha sin contar el rato fuera; si pasa más de media hora, queda parado. Lo que farmeas con un
farmeo en marcha queda apuntado con su id, así el motor mide tu oro por hora real de ese método (ya no
hace falta `/pg farmeo`).

**Al pulsar el nombre** se despliega el resto: lo esperado por hora, el precio y total de cada objeto, las
monedas, la zona y los bichos; en los crafteos, el beneficio, lo que tienes en el banco, los pasos y
**-**/**+** para cambiar cuántas fabricar.

**Flecha.** Lleva al sitio del primer farmeo activo que esté en marcha (o, si no hay ninguno, del
primero), como TomTom: gira según hacia dónde miras y dice los metros. Si el catálogo solo da la zona,
lleva hasta ella y avisa al entrar. Además pone el punto en el mapa del juego si el cliente lo permite.
Se mueve arrastrándola; clic derecho la esconde y `/pg flecha` la vuelve a enseñar.

**Bichos.** Sobre la placa de cada bicho de tus farmeos sale una calavera (hacen falta las placas de
enemigos, tecla **V**). No es una marca de banda: esas no se pueden poner desde un addon, así que la
dibuja el addon y solo la ves tú. Los bichos salen del catálogo (`bichos`) y de lo que aprende el addon:
- al lootear un objeto de un farmeo en marcha, apunta el bicho que lo soltó (hasta 6 por farmeo; los
  de «cualquier zona», como desollar mientras subes, no aprenden);
- **Añadir objetivo** en el recuadro desplegado apunta el bicho que tengas seleccionado (y **Quitar
  objetivo**, si ya estaba).

**Macro «PG Objetivo».** Al activar el primer farmeo con bichos el addon crea un macro general con ese
nombre (Esc > Macros). Ponlo en tu barra: cada vez que lo pulsas selecciona el bicho más cercano de tus
farmeos activos. Es uno solo para todo: el addon le reescribe los `/target` al activar o acabar un
farmeo, o al aprender un bicho. `/target` elige el más cercano cuyo nombre **empieza** por lo que le das,
así que «Arpía» vale para todas las arpías; con nombres distintos los prueba uno detrás de otro, primero
los que tienes a la vista. Cada pulsación selecciona un bicho y nada más (no ataca ni hace nada por ti).
En combate WoW no deja cambiar macros: si toca cambiarlo, se hace al salir del combate. `/pg objetivo`
dice qué busca.

## El asesor (Fase 4)

La carpeta `asesor/` es un asesor de Claude Code que usa tu suscripción: sin claves de API ni gasto
extra. Ábrela como carpeta de una sesión en Claude Code (la app de escritorio, pestaña Code) y pídele:

| Pídele | Qué hace |
|---|---|
| «¿Qué hago hoy? Tengo 2 horas» (`que-hago`) | Lee tus datos y te da un plan: qué vender y a qué ritmo, qué craftear, qué farmear y qué medir. |
| «Investiga» o «Busca métodos nuevos» (`buscar-metodos`) | Sesión de investigación: lee lo que has dejado en `fuentes/` y lo publicado en los últimos 7 días, y añade al catálogo los métodos concretos con lo que dan por hora. Lo que no se entienda sin ver un vídeo te lo pregunta, con el enlace. |
| «Revisa los métodos» (`revisar`) | Pone nota del 1 al 10 a cada farmeo y crafteo según tus personajes, con el porqué y los pasos. Sale en el addon. |
| «Mira los chollos» (`chollos`) | Comprueba en Wowhead si algún vendedor vende los posibles chollos y lo apunta (solo hace falta si no se han podido bajar los datos de Merchant Map). |
| «¿Me compensa subir Sastrería?» (`subir-profesion`) | Guía de subida, coste, y si se recupera según el comparador. |

El asesor no hace cuentas: las hace el motor y él las lee y te las explica. Solo edita los archivos de
`conocimiento/` (métodos, sus notas, rutas de recolección y fuentes); el código no lo toca.

**Transcripciones de vídeos**: guárdalas como `.txt` (o `.docx`) en `fuentes/` con el enlace del vídeo
dentro, por ejemplo en la primera línea. El asesor no puede ver vídeos: si la transcripción no basta («farmea
aquí» señalando el mapa), te pregunta lo concreto con el enlace y el minuto, y el método queda en espera.

**Para gastar pocos tokens**, `buscar-metodos` no lee internet a lo loco:

```
.venv\Scripts\python -m motor fuentes
```

Este comando lista solo lo nuevo y aún sin revisar: título, fecha y resumen de cada novedad. Lo sacan
los feeds de `conocimiento/fuentes.json` (de entrada, las noticias de Forever de Wowhead y r/woweconomy)
y los archivos nuevos que dejes en `fuentes/`. El asesor criba por el título y abre a fondo como mucho
5. Cada novedad sale una sola vez.
- **YouTube**: se añaden canales con su código `UC...`. Solo se leen el título y la descripción, no
  los subtítulos.
- **Discord**: no se puede leer sin cuenta. Copia lo que te interese a un `.txt` en `fuentes/` y saldrá
  como novedad.

**Activar los comandos con barra (`/que-hago`...).** Sin esto el asesor funciona igual, pidiéndoselo con
tus palabras. Claude no puede escribir su propia configuración, así que este paso lo haces tú:

1. Crea la carpeta `asesor\.claude\commands\` y copia en ella los archivos de `asesor\comandos\`.
2. Si quieres que no te pida permiso cada vez que lanza el motor o mira Wowhead, crea
   `asesor\.claude\settings.json` con esto:

   ```json
   {
     "permissions": {
       "additionalDirectories": [".."],
       "allow": [
         "Bash(../.venv/Scripts/python pg.py:*)",
         "WebSearch",
         "WebFetch(domain:www.wowhead.com)",
         "WebFetch(domain:www.reddit.com)",
         "WebFetch(domain:www.youtube.com)"
       ]
     }
   }
   ```

## Qué te conviene hacer (comparador)

Es lo primero del informe. Tu **referencia** es tu mejor farmeo medido, y cada método se compara con
ella a lo largo de 4 semanas según las horas que juegas (por defecto 10 a la semana):

```
.venv\Scripts\python -m motor ajustes --horas-semana 12 --semanas 4
```

Entran tus farmeos, tus crafteos rentables, la reventa desde vendedores, las mejores recetas de tus
profesiones que aún no sabes y la mejor receta de cada profesión que no tienes. Para cada uno: oro por
hora hoy y en 7 días, máximo al día (crafteos y reventas), **inversión** (oro y horas de subir la
profesión y aprender la receta), **en cuánto se recupera**, **cuánto ganas** frente a tu referencia en
esas semanas y un **veredicto**.

Las cuentas:
- Un **farmeo** ocupa tu tiempo: las horas de preparación no dan nada y el oro invertido se resta.
- Un **crafteo o una reventa** los limita el mercado, no tu tiempo, así que se hacen además de farmear:
  suman lo que el mercado absorbe cada día y restan el rato que le quitan a tu farmeo.
- El oro por hora va del de hoy al previsto a 7 días. Si tu farmeo actual va a bajar, un método nuevo
  puede compensar aunque hoy dé casi lo mismo.

Ejemplo: farmeas a 10 o/h y otro farmeo da 12 o/h, pero hay que invertir 300 o y 8 horas. Jugando 10 h a
la semana no compensa en 4 semanas (se recuperaría en unas 198 h de juego). Si tu farmeo va a bajar a
6 o/h, una preparación más barata sí compensa.

## Guía de subida de profesión

```
.venv\Scripts\python -m motor guia herreria --desde 50 --hasta 150
```

Elige en cada nivel la receta con menor coste esperado por punto: coste de los materiales menos lo que
paga un vendedor por lo fabricado, dividido por la probabilidad de subir (siempre en naranja; en
amarilla y verde baja hasta 0 al volverse gris). Da los tramos («del 1 al 36: Piedra de afilar férrea,
unas 44 veces»), la **lista de la compra** descontando lo que ya tienes entre todos tus personajes, el
**oro que tienes que gastar**, el coste real y el tiempo. Queda guardada en `datos/guias/`. No incluye lo
que cobra el instructor por enseñar recetas y subir de rango, porque no viene en los datos del juego.
Las recetas con espera de una hora o más (tela lunar, transmutaciones) no se usan para subir.

**Talento de Legacy que sube la probabilidad de subir habilidad.** Si lo tienes, dile cuánto suma:

```
.venv\Scripts\python -m motor ajustes --legado-subida 20
```

Se aplica a las recetas amarillas y verdes, multiplicando su probabilidad (sin pasar del 100 %): con
+20 %, una receta al 50 % pasa al 60 %. Cómo funciona exactamente el talento está por confirmar en el juego.

## Métodos de tus guías

`conocimiento/metodos.json` es un catálogo de métodos sacados de guías, vídeos y otras fuentes: qué se
farmea, dónde, a qué nivel, con qué profesión y qué objetos dan el dinero. El primero es la guía de
Studen (v1.0): 68 métodos entre farmeos, pesca, mazmorras, crafteos, inversiones, vendedores con
existencias limitadas y el talento de Legacy Estudio dedicado.

El motor **no usa las cifras de oro de las guías** (cada servidor es distinto). Cada método se valora
con lo tuyo:
- lo que valen hoy sus objetos en la subasta, o lo que paga el vendedor si es más;
- **mercado al día**: lo que podrías sacar al día vendiendo sus objetos sin hundir el precio;
- si alguno de tus personajes puede hacerlo ya, o qué te falta (nivel o profesión);
- **lo que da por hora** (`por_hora`: cuántos objetos y cuánto oro suelto), que apunta el asesor al
  investigar y el motor valora con tus precios;
- y tu oro por hora de verdad cuando lo mides: pulsa **Farmear este** en la ventana de métodos y lo
  que farmees con su reloj en marcha queda apuntado con su id (también vale `/pg farmeo <id>` al empezar
  y `/pg farmeo fin` al acabar). Desde ahí manda tu medida.

Los diez mejores salen en el informe y todos en `datos/metodos.md`:

```
.venv\Scripts\python -m motor metodos
```

Los objetos se reconocen por su nombre en inglés o en español, así que se puede copiar el nombre de una
guía en inglés. Lo que no aparece en los datos del juego (mucho equipo antiguo solo lo conoce el
servidor) se puede dar con su número: `{"nombre": "Shadowfang", "id": 1482}`. Para añadir métodos basta
con seguir el formato del archivo; en la Fase 4 lo hará el asesor con lo que encuentre.

Las guías que compres, guárdalas en `fuentes/`: no se suben a GitHub.

## Partes

| Carpeta | Qué es |
|---|---|
| `addon/PitiGolds/` | El addon. Está enlazado dentro de WoW (`_forever_\Interface\AddOns\PitiGolds`), así que cualquier cambio aquí se ve en el juego tras un `/reload`. |
| `motor/` | Programa en Python, sin IA, que lee lo que guarda el addon y lo pasa a `datos/pitigolds.db` (SQLite). |
| `tests/` | Un WoW simulado para probar el addon fuera del juego. |
| `asesor/` | El asesor de Claude Code: sus instrucciones (`CLAUDE.md`), sus guiones (`comandos/`) y `pg.py`, que lanza el motor desde ahí. |
| `conocimiento/` | Métodos de tus guías (`metodos.json`), escritos con otras palabras; las notas del asesor (`revision.json`); rutas de recolección (`recoleccion.json`), y las fuentes que revisa el asesor (`fuentes.json`). |
| `fuentes/` | Las guías tal cual (PDF, Word...). Solo en tu PC: no se suben a GitHub. |

## Uso diario

1. Haz doble clic en **`vigilar.cmd`** y deja esa ventana abierta mientras juegas.
2. En el juego verás un panel pequeño, **PitiGolds**, con lo que llevas ganado en la sesión y los botones
   **Mejor farmeo**, **Sesión** y **Farmeos activos**. Se pone al día en cuanto looteas. Puedes moverlo
   arrastrándolo.
3. En la casa de subastas aparecen dos botones encima de la ventana:
   - **PG: Materiales**: recorre materiales, consumibles, recetas y gemas. Guarda el precio mínimo y la cantidad total de cada objeto. Se puede repetir cuando quieras.
   - **PG: Completo**: toda la subasta, subasta por subasta, con cantidades por precio y número de vendedores. El servidor solo lo permite **cada 15 minutos**.
4. No hace falta exportar nada: el addon apunta solo lo que pasa (al entrar con cada personaje, al lootear,
   al escanear...) y WoW lo guarda en disco al cambiar de personaje, al salir del juego o con `/reload`.
   `vigilar.cmd` lo lee en un par de segundos, y el addon lo enseña al entrar con el siguiente personaje o
   tras otro `/reload`.
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

## Mercado: tendencias y previsión

Con al menos 3 escaneos repartidos en más de un día, el motor calcula para cada objeto que te afecta
(lo que tienes, lo que farmeas y lo que entra o sale de tus recetas):

- **Tendencia del precio** y lo limpia que es: una caída constante cuenta mucho; un precio que va y
  viene, poco.
- **Unidades a la venta y número de vendedores**: si cada vez hay más, el precio acabará cediendo.
- **Ventas al día**: unidades que había a buen precio y desaparecen entre dos escaneos completos
  seguidos (como mucho 12 horas de diferencia). Incluye las que alguien retiró para bajarles el precio,
  así que es una cota alta.
- **Días de oferta**: para cuántos días de ventas hay género.
- **Riesgo de bajada (0-100)** y **previsión a 3 y 7 días**, que mezcla la tendencia (a mitad de fuerza)
  con la vuelta a la mediana según lo limpia que sea la tendencia.

Son reglas fijas, sin IA, y su acierto se mide repitiendo la previsión en momentos pasados: el informe
dice qué porcentaje acertó y cuánto habría acertado decir siempre «estable». Si no supera a eso, no te
fíes de ella. Con confianza media o alta, la previsión cambia los consejos: lo que tiende a bajar se
vende ya aunque esté barato, y lo que sube se espera. En el tooltip aparece «baja» o «sube».

## Tus farmeos

El addon apunta solo lo que ganas mientras juegas: objetos que entran en las bolsas y oro, en tramos
de 5 minutos por zona. No cuenta lo que entra con el correo, la subasta, el banco, un vendedor, un
intercambio o la ventana de una profesión abiertos. Puedes poner nombre a lo que haces con
`/pg farmeo <nombre>`; si no, el motor lo deduce de lo que sacas (minería, hierbas, tela, oro...).

El motor une los tramos en sesiones (15 minutos sin ganar nada cortan la sesión) y calcula el **oro por
hora real** con los precios de hoy y con los previstos a 7 días. Así sabes cuánto rinde de verdad cada
farmeo y si va a dejar de compensar.

**En el juego, al momento.** El panel pequeño se pone al día en cuanto entra algo en las bolsas o cambia
tu oro: lo que llevas en la sesión, a cuánto sale por hora y lo de la última hora. El botón **Sesión**
(o `/pg sesion`) abre la lista de lo farmeado: cada objeto con cuántos llevas, su precio y el total, de
más a menos valioso. **Reiniciar** empieza a contar desde cero (`/pg sesion reiniciar`).
- La sesión es de cada personaje. Sigue tras un `/reload` o un cambio rápido de personaje, sin contar el
  rato fuera; si pasas más de 30 minutos sin jugar con él, empieza otra.
- Cada objeto vale lo que da en la subasta quitando la comisión y el depósito (ver «Cómo decide el
  informe»), o lo que paga el vendedor si paga más (sale con «(v)»). El precio de la subasta es el del último escaneo si el motor aún no lo ha leído, así
  que si escaneas a media sesión, la cuenta cambia en ese momento; si no, el del motor.

## Tu negocio en la subasta

Comprar materiales, fabricar y vender en la subasta también es una forma de hacer oro, pero no la
mide el registro de farmeos (que no cuenta nada con la subasta, la profesión o el correo abiertos).
Para eso el addon lleva una contabilidad aparte, que se apunta sola:

- **Compras de materiales** en la subasta: qué, cuántos y el precio total.
- **Crafteos**: cada vez que fabricas una receta.
- **Lo que pones a la venta**: cuántos, a qué precio y el depósito.
- **Ventas** (y compras de objetos que llegan por correo): al recoger el dinero o el objeto del correo,
  con su factura (precio, comisión y depósito devuelto). Cada correo cuenta una sola vez.
- **Tiempo de gestión**: el rato con la subasta, la profesión o el correo abiertos (como mucho 30
  minutos seguidos por ventana, por si te ausentas).

El informe saca el **beneficio real** de cada cosa que fabricas o revendes: lo cobrado menos la
comisión, menos lo que te costaron los materiales a ti (o a precio de mercado si no los compraste) y
menos los depósitos sin recuperar. Y el **oro por hora de gestión**, comparable con el de tus farmeos.
Lo que vendes de lo farmeado no cuenta como negocio: ya está en tus farmeos.

En los crafteos rentables, la columna **«Como mucho al día»** responde a la diferencia clave con
farmear: un farmeo lo limita tu tiempo, pero un crafteo lo limita el mercado. Supone que puedes vender
un 30 % de lo que se vende al día sin hundir el precio, y dice cuánto deja eso y cuánto tiempo lleva
(10 segundos por unidad hasta que haya medidas tuyas; con 20 crafteos apuntados usa tu tiempo real).

## Vendedores

Dos datos distintos que conviene no mezclar:

| Dato | ¿Se sabe sin hablar con el vendedor? |
|---|---|
| Cuánto cobraría un vendedor por un objeto | Sí: viene en los datos del juego, para todos los objetos |
| Si algún vendedor lo vende, cuál, dónde y con qué condiciones | Sí, con los datos de Merchant Map; y del todo al abrir su ventana |

Los datos del juego dan precio de vendedor también a objetos que no vende nadie (el paño de lino,
por ejemplo): de 12.500 objetos con precio, solo unos 1.900 los vende algún PNJ. Para saber cuáles,
`datos-juego` baja también los datos del addon [Merchant Map](https://github.com/knofle/MerchantMap)
(GPLv3), una vez por semana. No hace falta instalarlo. Trae dos listas:

- **Comprobados en Forever** (unos 220 vendedores): precio de verdad, existencias limitadas, si se
  paga con divisa y lo del Classic que ya no venden.
- **Lista del Classic** (sacada de Questie, unos 1.000 vendedores): qué vende cada uno, sin precio.
  Se cuenta al precio de los datos del juego y sale como «sin comprobar».

Para el coste de un material manda, por este orden: el vendedor que has visto tú, el comprobado
de Merchant Map y el de la lista del Classic. Solo cuentan los vendedores de la facción de tus
personajes, sin límite de existencias, que cobran en oro y que no son de fiestas. El precio
comprobado lleva los descuentos de reputación de quien lo vio, así que si se parece (±15 %) se usa
el de los datos del juego. Lo que no sale en Merchant Map se da por no vendido: ya no aparece la
pista «si lo vende un vendedor». Si ves en el juego que alguien sí lo vende, al abrir su ventana
queda apuntado y manda.

Al abrir un vendedor se apunta lo que vende (con quién lo viste, porque el precio puede llevar
descuentos de reputación o de Legacy) y se borra lo que ya no vende. El panel dice quién vende cada
material y cada receta, y en qué zona.

El informe añade:
- **Comprar a vendedores y revender**: lo que un vendedor (visto por ti o de Merchant Map) vende por
  debajo de lo que pagan en la subasta, con lo que da como mucho al día. La columna «Dato» dice de
  dónde sale el precio; los «sin comprobar» conviene confirmarlos abriendo su ventana.
- **Posibles chollos de vendedor**: solo si no se han podido bajar los datos de Merchant Map. Son
  objetos de tus crafteos o farmeos que en la subasta (ya sin
  comisión) se pagan al menos un 30 % más de lo que costaría comprárselos a un vendedor, si alguno los vende. Hay que mirar fuera del juego si alguien los vende:
  - `python -m motor chollos` lista los que toca comprobar;
  - `python -m motor chollo <id> nadie` o `python -m motor chollo <id> vende "Grimtak (Ratchet), Honorable"`
    apunta lo encontrado (en la Fase 4 lo hará el asesor de Claude).

  Si sale «nadie», se vuelve a mirar a la semana, a las dos y a las cuatro, y después solo con
  versiones nuevas del juego. Los materiales de botín (tela, mineral, hierbas, cuero...) y lo que
  farmeas se miran una vez y después solo con versiones nuevas.

## Datos del juego

El juego solo enseña las recetas de tus profesiones. Para conocer las de **todas**, el motor descarga
las tablas del cliente de Forever que publica [wago.tools](https://wago.tools): recetas, materiales, lo que
fabrica cada una, el nivel al que se aprende y al que pasa a amarilla, verde y gris, el objeto con el que
se aprende (diseños, patrones...), la **espera** de las que la tienen y lo que cobra y paga un vendedor
por cada objeto. Los nombres de los objetos se bajan también en inglés, para reconocer los de las guías.

Esperas según los datos de Forever: tela lunar, 4 días; transmutar arcanita, 2 días; el resto de
transmutaciones, 23 h, y todas comparten la misma espera. El pellejo basto curado no tiene espera en estos
datos, aunque en el Classic original sí la tenía.

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
objeto (y cuánto cuesta en la subasta), con el instructor o al aprender la profesión. Si el objeto
lo vende un PNJ, el panel lo saca de Merchant Map (ver «Vendedores»).

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
- **Lo que sacas**: precio de mercado de lo fabricado menos el 5 % de comisión y el depósito, o lo que
  paga el vendedor si es más.
- **Depósito**: en Forever cada puesta en la subasta (una pila) cuesta como mínimo 1 plata, que se devuelve
  si se vende y se pierde si no. Con la competencia de los megaservidores se cuenta una puesta perdida por
  cada pila vendida, repartida entre sus unidades: 5 cobre por unidad en lo que se apila de 20, 20 en lo
  que va de 5 en 5 y la plata entera en lo que no se apila (equipo, varitas). Por eso lo barato que no se
  apila suele ir mejor al vendedor. Vale para todo: farmeos, crafteos, qué vender y el addon.
- **Qué hacer con cada objeto** (solo los no ligados):
  - **guardar** si es material de una receta tuya que da beneficio;
  - **vendedor** si el vendedor paga más que la subasta;
  - **esperar** si está un 20 % o más por debajo de su mediana de 7 días;
  - **subastar** en otro caso, 1 cobre por debajo del más barato (nunca por debajo de lo que paga el
    vendedor). Avisa si tienes más de lo que hay a la venta.
- **Ritmo de venta**: se supone que puedes vender un 30 % de lo que se vende al día en toda la subasta
  sin hundir el precio. Si tienes 100 de algo que se vende a 10 al día, el informe dice que pongas unas 3
  al día y que tardarás unos 33 días, cuánto sacarás de media por unidad si el precio va a la baja,
  si hay muchos vendedores que te van a rebajar el precio, y si lo que no vas a colocar en dos semanas
  compensa vendérselo al vendedor. El total del consejo ya cuenta con ese precio medio.
- **Crafteos con mercado pequeño**: si puedes fabricar más de lo que se vende, la columna «Ya puedes
  hacer» dice cuántas hacer al día, y el beneficio enseña también el previsto a 7 días («ya no
  compensa» si el precio va a dejarlo en pérdidas). Lo mismo en la reventa desde vendedores.
- **Crafteos con espera** (tela lunar, transmutaciones): el máximo al día es lo que deja la espera, una por
  cada personaje que sabe la receta. Por eso compensa tener varios alters con la misma profesión.
- **El 30 % de los posibles chollos** es solo un filtro para decidir qué merece la pena mirar fuera del
  juego, no una garantía de beneficio: si se confirma un vendedor, la reventa pasa por las mismas cuentas
  de ritmo y previsión.

Cada personaje queda guardado tal como estaba la última vez que lo usaste.

## Comandos en el chat

| Comando | Qué hace |
|---|---|
| `/pg materiales` | Escaneo de materiales (con la subasta abierta) |
| `/pg completo` | Escaneo completo (con la subasta abierta) |
| `/pg estado` | Qué hay guardado y cuánto hace que lo leyó el motor |
| `/pg log` | Últimas líneas del registro, con los errores si los hay |
| `/pg panel` | Muestra u oculta el panel |
| `/pg sesion` | Abre la lista de lo farmeado en la sesión (igual que el botón Sesión); `/pg sesion reiniciar` empieza otra |
| `/pg metodos` | Abre la ventana de métodos (igual que el botón Mejor farmeo) |
| `/pg activos` | Muestra u oculta la ventana de farmeos activos (igual que el botón Farmeos activos) |
| `/pg flecha` | Enseña o esconde la flecha hacia tu farmeo activo |
| `/pg objetivo` | Dice qué bichos busca el macro «PG Objetivo» (y lo crea si lo has borrado) |
| `/pg farmeo Cobre en Durotar` | Pone nombre a lo que farmeas desde ahora (`/pg farmeo fin` lo quita; `/pg farmeo` a secas dice cuánto llevas en la última hora) |

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
6. Activa un farmeo con bichos y comprueba la flecha (que apunte bien al girar), la calavera sobre las
   placas y el macro «PG Objetivo». Los nombres de los bichos del catálogo son el principio del nombre
   en español: si alguno no coincide, el addon los aprende al lootear.

## Pruebas

```
.venv\Scripts\python -m unittest discover -s tests
```

Cargan el addon en un Lua 5.1 (el mismo que usa WoW) con la API simulada, juegan una sesión completa
y pasan el resultado por el motor.

## Instalar y actualizar el addon con WowUp

El código vive en esta carpeta (`addon/PitiGolds/`). Al juego llega con WowUp, desde las releases de GitHub.

Para ponerlo en el juego (la primera vez, tras reinstalar WoW o al clonar el repositorio en otro PC):

1. Si no existe `.venv`: `python -m venv .venv` y `.venv\Scripts\python -m pip install -r requirements-dev.txt`
   (solo hace falta para las pruebas; el motor funciona con Python a secas).
2. Doble clic en **`instalar.cmd`**. Si queda un enlace de la instalación antigua, lo quita.
3. En WowUp, con WoW Forever elegido: **Obtener addons → Instalar desde URL** y pega
   `https://github.com/PitiGameDeveloper/PitiGolds`.
4. Con el addon ya instalado, ejecuta `estado.cmd` para crear `Generated.lua` y haz `/reload` en el juego.

**Después de cada actualización de WowUp hay que repetir el paso 4.** WowUp reemplaza la carpeta entera y
`Generated.lua` no viene en el zip, porque es tuyo y lo escribe el motor. Mientras falte, el addon sigue
apuntando datos, pero no tiene precios ni métodos. Con `vigilar.cmd` abierto basta con dos `/reload`: el
primero guarda los datos y hace que el motor lo escriba, y el segundo lo carga. Tus datos no se pierden:
las SavedVariables están en `WTF`, fuera de la carpeta del addon.

### Publicar una versión

1. Cambia la versión en `PitiGolds.toc` y en `ns.VERSION` de `Core.lua`, y haz commit.
2. Crea la etiqueta y súbela (cambia `0.4.1` por tu versión):

   ```
   git tag v0.4.1
   git push origin main v0.4.1
   ```

GitHub crea la release con `PitiGolds-0.4.1-forever.zip` (`.github/workflows/publicar-addon.yml`), y WowUp
la ofrece como actualización. Si la etiqueta no coincide con la versión del addon, no se publica nada.

Para probar cambios sin publicar, **`probar-addon.cmd`** copia el addon de este repositorio al juego. Luego
haz `/reload`. La siguiente actualización de WowUp lo deja como en la release.

`datos/` (tu base de datos con el histórico de precios) y `Generated.lua` no se suben a GitHub.
Para no perder el histórico, haz copia de `datos/pitigolds.db` de vez en cuando.

## Configuración

Por defecto se usa `C:\Program Files (x86)\World of Warcraft\_forever_`. Para cambiarlo, crea un
`config.json` en esta carpeta:

```json
{ "wow_dir": "D:/Juegos/World of Warcraft/_forever_" }
```

El motor, `instalar.cmd` y `probar-addon.cmd` usan esa ruta. Si está mal, el addon sigue apuntando datos en el
juego, pero el motor no los ve y la ventana de métodos sale vacía; `vigilar.cmd` lo avisa al arrancar.
