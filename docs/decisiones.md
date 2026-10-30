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
