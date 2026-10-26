# Auditoría automatizada de estados financieros de fondos mutuos (CMF Chile)

¿El estado financiero auditado que lee el público es un espejo fiel de lo que la administradora reporta al regulador?

Este proyecto descarga los estados financieros anuales de los fondos mutuos chilenos publicados por la CMF (2011–2025) y los audita en forma automática, con los mismos criterios que usaría un auditor: cuadraturas, consistencia entre documentos y continuidad entre períodos.

> *English summary: an automated audit of ~4,500 annual financial statements of Chilean mutual funds published by the regulator (CMF). It cross-checks the machine-readable XML against the signed PDF, verifies continuity between years and recomputes the cash-flow statement subtotals directly from the PDF using word coordinates. Manually reviewed flags: 9/9 confirmed as real PDF errors.*

---

## Por qué importa

Cada fondo mutuo entrega a la CMF dos versiones de sus estados financieros:

- un **XML** estructurado, que pasa por las validaciones físicas y lógicas de la CMF, y
- un **PDF** con los estados auditados y firmados, que es lo que lee el inversionista.

Nadie verifica de forma sistemática que digan lo mismo. Tampoco que el "año anterior" que muestra cada reporte coincida con lo que se auditó ese año, ni que el PDF sume.

## Qué hace

| etapa | script | qué hace |
|---|---|---|
| 1 | `01_recolector.py` | Descarga XML y PDF de cada fondo-año desde el sitio de la CMF. Es reanudable y conservador con el servidor. |
| 2 | `02_parser.py` | Pasa el XML a tablas: encabezados (fondo, AGF, moneda, auditor) y cuentas (código, serie, período, valor). |
| 3 | `03_cruce_PDF.py` | **Cruce espejo:** busca cada cifra del XML en el PDF del mismo envío. |
| 3a | `03a_coordenadas.py` | Extrae las palabras de las páginas de estados **con su posición** en la página. |
| 3b | `03b_estructura.py` + `lector_espacial.py` | **Estructura del EFE:** reconstruye el estado de flujos desde el PDF y verifica que los subtotales sumen. |
| 4 | `04_candidatos.py` | Tipifica las discrepancias del cruce (redistribución entre series, signo invertido, rótulo, agregación), les asigna gravedad y aplica materialidad. |
| 6 | `06_ficha.py` | Ficha Excel por caso: XML, PDF y año anterior, lado a lado, para revisión manual. |
| 7 | `07_continuidad.py` | **Continuidad:** compara el comparativo de cada año con el original del año anterior, el arrastre de saldos y las identidades contables dentro del XML. |

Cada regla del pipeline existe por un caso concreto. El registro está en [`docs/decisiones.md`](docs/decisiones.md): qué se decidió, por qué, qué efecto tuvo y qué no resuelve.

## Resultados

**Universo:** ~4.500 estados financieros anuales de fondos mutuos vigentes, 2011–2025.

### Estructura de los estados leída desde el PDF (03b)

Se reconstruyen desde el PDF seis subtotales —flujo de operación y de financiamiento (EFE), total activo y total pasivo (ESF), total ingresos y total gastos (ERI)— y se verifica que cada uno sea la suma de sus líneas. La lectura usa solo la geometría de la página; el XML no interviene en cómo se lee el PDF.

| | |
|---|---|
| fondo-año analizados | 4.473 (193 de ellos escaneados, leídos con OCR) |
| subtotales ubicados en el PDF | 97,5% a 99,3% según el subtotal |
| subtotales de estados publicados como imagen (OCR) | 2.477 leídos, 2.236 cuadran (90%); los que no cuadran se tratan como lectura, nunca como error |
| subtotal-columna que no suman | 474 (233 de ellos, lectura de OCR) |
| **clasificados como probable error del PDF** | **71** |

Cada caso que no suma se clasifica:

| clase | qué significa |
|---|---|
| `probable_error` / `_tipeo` / `_linea_no_sumada` | las líneas no suman al total impreso, por un dígito, una transposición o una línea que no entra |
| `probable_error_linea_distinta` | el total impreso coincide con el XML, pero una línea del PDF está mal (la suma difiere < 5%) |
| `probable_lectura` / `probable_lectura_ocr` | la diferencia es grosera (líneas que faltan, dígitos pegados): el error es nuestro |
| `observacion_inmaterial` | diferencia ≤ 100 (M$) o ≤ 1 (otra moneda) |

**Dónde está el error:** en el EFE, el subtotal impreso es correcto y el error está en una línea. En el ESF y el ERI es al revés: en 18 de 22 casos confirmados el error está en el **total impreso** (un dígito, una transposición, el valor de otra línea o el total en blanco), mientras sus partidas coinciden con el XML. En tres casos el total repite el valor de otra línea del mismo estado (ingresos, utilidad, activo neto), lo que apunta a fórmulas mal referenciadas en la planilla que arma el PDF. Varios errores se repiten en el comparativo del año siguiente.

También se registran **observaciones de formato**: agrupación de miles mal escrita (`(3.021424)`), paréntesis duplicados, coma en vez de punto (`4.475,324`), caracteres sueltos impresos entre columnas y un estado de cambios rotulado como "Estado de Flujo de Efectivo".

### Cruce espejo XML ↔ PDF (03, 04)

| | fondo-año |
|---|---|
| evaluados | 4.280 |
| espejo completo (cada cifra del XML está en el PDF) | 2.825 (66%) |
| verificación parcial (alguna página no se pudo leer; sin señales de discrepancia) | 848 |
| **candidatos** (cifra del XML con otro valor en el PDF) | **607** |

Los candidatos se tipifican (discrepancia consistente, par aislado, redistribución entre series, signo invertido) y se les asigna una pista de subtipo: agregación de líneas sin código en el XML, rótulo incorrecto, series cargadas por posición. Con materialidad por moneda:

| revisión | candidatos |
|---|---|
| gravedad demostrada por la regla (no requiere revisión) | 133 |
| observación inmaterial (no se revisa) | 190 |
| revisión manual | 284 |

### Continuidad entre años (07)

Para cada par de años consecutivos, el comparativo que presenta el año *t* se contrasta con lo que se reportó y auditó el año *t−1*:

| comparativo vs original | fondo-año |
|---|---|
| idéntico | 3.286 |
| modificado | 518 |
| diferencia menor | 158 |
| saldos modificados | 69 |
| incompleto / subtotal vacío | 48 |

Además, 204 fondo-año tienen al menos una identidad contable rota **dentro del mismo XML** (por ejemplo, una suma de líneas que no da el total).
Además, **3 XML repiten íntegramente las cifras del año anterior**, con el período nuevo declarado: el 100% de sus cuentas es idéntico al XML previo (más 1 caso parcial, con 80%). En el resto del universo, ningún fondo-año supera el 25% de cuentas iguales. El cruce espejo no los detectaba, porque las cifras están en el PDF, pero en la columna del comparativo.

**Alcance de las validaciones de la CMF.** La CMF cuenta con validaciones físicas y lógicas sobre el XML, cuyo alcance está pendiente de confirmación por parte del regulador. Mientras tanto, los datos dan pistas: hay identidades contables que fallan solo en la columna comparativa y nunca en la actual (por ejemplo, las sumas del estado de situación comparativo no muestran fallas en 2011–2016 y sí desde 2017). Eso sugiere qué se valida y qué no, pero es una hipótesis hasta tener la respuesta oficial.

## Validación

Cada etapa que marca casos se contrastó con revisión manual del PDF original:

| etapa | validación |
|---|---|
| 04 cruce espejo | muestra de 30 candidatos: 30/30 confirmados |
| 07 continuidad | 8/8 casos conocidos detectados |
| 03b, `probable_error*` del EFE | 9/9 (muestra 1) y 14/15 (muestra 2, independiente) |
| 03b, `probable_error*` del ESF/ERI | 22/22¹ |
| 03b, `probable_error_linea_distinta` | 5/5 en la muestra que la originó; **10/11 fuera de muestra** |
| 03b, no detección | errores reales escondidos en las clases de lectura: 5/35 (14%), hoy capturados por `linea_distinta`; en páginas OCR: 0/15 |

¹ Esa muestra (37 casos) también se usó para corregir el lector: 16 eran lectura nuestra, por 4 causas que se corrigieron. La cifra es en muestra.


## Hallazgos de método

**1. El cruce por números tiene un punto ciego.** Buscar cada cifra del XML en el PDF no detecta un error si el valor equivocado coincide con otra cifra del documento, porque no queda ningún monto huérfano. Por eso el 03b no busca cifras: **reconstruye cada estado y verifica que sume**. Medido: de 69 fondo-año con error estructural en el PDF, **34 no aparecen** entre los candidatos del cruce espejo.

**2. Leer el PDF por posición, no por texto.** La primera versión del 03b leía el texto extraído y acumuló reglas por cada plantilla de AGF: números de nota, montos partidos por la extracción, negrita simulada, glosas en dos líneas. Además usaba el XML para decidir cómo leer el PDF, y **auditar un documento usando como árbitro al documento auditado sesga el resultado**. La versión final usa la geometría de la página:

- los trozos de un monto están pegados (< 1 pt) y las columnas separadas por 70–90 pt;
- la columna de cada monto se decide por su borde derecho;
- el signo es el paréntesis o guion pegado (< 6 pt).

Con eso, el ruido de lectura cayó a la mitad y la ubicación de subtotales subió de 96% a 98,7%, sin usar el XML para leer.

**3. Materialidad.** Como en una auditoría real, las diferencias iguales o menores a un umbral se registran como observación pero no se revisan: 100 en fondos en pesos (montos en M$) y 1 en fondos en otra moneda. Es una sola definición (`config.py`) que usan el cruce espejo (04) y la estructura del EFE (03b).

## Limitaciones

- **PDF escaneados:** se leen con OCR (Tesseract). El 10% de los subtotales escaneados que no cuadra se trata como lectura, nunca como error, así que en esos documentos el método puede no ver un error real.
- **Solo el EFE en la pasada estructural.** El ESF y el ERI requieren solo configuración (subtotales y glosas). El ECP tiene una columna por serie y requiere otro diseño.
- **Solo fondos vigentes** (sesgo de supervivencia) y **solo el último envío** de cada fondo-año (los reenvíos no son observables).
- **El cruce detecta desacuerdo, no culpa.** Cuál de los dos documentos tiene el error se determina caso a caso, en revisión manual.

## Uso responsable

Los resultados son **observaciones técnicas sobre documentos públicos**, no imputaciones. Este repositorio no publica nombres de administradoras ni de fondos asociados a observaciones: en la documentación, las administradoras aparecen como "AGF A", "AGF B"… y los fondos como "F01", "F02"…, con claves que se mantienen fuera del repositorio. Los casos conocidos que usa la validación automática tampoco se versionan. Ningún caso se discute sin verificación manual contra el documento original.

## Cómo correrlo

```bash
pip install -r requirements.txt
python 01_recolector.py      # descarga (lento; reanudable)
python 02_parser.py
python 03_cruce_PDF.py
python 03a_coordenadas.py    # una vez; ~15-30 min en paralelo
python 03b_estructura.py
python 04_candidatos.py
python 07_continuidad.py
```

Los datos (`data/`) y las planillas de verificación manual (`verificacion/`) no se versionan.

## Estructura

```
01_recolector.py … 07_continuidad.py   pipeline (en orden de ejecución; 05 es herramienta)
lector_espacial.py                       lectura de estados por coordenadas
config.py                                parámetros compartidos (materialidad)
herramientas/diag_coords.py              inspección de coordenadas de una página
herramientas/muestra_04.py               muestra estratificada para verificar a mano los candidatos del 04
docs/decisiones.md                       registro de decisiones y casos
```

---

Autor: Nicolás Valdenegro H. — Contador Auditor. Proyecto personal de portafolio en análisis de datos.
