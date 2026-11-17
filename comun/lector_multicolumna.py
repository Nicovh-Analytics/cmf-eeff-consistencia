"""
Lector de estados con N columnas de montos (ECP: una columna por serie + Total)
===============================================================================

Variante del lector_espacial para paginas donde los montos no estan en dos
columnas (actual/anterior) sino en N: el estado de cambios en el activo neto
trae una columna por serie y una de total, y cada periodo va en su propio bloque.

  1. Montos y signos: mismas reglas que lector_espacial (_unir_tocandose,
     _valor_espacial): trozos pegados, parentesis o guion = negativo, "-" = 0.
  2. Franjas: bordes derechos de los montos, agrupados (GAP_FRANJA). A diferencia
     del lector de dos columnas, se buscan desde el 25% del ancho: con 9-10 series
     la primera columna empieza cerca de la glosa (x1 ~ 270 de 792).
  3. Lineas: palabras agrupadas por altura (+-3 pt). Cada monto va a la franja
     mas cercana (<= TOL_FRANJA); enteros de 1-2 digitos lejos de una franja
     son notas y se descartan.
  4. Renglones: una linea que empieza en mayuscula abre renglon; las que empiezan
     en minuscula, "(" o sin texto lo continuan (glosas partidas en 2-3 lineas,
     con los montos en la primera, la del medio o la ultima).

Devuelve (renglones, franjas): renglones = [{"glosa", "vals": {indice_franja: valor},
"irr": {indices con agrupacion de miles irregular}, "y"}], en orden vertical. No usa el XML.
"""
import re

from comun.lector_espacial import (GAP_FRANJA, RE_FECHA_NUM, RE_NUMTOK, TOL_FRANJA,
                                   _es_monto_de_franja, _unir_tocandose, _valor_espacial)

X_MIN = 0.25          # las franjas se buscan a la derecha del 25% del ancho
MIN_FRANJA = 3        # una columna real tiene al menos 3 montos en la pagina
TOL_LINEA = 3.0       # palabras de una misma linea (pt)
# Continua la fila anterior: minuscula o "(" que no abre una glosa ("(+ o -)", "(-)").
# "(Disminucion)/Aumento neto ..." empieza fila nueva.
RE_CONTINUA = re.compile(r"^([a-záéíóúñ]|\((?![A-ZÁÉÍÓÚÑ]))")


MESES = re.compile(r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|sep?tiembre|octubre|noviembre|diciembre",
                   re.I)


def _fechas_glosa(palabras):
    """Dias de las glosas ("al 1 de enero", "al 31 de diciembre"): entero de 1-2 digitos con un mes
    a su derecha en la misma linea. En la variante cortos formaban una columna falsa (revision D-L9:
    una serie vacia, o tablas que perdian las series del inicio y del cierre)."""
    out = set()
    for w in palabras:
        if re.fullmatch(r"\d{1,2}", w[0]) and any(
                abs(v[3] - w[3]) <= 2 and 0 <= v[1] - w[2] <= 60 and MESES.search(v[0]) for v in palabras):
            out.add((w[2], w[3]))
    return out


RE_CORTO = re.compile(r"\(?[-−–—]?\d{1,2}\)?")      # monto de 1-2 digitos: "6", "(18)"


def _agrupar(xs):
    grupos = []
    for x in sorted(xs):
        if grupos and x - grupos[-1][-1] <= GAP_FRANJA:
            grupos[-1].append(x)
        else:
            grupos.append([x])
    return grupos


def franjas_multi(nums, ancho, cortos=False):
    """Bordes derechos de las columnas de montos, de izquierda a derecha.
    Primero con montos "de franja" (separador de miles o 3+ digitos). Despues, las series de
    montos chicos (1-2 digitos y guiones: fondos o series pequenas) que no forman franja con esa
    regla y quedaban "lejos" de toda franja, descartadas sin aviso (diag_suma_series: la mayor
    causa de suma_series de lectura): enteros cortos alineados fuera de las franjas, 3+ en la
    columna. No a la izquierda de la primera franja por mas de 1,5 pasos: ahi va la columna de notas.
    Solo con cortos=True: en el universo esta pasada sola agrega columnas falsas (bloques confiables
    80% -> 63%); el 03d la usa como variante y se queda con ella solo si la tabla suma mejor."""
    franjas = [sorted(g)[len(g) // 2] for g in
               _agrupar(w[2] for w in nums if w[2] > ancho * X_MIN and _es_monto_de_franja(w[0]))
               if len(g) >= MIN_FRANJA]
    if len(franjas) < 2:
        return franjas
    paso = sorted(b - a for a, b in zip(franjas, franjas[1:]))[(len(franjas) - 1) // 2]
    # Tablas anchas (15+ series): las primeras columnas quedan antes del 25% del ancho y se perdian
    # enteras (diag_suma_series: dos series en x1 139 y 176 con la primera franja en 217). Se agregan
    # hacia la izquierda solo si siguen el paso regular de las columnas, una a una.
    izq = sorted((sorted(g)[len(g) // 2] for g in
                  _agrupar(w[2] for w in nums if w[2] <= ancho * X_MIN and _es_monto_de_franja(w[0]))
                  if len(g) >= MIN_FRANJA), reverse=True)
    for x in izq:
        if abs(franjas[0] - x - paso) <= GAP_FRANJA / 2:
            franjas.insert(0, x)
    if not cortos:
        return franjas
    cortos = [w[2] for w in nums if w[2] > ancho * X_MIN and RE_CORTO.fullmatch(w[0])
              and min(abs(w[2] - f) for f in franjas) > TOL_FRANJA]
    nuevas = [sorted(g)[len(g) // 2] for g in _agrupar(cortos) if len(g) >= MIN_FRANJA]
    return sorted(franjas + [x for x in nuevas if x >= franjas[0] - 1.5 * paso])


RE_INCOMPLETO = re.compile(r"\(?[-−–—]?\d{1,3}(?:\.\d{3})*\.\d{1,2}")    # "(5.250.38": ultimo grupo corto
RE_RESTO = re.compile(r"\d{1,2}\)?")                                    # "9)" en la linea de abajo


def _unir_cortados(nums):
    """Monto que no cabe en la celda: los ultimos digitos bajan a la linea siguiente con el
    mismo borde derecho ("(5.250.38" / "9)"). Un monto normal termina en un grupo de 3."""
    usados, out = set(), []
    for i, w in enumerate(nums):
        if i in usados:
            continue
        if RE_INCOMPLETO.fullmatch(w[0]):
            j = next((j for j, o in enumerate(nums) if j != i and j not in usados and RE_RESTO.fullmatch(o[0])
                      and abs(o[2] - w[2]) <= 3 and 3 <= o[3] - w[3] <= 14), None)
            if j is not None:
                o = nums[j]
                usados.add(j)
                out.append([w[0] + o[0], w[1], max(w[2], o[2]), o[3], o[4]])   # queda en la linea de abajo
                continue
        out.append(w)
    return out


def filas_multicolumna(pagina, cortos=False):
    """cortos=True: tambien columnas de montos chicos y enteros cortos dentro de la tabla como
    montos (no notas). Ver franjas_multi."""
    palabras, ancho = pagina["palabras"], pagina["ancho"]
    es_num = lambda t: bool(RE_NUMTOK.match(t)) and not RE_FECHA_NUM.match(t)
    nums = _unir_tocandose([w for w in palabras if es_num(w[0])])
    nums = _unir_cortados(nums)
    if cortos:
        fechas = _fechas_glosa(palabras)
        nums = [w for w in nums if (w[2], w[3]) not in fechas]
    # Los anios van como texto (no son montos): sirven para fechar cada bloque
    textos = [w for w in palabras if not es_num(w[0]) or re.fullmatch(r"\(?(19|20)\d\d\)?", w[0])]
    # Plantillas con digitos sueltos ("2 0 2 2"): el anio solo aparece al unirlos
    textos += [w for w in nums if re.fullmatch(r"(19|20)\d\d", w[0])]
    franjas = franjas_multi(nums, ancho, cortos)
    if not franjas:
        return [], []

    items = [(w[3], "t", w) for w in textos]
    for w in nums:
        if re.fullmatch(r"(19|20)\d\d", w[0]):
            continue                                   # anio del titulo o del encabezado
        v, irregular = _valor_espacial(w[0])
        if v is None:
            continue
        d = [abs(w[2] - f) for f in franjas]
        k = min(range(len(franjas)), key=d.__getitem__)
        if d[k] > TOL_FRANJA:
            continue                                   # nota, numero de la glosa, pie de pagina
        # nota pegada a la primera columna. Con cortos, solo a su IZQUIERDA: dentro de la tabla un
        # entero corto a > 5 pt es un monto chico ("(26)" / "48": el parentesis corre el borde ~6 pt)
        if (re.fullmatch(r"\(?\d{1,2}\)?", w[0]) and d[k] > 5
                and (not cortos or (k == 0 and w[2] < franjas[0]))):
            continue
        items.append((w[3], "n", (k, v, irregular)))

    lineas = []
    for y, tipo, x in sorted(items, key=lambda i: i[0]):
        if not lineas or y - lineas[-1]["y"] > TOL_LINEA:
            lineas.append({"y": y, "txt": [], "vals": {}, "irr": set()})
        if tipo == "t":
            lineas[-1]["txt"].append(x)
        else:
            lineas[-1]["vals"].setdefault(x[0], x[1])
            if x[2]:
                lineas[-1]["irr"].add(x[0])          # "26.767.9609": agrupacion irregular

    renglones = []
    for ln in lineas:
        txt = " ".join(w[0] for w in sorted(ln["txt"], key=lambda w: w[1])).strip()
        # Un anio solo en su linea continua la glosa: "... al 31 de diciembre de" / "2020"
        continua = (not txt) or bool(RE_CONTINUA.match(txt)) or bool(re.fullmatch(r"\(?(19|20)\d\d\)?\.?", txt))
        r = renglones[-1] if renglones else None
        # Un renglon que ya tiene montos no absorbe otra linea con montos: eso es otro renglon.
        # Salvo que sus "montos" sean solo guiones: glosa en 2 lineas con un "-" suelto en la
        # primera y los montos en la segunda (revision 03d_eri: el "antes de distribucion"
        # quedaba en 0). Los montos de la continuacion reemplazan a los guiones.
        solo_guiones = r is not None and r["vals"] and not any(r["vals"].values())
        if r is not None and continua and not (ln["vals"] and r["vals"] and not solo_guiones):
            r["glosa"] = (r["glosa"] + " " + txt).strip()
            for k, v in ln["vals"].items():
                if solo_guiones:
                    r["vals"][k] = v
                else:
                    r["vals"].setdefault(k, v)
            r["irr"] |= ln["irr"]
        else:
            renglones.append({"glosa": txt, "vals": dict(ln["vals"]), "y": ln["y"], "irr": set(ln["irr"])})
    return renglones, franjas


def columna_total(pagina, franjas, y_desde=None, y_hasta=None):
    """True si la ultima franja tiene un rotulo "Total" encima (encabezado de la tabla).
    Con y_desde / y_hasta solo mira esa franja vertical (el encabezado de UNA tabla: hay
    paginas con dos tablas apiladas del mismo periodo y solo la segunda trae el Total)."""
    if len(franjas) < 2:
        return False
    f = franjas[-1]
    return any(re.match(r"total", w[0], re.I) and f - 70 <= w[2] <= f + 5
               and (y_desde is None or y_desde < w[3] < y_hasta) for w in pagina["palabras"])