---
description: Busca métodos de oro en lo publicado estos días (Wowhead, Reddit, YouTube, guías nuevas) y los añade al catálogo
argument-hint: "[días, 7 si no se dice]"
---
Días a mirar: $ARGUMENTS (si no es un número, 7).

1. `../.venv/Scripts/python pg.py fuentes --dias <días>`. Lista solo lo que aún no se ha revisado:
   número, fecha, fuente, título, enlace y un resumen.
2. **Criba por título y resumen**, sin abrir nada. Interesa:
   - métodos de oro en Forever (farmeos, recetas, subasta, vendedores, pesca, mazmorras);
   - cambios que afecten a un método (hotfix, nerf, parche, botín, recetas nuevas, precios de vendedor);
   - Legacy, Merchant's Favor, cajas extraviadas.
   Lo demás (historia, cinemáticas, sorteos, retail), fuera.
3. **Abre a fondo como mucho 5**, los más prometedores:
   - enlaces, con WebFetch, pidiendo solo los métodos concretos (dónde, nivel, profesión, objetos);
   - PDF de `../fuentes/`, con Read (por páginas si es largo);
   - Word de `../fuentes/`, con `pg.py fuentes --texto <archivo>` y leyendo el .txt que crea;
   - YouTube: solo hay título y descripción. Si parece importante, dile a Piti que lo vea.
4. **Por cada método nuevo y concreto**, añádelo a `../conocimiento/metodos.json` con tus palabras:
   - `id` corto en minúsculas con guiones; `fuente`: «<fuente> (<fecha de publicación>)»; `fecha`: hoy;
   - `objetos` con su nombre en inglés tal como sale en el juego;
   - si ya hay uno parecido, mejóralo (notas, objetos, zona) en vez de duplicarlo;
   - si algo se ha nerfeado o cambiado, apúntalo en las notas del método que corresponda.
   Lo que sea opinión sin método concreto («invierte pronto», «sube dos recolecciones») no va al
   catálogo: cuéntaselo a Piti en el resumen si es útil.
5. **Valida** con `pg.py metodos` y corrige lo que diga. Si un objeto «no sale en los datos del juego»,
   busca en Wowhead su nombre exacto en inglés o su número y ponlo como `{"nombre": "...", "id": 1234}`.
6. **Marca como revisado** lo que hayas cribado: `pg.py fuentes --hecho` (todo) o `--hecho 2 5` (solo
   esos, si dejas alguno para otro día).
7. **Resume a Piti** en pocas líneas: qué has añadido o cambiado y, de `../datos/metodos.md`, cuáles de
   los nuevos pintan mejor con sus precios.

Si Piti te da un canal de YouTube o una web con RSS, añádelo a `../conocimiento/fuentes.json`. YouTube
necesita el `channel_id` (UC...): búscalo si no lo da.
