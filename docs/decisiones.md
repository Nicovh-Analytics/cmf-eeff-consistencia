<!-- Generado por verificacion/anonimizar_docs.py desde decisiones_privado.md. No editar aqui. -->

# Registro de decisiones

Cada regla del pipeline existe por un caso concreto. Este archivo documenta **qué se decidió, qué caso lo motivó y qué efecto tuvo**, para que cualquier cifra del análisis se pueda rastrear hasta su origen.

Formato de cada entrada: **Caso** (qué se observó) · **Decisión** (qué se hizo) · **Efecto** (cómo cambiaron los números) · **Límite** (lo que la decisión no resuelve).

**Cierre 04/07 (con materialidad por moneda, ver config.py):** de 607 candidatos, 133 con gravedad demostrada por regla (gravedad_auto), 190 observaciones inmateriales y 284 para revisión manual. 07 separa subtotal_vacio (4) de modificado_saldos (69) y marca 204 fondo-año con identidades internas rotas (C/C2).

---

## Premisas del proyecto

**P1. Pregunta.** ¿El PDF auditado y firmado que lee el público es un espejo fiel del XML que la AGF envía a la CMF, en los cuatro estados financieros principales (ESF, ERI, ECP, EFE)?

**P2. El XML es la referencia, no la verdad.** El XML pasa una validación lógico-matemática de la CMF, por eso se usa como punto de comparación. Pero esa validación verifica, por ejemplo, que las series sumen el total, no que cada serie tenga el valor correcto (ver H1). Por lo tanto, **el cruce detecta desacuerdo entre documentos, no cuál de los dos está mal**. La atribución se hace después, caso a caso.

**P3. Alcance actual Fase 1.** Fondos mutuos vigentes, cierres anuales (diciembre) 2011-2025. Desde 2011 los EEFF de fondos mutuos son IFRS y anuales (Circular 1997), y todos los cierres anuales van auditados.

---

## 1. Recolección (`01_recolector.py`)

**D1. Flujo de la fuente.**
- Caso: exploración con DevTools sobre el sitio de la CMF.
- Decisión: tres pasos. (1) GET al listado de fondos (`rut` + `row`). (2) POST a `entidad.php?pestania=3` con `mm`/`aa` en el cuerpo. (3) GET a `ifrs_xml_verarchivo` con los parámetros del enlace.
- Detalle: los campos del CMS (`cid`, `fdid`, `context_iid`, etc.) se verificaron idénticos en dos fondos distintos (rut F01 y F02): son constantes, no tokens de sesión.
- Detalle: el parámetro `row` (rowid de Oracle) no es derivable del RUT; sale del listado. El servidor tolera tanto `+` como `%20` en ese parámetro.

**D2. Solo cierres anuales.**
- Decisión: solo `mm=12`.
- Motivo: es el único período auditado; hace homogénea la comparación.
- Límite: el recolector soporta más alcance (no vigentes, otros meses), pero la fase 1 lo acota. Ver "Extensiones previstas".

**D3. Filtro por prefijo de archivo.**
- Caso: una prueba con 5 fondos bajó 104 archivos donde se esperaban ~50. Bajo la ruta `/fmifr/notas/` conviven tres PDF: `FMNO` (EEFF completos), `FMDA` y `FMDR` (dictamen y declaración de responsabilidad).
- Decisión: filtrar por prefijo del nombre (`FMEF` = XML, `FMNO` = PDF), no por ruta.
- Efecto: ~2 archivos por fondo-año en la corrida completa. El `FMNO` ya incluye el dictamen.

**D4. Recolección reanudable y conservadora.**
- Decisión: caché de HTML en disco (si existe, no se repite el POST); recorrido año → fondo, del más reciente al más antiguo; pausa adaptativa (mínimo 2x el tiempo de respuesta del servidor); User-Agent identificable con correo de contacto; descargas atómicas (`.part` + renombrar).
- Efecto: segunda corrida sobre datos completos = 0 peticiones. Corrida completa sin un solo error del servidor.

**D5. Solo se publica el último envío.**
- Caso: exactamente un XML por fondo-año en toda la descarga.
- Consecuencia: los reenvíos no son observables directamente. Un timestamp tardío puede ser presentación fuera de plazo **o** rectificación posterior; no se pueden distinguir.

**D6. Solo fondos vigentes.**
- Límite: sesgo de supervivencia. Los fondos que cerraron no están, y en los años antiguos el universo es una fracción del actual. Opción preparada en el script (`INCLUIR_NO_VIGENTES`) pero sin verificar contra el sitio.

---

## 2. Parseo de XML (`02_parser.py`)

**D7. Formato largo.**
- Decisión: una fila por cifra (`rut | anio | contexto | codigo | serie | nota | valor`).
- Motivo: no todos los fondos reportan las mismas cuentas ni series; el formato largo no necesita saberlo de antemano.
- Efecto: 4.512 XML → ~1,08 millones de filas, 90 códigos de cuenta distintos. La taxonomía es uniforme entre AGF.

**D8. Escala y signo.**
- Montos en miles (verificado contra el PDF: `5233424` en el XML = `5.233.424` en el PDF).
- Gastos, rescates y compras van en negativo en el XML.

**D9. Reparación de encoding.**
- Caso: 170 XML (3,8%) no parseaban. Archivos declarados UTF-8 con tildes y eñes en Latin-1 (`Compa\xf1ia`, `Ita\xda`, `D\xf3lar`), y uno con `encoding="iso-F03-K"` (el RUT del fondo pegado en la declaración).
- Decisión: intentar UTF-8; si falla, decodificar como cp1252, corregir la declaración y reparsear. Columna `reparado` marca cada caso. El orden importa: cp1252 acepta casi cualquier byte, así que probarlo primero leería mal archivos UTF-8 válidos sin avisar.
- Efecto: 0 errores; los 170 reparados son exactamente los que fallaban.
- Hallazgo: la CMF aceptó y publicó XML que no son XML válido.

**D10. Auditores: normalizar por nombre, no por número.**
- Caso: el número de registro del auditor no identifica a la firma. KPMG aparece como 9, 09, 4, 40, 48 y 899073002; el número 1 incluye a Deloitte, KPMG y EY; hay RUT en el campo de número. Los nombres tienen errores ("KPGM", "ERNEST YOUNG", "x").
- Decisión: firma canónica por palabras clave del nombre (`auditor_firma`). Cambios de marca legítimos: Horwath HB → Crowe; Ernst & Young → EY. Número sin ceros a la izquierda. Columna `auditor_num_inconsistente` cuando el número apunta a otra firma.
- Efecto: Big Four = 97,7% de los envíos (por conteo). 74 envíos con número inconsistente, 26 sin nombre de auditor.

---

## 3. Cruce XML ↔ PDF (`03_cruce_PDF.py`)

**D11. Cruzar por números, no por glosas.**
- Decisión: por cada cifra del XML, buscar si el monto aparece en las páginas de estados del PDF (ida). En reversa, montos del PDF que no existen en el XML (huérfanos).
- Motivo: no requiere mapear ~90 glosas por AGF ni entender cada layout.
- Patrón clave: una discrepancia real aparece como **par**: cifra XML no encontrada + monto huérfano.
- Límite: no verifica que el monto esté en la línea correcta.

**D12. Ubicar páginas de estados por contenido.**
- Decisión: una página es de estados si contiene ≥3 cifras del XML; se deja de leer al empezar las notas (las notas repiten cifras y darían falsos aciertos).
- Huérfanos: solo montos escritos con separador de miles, para excluir años y números de nota.

**D13. Inicio de notas: solo en el encabezado.**
- Caso: AGF G (y otras) incluyen un índice ("Contenido") que menciona "Notas a los estados financieros"; el script lo tomaba como inicio de notas y dejaba de leer justo antes de los estados.
- Decisión: la frase cuenta solo si está en las 3 primeras líneas de la página.
- Efecto: `sin_paginas_de_estados` 1.337 → 114.

**D14. Extracción separada del cruce, con caché y en paralelo.**
- Decisión: etapa 1 guarda el texto de las primeras 25 páginas de cada PDF (y sus metadatos) en JSON; etapa 2 cruza leyendo los JSON. Procesos paralelos (núcleos − 2).
- Efecto: extracción completa en ~17 min con 14 procesos; cada ajuste posterior del cruce toma ~1-2 min.
- Además: chequeo `%PDF` separa archivos que no son PDF (`no_es_pdf`) de PDF dañados.

**D15. Texto espaciado (re-extracción con otra tolerancia).**
- Caso AGF K F04-2023: la tabla del ECP salía como `2 .5 6 1 .2 9 8`. pdfplumber inserta un espacio cuando dos caracteres están a más de `x_tolerance` (3 pt por defecto). Probado: falla con 3, funciona de 4 a 8 sin pegar columnas.
- Caso AGF I F05-2023: mismo problema, pero la extracción sale por columnas (un monto por línea), y el primer detector no lo veía.
- Decisión: detectar páginas espaciadas (letras sueltas en una línea **o** números con dígitos separados), re-extraerlas con `x_tolerance=5` y, por página, usar la versión que encuentra más cifras del XML. Si la marca era falsa, ambas versiones dan lo mismo.

**D16. Signo: convención de presentación.**
- Caso: AGF T presenta los gastos en positivo bajo un título "Gastos" (XML -703, PDF 703). 97 de 125 fondos con este perfil eran de AGF T.
- Decisión: `pct_valor_abs` cuenta el monto aunque el signo difiera; los signos siguen visibles en `signo_distinto`.
- Límite: no distingue convención de error real (un activo en negativo). Refinable restringiéndolo a cuentas de gasto.

**D17. Redondeo ±1.**
- Caso AGF I F05-2023: diferencias de exactamente 1 en ambas direcciones (XML -24.406.945 / PDF (24.406.944)), por redondeo al expresar en miles.
- Decisión: estado `ok_redondeo` para diferencias de ±1, solo en montos ≥1.000 (en cifras chicas, ±1 puede ser coincidencia). Esos montos no cuentan como huérfanos. `pct_tolerante` = ignora signo y redondeo.
- Efecto: +226 fondos al 100% tolerante.

**D18. Montos partidos (candidatos de unión).**
- Caso AGF AA F06-2025: un espacio tras el primer dígito: `8 6.389.311`, `6 .526`, `3 50.354`.
- Decisión: generar la versión unida solo como **candidata**; cuenta si coincide exactamente con una cifra del XML (`ok_union`). No se reescribe el texto porque `15 5.233.424` (nota 15 + monto, en AGF M) también encaja en el patrón.
- Efecto: bajo 90% tolerante 517 → 334. **"Pares" (posibles hallazgos) 184 → 40**: casi todos los "hallazgos" de AGF AA eran montos partidos.

**D19. Estados publicados como imagen.**
- Caso AGF I F05-2023: el EFE es una imagen; la página tiene 228 caracteres (solo el encabezado) y 1 imagen.
- Decisión: marcar páginas con el título de un estado en el encabezado y <500 caracteres, excluyendo índices (`paginas_sin_tabla`). Sin OCR por ahora: agrega su propio error en los dígitos, justo lo que el cruce necesita evitar.
- Efecto: 89 fondos con al menos un estado como imagen.

**D20. Elegir la versión de cada página por montos grandes; varias tolerancias.**
- Caso AGF K F04-2023: la versión re-extraída de la página del ECP era correcta, pero el cruce elegía la original espaciada. Criterio anterior: gana la versión con más aciertos. La versión espaciada ('2 .5 6 1') genera muchos dígitos sueltos que coinciden por azar con cifras chicas del XML (en una simulación: 181 aciertos contra 7 de la versión limpia).
- Caso AGF I F07-2022: la página del ERI seguía espaciada con x_tolerance=5.
- Decisión: puntaje por página = (aciertos en montos ≥ 1.000, aciertos totales); el total solo desempata. Las páginas marcadas se re-extraen con tolerancias 5, 8 y 12, y el cruce elige la mejor. Una tolerancia que pegue columnas produce menos montos válidos y pierde sola.
- Efecto: fondos que usan páginas re-extraídas 222 → 301; 100% tolerante 2.811 → 2.878; bajo 90% tolerante 334 → 228. "Páginas no leídas" quedó disperso (máx. 11 casos por AGF).
- Cierre de etapa: los 115 fondos restantes con perfil "páginas no leídas" se etiquetan como "verificación parcial"; no se persiguen caso a caso.

**D21. Candidatos: emparejar de verdad, no solo "hay faltantes y hay huérfanos".**
- Caso: la regla inicial (al menos una cifra faltante y al menos un huérfano) produjo 916 candidatos (21,5% del universo), no creíble para estados auditados. Un huérfano puede ser un subtotal propio del PDF o hasta un RUT (AGF V F08-2024: `80276200`), y se "emparejaba" con cualquier cifra no leída.
- Firmas de una discrepancia real, observadas en casos concretos:
  - Redistribución: la suma de lo faltante = la suma de lo huérfano (H1, AGF M F09).
  - Discrepancia consistente: la misma diferencia en 2+ cifras distintas, porque un número distinto en una línea se arrastra a los subtotales (AGF C F10-2017: 12.237 en compras, flujo neto y aumento neto de efectivo; AGF F F11-2017: 10 en ventas y flujo neto).
- Decisión: clasificar cada candidato en redistribucion / discrepancia_consistente / par_aislado (un par con diferencia ≤1% y monto ≥1.000) / sin_par_plausible (pasa a verificación parcial). Se usan montos únicos para que las filas repetidas del PDF no cuenten dos veces. Diferencias ≤5 se marcan como posible redondeo acumulado.
- Materialidad: sobre la diferencia, no sobre el tamaño de la línea (AGF C: 12.237, no 87 millones).
- Efecto: candidatos 916 → 607 en la versión actual del 04 (ver README).
- Límite: la clasificación ordena la revisión; no reemplaza la verificación manual de cada caso.

### D22. Clasificación de casos confirmados: subtipo y gravedad

Cada caso confirmado lleva subtipo (mecanismo), gravedad (efecto sobre el documento), ajuste compensatorio, columna (actual/comparativo) y documento con error (PDF/XML/ambos/criterio).

**Gravedad** (independiente del monto y del año):
- 1: la diferencia queda dentro de un subtotal; subtotales y saldo final iguales.
- 2: cambian subtotales relevantes (flujo de operación, total ingresos, aumento neto) o el comparativo se modificó sin revelación; saldo final igual.
- 3: el documento no suma internamente o se contradice.

**Subtipos:** reclasificacion, diferencia_cambio, redistribucion_series, error_aritmetico, transposicion, comparativo_modificado, ajuste_redondeo, linea_sin_codigo, bruto_vs_neto, error_signo, rotulo_incorrecto.

**doc_con_error = criterio** cuando ninguno de los dos documentos está mal (diferencia de presentación). Nunca llega a gravedad 3.

**Materialidad y gravedad son ejes separados.** El hallazgo mide prolijidad del proceso de reporte, no errores materiales: un PDF auditado que no suma es una falla de control aunque la diferencia sea mínima.

---

## 4. Estado del cruce al cierre de la etapa 03

Foto de la corrida de D19 (antes de D20); las cifras vigentes están en el README.

| Estado | Fondos |
|---|---|
| Espejo perfecto (tolerante) | 2.811 |
| ok bajo 90% tolerante | 334 (89 con algún estado-imagen) |
| `sin_texto` (PDF escaneados) | 159 (concentrados en 2011-2013) |
| `sin_paginas_de_estados` | 83 |
| `no_es_pdf` | 15 (13 de ellos en 2021) |

Entre los 264 fondos bajo 90% sin imágenes: 224 con perfil "páginas no leídas" (concentrados en AGF I y AGF K) y 40 "pares".

**Muestra de verificación (cerrada):** 30 casos (15 más materiales + 15 aleatorios, 5 por tipo). 30/30 confirmados; 15/15 en aleatorios. Con n=15 y 0 falsos positivos, la tasa de falsos positivos es < ~20% (95%), no 0%. Gravedad: 12 / 7 / 11 (1/2/3). En aleatorios, 5 de 15 son gravedad 3.

**Reglas de subtipo_probable (04), validadas contra la muestra:** redistribucion_series 3/3, agregacion_xml 9/9 (incluye línea sin código y reclasificación de una línea con código), rotulo_incorrecto 1/1, dif_menor 2/2 redondeos + 1 error aritmético (delta chico no implica gravedad baja). Falso positivo corregido en la firma de series: series con inicio y neto ~0 hacían calzar cierres redondeados.

**Parciales (848), diagnóstico:** 473 con ≤3 cifras faltantes. De sus 424 cifras grandes (≥10.000), búsqueda en todo el texto del PDF: 0 en otra página, 242 ausentes, 182 con un número cercano (≤1%) en páginas de estados: 165 ruido (otro número de magnitud similar), 15 redondeo de ±2 a ±5, 2 diferencia de un dígito (F12-2013, F13-2022; el valor del PDF coincide con otra cifra del XML y por eso no formó par). Conclusión: los parciales esconden muy pocos errores; el hueco del detector existe pero es marginal.

---

## 5. Hallazgos verificados a mano

**H1. AGF M F09, reporte 2024, ECP del período comparativo (2023), por serie.** El total y la serie B coinciden (2.205.457), pero las otras cinco series son distintas. XML: -61.763.459 / 2.410.956 / 858.230 / 63.847.756 / -3.190.558. PDF: 2.100.214 / 2.886 / 52.322 / (11.972) / 19.475. Las cifras del PDF son coherentes con el tamaño de cada serie; las del XML se compensan entre sí. Probable error en la generación del XML (la suma por serie pasa la validación de la CMF). Mismo patrón en AGF M F14. Pendiente: confirmar con el XML 2023 del mismo fondo (continuidad entre períodos).
**Mecanismo demostrado (muestra, ids 22, 23, 30):** en el ECP del período anterior, el XML carga inicio, aportes, rescates y neto por **posición de columna** (orden del PDF ≠ orden de series del XML), mientras los cierres sí quedan en la serie correcta. El resultado por serie queda como diferencia (cierre − inicio − neto), lo que fuerza la cuadratura. La reconstrucción por posición reproduce exactamente los resultados del PDF en los tres fondos. Totales del fondo iguales: la validación CMF por suma no lo detecta. Tres fondos de la misma AGF en el reporte 2024 → problema de proceso de carga, no caso aislado.
**Alcance en el universo (regla automática, ver D22):** 4 fondo-año, todos AGF M: 3 en el reporte 2024 y 1 en el reporte 2022 (comparativo 2021; serie BCH ↔ APVDIGITAL). En el caso 2022 el XML comparativo además difiere del XML 2021 original, que coincide con el PDF.

**H2. XML mal formados aceptados por la CMF durante 15 años.**
- Condición: 170 XML (3,8%) declaran UTF-8 pero contienen caracteres en Latin-1 (ver D9). No son XML válidos y fueron aceptados y publicados.
- Concentración: 5 AGF explican 155 de 170 (91%): AGF I 42 envíos (16 fondos, 2011-2025), AGF AA 39 (28 fondos, 2014-2025), AGF T 30 (9 fondos, 2011-2025), AGF C 23 (5 fondos, 2011-2017), AGF B 21 (5 fondos, 2013-2025).
- Por año (EEFF): entre 2% y 5% cada año de 2011 a 2024; salto a 10,1% en 2025 (43 casos).
- Mecanismo del salto: el error solo se manifiesta si el archivo contiene caracteres no ASCII. En 2025 aparece una variante nueva del nombre del auditor, "PriceWaterhouseCoopers Consultores, Auditores y Compañia Limitada", en exactamente 28 envíos: los 28 reparados de AGF AA auditados por PwC. Hasta 2024 esos fondos registraban "PRICEWATERHOUSECOOPERS Y CIA. LIMITADA", sin ñ: el defecto existía pero estaba latente.
- Control: en 2025, 16 envíos de otras AGF registran "...Y COMPAÑIA LIMITADA" (misma Ñ, mismo año, mismo auditor) y se parsean sin error. El defecto está en el generador de XML de cada AGF, no en la CMF ni en el auditor.
- Conclusión: la recepción de la CMF no rechazó XML mal formados en toda la ventana 2011-2025. El alcance de sus validaciones físicas y lógicas está pendiente de confirmación (solicitud enviada).
- Límite: 170 es un piso. Un generador defectuoso solo se delata cuando el archivo trae tildes o eñes; las AGF sin caracteres especiales en sus datos podrían tener el mismo defecto sin que sea observable.

**H3. Comparativo 2024 modificado sin revelación, con inconsistencia interna (fondo con dos series, AGF R, EEFF 2025).**
- Condición: en el PDF de los EEFF 2025, el ECP comparativo 2024 muestra aportes 799.501 y resultado del ejercicio 80.400. El ERI del mismo PDF muestra un resultado 2024 de 117.437. El PDF 2024 (auditado y publicado en su momento), el XML 2024 y el XML 2025 coinciden entre sí: aportes 762.465 y resultado 117.437. Los saldos inicial (379.076) y final (375.196) coinciden en todas las fuentes. Por serie, la serie B cierra en cero con un resultado de (298.542) en el comparativo del PDF 2025, contra 49.596 en el original.
- Criterio: una reclasificación de cifras comparativas debe revelarse (naturaleza, monto y motivo). El PDF 2025 declara en su nota 2c que no se efectuaron reclasificaciones a los EEFF al 31-12-2025 y 2024.
- Desviación: el comparativo difiere de lo publicado y auditado originalmente, sin revelación, y el documento es inconsistente consigo mismo (dos resultados distintos para 2024).
- Contexto: fusión con otro fondo de la misma AGF vigente desde el 08-02-2024 (nota de información general). Explica el movimiento de series de 2024, pero no un cambio en el comparativo de un año ya cerrado.
- Proceso: PDF 2025 creado y firmado digitalmente el 26-03-2026, misma fecha de autorización de emisión; sin modificación posterior. Auditor: EY en 2024 y 2025.
- Atribución: por continuidad, el documento que se desvía es el PDF 2025. La inconsistencia no fue detectada ni corregida antes de la publicación.
- Método: detectado como candidato por el cruce XML-PDF; atribuido con la capa de continuidad entre períodos y la cuadratura ERI-ECP dentro del mismo documento.

**H4. Error de transposición en el comparativo, "cuadrado" en el XML con un ajuste compensatorio (fondo F15, AGF B, EEFF 2016).**
- Condición: en el reporte 2016, el EFE comparativo 2015 presenta rescates de cuotas por 5.365.609. El reporte 2015 original (XML y PDF, coincidentes) los presenta por 5.635.609: mismos dígitos con "63" y "36" transpuestos. Diferencia: 270.000 (divisible por 9, firma de una transposición).
- PDF 2016: el subtotal del flujo de financiamiento se mantuvo en (4.121.314), el valor original, por lo que la columna no cuadra con sus partidas (1.514.295 − 5.365.609 = (3.851.314)).
- XML 2016: el subtotal de financiamiento se recalculó a (3.851.314) y la venta/cobro de activos financieros aparece reducida en 270.000 (17.177.657 → 16.907.657), con lo que el flujo de operación baja a 3.699.220 y el aumento neto se mantiene en (152.094). El archivo cuadra internamente con dos cifras distintas a las originales y pasó la validación de la CMF.
- Criterio: las cifras comparativas deben corresponder a las publicadas para ese período, salvo reexpresión revelada.
- Desviación: el comparativo difiere del original en dos documentos y de dos formas distintas: con un descuadre visible en el PDF y con un ajuste compensatorio en el XML.
- Mecanismo del ajuste: no determinable con estos datos (puede ser manual o automático del generador del XML).
- Relevancia para el método: demuestra la premisa P2. La validación lógico-matemática verifica que el archivo cuadre, no que sus cifras sean correctas; un error puede quedar "cuadrado" por una partida compensatoria.
- Método: detectado como candidato por el cruce XML-PDF (pares en venta/cobro y flujos), confirmado por cuadratura del PDF y atribuido por continuidad con el reporte 2015.

### H5. Los errores graves se concentran en la columna comparativa

En la muestra, 8 de 11 casos de gravedad 3 están en el comparativo, y 7 de 11 son del PDF auditado. Dos mecanismos:
1. **Errores al rearmar el comparativo:** la columna t-1 se re-digita en vez de copiarse del PDF auditado anterior (transposición, dígitos, cambio de formato). El original t-1 está correcto.
2. **Comparativo modificado sin revelación:** el comparativo difiere del PDF auditado del año anterior y no hay nota de reclasificación (NIC 1.41); en un caso el documento además declara no haber reclasificado.

Implicancia: la capa de continuidad (comparativo t vs. original t-1) es la de mayor rendimiento esperado.

---

### H6. Alcance de la validación del XML, y su cambio en el tiempo

Chequeo: 16 identidades por XML, por columna y por año de ejercicio (07, chequeo C).
1. ERI, EFE, ECP (sumas internas) y cruces ESF↔ECP, ERI↔ECP: 0 fallas en ambas columnas, todos los años.
2. ESF comparativo (suma de activos, suma de pasivos, activo − pasivo): 0 fallas en 2011–2016 (~1.360 XML); 37 fallas en 2017–2024 (~2.700 XML). Columna actual: 0 siempre.
3. Efectivo ESF = saldo final EFE: falla en ambas columnas en 2011–2015 (12–20/año); 0 en la actual desde 2016; en el comparativo 0 en 2016–2017 y casos aislados desde 2018.
Lectura: (3) sugiere una regla incorporada desde los EEFF 2016. (2) y el retorno de fallas en (3) desde los EEFF 2017–2018 sugieren que el comparativo del ESF dejó de validarse en esa fecha, coincidente con la transición SVS → CMF (hipótesis, no verificada).
Preguntas para la CMF: ¿qué reglas se aplican al Periodo Anterior? ¿Cambiaron las reglas o el sistema de recepción entre 2016 y 2018?
Advertencia: una identidad que se cumple no prueba que las cifras estén bien. Puede cumplirse a la fuerza: en el XML 2019 del fondo F16, el EFE comparativo trae saldo inicial 0 y saldo final 65.785 (= aumento neto), cuando el original era 6.283 → 72.068. La identidad inicial + aumento = final cuadra, el ESF del mismo XML dice 72.068 y el cruce efectivo ESF = EFE no se valida. Por eso las identidades del chequeo C miden qué valida la CMF, no la calidad de las cifras; esa la miden el cruce espejo (03/04) y la continuidad (07).
**Entre columnas del mismo XML (07, chequeo C2):** apertura del período actual = cierre del anterior. Ninguna se valida en 2011–2025: EFE inicial = final anterior (40 fallas, 0,9%), ECP inicio = cierre anterior (23), ECP inicio = activo neto ESF anterior (25), ECP por serie (101, 2,4%). Sin corte temporal. Caso F12-2013: efectivo final 2012 en el comparativo 2.434.815 vs 2.414.815 en el XML 2012 original y en el PDF; cada columna cuadra por separado.
**Parciales, muestra de cifras ausentes (5):** 1 error real (F17-2017, flujo de operación del PDF no suma), 1 redondeo, 1 lectura, 2 agregaciones en el XML (F18-2018 línea sin código; F07-2023 diferencia de cambio con código en 0 sumada a valor razonable, repetida en el año siguiente). Junto con los 2 de un dígito (F12, F13): los parciales esconden errores por un mecanismo común: el valor del PDF coincide con otra cifra del XML y no forma huérfano. Se justifica una pasada estructural por subtotales (03b).
Corroboración desde el PDF (03c): en 22 fondo-año la identidad efectivo ESF = saldo final EFE falla solo en el comparativo del XML, mientras el PDF del mismo envío cuadra. El error vive solo en el XML: el documento que lee una persona está bien y el que procesan los sistemas no. Hay patrones de escala (÷1.000), cifras ajenas y dígitos. Se suman 10 casos de activo − pasivo en el comparativo, con diferencias de hasta 563 millones.
El aparente corte de 2016 era un artefacto en dos capas: 76 XML de 2011–2015 traen el código del saldo final con un espacio final (corregido en el 02 con str.strip()), y usan EFE por método indirecto, cuyo aumento neto (AumentoDisminucionNetoDeEfectivoYEfectivoEquivalente) el asignador de estados deja en ECP o ESF (68 y 4 XML). El 07 acepta ese código como alternativa. Con eso, ninguna identidad del XML falla en la columna actual (salvo 1 caso del ECP); todas las fallas están en el comparativo. Las anclas del EFE en comun/secciones.py incluyen ahora los códigos del método indirecto, y el 07 acepta sus totales (FlujoNetoUtilizado..., AumentoDisminucionNeto...) como alternativa: las identidades del EFE se evalúan en los 4.512 XML sin fallas.

### H7. Subtotales con signo invertido en el PDF auditado

Regla (04, tipo signo_invertido): cifra encontrada en el PDF con signo opuesto, fuera de las líneas con convención de presentación (rescates, gastos, compras...).
- 60 fondo-año. Revisión manual 5/5 confirmados.
- 31 son "subtotal único invertido" en fondos que por lo demás cuadran al 100%: si las líneas coinciden en signo con el XML y el XML suma, el subtotal impreso con el signo contrario hace que el PDF no sume. Gravedad 3 demostrable sin revisión. 13 AGF, ejercicios 2012–2025; varios se repiten en años consecutivos (contar también hechos distintos).
- 9 con varias cifras: pasivos entre paréntesis (presentación, gravedad 1) y un caso con 30 cifras invertidas (pendiente: ¿PDF o XML?).
- 20 líneas sueltas: pendientes de muestra.
Lectura: el XML venía correcto y pasó la validación; el PDF firmado no se contrasta con el XML (P2). Ni la CMF ni la auditoría detectaron estos subtotales.
Caso F16 (AGF Y), resultado 2018 = ganancia de 3.888.604: el PDF 2018 la presenta como pérdida en el ERI y como ganancia en el ECP (se contradice). En el PDF 2019 el comparativo pasa ambas a pérdida, y el ECP deja de sumar en las 13 series. El error del año anterior se "corrige" en el comparativo hacia el lado equivocado. El XML trae la ganancia en ambos años.

### H8. PDF no disponibles en la CMF

Enlace de notas (FMNO) roto en 15 fondo-año: el PDF devuelve "ACCION NO PERMITIDA 16" por la ruta de notas. 13 se recuperaron desde la sección de estados financieros anuales del mismo sitio. 2 no están disponibles por ninguna vía: F19 (2020, la sección anual parte en 2021) y F20 (2021, el enlace alternativo tampoco funciona). Se excluyen como pdf_no_disponible.

### H9. XML con las cifras del año anterior, publicado como XML del año

- Condición: en F21, F22 y F23 (AGF Y, reporte 2019), la columna actual del XML 2019 trae
  exactamente las cifras del XML 2018: 100% de las cuentas distintas de cero, con y sin serie
  (83, 81 y 65 cuentas). El PDF 2019 del mismo envío presenta cifras propias de 2019, con 2018
  como comparativo.
- Mecanismo: el XML declara el período 2019 en <Contextos> (01-01-2019 a 31-12-2019) y el
  comparativo 2018, pero las cifras de ambas columnas son las del XML 2018: se actualizó la fecha,
  no los datos. En F23 (fondo iniciado en 2018) el comparativo 2018 declarado es 0, mientras la
  columna "2019" trae las cifras reales de 2018. Cada columna cuadra por separado: pasa una
  validación lógica y solo se detecta contra el XML del año anterior (ver H6, C2).
- Universo: de 4.080 fondo-año con año anterior, 4.026 repiten < 10% de sus cuentas, 14 entre 10%
  y 25%, y solo 4 sobre 75%: estos 3 y un caso parcial (F24-2022, AGF F, 76%).
- Concentración: misma AGF, mismo año, envíos del 6-7 de abril de 2020 → proceso de carga, no caso aislado.
- Por qué no se detectó antes: el cruce espejo (03) busca cada cifra del XML en el PDF sin mirar
  la columna; las cifras "actuales" del XML están en el PDF como comparativo, así que el fondo
  quedaba como espejo. Lo destapó el 03b al ubicar subtotales por glosa aunque su valor no
  coincidiera con el XML.
- F24-2022 (AGF F) confirmado: el PDF 2022 presenta cifras propias que cuadran; el XML repite el
  de 2021 en el 80% de las cuentas, con algunas cifras retocadas (p. ej. operación anterior 1.308.972
  vs 1.308.872 en el XML 2021). 

## H10

F31 2011: anomalía de asignación del resultado por serie (aislada). Serie A +288.073.091 y APV-A −287.042.826 antes de distribución, sobre un activo neto total de 56,3 millones; se compensan (neto 1.030.265; resultado del fondo 2.226.661). Coinciden PDF, XML y comparativo del PDF 2012. Barrido del XML por serie de todo el corpus (pares de series con resultados opuestos que se compensan y superan el activo neto de cada una): único caso. Hipótesis: traspaso de A a APV-A registrado como aporte en APV-A con contrapartida en resultado. Fuera del alcance de consistencia; no publicable sin nota que lo explique. Mismo PDF: fusión de series B+D→F revelada en nota al pie, presentada en el saldo inicial.

## 6. Lecciones de método

- **Un patrón de hallazgo puede ser un artefacto del script.** Con el script anterior a D18, AGF AA habría parecido la AGF con peor fidelidad del mercado. Ningún nombre de AGF se publica sin verificación a mano.
- **Cada regla nació de mirar el texto crudo de un caso concreto**, no de suponer. Cuando una métrica se ve rara: un ejemplo, el texto original, y recién ahí la regla.
- **Los casos seguros se resuelven en automático y quedan marcados; lo que no calza queda visible** para revisión, nunca descartado en silencio.

## 03b – Lectura espacial del EFE y clasificación (2026-10-15)

- Cambio de método: el lector por texto (heurísticas por plantilla, XML como árbitro de lectura)
  se reemplazó por lectura por coordenadas (03a_coordenadas.py + lector_espacial.py). La lectura
  del PDF ya no usa el XML: auditar con el documento auditado como árbitro sesga hacia "arreglar"
  lecturas en la dirección del error.
- Parámetros medidos en PDFs reales: trozos de un monto pegados (<1 pt; medido 0,0–0,1), signo "(" o
  "-" a <6 pt, franjas de columnas por borde derecho (separación 70–90 pt, tolerancia 20), monto→glosa
  ≤12 pt (medido ≤6), notas = enteros de 1–2 dígitos a la izquierda de la franja actual.
- Resuelve sin reglas específicas: columna de nota, fondos en su primer año, montos partidos, negrita
  sobreimpresa (dedupe_chars), texto con letras separadas (AGF I), signos desplazados.
- Resultado vs lector de texto: ubicación 96,1% → 98,7%; no suman 163 → 116; arregla 79, rompe 4.
- Clasificación de los que no suman: probable_error / _tipeo / _linea_no_sumada, probable_lectura,
  revisar_linea_faltante, observacion_inmaterial.
- Materialidad: |dif| ≤ 100 en pesos ($$), ≤ 1 en otra moneda (PROM) → observación, sin revisión.
- Validación: 9/9 probable_error* revisados confirmados como error del PDF (IC95% ~70–100%).
  En los 6 errores reales, el subtotal es correcto y el error está en una línea (tipeo o línea
  que no corresponde): el total viene de la contabilidad y las líneas se digitan a mano.
- Observaciones de formato en el PDF: montos mal agrupados "(3.021424)", doble paréntesis
  "((31.340.008.234)", rótulo de subtotal incorrecto (una plantilla de AGF, 66 casos).
- Pendiente: OCR para EFE como imagen (~192 fondo-año; Tesseract entrega cajas → mismo lector, con
  marca de origen OCR); extensión a ESF y ERI (configuración por estado); ECP requiere N columnas.
- GAP_UNION 1,0 → 2,0 pt (2026-10-21). Una plantilla escribe cada dígito como palabra
  separada, con huecos de hasta 1,4 pt entre dígitos ("160" + ".680"). Con 1,0 se cortaban
  montos y 3 subtotal-columna (F25-2024 x2, F26-2025) caían como probable_error cuando eran
  lectura. Con 2,0: no suman 125 → 122, probable_error* 39 → 36, casos conocidos sin cambios.
  Margen: columnas a 20+ pt, nota a ~30 pt; un espacio real dentro de un monto mide 2,5-3 pt.
- 03b: respaldo de ubicación por glosa única (solo_glosa) cuando el subtotal impreso difiere
  del XML; antes un subtotal mal impreso quedaba "no ubicado" (F27-2025). Ubicación 98,7% → 99,0/98,9%.
  - Extensión a ESF y ERI (2026-10-22): total activo/pasivo/ingresos/gastos. Muestra manual de 37
  probable_error*: 21 error real del PDF, 16 lectura en 4 causas (rótulo de total en 2 líneas con un
  "0" oculto, punto suelto que parte el monto, encabezado MUS$ con años, dígito suelto entre
  columnas). Corregidas las 4: precisión 21/23 (91%); el EFE no empeoró (operación 43→42).
- Hallazgo: en ESF/ERI el error está en el TOTAL impreso (17 de 21: dígito/transposición, valor de
  otra línea, total en blanco), al revés que en el EFE (total correcto, línea mal). 2 errores se
  arrastran al comparativo del año siguiente (como H5).
- Regla de páginas espaciadas: si >50% de las palabras son de 1 carácter, un no-suma es lectura.
- Correcciones al lector por la muestra ESF/ERI: punto suelto como trozo de monto; dígito
  desalineado se descarta solo si compite con un monto alineado; rótulo de total en 2 líneas
  (incluso con un "0" oculto en la primera); monto del total hasta 20 pt sobre su rótulo; MUS$.
  Resultado: 16/16 lecturas resueltas, 22/22 errores conservados (en muestra).
- Mecanismo recurrente: total impreso con el valor de otra línea del mismo estado (F28, F15-2011,
  F29). Candidato a regla automática.
- OCR (2026-10-23/26): Tesseract spa+eng, 300 dpi, psm 6, sin binarizar. Cache aparte (.ocr.json.gz).
  Calibración con EFE sintéticos: 0 sumas falsas; un no-suma en página OCR es lectura, nunca error.
  En PDF reales: 76% de cuadre; causa principal: el OCR lee el separador de miles como coma
  ("17,553,514"), y el lector no lo reconocía como monto. Normalizado al cargar (solo grupos de 3
  dígitos, para no tocar decimales): 90%. Pasadas múltiples (400 dpi, psm 4), elegidas por confianza
  y no por suma: 67% -> 69% en 25 fondos reales; no se adoptan.
- Muestra de no detección (65 casos): EFE probable_error 14/15; errores escondidos en lectura/línea
  faltante 5/35 (14%); en OCR 0/15. Los 5 escondidos comparten firma: total impreso = XML y suma de
  líneas a <2% del total (las lecturas: >90%). Regla probable_error_linea_distinta (< 5%):
  16 casos, incluye los 5 y un caso conocido (F13-2022); fuera de muestra 10/11 confirmados.
- Decimales de presentación ("86.451,00"): 2 casos de lectura (F12-2021, F30-2013) -> el lector
  acepta y descarta ",dd".

---
## Extensiones previstas

- **Fondos mutuos no vigentes** (fase 1b): misma fuente y mismo código; corrige el sesgo de supervivencia. Requiere verificar el POST con `vig=NV`.
- **Trimestres no auditados** (fase 2): contraste auditado vs. no auditado. El caché ya distingue por mes.
- **Fondos de inversión** (fase 3): reutiliza la infraestructura de descarga, pero con parser y reglas de cruce propias (otra taxonomía).

## Pendientes

- Revisión acotada de AGF I y AGF K ("páginas no leídas"), o etiquetarlos como no verificables automáticamente.
- Buscar pares en **todo** el universo (H1 estaba en 94%, no bajo 90%).
- Capa de fechas: dictamen (texto del PDF), modificación del PDF (metadatos), envío (nombre del archivo), plazos por año.
- Confirmar el significado del código de moneda `PROM`.
- 04: reglas automáticas: permutación de series en ECP; suma de huérfanos misma página (linea_sin_codigo); redondeo ±1/±2; excluir fila de saldo acumulado del ECP; comparativo vs XML t-1.
- 04: materialidad n/a o sobre diferencia neta cuando la redistribución deja totales iguales (hoy marca 142–492%).
- Continuidad: emparejar series por monto (cierre t-1 = inicio t) cuando cambia el código (ej. EA-AM → Z).
- Agrupar por rut_agf (nombre_agf trae nombre de fondo en algunos XML).
- Hipótesis a verificar: el XML no acepta gastos con saldo positivo (caso de otros gastos reclasificados a ingresos).
- Respuesta de la CMF sobre el alcance de sus validaciones (solicitud enviada; incorporar al README cuando llegue).## 03d – Cobertura del ECP y cruce con el resultado del ERI (2026-10-29)

Sesión de cobertura del 03d: de 86,5% a 92,4% de fondo-año con el ECP del año leído (97,6% sobre los PDF legibles; 236 fondo-año son escaneados sin OCR de la página del ECP). Los errores del PDF en `evolucion` no subieron (40 → 39): cada regla nueva se validó contra la lista de errores, no solo contra la cobertura.

### Decisiones de lectura

**D-ECP1. Resultado del ERI = resultado del ECP (chequeo `resultado_eri`).**
- Caso: identidad pendiente entre estados; el 03c ya ubicaba líneas del ERI.
- Decisión: el 03c ubica "aumento de activo neto antes de distribución" en el ERI (`lineas_03c.csv`) y el 03d lo compara con la misma fila de la columna Total del ECP. La glosa se busca uniendo líneas previas y siguientes (el monto suele ir en la primera o en la del medio y "antes de distribución" abajo); la página siguiente al ERI se lee solo si en la del ERI no hay candidata, y se corta en el título del ECP (el ECP trae una fila con la misma glosa y el mismo valor: tomarla haría cuadrar la identidad sin probar nada).
- Efecto: ubicación 81,0% → 96,7%; cuadra 98,2% en el PDF y 100% en el XML.
- Límite: primera revisión 12/34 errores reales; los 22 restantes eran lectura y se corrigieron las causas con 3+ casos (D-ECP2 a D-ECP4). Quedan 18 `probable_error_pdf`.

**D-ECP2. Columna anterior con montos menores a 100 (`lector_espacial._franjas`).**
- Caso: un fondo en dólares: toda la columna anterior del ERI tiene montos < 100 ("(56)", "5"); `_es_monto_de_franja` exige separador de miles o 3+ dígitos, la columna no formaba franja y se perdía entera (anterior = 0 en todas las líneas).
- Decisión: si solo hay una franja, se busca a su derecha el grupo más poblado (3+) de enteros cortos alineados. El "31" de "31 de diciembre" del encabezado queda en otro grupo.
- Efecto: `resultado_eri` 25 → 17 `probable_error_pdf`; en el 03b, `distinto_xml` de total_gastos y total_ingresos anterior 56 → 32 y 56 → 35.
- Límite: hizo visible un caso con "73.0" en una columna de enteros, leído 730 (ver D-ECP10).

**D-ECP3. Guion suelto en la primera línea de una glosa partida (`lector_multicolumna`).**
- Caso: un fondo: "Aumento (disminución)…" con un "-" en la columna Total y los montos en la línea siguiente; la regla "un renglón con montos no absorbe otra línea con montos" dejaba el guion (0) como valor.
- Decisión: un renglón con solo guiones absorbe la continuación con montos, que los reemplazan.

**D-ECP4. Tablas apiladas del mismo período.**
- Caso: muchas series: la página trae dos tablas, la primera sin columna Total; el "Total" de la página hacía tomar la última serie de la primera tabla como Total.
- Decisión: "Total" se busca solo en el encabezado de cada tabla; tabla sin Total seguida de otra del mismo período en la misma página → se unen las columnas.
- Efecto: 121 bloques unidos; `resultado_eri` lectura 214 → 145, `cierre_esf` lectura 194 → 127.

**D-ECP5. Dos períodos lado a lado en una tabla.**
- Caso: una plantilla (series y Total de 2016 | series y Total de 2015): el bloque tomaba el Total de 2015 y se fechaba como anterior; el año actual quedaba sin bloque.
- Decisión: dos columnas Total (por rótulo, o por suma si el rótulo no está en las coordenadas) y un año distinto sobre cada mitad → dos bloques. Años sueltos o como fecha ("31/12/2015"); se usa solo la línea de años más cercana a la tabla (el título "2014 y 2013" también queda encima).
- Efecto: 240 bloques partidos. Casos conocidos: F32 2016, F33 2015, F34 2014.

**D-ECP6. Variantes de título y de fila.**
- "cambios en activo neto" sin artículo y "cambios en el patrimonio" (52 fondo-año sin título reconocido).
- Filas "patrimonio neto atribuible" (plantillas con título "activo neto" y filas "patrimonio").
- Hasta 4 letras arrastradas de filas vecinas antes de "activo neto" en texto espaciado ("AARA c tiv o n e to…", un fondo); "Total activo neto" (5 letras) sigue excluido.
- Un año solo en su línea continúa la glosa ("… al 31 de diciembre de" / "2020").
- Montos sobre la glosa (alineación superior de celda): una fila reconocida sin montos toma los del renglón sin nombre inmediatamente anterior (≤ 15 pt).

**D-ECP7. Apertura del bloque.**
- Caso: el saldo inicial también se titula "al 31 de diciembre de <año anterior>" (correcto); el 03d lo leía como cierre y no abría el bloque.
- Decisión: cualquier fila de activo neto abre si no hay bloque abierto, salvo que venga justo después de movimientos (es el cierre de un bloque cuyo inicio no se reconoció). Una apertura sin movimientos se reemplaza solo si estaba titulada como cierre.
- Efecto colateral detectado y corregido: la primera versión mezclaba períodos (un fondo: abría con el cierre de 2023 y sumaba movimientos de 2022). Se vio porque apareció un patrón nuevo concentrado (`distinto=inicio`, 6 casos) y `evolucion` subió de 40 a 53 errores. Con la regla del cierre huérfano volvió a 39.

**D-ECP8. Montos desfasados una fila.**
- Caso: dos fondos: glosas de varias líneas con montos alineados arriba; cada fila lee los montos de la siguiente (aportes negativos, rescates vacíos).
- Decisión: aportes todos negativos, o rescates sin aportes → los errores del bloque pasan a lectura ("montos desfasados una fila"). Rescates positivos no cuentan (hay plantillas que los imprimen sin paréntesis).

**D-ECP9. Fecha por el XML cuando el texto la contradice.**
- Caso: un ECP 2015 con glosa "al 31 de diciembre de 2013"; el 03d priorizaba el año de la glosa y descartaba el bloque.
- Decisión: si el cierre del Total coincide con el XML de una sola columna y el año del texto dice otra cosa, manda el XML; el año del texto queda en `ecp_bloques.anio_texto`.
- Efecto: `solo_anterior` 93 → 55 en la cobertura; da origen al hallazgo de glosa desactualizada.

**D-ECP10. Decimales concatenados, a propósito.**
- Caso: "73.0" en una columna de enteros se lee 730 (03b: transposición falsa).
- Decisión: no se cambia `_valor_espacial`. Distinguir "73,0" de un monto con un grupo de miles faltante exige contrastar con la suma o el XML, que es justo lo que hace la validación. Un caso aislado; mejor un falso positivo descartable en revisión que ocultar un tipeo.

**D-ECP11. Decisión de cobertura por muestra.**
- Caso: tras los arreglos por plantilla quedaban ~230 fondo-año legibles sin bloque, repartidos en varios motivos.
- Decisión: muestra del 10% por motivo (mínimo 3), priorizando una AGF distinta por caso, con etiqueta de patrón; arreglar solo patrones con 3+ casos de 2+ AGF. 38 casos: 31 en 5 patrones.
- Efecto: 90,2% → 92,4%. Lo que queda (108 legibles) son grupos de 2 a 34 casos; se cierra la cobertura.

### Hallazgos

**H-ECP1. Errores en el tramo antes → distribución → después del ECP (5 casos, PDF).** En los cinco el "después de distribución" y el cierre son correctos; el error está en "antes" o en la distribución, por eso el ECP cuadra hasta el cierre y solo lo ve el cruce con el ERI.
- Signo invertido: antes = después − distribución (dif = 2 × distribución) (un fondo).
- Fila desplazada: el resultado impreso en la fila de distribución; antes = "-", en efectivo / en cuotas = "-" (dos fondos, uno de ellos lo repite en el comparativo del año siguiente).
- Reparto compensado: antes y distribución rebajados en el mismo monto; corregido en el comparativo del año siguiente (un fondo).
- Pendiente: regla automática (ubicar "después de distribución" en el ERI; marcar cuando el "después" coincide y el "antes" no).

**H-ECP2. Resultado del ERI inconsistente con el ECP, corregido en el comparativo del año siguiente sin aviso visible (5 casos, PDF).** cinco fondo-año. Más dos errores puntuales del ERI: tipeo en la línea (un caso) y línea omitida (un caso). Pendiente: chequeo de comparativos PDF vs PDF (año t−1 actual vs año t anterior) y búsqueda de nota (`notas_continuidad.py`).

**H-ECP3. Glosa con el año desactualizado (46 fondo-año).** El texto de la glosa dice un año anterior al del bloque (plantilla copiada sin actualizar), mientras el cierre coincide con el XML del año correcto. Muestra: 7/7 confirmados en la columna actual (desfase 1, 2 o 3) y en el comparativo con desfase 2; el comparativo con desfase 0 resultó lectura nuestra (glosas sin año, 3/3) y se excluye del conteo. 2 casos sin determinar. Es un error de forma, no de cifras.

**H-ECP4. Error de cifra en el Total de una serie única.** Un fondo de serie única: el aporte del Total difiere del de la serie; transacciones y cierre calzan con la serie. Pendiente confirmar con el XML.



### Casos conocidos agregados (03d)

F32 2016, F33 2015, F34 2014 (lado a lado), F35 2023 (texto espaciado), F36 2025 (guion suelto), F37 2018 (desfase de filas), F38 2022 (columna anterior con montos chicos). La salida del 03d muestra para cada caso sus bloques (columnas, lado a lado, tablas unidas, fechado).

## 03d tramo, 03e comparativos PDF vs PDF y 04b casos (2026-10-30 a 2026-11-02)

### 03d – Tramo antes → distribución → después (regla automática)

**D-ECP12. Forma del tramo cuando el ECP no cuadra con el ERI.**
- Caso: H-ECP1 (5 casos a mano). El 03c ahora ubica también "aumento de activo neto después de distribución" en el ERI (`resultado_eri_despues`, 95,1% ubicado).
- Decisión: si el "después" del ECP coincide con el del ERI y el "antes" no, se clasifica la forma del tramo, en este orden: `desplazada` (antes ≈ 0 y la distribución del ECP ≈ resultado), `signo` (antes = después − distribución), `compensado` (antes y distribución rebajados en el mismo monto), `antes_vacio`, `tipeo`, `digito_extra`, `otra`. Diferencia bajo materialidad → `observacion_inmaterial`. `antes_vacio` y `digito_extra` → `probable_lectura`; el resto → `probable_error_pdf`.
- Revisión: 7/7 confirmados en las formas que quedan como error. `digito_extra` fue lectura nuestra (dígito pegado, un caso); `antes_vacio` 2 lectura + 1 PDF.
- Límite: falso negativo conocido un caso con el resultado en la fila de distribución; por precisión primero, un cero sigue siendo lectura.

### 03e – Comparativos PDF contra PDF

**D-03e1. Qué compara.** Lo que el PDF de *t* informa en su columna actual contra lo que el PDF de *t+1* informa para ese año en su columna anterior, en 12 líneas: los 6 subtotales del 03b y 6 líneas del 03c (activo neto, utilidad de la operación, efectivo, saldo final, resultado antes y después de distribución). No lee PDF: usa lo que ya ubicaron el 03b y el 03c. El XML de ambos años dice qué documento cambió.
- Clases: `cuadra`, `pdf_corregido_despues` (el PDF de *t* difiere de su XML y el comparativo de *t+1* lo corrige), `pdf_error_comparativo` (el error aparece al copiar el comparativo), `reexpresion` (cada PDF calza con su XML, pero el XML de *t+1* cambió la cifra), `otro`, `sin_xml`, `lectura`.
- Efecto: 45.910 pares en 3.984 fondo-año; 91,3% cuadra, 8,0% lectura.

**D-03e2. Huellas de lectura.** Primera corrida: las clases de error mezclaban columnas no leídas (monto en 0), un dígito de más o de menos, y el ESF 2011 (columna del balance de apertura). Regla: PDF en 0 con XML distinto de 0, o el mismo número con un dígito insertado o quitado → `lectura`; ESF 2011 en `pdf_corregido_despues` → `lectura`.
- Efecto: `pdf_corregido_despues` 151 → 88 (64 fondo-año), `pdf_error_comparativo` 68 → 37 (25 fondo-año).
- Límite: falso negativo conocido un caso (resultado "antes" en 0 en el PDF, error real); misma ambigüedad que `antes_vacio`.

**D-03e3. Marca dudosa: se mantiene, también para "solo glosa".** Una lectura del 03c ubicada solo por glosa, o de OCR, manda el par a `lectura`. En el control (lectura con los dos PDF distintos), 2 de 6 eran errores reales. Muestra de 10 señales marcadas solo por glosa (sin OCR): 8 lectura (4 montos en 0 no leídos, 2 ESF 2011 con 3 columnas, 2 columna o cifra equivocada), 1 error real que ya ve el 03c (efectivo del ESF ≠ saldo final del EFE), 1 "antes" vacío. Se mantiene la regla.

**D-03e4. Patrón de cuatro versiones.** Cada monto tiene cuatro versiones: PDF *t*, XML *t*, comparativo del PDF *t+1* y comparativo del XML *t+1*. El 03e deja `patron` (`solo_pdf_t`, `solo_pdf_t1`, `solo_xml_t`, `solo_xml_t1`, `reexpresion`, `criterio`, `otro`) y `dif_patron`, independiente de la lectura (la duda va en `motivo_t` / `motivo_t1`). A diferencia de `clase`, ve los errores del XML cuando los dos PDF coinciden.

### 04b – De señales a casos

**D-04b1. Un error, varias señales.** Un tipeo en el resultado del ERI aparece en utilidad, resultado antes y después de distribución e ingresos: contado por línea son cuatro hallazgos. El 04b agrupa en un caso las señales del mismo fondo-año y patrón con la misma diferencia (±2).
- Efecto: 1.154 señales → 355 casos en 257 fondo-año (485 señales de lectura y 168 inmateriales no forman caso).

**D-04b2. Familia y nivel.** `tipo` es la familia según el patrón: `pdf`, `error_xml`, `reexpresion`, `criterio`, `otro`. `subtipo` es el nivel, de lo agregado a lo fino: `error_total` (la línea ancla del estado está en el caso: activo neto, resultado del ERI, saldo final de efectivo), `error_suma` (el subtotal no suma sus líneas, `pdf_suma` del 03b), `reclasificacion` (2+ líneas del mismo estado se mueven el mismo monto y el ancla calza; en el ESF, activo y pasivo), `reclasificacion_dc` (EFE: una línea cambia, el saldo final calza y el subtotal suma: el monto fue a o desde el efecto de diferencias de cambio, que no está entre las 12 líneas), `error_linea`, `sin_ancla`, `omision` (el documento distinto trae todas las líneas del caso en 0: un comparativo omitido es un caso, aunque cada línea tenga otra diferencia; 7 casos, de hasta 12 líneas).
- Revisión (muestra del 03e, 39 casos): subtipos de error 11/12 error del PDF; subtipos de reclasificación 18/18 "otro" (reclasificación entre líneas, con o sin nota).

**D-04b3. Lado XML: revisión por lotes.** Patrón `solo_xml_t` / `solo_xml_t1`: los dos PDF coinciden y el XML es el distinto. El 07 los había marcado todos (ninguno `identico`) sin poder decir qué documento estaba mal; con el PDF como testigo, es el XML. Concentración: 115 casos en 15 administradoras, 4 concentran 86. Revisión de 3 representantes por lote (uno por subtipo): 10/10 error del XML, incluidos los subtipos de reclasificación y sin ancla. Los lotes heredan el veredicto. 
- Convención de revisión: si cada documento cuadra y los totales calzan, una distribución distinta entre líneas es "otro"; si hay valores omitidos o montos que no corresponden, es error aunque el total compense.

**D-04b4. Criterio: taxonomía distinta, no error de cifra.** Patrón `criterio`: PDF y XML distintos, igual en los dos años. 55 casos en 16 administradoras; una administradora concentra 13 casos en 11 fondos, casi todos `reclasificacion_dc`. Revisión 2/2: el XML trata distinto la diferencia de cambio y redistribuye partidas (otros ingresos, otros gastos) respecto del PDF. Se cuenta aparte de los errores.

### Hallazgos

**H-03e1. Errores del PDF corregidos en el comparativo del año siguiente, sin aviso visible.** El comparativo del PDF de *t+1* coincide con el XML de ambos años y el PDF de *t* no. Tipeos (un dígito, transposición), subtotales que no suman, resultado del ERI inconsistente con el ECP (H-ECP2). Seis ejemplos verificados.

**H-03e2. Errores introducidos al copiar el comparativo.** El PDF de *t* está bien y su comparativo en el PDF de *t+1* no. Tipeos y glosas cruzadas. Un fondo arrastra en sus comparativos, en PDF y XML, cifras de otra versión o de otro año.

**H-03e3. Reclasificaciones en el PDF que el XML no acompaña.** Montos que pasan entre operación y financiamiento, o hacia la diferencia de cambio, en el PDF de un año y no en el XML (o al revés), con el saldo final intacto. No son errores de cifra: se cuentan como inconsistencias de presentación.

**H-03e4. Reexpresiones (75 casos).** Los dos documentos de *t+1* cambian la cifra de *t*; el 07 lo confirma en 75/75. La mayoría son reclasificaciones dentro del EFE. Dos con causa conocida: un fondo cambia la moneda de presentación (todas las líneas × ~856), y en 2012 tres fondos redefinen efectivo equivalente con aplicación retroactiva, con nota que dice afectar solo al EFE, aunque también cambia el efectivo del ESF (el activo neto no).

**H-04b1. El XML no es espejo de un PDF que no cambió (115 casos).** Formas: comparativo del XML omitido (en 0), miles truncados (920 por 920.492), dígito mal tipeado, una distribución de beneficios que no está en ningún PDF, cifra de otro año. 48 son el XML original corregido al año siguiente y 67 el comparativo del XML de *t+1*. Cuatro administradoras concentran 86 casos.

### Casos conocidos agregados

- 03d: F39 2023 (signo), F40 2020 (desplazada), F41 2023 (compensado), F42 2018 (otra, PDF), F43 2015 (dígito extra, lectura).
- 03e: F44 2021, F45 2016, F46 2017 (no cubierto: la corrección fue en el ECP), F47 2024, F48 2021 (falso negativo).
- 04b: F44 2021, F24 2019, F49 2013, F50 2022, F51 2022.

### Pendientes

- Una administradora figura con un nombre genérico en años recientes de `encabezados.csv`: revisar el campo en el 02.
- 
- 
- Búsqueda de notas para reexpresiones y criterio (extender `notas_continuidad.py`): encontrar la nota y contrastar el alcance que declara con las líneas que cambiaron.
- Gráficos por año: casos apilados por tipo y por estado (tasa por 100 fondo-año, no solo conteo).

## Cobertura de lectura: resultado del ERI, ceros y dígitos apilados (2026-11-03)

Sesión de cobertura guiada por el esquema de casos del 04b: la tabla de cobertura del ancla mostró dónde faltaba el par t / t+1 y cada cambio se midió contra la lista de errores con `comparar_corridas.py` (foto antes, diff después: líneas ubicadas, `probable_error*` nuevos o perdidos en 03c y 03d, casos del 04b). Resultado: resultado del ERI ubicado 4.255 → 4.346 fondo-año; ERI sin par en el 03e 244 → 141; ancla limpia ERI 86,5% → 88,5%, ESF 89,2% → 89,3%, EFE 88,7% → 88,8%; lectura del 03c 78 → 60; casos del 04b 355 → 351 (salen 4 artefactos de lectura, no entra ninguno). Cero errores nuevos en todos los pasos.

### Decisiones de lectura

**D-ECP13. Resultado del ERI: cuatro reglas en el 03c (`03c_identidades.py`).** Diagnóstico por motivo (`diag_cobertura_lineas.py`): 146 sin glosa, 63 sin página, 35 sin glosa con OCR.
- **Patrimonio neto.** La regex del resultado antes y después de distribución acepta "activo neto" o "patrimonio neto" (una plantilla).
- **Posición, solo con el XML.** Si no hay candidata por glosa, el "antes" es la única línea de aumento de activo (o patrimonio) neto justo antes de "Distribución de beneficios" (página del ERI y la siguiente, sin pasar del título del ECP). Primera versión: sin el valor del XML quedaba como `solo_glosa`; subió en 16 la lectura del 03d (líneas equivocadas) y no detectaba nada. Se acepta solo si calza con el XML (`posicion_y_valor`, 36 casos).
- **Guion suelto en la primera línea de una glosa partida** (como D-ECP3 en el ECP): "Aumento … originadas  -" / "por actividades … antes de distribución  2.313.023" (un fondo). La fila en cero se emite, pero su glosa pasa como previa a la siguiente. Solo en el resultado del ERI: en otras líneas, una fila en cero arrastrada podría hacer calzar dos candidatas.
- **Fila vecina, solo hacia abajo y con el XML.** La única candidata en 0 en las dos columnas toma la fila de abajo si es continuación (su glosa no empieza con un rótulo propio) y calza con el XML (`vecina_y_valor`, 18). No la de arriba: suele ser la utilidad, con el mismo monto, y taparía un "antes" omitido en el PDF (forma `antes_vacio`, que puede ser error real). No agrega detección: saca líneas de la lectura dudosa.
- Efecto: +91 resultados ubicados (4.255 → 4.346); lectura del chequeo `resultado_eri` del 03d 101 → 117 con la primera versión de la posición, 105 al final.

**D-LE1. Dígitos finales apilados (`comun/reparar_palabras.py`, aplicado en `cargar_coords`).**
- Caso: una plantilla de 2023–2025: texto letra por letra; el último dígito de cada monto de una columna viene como UNA palabra de k dígitos con el ancho de un carácter ("28776" en 5 pt). Sin ese dígito los montos no forman columna y la del año anterior se lee como actual (activo neto "actual" = cifra del año anterior). Las páginas espaciadas de esa AGF cuadraban 93,1%; las de otras AGF, 97,7–100%.
- Decisión: repartir los dígitos, en orden de altura, entre las filas de esa columna cuyo monto termina justo a la izquierda y está incompleto (último grupo de 1–2 dígitos, "3.150.44", o corto sin separador). Condiciones: ancho por dígito < 1,8 pt; receptoras seguidas (≤ 30 pt) y la primera a ≤ 30 pt; al menos una con separador de miles incompleto; exactamente k receptoras.
- Tres iteraciones, cada una medida con el diff:
  1. Ancho < 2,5 pt y receptoras = las k filas siguientes: sacó 6 artefactos del 04b, pero actuaba en otras AGF (glifos duplicados para simular negrita, ~2 pt por dígito) y repartía a filas a 140 pt: 2 `probable_error_pdf` falsos en el ECP (dos fondos).
  2. Ancho < 1,6 pt, primera receptora = fila de la apilada, saltos ≤ 20 pt: sin errores falsos, pero un fondo entró como caso nuevo: la primera receptora era un monto completo (83.797) y el dígito corrió.
  3. Receptoras solo entre montos incompletos y ancho < 1,8 pt (había otra palabra apilada de 1,67 pt por dígito en la misma página): limpio.
- Efecto: actúa en 37 fondo-año (tres administradoras); lectura del 03c 78 → 60; salen del 04b cuatro casos, todos lectura nuestra.
- Límite: la primera versión también bajaba en 47 la lectura de `transacciones` del ECP (otras plantillas): probablemente dígitos apilados con otra forma (más anchos o en tablas de muchas columnas). No se recupera sin una regla propia: venía con errores falsos.

**D-COB1. Lectura en 0: se mantiene la regla.** `diag_ceros.py`: 221 lecturas en 0 con el XML distinto de 0 (111 fondo-año); en 66% el monto está en la página. Muestra de 12 al azar: 10 lectura nuestra, 2 errores reales del PDF (dos montos no digitados), y los dos ya los detecta el 03c por la identidad. La regla "cero = lectura" del 03e no pierde hallazgos.

**D-COB2. ERI sin página: montos de 1–2 dígitos (inmaterial).** 63 fondo-año sin página del ERI en el 03b (`diag_pagina_eri.py`): 38 tienen el ERI con montos mínimos (mediana del mayor monto: 24 miles; 2 sobre 100). Columnas de 1–2 dígitos no forman franja (como D-ECP2, pero con las dos columnas chicas) y la búsqueda por valor calza en cualquier parte. No se amplía: cualquier diferencia sería inmaterial. El resto: totales en 0 en el XML (el PDF imprime guiones) y PDF sin texto.

### Lo que queda sin par en el ERI (141)
ERI de montos mínimos (~38, inmaterial); `sin_glosa` 51 (parte son PDF sin la línea "antes": nada que leer); `sin_glosa_ocr` 20 (OCR 2011–2012); ambiguas 7; resto disperso.

### Herramientas
`comparar_corridas.py` (foto / diff), `diag_cobertura_lineas.py`, `diag_pagina_eri.py`, `diag_ceros.py`, `diag_apilados.py`, `diag_lineas.py` (ahora acepta `p=N` y líneas no ubicadas), `muestra_ceros.py`.

### Casos conocidos agregados
- 03c: F52 2025 y F47 2023 (dígitos apilados: todas las identidades cuadran).
- 03d: F53 2014 (guion suelto en el resultado del ERI: `resultado_eri` cuadra).

### Pendientes
- Dígitos apilados con otra forma en el ECP (otras plantillas).
- Plantilla con la glosa del resultado terminada en "…originado" sin el "antes" (dos administradoras).
- Pico de 47 lecturas en 0 en 2017 sin revisar; grupo de 2011–2013 con las dos columnas en 0 y la fila vecina sin confirmar.
- Primera letra de la glosa perdida en las páginas espaciadas de una plantilla (no afecta las líneas buscadas).

## 04c – Conteo único de casos (2026-11-04/05)

Objetivo: que cada error (o inconsistencia de presentación) cuente una vez aunque lo marquen varias etapas y varias líneas. Junta las señales de 03b, 03c, 03d, 04 (cruce espejo, al detalle), 04b y 07 en una tabla común y las agrupa en casos. Base para los gráficos por año / tipo / estado y para la revisión de notas por caso. Diseño: `verificacion/diseno_casos_unicos.md`.

Resultado: **9.867 señales → 758 casos en 593 fondo-año; 332 errores en 276 fondo-año.**

| tipo | casos |
|---|---|
| error_PDF | 189 |
| error_XML | 62 |
| error_continuidad (identidad del XML rota) | 56 |
| error_PDF/XML (difieren; sin documento atribuible) | 19 |
| error_PDF+XML | 6 |
| reclasificacion | 89 |
| reexpresion | 75 |
| desglose (PDF y XML desglosan distinto; subtotal o cierre igual) | 69 |
| criterio | 55 |
| rotulo | 52 |
| glosa | 46 |
| agregacion_xml | 40 |

### Decisiones

**D-CU1. Unidad: la celda.** Una cifra se identifica por dónde está impresa: `rut`, `anio_doc`, `documento` (PDF / XML / PDF+XML / PDF/XML = difieren sin saber cuál / ? = sin resolver), `columna` (actual / anterior). La columna "anterior" del PDF de t+1 y el comparativo que mira el 03e para t son la misma celda.

**D-CU2. Señal.** Una fila por etapa y cifra con clase `error`, `presentacion`, `lectura`, `inmaterial` o `revisar`. Solo `error` y `presentacion` forman casos; `lectura` e `inmaterial` quedan como contexto (cota superior: 5.809 señales de lectura en 1.120 fondo-año, si todas fueran error). `revisar` y las de documento `?` o `PDF/XML` se pegan a un caso existente de la misma celda y diferencia; si no hay, las del 04 forman caso propio y las demás quedan sin resolver (03b distinto del XML sin pareja: 283 señales en 115 fondo-año).

**D-CU3. Agrupación.**
- Misma celda y |dif| igual (± 2): un caso, aunque cruce líneas y estados (un tipeo en el resultado aparece en el 03b, el 03c, el 03d y el 04).
- Los casos del 04b se mantienen (un caso del 04b = un caso) con union-find sobre su `caso_id`: la omisión de un comparativo en el XML (un fondo) son 12 líneas y un caso.
- Rótulo y glosa: un caso por fondo-año (es la plantilla, no cada celda). El rótulo del 04 (`rotulo_incorrecto`) se une al del 03d (un fondo: un caso con las dos fuentes).
- 07 solo: las identidades del XML rotas en la misma celda se juntan en un caso; las "por serie" quedan en `revisar`.

**D-CU4. Tipo y raíz.** La raíz es la señal más fina (línea > subtotal > total > identidad); con otras fuentes, el 04 no define ni la raíz ni el documento (solo dice que PDF y XML difieren). `error_continuidad` cuando la única fuente es el 07.

**D-CU5. 03b distinto del XML.** Si el subtotal impreso es igual al XML y otra fuente no lo confirma, el `probable_error` del 03b baja a `revisar` (revisión: 2 de 4 casos solo-03b eran una línea mal leída por nosotros). Siguen como error `linea_distinta`, `linea_no_sumada` y `tipeo` (error de una línea con el total bien).

**D-CU6. 04 al detalle.** Cada cifra del XML no encontrada en el PDF, emparejada con el huérfano del PDF más cercano a ≤ 1% (reglas de par del 04), solo si explica el `delta_principal` del candidato (± 2). Sin ese filtro: 821 señales y 363 casos solo-04, casi todos montos parecidos por coincidencia. Inmaterial bajo el umbral o `dif_menor`; `agregacion_xml` y `rotulo_incorrecto` → presentación.

**D-CU7. Estado de las señales del 04 por `comun/secciones.py`.** El `estado_financiero()` del 04 clasifica por palabras clave: 13 códigos quedaban en otro estado (p.ej. `OtrosIngresosDeOperacion` → ERI; `ColocacionDeCuotasEnCirculacion` → ECP por "cuotas"). Se usa el mapa del XML y solo si el código no está, la clasificación del 04. Cambia la distribución por estado, no el conteo. Pendiente: corregirlo en el propio 04.

**D-CU8. Desglose en subtotales (`compensa_subtotal`).** Revisión de casos solo-04 (10): 1 error confirmado; la mayoría eran el PDF y el XML desglosando distinto las mismas líneas (montos recibidos de la administradora dentro de venta/cobro, diferencia de cambio junto al valor razonable, compra e intereses compensados). Si la línea es parte de un subtotal del 03b que en el PDF suma sus líneas, es igual al XML y en el XML suma sus partes (desde `cuentas.csv`: el `cruce_detalle` no trae subtotales ni todas las partes), la diferencia se compensa dentro del subtotal → `desglose` (presentación). 67 señales; 1 queda como error porque el XML no suma.

**D-CU9. Documento del ECP por las identidades de cada uno (`ecp_documento`).** Segunda muestra solo-04 (10): 9 eran ECP por serie con PDF ≠ XML. Para cada señal del 04 en el ECP, en esa serie y columna:
- XML: aportes − |rescates| = neto; inicio + neto + resultado después = cierre (desde `cuentas.csv`).
- PDF: la columna del 03d (`ecp_chequeos`) que contiene el monto huérfano (el 03d nombra las columnas serie_1, serie_2…, no por la serie del XML).

| XML | PDF | resultado |
|---|---|---|
| no cuadra | cuadra o sin lectura | error XML |
| cuadra | no cuadra | error PDF |
| — | solo falla un rótulo (la fila "transacciones" trae el inicio sumado) | rótulo |
| cuadra | cuadra; neto igual, o cierre e inicio iguales | desglose |
| cuadra | cuadra; el inicio no es el cierre anterior (continuidad de la serie o, si el 03d no la tiene, del total) | error PDF |
| resto | | sigue PDF/XML |

Cierre igual con inicio distinto no es desglose: la diferencia se compensó contra el inicio (un fondo: el PDF parte de saldos que no son el cierre anterior; el XML sí; el 03d marcó la continuidad del total como lectura).

### Precisión medida

| muestra | casos | resultado |
|---|---|---|
| errores por fuente única y multi (`revision_04c`) | 27 | 24 reales; 07: 8/8 (la mitad también en el PDF → `error_continuidad`); multi: 4/4 un solo error |
| solo-04, 1ª (`revision_04c_04`) | 10 | 1 error confirmado, 2 posibles, 7 desglose → D-CU8 |
| solo-04, 2ª | 10 | ECP por serie → D-CU9; 2 errores PDF confirmados |
| ramas del ECP (`revision_04c_ecp`) | 8 | desglose 4/4 sin error de cierre; PDF no cuadra 2/4 errores, 1 rótulo (→ regla), 1 fusión |

### Casos conocidos (`casos_conocidos.csv`, etapa 04c)
un fondo: 1 caso error_PDF raíz ERI · otro: error_PDF en el comparativo · otro: omisión del comparativo XML + reclasificación · otro: un rótulo · otro: sin caso.

### Límites y pendientes
- `error_PDF/XML` (19): cada documento coherente y cifras distintas, o el monto del PDF no se ubica en una sola columna del 03d.
- Continuidad por serie: el 03d solo la mide en el total. Reorganizar series en el saldo inicial no se detecta (dos casos vistos). Propuesta: continuidad por serie en el 03d y, si varias series antiguas suman una nueva, "reorganización de series".
- 03d: un salto en el inicio que está solo en el PDF y no en el XML queda como `probable_lectura`.
- Revisión de notas por caso (`muestra_notas.py`) y ficha con PDF y XML lado a lado (extender `06_ficha.py`).

## 06 – Ficha de revisión en forma de estado (2026-11-05)

La ficha pasa a ser el archivo de revisión de un fondo-año: rearma cada estado con lo que dice cada documento y deja las sumas como fórmulas de Excel, para revisar sin rearmar a mano.

**D-FI1. Lectura por líneas.** ESF, ERI y EFE: líneas del PDF (lector espacial del 03b, páginas ubicadas por sus subtotales) emparejadas con las cuentas del XML, primero por glosa parecida y, si no, por valor. Tres bloques: coinciden por glosa (orden del estado), solo por valor (glosa del PDF al lado de la cuenta del XML) y sin coincidencia. Dif = |PDF| − |XML|; el signo distinto se anota aparte (convención de cada documento).

**D-FI2. Verificación con fórmulas.** Por cada subtotal e identidad: el impreso (referencia a su celda), la suma de partes (`SUM`, o `ABS` en las identidades que restan) y la diferencia, en PDF y XML por separado. Partes del PDF: las líneas entre el subtotal anterior y el suyo, como el 03b; partes del XML: sus códigos.

**D-FI3. ECP por serie.** Lado PDF desde la lectura del 03d (`ecp_chequeos`); cada columna del 03d se asocia a la serie del XML con la que comparte más valores. Verificación por serie: transacciones, evolución, suma de series = total y continuidad dentro del mismo reporte.

**D-FI4. Hoja t+1 y veredicto.** Cada cifra de t frente a la misma cifra en el reporte de t+1 (columna anterior), en PDF y XML, más la continuidad cierre t = inicio t+1. Veredicto entre las cuatro versiones: 4 iguales → ok; 3 contra 1 → error en la que discrepa; 2 contra 2 → error en el grupo cuyo documento no cuadra internamente (subtotales e identidades en que participa la cifra), si el otro sí; si no, sin determinar (queda para las notas). El resumen de la hoja Fondo dice qué estados tienen error y en qué documento.

**D-FI5. Cruce y huérfanos.** Las vistas del cruce (identificación numérica del 04: sabe si un monto está en el PDF, no en qué línea) solo quedan cuando no hay lectura por líneas. Huérfanos de t y t+1, del PDF con la glosa de su línea (en el ECP, la fila y serie del 03d) y del XML: es el control de cobertura del lector.

**Ejemplo (un fondo).** La ficha muestra el reparto por serie del ECP errado en el PDF (3 contra 1, corregido sin nota en el comparativo del año siguiente), el resto que reaparece en las transacciones del año siguiente (el PDF no cuadra) y un aumento neto de efectivo con un dígito distinto (2.000) que ninguna etapa marcaba → D-EF1.

## 03b – Identidades del EFE (2026-11-05)

**D-EF1.** El 03b revisaba cada flujo contra sus líneas, no la identidad entre flujos. Se agregan `aumento_neto` (operación + financiamiento) y `evolucion_efectivo` (saldo inicial + aumento neto + diferencias de cambio = saldo final), buscadas después del primer flujo ubicado; si el valor no calza con el XML, por glosa única. Mismo esquema de `estructura_efe.csv` y misma clasificación. Ubicadas: 99,7% y 99,9%.

Efecto en el 04c: errores 332 → **368 casos en 298 fondo-año** (error_PDF 189 → 226). Muchos son ecos de un flujo que no suma (misma celda y diferencia → mismo caso). Precisión del check sin medir: muestra `--efe` (plantilla de una AGF con varios fondos marcados el mismo año, diferencias grandes y resto).

### D-EF2. Identidades del EFE: correcciones y precisión (2026-11-08)

Ajustes a la ubicación de las líneas (`identidades_efe` del 03b), cada uno por un falso positivo de la revisión o de la corrida:
- **Glosa partida**: "Aumento (disminución) neto de efectivo y" sin montos / "efectivo equivalente (315.080)". Se busca la glosa en dos líneas seguidas con el valor en la segunda; por glosa sola no se acepta una línea en 0 si el XML trae monto (un fondo).
- **Parte en cero en el XML**: vale 0 si no se ubica (saldo inicial de un fondo nuevo). Si el XML no trae la cuenta, solo la diferencia de cambio puede faltar: sin aumento neto la identidad no se evalúa.
- **Diferencia de cambio**: se busca aunque el XML diga 0 (hay PDF que la imprimen), pero por glosa nunca en una línea de aumento neto o de saldo ("aumento neto … antes del efecto de las diferencias de cambio" duplicaba el aumento).
- **Una línea, una parte**: el aumento neto se ubica primero (se confirma con su valor) y ninguna línea sirve para dos partes. Con montos corridos una línea respecto de su glosa (un fondo) las identidades quedan sin ubicar en vez de dar error.

Efecto en el 04c: 332 → **362 casos de error en 296 fondo-año** (+30 netos; los ecos de un flujo que no suma quedan en el caso del flujo).

**Precisión** (`revision_04c_efe`, 10 casos): 6 errores reales — tipeo del XML (7.000), dos PDF que no suman, y tres fondos de una misma AGF en 2023-2024 cuyo EFE no presenta el aumento neto o pone en esa línea el saldo final del año anterior (el saldo final cuadra) —; 1 otro (reexpresión del comparativo en el reporte siguiente); 3 de lectura: uno corregido arriba y dos glosas que el 03b no reconoce (saldo final y diferencia de cambio con otra redacción), que quedan para el lector unificado.

**Pendiente (lector unificado)**: sinónimos de glosas en una sola tabla para todas las etapas; montos corridos una línea cuando la glosa de un total ocupa dos líneas (también en la ERI de la ficha).

### D-L1. Lector unificado, paso 1: ESF, ERI y EFE (2026-11-09)

Una sola lectura del PDF y un solo emparejador para todas las etapas (`comun/lector.py`, `comun/emparejar.py`, `comun/glosario.csv`). Ninguna etapa lo usa todavia; `verificacion/diag_lector.py` escribe `procesado/lineas_pdf.csv` y mide.

**Lector** (no usa el XML): envuelve `filas_espaciales` y agrega:
- Estado de cada linea por titulo (en cualquier parte de una linea corta, tambien precedido del nombre del fondo); una pagina sin titulo se clasifica por lineas tipicas (total activo, total gastos, aportes de cuotas, flujo neto) y, si no hay, hereda la anterior.
- Filas de fecha, anio, nota o pagina leidas como montos: `encabezado`, no se emparejan.
- Glosas partidas (`glosa_partida`): montos en la primera linea (la glosa quedo abierta o la siguiente empieza en minuscula), en la ultima (vacia, solo signo "(+)" o cola como "entregados en garantia", "EQUIVALENTE") o repartidos entre las dos.
- `lector_espacial`: una pagina sin ningun monto de 3+ digitos (fondo en miles de dolares) no se leia; ahora, solo cuando no hay franjas, se buscan dos columnas de enteros cortos alineados (un fondo). Con una sola columna leia la de notas o un indice: se exigen dos.

**Emparejador** (usa el XML, no las validaciones): glosario (redacciones y exclusiones; manda sobre la similitud, que llega a 0,99), similitud tambien sobre el texto sin espacios (PDF extraidos pegados o con letras separadas), uno a uno: glosa, luego valor.

**Montos corridos**: la primera version usaba solo el XML y en una muestra de 15 acerto en 2. Corregia un PDF bien leido cuando el corrido estaba en el XML (un fondo: valor razonable 10.583 y venta 552 en el PDF; venta 10.583 y otros 552 en el XML), y tomaba glosas partidas por corrimientos. Ahora se corrige solo con evidencia de lectura: la linea que sobra con montos no es una cuenta (sin glosa, encabezado "...:" o sin codigo), montos >= 100, y ninguna otra linea con la misma glosa ya tiene el monto. Quedan 15 renglones en 14 fondo-anio.

**Cobertura** (4.258 fondo-anio; cuentas del XML con valor != 0 halladas en el PDF / con glosa y valor): ESF 98,2 / 96,1; ERI 98,0 / 96,8; EFE 97,8 / 96,8. Base sin glosario ni corridos: ESF 88,8 en glosa y valor.

**Pendiente**: estados sin renglones (ESF 63, ERI 80, EFE 82): en una muestra de 15, 10 son paginas que no estan en `paginas_estados` del 03 (el 03a solo guarda esas paginas) y 5 paginas con texto sin montos leidos. Propuesta: 03/03a con el rango continuo de paginas. ECP en el paso 1b.

### D-L2. Lector unificado: cobertura de paginas (2026-11-09)

Los estados sin renglones (63 ESF, 80 ERI, 82 EFE fondo-anio) tenian tres causas, revisadas en dos muestras de 15:
- **Paginas que el 03 no ve.** El 03 ubica paginas por contenido (>= N cifras del XML) y pierde las que calzan poco: fondos con montos chicos y estados con diferencias. `comun.lector.paginas_lector` agrega los huecos y una pagina antes y una despues (tres si el 03 vio menos de 4); el 03a las extrae (completa los cache existentes) y el lector usa una pagina agregada solo si trae el titulo de un estado arriba o >= 2 lineas tipicas de un solo estado. Una pagina que nombra 3+ estados (indice, informe del auditor) no cambia el estado.
- **Titulos no reconocidos**: en singular ("Estado de Resultado Integral", "Estado de cambio en el Patrimonio Neto"), con los anios en la misma linea, o un EFE sin titulo propio bajo "Notas a los estados financieros".
- **Texto ilegible**: una plantilla de un anio publica PDF cuyas palabras son "(cid:N)" (fuente sin tabla de caracteres). El 03a_ocr ahora hace OCR tambien de las paginas con mayoria "(cid:": 130 paginas en 14 fondo-anio, con lectura completa en la muestra.

**Resultado** (4.280 de 4.280 fondo-anio leidos; cuentas del XML con valor != 0 halladas / con glosa y valor): ESF 99,1 / 97,0; ERI 98,9 / 97,6; EFE 99,1 / 98,0. Estados sin renglones: 22 / 38 / 28.

El 03b, el 03c y la ficha usan el mismo cache: con el OCR nuevo y las paginas de montos chicos del lector_espacial leen paginas que antes salian vacias. Se mide en la regresion de cada etapa al migrarla.

### D-L3. Lector: titulo impreso de otro estado y fondos en su primer periodo (2026-11-09)

Revision de los 88 estados que seguian sin renglones:
- **Titulo impreso equivocado.** Hay PDF cuyo balance va bajo "Estado de Resultados Integrales" o "Estados de Flujos de efectivo" (la plantilla repite el titulo de otra pagina). El lector seguia el titulo. Ahora, si la pagina tiene >= 2 lineas tipicas de un solo estado y ninguna del titulado (y un solo titulo), manda el contenido; el titulo impreso queda en `rotulo` (`verificacion/diag_lector_rotulos.csv`). Primera corrida: 55 paginas en 49 fondo-anio. Es un candidato a hallazgo de presentacion: se verifica a mano antes de usarlo.
- **Fondo en su primer periodo con montos chicos**: una sola columna de enteros cortos. Se acepta si son montos (alguno de 3 digitos o >= 2 negativos), no notas ni un indice.
- **Limitacion del 03**: en algunos PDF de 2011 las paginas que entrega el 03 son notas (riesgo, vencimientos) y no los estados; el lector no las corrige.

**Resultado**: estados sin renglones 7 / 13 / 12 (ESF / ERI / EFE; antes 63 / 80 / 82). Cuentas del XML halladas / con glosa y valor: ESF 99,5 / 97,4; ERI 99,5 / 98,2; EFE 99,4 / 98,3.

**Precision (rotulos)**: muestra de 10 paginas (5 con rotulo ECP, 5 con rotulo ESF/ERI/EFE), revisadas en el PDF: 10/10 llevan impreso el titulo de otro estado. Se incorporan al 04c como caso de presentacion al migrarlo al lector.

### D-L4. Lector: PDF que el 03 no ubica, tablas como imagen y ficha sobre el lector (2026-11-09)

- **Universo**: el lector lee tambien los fondo-anio que el 03 deja fuera: `sin_texto` (PDF escaneado, con el OCR completo del 03a_ocr) y `sin_paginas_de_estados` (el 03 no encontro cifras del XML en el texto). Sin paginas del 03, el 03a extrae las primeras 15 y el lector usa solo las que traen titulo o lineas tipicas de un estado. Leidos: 4.493 de 4.510 (ok 4.280/4.280, sin_texto 193/195, sin_paginas 20/35). Estos fondo-anio no tienen cruce numerico del 04: la ficha muestra la lectura del PDF pero no huerfanos.
- **Tabla como imagen**: paginas con el titulo de un estado en texto y la tabla como imagen (<= 80 palabras, sin montos; un fondo). El 03 solo hacia OCR de estas paginas dentro de las que ubicaba; el 03a_ocr lo hace en todas las del cache. La lectura por OCR puede traer digitos mal leidos: una diferencia de un PDF leido por OCR se confirma en el PDF.
- **Conector en PDF con letras separadas**: "O t r o s ingresos" empieza con "O " y se tomaba como el conector "o" de una glosa partida (se pegaba a la linea de arriba). El conector debe ir seguido de una palabra de >= 2 letras.
- **Ficha**: las hojas de forma, t-1 y t+1 leen con el lector y el emparejador comunes (sin el emparejador propio ni las paginas del 03b). En 12 casos de prueba: 9 iguales o mejores (tres PDF con texto pegado o letras separadas pasan de 2-3 a 8-17 cuentas por glosa por estado; errores de lectura de saldo final, diferencia de cambio y "468"/"4" desaparecen), uno lee un monto que antes se perdia y uno corregido (el conector).

**Cobertura** (cuentas del XML con valor != 0 halladas / con glosa y valor): ESF 98,9 / 96,7; ERI 98,9 / 97,6; EFE 98,9 / 97,8, sobre 4.510 fondo-anio.

### D-L5. 03b sobre el lector unificado (2026-11-10)

El 03b ubica subtotales e identidades con los renglones del lector ya emparejados (`comun.emparejar.leer_y_emparejar`), en vez de su propia ubicacion por glosa y posicion. La salida (`estructura_efe.csv`, `estructura_efe_no_suma.csv`) y la clasificacion de los que no suman no cambian.

- **Subtotal** = renglon de su codigo (metodo glosa_y_valor / valor / solo_glosa). **Componentes** = renglones del mismo estado entre el subtotal anterior y el suyo. Cortan: el renglon de otro subtotal o identidad del mismo estado (la diferencia de cambio sobre efectivo es parte de la ERI y linea de identidad del EFE: un solo conjunto de cortes cortaba los ingresos), una linea "total/subtotal/flujo neto" que no es parte del subtotal (aunque el emparejador le haya dado otra cuenta) y el activo neto atribuible (linea del ECP o del ESF dentro de otro estado). No se suman las lineas sin cuenta cuyos montos son el anio del documento o un dia de cierre.
- **Identidades del EFE**: cada parte es el renglon de su codigo; salen los parches v4-v7 (glosa partida, una linea una parte, exclusiones de la diferencia de cambio), que ahora resuelve el emparejador.
- **Lectura** (comun/lector.py): son encabezado, sea cual sea el numero al lado, el periodo del estado ("por el periodo comprendido", "desde el ... de"), la unidad ("expresado en miles de"), datos de contacto ("@", "www.", "+56"), fechas en la glosa ("N° 31.12.2018"), dia y anio en una linea de fecha ("31 | 2015"), anios en una linea de seccion ("ACTIVOS 2019") y un titulo con un numero chico (entrada de indice, que ademas no cambia el estado).
- **Clasificacion**: un no-suma es lectura si el bloque paso por la correccion de montos corridos, si la linea de al lado trae el subtotal del XML (montos corridos que el lector no corrigio: un fondo) o si la diferencia es imposible (> 10^13, digitos de OCR pegados).

**Ubicacion** (fondo-anio, 03b anterior -> nuevo): total gastos 96,3 -> 99,0; total ingresos 97,5 -> 99,1; aumento neto 99,3 -> 100; operacion 98,7 -> 99,2; financiamiento 98,8 -> 99,3; el resto +0,1 a +0,3. Universo: tambien los `sin_paginas_de_estados`.

**Regresion contra el 03b anterior** (`verificacion/revision_03b.xlsx`): errores del 04c 367 -> 365 (+6 / -8). Aparecen: el aumento neto impreso en 0 de un fondo (patron ya confirmado de esa AGF, error real), un caso del 07 que cambia de tipo, dos de lectura conocida que vienen del 04b y una diferencia de 7. Se van: lectura que el lector corrige (3), dos diferencias de 6 y 9, el caso del 07 que cambia de tipo y dos del 04 por revisar (dos fondo-anio). En la iteracion se corrigieron 8 falsos positivos de lectura (indice, unidad, periodo, contacto del auditor, total del activo dentro del pasivo).

### D-L6. 03c sobre el lector unificado (2026-11-10)

El 03c ubica sus lineas (activo neto, utilidad de la operacion, efectivo, saldo final y resultado del ERI antes y despues de la distribucion) con los renglones del lector ya emparejados (`comun.emparejar.leer_y_emparejar`): cada linea es el renglon de su codigo. Salen la lectura por pagina, la regex de cada linea, el corte en el titulo del ECP y los respaldos por posicion ("antes de Distribucion") y por fila vecina con guiones. Identidades, clasificacion y salidas no cambian. Universo: tambien los `sin_paginas_de_estados`.

- **Linea dudosa**: una linea emparejada solo por glosa con las DOS columnas distintas al XML no se usa (queda sin ubicar). Casi siempre es otro renglon de glosa parecida (utilidad antes de impuesto no impresa: se tomaba un renglon en 0) o una lectura mala (digitos pegados o cortados). Un error real en una columna deja la otra calzando (glosa y valor); con una sola columna en el XML (primer anio) se acepta. Sin esta regla, 58 de 68 identidades nuevas que no cuadraban venian de estas lineas.
- **Lector**: una pagina con "transicion ... NIIF", "segun PCGA" o "efecto de la transicion" en sus primeras lineas no es un estado (nota de transicion a NIIF de 2011, con las mismas lineas y montos del ERI o el ESF en columnas PCGA / efecto / NIIF). El 03 la toma por contenido y el lector la leia como ERI (un fondo-anio: utilidad tomada de la nota, falso error del PDF).

**Ubicacion** (fondo-anio, 03c anterior -> nuevo): efectivo 4.351 -> 4.409, saldo final 4.375 -> 4.458, resultado despues de distribucion 4.305 -> 4.394, activo neto +7, utilidad +11; resultado antes de distribucion 4.393 -> 4.342 (82 lineas dudosas descartadas; no entra en las identidades y el 03d no cambia). Efectivo ESF = saldo final EFE: cuadra_pdf 98,9 -> 99,7 %.

**Regresion contra el 03c anterior**: probable_error_pdf 40 -> 40, probable_error_xml 35 -> 34, probable_lectura 68 -> 21, probable_lectura_ocr 73 -> 51; 03b, 03d, 04b y 04c sin cambios. El error del XML que se va (un fondo-anio) era un artefacto: el PDF trae un anio mas que el XML (el comparativo del PDF es el periodo actual del XML, en todas las cuentas), asi que ninguna linea calza en valor y el 03c anterior comparaba montos de periodos distintos. Queda como hallazgo a verificar aparte (PDF y XML de periodos distintos), no como error de una identidad. Validacion con casos conocidos: 7 de 7.

### D-L7. 03d: paginas del ECP desde el lector unificado (2026-11-11)

El 03d toma las paginas del ECP del lector (`paginas_de` + `leer_estados`: las que quedan en estado ECP), las mismas que ven el 03b, el 03c y la ficha, y suma los `sin_paginas_de_estados` al universo. Antes leia las paginas del 03 mas las de OCR, solo si traian el titulo del ECP en el texto: perdia las paginas fuera del 03 (el ECP suele calzar poco con las cifras del XML por estar en series), las continuaciones sin titulo y el ECP titulado como otro estado; y leia paginas que solo mencionan el estado (indice). La lectura de filas (`lector_multicolumna` + reglas por glosa) y los chequeos no cambian.

**Diagnostico previo** (`verificacion/diag_03d_paginas.py`): ningun fondo-anio pierde bloques; 62 ganan. Fondo-anio con bloque 4.191 -> 4.241, bloques del anio o el anterior 7.821 -> 7.920; los `sin_paginas_de_estados` pasan de 0 a 18 con bloque.

**Regresion contra el 03d anterior**: los chequeos que cuadran no cambian (evolucion 98,0 -> 97,9 por los bloques nuevos), 03b, 03c, 04b y 04c sin cambios. probable_error* +7 casos (fondo-anio-columna), -0, todos de bloques que antes no se leian: el rotulo del aumento neto por transacciones (impreso inicio + aportes - rescates) en dos fondos de una AGF, confirmado contra el PDF (en un comparativo sale como error del PDF en la evolucion: misma causa); y la continuidad del XML en un fondo-anio, cuyo ECP del comparativo viene titulado "Estado de Flujo de Efectivo" (titulo de otro estado, confirmado) y cuyo XML no corresponde al periodo del PDF (pendiente de verificar a mano). Casos conocidos del 03d: 18 de 18.

**Fuera de alcance**: emparejar las filas del ECP con el glosario y las columnas con las series del XML. Las reglas por glosa del 03d validan los casos conocidos; cambiarlas no gana cobertura.
