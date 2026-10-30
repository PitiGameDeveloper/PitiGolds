---
description: Si compensa subir una profesión, cuánto cuesta y cómo (guía con lista de la compra)
argument-hint: "<profesión> [nivel al que llegar]"
---
Profesión y nivel: $ARGUMENTS

1. `../.venv/Scripts/python pg.py guia <profesión> [--hasta <nivel>]`. Sin nivel, llega hasta la receta
   más alta de la profesión. Usa el nombre en español (herrería, costura, peletería, alquimia...).
2. En `../datos/informe.md`, sección «Qué te conviene hacer», busca las filas «Aprender ...» o
   «Subir <profesión> para ...».
3. Explícale a Piti:
   - coste real y oro que tiene que gastar (lo que ya tiene no cuenta), y tiempo;
   - los tramos en una frase cada uno («del 1 al 36, piedras de afilar férreas, unas 44»);
   - qué receta hace que valga la pena, cuánto da al día y en cuánto se recupera según el comparador.
     Si la profesión no sale en el comparador, dilo: con los precios de hoy no hay nada que compense,
     o faltan precios;
   - tu conclusión: compensa o no, y por qué.
4. Recuerda, si aplica:
   - lo que cobra el instructor (recetas y rangos) no está en la cuenta;
   - si en `pg.py ajustes` no tiene puesto el talento de Legacy de subir profesión, pregúntale si lo
     tiene y cuánto da, y ponlo con `pg.py ajustes --legado-subida N`;
   - si es para Estudio dedicado, hacen falta también las secundarias (cocina, pesca, primeros auxilios)
     a 300.
