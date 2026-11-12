"""
Emparejador unico: renglon del PDF -> cuenta del XML
====================================================

Reemplaza a los emparejadores de cada etapa (posicion en el 03b, regex en el 03c,
similitud en la ficha). Por estado:

  1. Codigo por GLOSA de cada renglon (con y sin las lineas previas sin montos):
     a. glosario.csv (redacciones conocidas, con exclusiones) -> puntaje 1.0
     b. si no, similitud con el nombre de la cuenta (como la ficha) >= MIN_GLOSA
  2. MONTOS CORRIDOS: renglones seguidos cuyos montos no calzan con la cuenta de su
     glosa pero si con los del renglon de abajo (o de arriba) se corrigen (metodo
     "corrido"), solo si la linea que sobra con montos no es una cuenta (sin glosa,
     encabezado "...:" o sin codigo) y los montos son materiales.
  3. Asignacion uno a uno: glosa (mayor puntaje; a igualdad el que calza en valor),
     luego valor solo para lo que quedo sin par. Un renglon = una cuenta.

El emparejador SI usa el XML (para eso esta), pero no el resultado de ninguna
validacion: los chequeos se hacen despues, sobre su salida.
Agrega a cada renglon: codigo, coincide ("ambos" | "glosa" | "valor" | None) y glosa_de: la cuenta
que el glosario reconoce en su glosa (1.0), si no es la suya (que no llega a 1.0) y esa cuenta ya
tiene su propio renglon con glosa y valor. Es un rotulo de otra cuenta impreso sobre estos montos
("Flujo neto ... operacion" sobre el subtotal de financiamiento): hallazgo de presentacion.
"""
import csv
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from comun.lector import RE_ABIERTA, es_cola, norm

TOL = 2               # diferencia de redondeo al comparar montos
MIN_GLOSA = 0.75      # similitud minima (la misma de la ficha)
MIN_CORRIDO = 100     # monto minimo para aceptar montos corridos (un "2" suelto no es evidencia)
STOP = {"de", "del", "la", "las", "el", "los", "y", "en", "por", "a", "al", "con", "sobre", "o", "e"}
RUTA_GLOSARIO = Path(__file__).with_name("glosario.csv")


def cargar_glosario(ruta=RUTA_GLOSARIO):
    """[(codigo, {estados}, patron, excluir|None)]"""
    with open(ruta, encoding="utf-8") as f:
        return [(r["codigo"], set(r["estado"].split("|")), re.compile(r["patron"]),
                 re.compile(r["excluir"]) if r["excluir"] else None) for r in csv.DictReader(f)]


GLOSARIO = cargar_glosario()


def legible(codigo):
    palabras = re.findall(r"[A-Z][a-z0-9]*|[a-z0-9]+|[A-Z]+(?![a-z])", codigo)
    return " ".join(palabras).lower()


def _tokens(texto):
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()
    return [w for w in re.findall(r"[a-z]+", t) if w not in STOP]


@lru_cache(maxsize=200_000)
def parecido(glosa, codigo):
    """0-1: max(SequenceMatcher, fraccion de palabras de la cuenta presentes en la glosa).
    Tambien sobre el texto sin espacios: hay PDF que se extraen pegados ("Colocaciondecuotas...")
    o con letras separadas ("L iq u id a c io n"), y ahi las palabras no sirven."""
    ng, nc = norm(glosa), norm(legible(codigo))
    if not ng or not nc:
        return 0.0
    if ng == nc:
        return 1.0
    pegado = SequenceMatcher(None, ng, nc).ratio()
    a, b = _tokens(glosa), _tokens(legible(codigo))
    if not a or not b:
        return pegado
    return max(pegado, SequenceMatcher(None, " ".join(a), " ".join(b)).ratio(), len(set(b) & set(a)) / len(set(b)))




def continua(r):
    """La glosa sigue a las lineas previas sin montos: esta vacia (montos en una linea sin texto),
    empieza en minuscula, o la previa
    quedo abierta ("Aumento (disminucion) neto de efectivo y" / "efectivo equivalente ...").
    Sin esto, el rotulo de un total sin montos se pegaba a la cuenta de abajo."""
    return bool(r["previa"]) and (not r["glosa"] or es_cola(r["glosa"]) or bool(RE_ABIERTA.search(r["previa"].lower())))


def puntaje_glosa(r, codigo, estado, glosario=True):
    """1.0 si el glosario reconoce la glosa (sola o con las previas); si no, la similitud.
    Una exclusion del glosario anula tambien la similitud."""
    textos = [r["glosa"]] + ([(r["previa"] + " " + r["glosa"]).strip()] if continua(r) else [])
    for cod, ests, patron, excluir in (GLOSARIO if glosario else []):
        if cod != codigo or estado not in ests:
            continue
        for t in textos:
            n = norm(t)
            if excluir and excluir.search(n):
                return 0.0
            if patron.search(n):
                return 1.0
    return min(0.99, max(parecido(t, codigo) for t in textos))     # el glosario manda


def _igual(p, x):
    return p is not None and x is not None and abs(abs(p) - abs(x)) <= TOL


def calza(vals, xml_c):
    """Algun monto calza (como la ficha)."""
    return any(_igual(p, x) and (p or x) for p, x in zip(vals, xml_c))


def calza_todo(vals, xml_c):
    """Todos los montos leidos calzan y al menos uno no es cero (para montos corridos)."""
    pares = [(p, x) for p, x in zip(vals, xml_c) if p is not None and x is not None]
    return bool(pares) and all(_igual(p, x) for p, x in pares) and any(p for p, _ in pares)


def _corregir_corridos(rs, cod_glosa, xml):
    """Montos corridos una linea. rs: renglones de un estado (se modifican)."""
    vals = [(r["actual"], r["anterior"]) for r in rs]
    n = len(rs)
    # una cuenta cuyo monto ya esta en otra linea (con sus propios montos) no se corrige:
    # esa linea es la suya (dos rotulos parecidos, uno en 0)
    ya_esta = {c for c, v in zip(cod_glosa, vals) if c is not None and calza(v, xml[c])}
    for paso in (1, -1):                       # 1: el monto esta en la linea de abajo
        corr = []
        for i in range(n):
            j, c = i + paso, cod_glosa[i]
            ok = (c is not None and c not in ya_esta and 0 <= j < n and rs[i]["metodo"] == "espacial"
                  and rs[j]["metodo"] != "encabezado"
                  and not calza(vals[i], xml[c])
                  and calza_todo(vals[j], xml[c]))
            corr.append(ok)
        i = 0
        while i < n:
            if not corr[i]:
                i += 1
                continue
            k = i
            while k + 1 < n and corr[k + 1]:
                k += 1
            racha = range(i, k + 1)
            borde = k + paso if paso == 1 else i + paso          # vecino que cede montos y no recibe
            # Se acepta solo con evidencia de lectura, no solo del XML (si no, un XML con montos
            # corridos "corregia" un PDF correcto): el que cede los montos es una linea que no es
            # cuenta (sin glosa, encabezado "...:" o sin codigo), y los montos son materiales.
            cede = 0 <= borde < n and rs[borde]["metodo"] == "espacial" and any(vals[borde])
            no_cuenta = cede and (not rs[borde]["glosa"] or rs[borde]["glosa"].rstrip().endswith(":")
                                  or cod_glosa[borde] is None)
            material = any(max(abs(v or 0) for v in vals[m + paso]) >= MIN_CORRIDO for m in racha)
            if no_cuenta and material:
                # Una glosa sin montos y sus montos en una linea sin texto al lado: no es un
                # corrimiento, es el monto de esa glosa ("monto_sin_glosa").
                suelto = len(racha) == 1 and not any(v is not None for v in vals[i]) and not rs[borde]["glosa"]
                for m in racha:
                    rs[m]["actual_leido"], rs[m]["anterior_leido"] = vals[m]
                    rs[m]["actual"], rs[m]["anterior"] = vals[m + paso]
                    # una sola linea cuyo vecino (sin cuenta) trae los montos es la otra mitad de una
                    # glosa partida ("Remuneraciones Sociedad" / "Administradora 56.566"); corrido
                    # queda para rachas de 2+ (montos de varias cuentas desplazados)
                    rs[m]["metodo"] = ("monto_sin_glosa" if suelto else
                                       "glosa_partida" if len(racha) == 1 else "corrido")
                rs[borde]["actual_leido"], rs[borde]["anterior_leido"] = vals[borde]
                rs[borde]["actual"] = rs[borde]["anterior"] = None
                rs[borde]["metodo"] = ("monto_sin_glosa_origen" if suelto else
                                       "glosa_partida_origen" if len(racha) == 1 else "corrido_origen")
            i = k + 1


def emparejar(rs, xml, estado, glosario=True, corridos=True):
    """rs: renglones de UN estado (de leer_estados, en orden); xml: {codigo: (actual, anterior)}
    del mismo estado. Agrega codigo y coincide a cada renglon (in place) y devuelve rs.
    glosario / corridos = False: sin esas mejoras (para medir cuanto aporta cada una)."""
    # 1. codigo por glosa (sin mirar montos)
    punt = [{} if r["metodo"] == "encabezado" else {c: puntaje_glosa(r, c, estado, glosario) for c in xml}
            for r in rs]
    cod_glosa = []
    for p in punt:
        c = max(p, key=p.get) if p else None
        cod_glosa.append(c if c is not None and p[c] >= MIN_GLOSA else None)
    # 2. montos corridos
    if corridos:
        _corregir_corridos(rs, cod_glosa, xml)
    # 3. uno a uno: glosa, luego valor
    for r in rs:
        r["codigo"], r["coincide"], r["glosa_de"] = None, None, None
    con_monto = [i for i, r in enumerate(rs) if (r["actual"] is not None or r["anterior"] is not None)
                 and r["metodo"] != "encabezado"]
    v = lambda i: (rs[i]["actual"], rs[i]["anterior"])
    cand = [(sc + (0.1 if calza(v(i), xml[c]) else 0), -i, c)
            for i in con_monto for c, sc in punt[i].items() if sc >= MIN_GLOSA]
    usados_r, usados_c = set(), set()
    for _, mi, c in sorted(cand, reverse=True):
        i = -mi
        if i not in usados_r and c not in usados_c:
            rs[i]["codigo"], rs[i]["coincide"] = c, "ambos" if calza(v(i), xml[c]) else "glosa"
            usados_r.add(i), usados_c.add(c)
    for i in con_monto:
        if i in usados_r:
            continue
        c = next((c for c in xml if c not in usados_c and calza(v(i), xml[c])), None)
        if c:
            rs[i]["codigo"], rs[i]["coincide"] = c, "valor"
            usados_r.add(i), usados_c.add(c)
    # glosa de otra cuenta: solo con el glosario (1.0, no similitud), con esa cuenta ya en su renglon
    # y la propia sin reconocer por el glosario (un patron que calza con las dos no es un rotulo malo)
    propio = {r["codigo"]: i for i, r in enumerate(rs) if r["coincide"] == "ambos"}
    for i in con_monto:
        c0, c = cod_glosa[i], rs[i]["codigo"]
        if (c and c0 and c0 != c and punt[i].get(c0) == 1.0 and punt[i].get(c, 0) < 1.0
                and propio.get(c0, i) != i):
            rs[i]["glosa_de"] = c0
    return rs


# ---------------------------------------------------------------------------
# Lectura + emparejamiento de un reporte (lo usan el 03b y la ficha)
# ---------------------------------------------------------------------------
def xml_estado(c):
    """{codigo: (actual, anterior)} de las cuentas de UN estado (sin series), en orden del XML.
    Una cuenta sin valor en una columna que el estado si trae = 0."""
    hay_ctx = set(c["contexto"])
    out = {}
    for cod, g in c.groupby("codigo", sort=False):
        m = dict(zip(g["contexto"], g["valor"]))
        out[cod] = tuple(m.get(k, 0 if k in hay_ctx else None) for k in ("PeriodoActual", "PeriodoAnterior"))
    return out


def leer_y_emparejar(coords, paginas_estados, cta):
    """Renglones del ESF, la ERI y el EFE de un reporte, emparejados con su XML.
    cta: cuentas del archivo con columna estado_fin (comun.secciones.asignar_secciones).
    Devuelve ({estado: renglones}, paginas leidas)."""
    from comun.lector import leer_estados, paginas_de
    paginas, base = paginas_de(paginas_estados, coords)
    if not paginas:
        return {}, []
    rs, _ = leer_estados(coords, paginas, base=base)
    out = {}
    for est in ("ESF", "ERI", "EFE"):
        sub = [r for r in rs if r["estado"] == est]
        c = cta[(cta["estado_fin"] == est) & cta["serie"].isna()]
        emparejar(sub, xml_estado(c), est)
        out[est] = sub
    return out, paginas