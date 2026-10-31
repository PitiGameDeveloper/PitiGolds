---
description: Investiga métodos de oro nuevos (tus archivos de fuentes/, Wowhead, Reddit, YouTube) y los añade al catálogo con lo que dan por hora
argument-hint: "[días, 7 si no se dice]"
---
Días a mirar: $ARGUMENTS (si no es un número, 7). Esto es una sesión de investigación: Piti la pide
cuando quiere métodos nuevos o cuando el addon le avisa de que ningún método guardado da dinero.

1. `../.venv/Scripts/python pg.py fuentes --dias <días>`. Lista solo lo que aún no se ha revisado:
   número, fecha, fuente, título, enlace y un resumen. Los archivos que Piti deja en `../fuentes/`
   (guías, transcripciones de vídeos) salen con el enlace que lleven dentro («Enlace: ...»).
2. **Criba por título y resumen**, sin abrir nada. Interesa:
   - métodos de oro en Forever (farmeos, recetas, subasta, vendedores, pesca, mazmorras);
   - cambios que afecten a un método (hotfix, nerf, parche, botín, recetas nuevas, precios de vendedor);
   - Legacy, Merchant's Favor, cajas extraviadas.
   Lo demás (historia, cinemáticas, sorteos, retail), fuera. Los archivos de `../fuentes/` siempre
   interesan: Piti los ha dejado ahí para esto.
3. **Abre a fondo como mucho 5**, empezando por los archivos de Piti:
   - transcripciones (.txt) con Read; Word con `pg.py fuentes --texto <archivo>` y leyendo el .txt que
     crea; PDF con Read (por páginas si es largo);
   - enlaces de webs, con WebFetch, pidiendo solo los métodos concretos (dónde, nivel, profesión, objetos,
     cuánto da);
   - de YouTube solo hay título y descripción: si parece importante y no hay transcripción, pídesela a Piti.
4. **No puedes ver los vídeos.** Si la transcripción no basta para saber cómo funciona un método («farmea
   en esta zona» señalándola, «mata a estos» sin decir cuáles, una ruta que solo se ve en el mapa...):
   - añade el método igualmente con lo que sepas y pon la duda en `pendiente`;
   - al final, pregúntale a Piti cada duda en concreto, con el enlace y, si lo sabes, el minuto:
     «El vídeo (https://...) dice "farmea aquí" hacia el minuto 4:10 sin decir la zona. ¿Cuál es?».
   Cuando Piti conteste, completa el método y borra `pendiente`. Mientras la tenga, el addon no lo
   recomienda.
5. **Por cada método nuevo y concreto**, añádelo a `../conocimiento/metodos.json` con tus palabras:
   - `id` corto en minúsculas con guiones; `fuente`: «<fuente> (<fecha de publicación>)»; `fecha`: hoy;
     `enlace`: el vídeo o la página;
   - `nivel` (el recomendado) y, si se puede hacer antes rindiendo menos, `nivel_minimo`;
   - `objetos` con su nombre en inglés tal como sale en el juego;
   - **`por_hora`**: cuántos objetos da en una hora, `[{"objeto": "Thick Leather", "cantidad": 40}]`, y
     `oro_hora` (oro de monedas y basura de vendedor por hora). Sácalo de la fuente si lo dice; si no,
     estímalo tú (reaparición, bichos por hora, probabilidad de botín) y dilo en `notas` («estimado:
     unos 3 bichos por minuto»). El motor lo valora con los precios de Piti hasta que lo mida;
   - si ya hay uno parecido, mejóralo (notas, objetos, zona, por hora) en vez de duplicarlo;
   - si algo se ha nerfeado o cambiado, apúntalo en las notas del método que corresponda (y baja su
     `por_hora` si da menos).
   Lo que sea opinión sin método concreto («invierte pronto», «sube dos recolecciones») no va al
   catálogo: cuéntaselo a Piti en el resumen si es útil.
6. **Valida** con `pg.py metodos` y corrige lo que diga. Si un objeto «no sale en los datos del juego»,
   busca en Wowhead su nombre exacto en inglés o su número y ponlo como `{"nombre": "...", "id": 1234}`.
7. **Marca como revisado** lo que hayas cribado: `pg.py fuentes --hecho` (todo) o `--hecho 2 5` (solo
   esos, si dejas alguno para otro día).
8. **Revisa los métodos nuevos** siguiendo `comandos/revisar.md` (nota, por qué y pasos).
9. **Resume a Piti** en pocas líneas: qué has añadido o cambiado, cuáles pintan mejor con sus precios
   (de `../datos/panel.md`) y las preguntas pendientes del paso 4, numeradas. Recuérdale que haga `/reload`
   para verlo en el addon.

Si Piti te da un canal de YouTube o una web con RSS, añádelo a `../conocimiento/fuentes.json`. YouTube
necesita el `channel_id` (UC...): búscalo si no lo da.
