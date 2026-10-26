"""
Lector espacial de estados financieros en PDF
=============================================

Reconstruye las lineas de una pagina (glosa + monto actual + monto anterior)
a partir de las palabras con coordenadas que guarda 03a_coordenadas.py.
NO usa el XML: la columna de cada monto se decide por su posicion.

  1. Une trozos de un mismo monto que la extraccion separo pero estan pegados
     ("1"+"5.772.597", "("+"63.180)"); un "(" o "-" a <6 pt es el signo.
  2. Franjas de columnas: bordes derechos (x1) de los montos agrupados; las dos
     franjas de mas a la derecha son actual y anterior (una sola: primer anio).
  3. Enteros de 1-2 digitos a la izquierda de la franja actual = numero de nota.
  4. Cada monto se pega a la glosa mas cercana en vertical (<=12 pt),
     prefiriendo filas que ya tienen montos (glosa partida en dos lineas).
  5. Continuaciones de glosa en minuscula sin montos se unen a la fila anterior.
  6. Montos con formato irregular ("(3.021424)", "((31.340.008.234)") se reportan.

Parametros medidos sobre PDFs reales de distintas plantillas de AGF.
"""

import gzip
import json
import re
from pathlib import Path
from config import CMF_HOME

RE_CONTINUACION = re.compile(r"^[a-záéíóúñ][^\d]{0,40}$")
DIR_COORDS = CMF_HOME / "coords_pdf"
GAP_UNION = 2.0       # trozos de un mismo monto: separados por <1 pt (medido: 0.0-0.1)
GAP_FRANJA = 20.0     # separacion minima entre franjas de columnas (medido: 70-90)
TOL_FRANJA = 20.0     # distancia maxima del borde derecho a la franja (guion centrado: ~13)
TOL_FILA = 12.0       # distancia vertical maxima monto -> glosa (medido: hasta 6)
RE_FECHA_NUM = re.compile(r"^\d{1,2}[./-]\d{1,2}[./-]\d{2,4}$")   # 31.12.2021 es texto, no monto
RE_NUMTOK = re.compile(r"^\(*[-−–—]?[\d.]*\d[\d.]*(,\d{2})?\)*$|^\($|^[-−–—]$|^[\d.]*\)$|^\.$")
RE_GUION = re.compile(r"^[-−–—]$")
RE_MILES_OK = re.compile(r"\d{1,3}(?:\.\d{3})*")
RE_MILES_COMA = re.compile(r"^\(?-?\d{1,3}(?:[.,]\d{3})+\)?[.,]?$")


def normalizar_ocr(pagina):
    """OCR: '17,553,514' -> '17.553.514' (separador de miles leido como coma). Solo
    con grupos de 3 digitos: '1,40' (decimal) no cambia."""
    for w in pagina["palabras"]:
        if "," in w[0] and RE_MILES_COMA.match(w[0]):
            w[0] = w[0].replace(",", ".")
    return pagina


def _valor_espacial(t):
    """(valor, formato_irregular). '(3.021424)' -> (-3021424, True)."""
    if RE_FECHA_NUM.match(t.strip("()")):
        return None, False          # "31.12.2023" (tambien si llego partida y se unio)
    if RE_GUION.match(t):
        return 0, False
    nucleo = t.strip("()-−–— ")
    nucleo = re.sub(r",\d{2}$", "", nucleo)      # "86.451,00": decimales de presentacion (cifras en miles)
    dig = re.sub(r"\D", "", nucleo)
    if not dig:
        return None, False
    neg = t.startswith("(") or t.endswith(")") or t.lstrip("(")[:1] in "-−–—"
    grupos = nucleo.split(".")
    # "(3.021424)": algun grupo despues del primero con mas de 3 digitos. Grupos
    # de 1-2 digitos son decimales ("1.40", "11.152.4") y no se marcan.
    irregular = (len(grupos) > 1 and all(grupos) and any(len(g) > 3 for g in grupos[1:])
                 and not any(len(g) < 3 for g in grupos[1:]))
    # Parentesis duplicados: "((31.340.008.234)"
    irregular = irregular or t.count("(") > 1 or t.count(")") > 1
    return (-1 if neg else 1) * int(dig), irregular


def _unir_tocandose(nums):
    """Une trozos de monto pegados en la misma linea ('1'+'5.772.597', '('+'63.180)').
    Un guion a menos de 6 pt antes de un monto es su signo ("- 89.243.084"); un
    guion aislado es un cero (las columnas estan a 50+ pt).
    Primero agrupa por linea (top +-2) y ordena por x0 dentro de cada una: ordenar
    por round(top) mezclaba lineas con top 300.4 / 300.6 y unia montos de columnas
    distintas ("658.2344.963.807")."""
    lineas = []
    for w in sorted(nums, key=lambda w: w[3]):
        if lineas and abs(w[3] - lineas[-1][0][3]) <= 2:
            lineas[-1].append(w)
        else:
            lineas.append([w])
    out = []
    for ln in lineas:
        previo = None
        for w in sorted(ln, key=lambda w: w[1]):
            hueco = w[1] - previo[2] if previo else None
            # Guion o "(" sueltos a menos de 6 pt antes de un monto son su signo:
            # "- 89.243.084", "( 78.329.610)" (el "(" a 2.8 pt).
            signo = (previo is not None and (RE_GUION.match(previo[0]) or previo[0] == "(")
                     and re.match(r"\d", w[0]) and hueco < 6)
            if previo is not None and (-1.5 < hueco < GAP_UNION or signo):
                previo = [previo[0] + w[0], previo[1], w[2], previo[3], max(previo[4], w[4])]
                out[-1] = previo
            else:
                previo = list(w)
                out.append(previo)
    return out


def _es_monto_de_franja(t):
    """Token que sirve para ubicar columnas: monto con separador de miles o de
    3+ digitos (fondos chicos sin separador). Excluye notas (1-2 digitos) y guiones."""
    nucleo = t.strip("()-\u2212\u2013\u2014 ")
    if re.fullmatch(r"(19|20)\d\d", nucleo):
        return False                      # anio del encabezado
    return bool(re.fullmatch(r"\d{1,3}(?:\.\d{3})+|\d{3,}", nucleo))


def _franjas(nums, ancho):
    """Bordes derechos de las columnas de montos (de izquierda a derecha)."""
    xs = sorted(w[2] for w in nums if w[2] > ancho * 0.45 and _es_monto_de_franja(w[0]))
    grupos = []
    for x in xs:
        if grupos and x - grupos[-1][-1] <= GAP_FRANJA:
            grupos[-1].append(x)
        else:
            grupos.append([x])
    grupos = [g for g in grupos if len(g) >= 2]
    return [sorted(g)[len(g) // 2] for g in grupos]


def filas_espaciales(pagina):
    """Lineas (glosa, actual, anterior, texto) de una pagina con coordenadas,
    mas la lista de montos con formato irregular. Columnas por posicion:
    las dos franjas de mas a la derecha son actual y anterior (una sola franja:
    fondo en su primer anio -> actual); enteros chicos a la izquierda = nota."""
    palabras, ancho = pagina["palabras"], pagina["ancho"]
    es_num = lambda t: bool(RE_NUMTOK.match(t)) and not RE_FECHA_NUM.match(t)
    nums = _unir_tocandose([w for w in palabras if es_num(w[0])])
    textos = [w for w in palabras if not es_num(w[0])]
    franjas = _franjas(nums, ancho)
    if not franjas:
        return [], []
    f_act, f_ant = (franjas[-2], franjas[-1]) if len(franjas) >= 2 else (franjas[-1], None)

    # Filas de glosa: palabras de texto agrupadas por altura
    filas = []
    for w in sorted(textos, key=lambda w: (w[3], w[1])):
        if filas and abs(w[3] - filas[-1]["y"]) <= 3:
            filas[-1]["pal"].append(w)
        else:
            filas.append({"y": w[3], "pal": [w], "act": None, "ant": None, "nota": None})

    # Montos -> columna por posicion
    irregulares, piezas = [], []
    for w in nums:
        v, irr = _valor_espacial(w[0])
        if v is None:
            continue
        d_act = abs(w[2] - f_act)
        d_ant = abs(w[2] - f_ant) if f_ant else 1e9
        if min(d_act, d_ant) <= TOL_FRANJA:
            col = "act" if d_act <= d_ant else "ant"
            # Digito suelto entre columnas ("5" junto a "93.819"): se descarta solo si
            # compite con un monto alineado de 3+ digitos en la misma fila y columna.
            # Un monto chico real (94, 9) desalineado unos pt se conserva.
            if re.fullmatch(r"\(?\d{1,2}\)?", w[0]) and min(d_act, d_ant) > 5:
                borde = f_act if col == "act" else f_ant
                rival = any(o is not w and abs(o[3] - w[3]) <= 3 and abs(o[2] - borde) <= 5
                            and len(re.sub(r"\D", "", o[0])) >= 3 for o in nums)
                if rival:
                    continue
        elif re.fullmatch(r"\d{1,2}", w[0]) and ancho * 0.4 < w[2] < f_act - 25:
            col = "nota"
        else:
            continue                          # pie de pagina, numeros de la glosa, etc.
        if irr:
            irregulares.append(w[0])
        piezas.append({"y": w[3], "col": col, "v": v})

    # Asignacion greedy: primero lo que esta en la misma linea (<=2 pt); luego,
    # por cercania, preferiendo filas que ya tienen montos (glosa partida con
    # los valores entre dos lineas de texto).
    pendientes = []
    for pz in piezas:
        cerca_ = [f for f in filas if abs(f["y"] - pz["y"]) <= 2 and f[pz["col"]] is None]
        if cerca_:
            min(cerca_, key=lambda f: abs(f["y"] - pz["y"]))[pz["col"]] = pz["v"]
        else:
            pendientes.append(pz)
    for pz in sorted(pendientes, key=lambda pz: min([abs(f["y"] - pz["y"]) for f in filas] or [1e9])):
        cand = [f for f in filas if abs(f["y"] - pz["y"]) <= TOL_FILA and f[pz["col"]] is None]
        if cand:
            def puntaje(f):
                tiene = f["act"] is not None or f["ant"] is not None
                return abs(f["y"] - pz["y"]) - (4 if tiene else 0)
            min(cand, key=puntaje)[pz["col"]] = pz["v"]
        else:
            filas.append({"y": pz["y"], "pal": [], "act": None, "ant": None, "nota": None, pz["col"]: pz["v"]})
            filas[-1].setdefault("act", None)
    filas.sort(key=lambda f: f["y"])

    # Continuacion de glosa en minuscula sin montos -> se pega a la fila anterior
    unidas = []
    for f in filas:
        glosa = " ".join(w[0] for w in sorted(f["pal"], key=lambda w: w[1]))
        sin_montos = f["act"] is None and f["ant"] is None
        if (unidas and sin_montos and RE_CONTINUACION.match(glosa)
                and f["y"] - unidas[-1]["y"] <= 14):
            unidas[-1]["glosa"] += " " + glosa
            continue
        # "Total pasivos (excluido el activo neto atribuible" / "a participes)  5.711  5.272":
        # el rotulo partido queda en la linea que tiene los montos.
        prev = unidas[-1] if unidas else None
        if (prev and not sin_montos and RE_CONTINUACION.match(glosa)
                and not prev["act"] and not prev["ant"]          # None o 0 ("0" oculto bajo el rotulo)
                and (f["act"] or f["ant"]) and f["y"] - prev["y"] <= 14):
            prev.update(glosa=prev["glosa"] + " " + glosa, act=f["act"], ant=f["ant"], y=f["y"])
            continue
        unidas.append({"y": f["y"], "glosa": glosa, "act": f["act"], "ant": f["ant"]})
    # Monto del total impreso un poco ARRIBA de su rotulo ("(204.537)" / "Total gastos de operacion"):
    # una fila sin glosa con montos, seguida de cerca por un "Total ..." sin montos -> el monto baja.
    for k in range(len(unidas) - 1):
        a, b = unidas[k], unidas[k + 1]
        if (not a["glosa"].strip() and (a["act"] or a["ant"])
                and b["glosa"].strip().lower().startswith("total")
                and not b["act"] and not b["ant"] and b["y"] - a["y"] <= 20):
            b["act"], b["ant"] = a["act"], a["ant"]
            a["act"] = a["ant"] = None
    out = []
    for f in unidas:
        if f["act"] is None and f["ant"] is None:
            out.append((f["glosa"], None, None, f["glosa"]))
        else:
            out.append((f["glosa"], f["act"] or 0, f["ant"] or 0, f["glosa"]))
    return out, irregulares


def _leer_cache(ruta):
    if not ruta.exists():
        return None
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        d = json.load(f)
    return None if d.get("error") else d


def cargar_coords(rut, anio, pdf):
    """Cache del 03a + cache OCR (03a_ocr). Las paginas OCR reemplazan a las del 03a:
    solo se hace OCR de paginas que en el PDF son imagen (casi sin texto)."""
    carpeta = DIR_COORDS / str(rut) / str(anio)
    d = _leer_cache(carpeta / (Path(pdf).stem + ".json.gz"))
    o = _leer_cache(carpeta / (Path(pdf).stem + ".ocr.json.gz"))
    if o and o.get("paginas"):
        d = d or {"pdf": pdf, "error": None, "paginas": {}}
        d["paginas"].update({p: normalizar_ocr(v) for p, v in o["paginas"].items()})
    return d