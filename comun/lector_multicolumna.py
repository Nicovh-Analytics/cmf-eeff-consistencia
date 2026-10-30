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


def franjas_multi(nums, ancho):
    """Bordes derechos de las columnas de montos, de izquierda a derecha."""
    xs = sorted(w[2] for w in nums if w[2] > ancho * X_MIN and _es_monto_de_franja(w[0]))
    grupos = []
    for x in xs:
        if grupos and x - grupos[-1][-1] <= GAP_FRANJA:
            grupos[-1].append(x)
        else:
            grupos.append([x])
    return [sorted(g)[len(g) // 2] for g in grupos if len(g) >= MIN_FRANJA]


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


def filas_multicolumna(pagina):
    palabras, ancho = pagina["palabras"], pagina["ancho"]
    es_num = lambda t: bool(RE_NUMTOK.match(t)) and not RE_FECHA_NUM.match(t)
    nums = _unir_tocandose([w for w in palabras if es_num(w[0])])
    nums = _unir_cortados(nums)
    # Los anios van como texto (no son montos): sirven para fechar cada bloque
    textos = [w for w in palabras if not es_num(w[0]) or re.fullmatch(r"\(?(19|20)\d\d\)?", w[0])]
    # Plantillas con digitos sueltos ("2 0 2 2"): el anio solo aparece al unirlos
    textos += [w for w in nums if re.fullmatch(r"(19|20)\d\d", w[0])]
    franjas = franjas_multi(nums, ancho)
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
        if re.fullmatch(r"\(?\d{1,2}\)?", w[0]) and d[k] > 5:
            continue                                   # nota pegada a la primera columna
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