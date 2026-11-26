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

El emparejador no usa el resultado de ninguna validacion: los chequeos se hacen despues, sobre su
salida. Desde E7 (MODO "catalogo") el XML tampoco decide el codigo: la glosa elige entre los codigos
del catalogo, un concepto por renglon; el XML solo desempata glosas de igual puntaje, corrige montos
corridos (lectura) y queda como testigo: monto_de marca el renglon cuyos montos son los de otra cuenta.
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
MIN_POSICION = 0.6    # la glosa debe parecerse a alguna cuenta para asignarla por posicion
RE_TOTAL = re.compile(r"^(sub)?total|flujos?(de)?(efectivo)?(neto)?|^aumento|^saldo")


def duplicada(glosa):
    """Texto con cada caracter dos veces ("AACCTTIIVVOO NNEETTOO"): dos capas del mismo texto. Sus montos
    tambien vienen duplicados (66.887.711.000.011): es lectura, no se empareja."""
    t = re.sub(r"\s+", "", glosa or "")
    return len(t) >= 6 and t[0::2] == t[1::2]


def paginas_repetidas(rs, minimo=0.8):
    """Paginas que repiten el estado de una pagina anterior: al menos el 80% de sus renglones con montos
    tienen la misma glosa y los mismos montos (+-2) en otra pagina anterior. Es el mismo estado impreso dos
    veces (hallazgo de formato); solo la primera toma cuentas."""
    filas = {}
    for r in rs:
        if r["actual"] is not None or r["anterior"] is not None:
            filas.setdefault(r["pagina"], []).append((norm(r["glosa"]), r["actual"] or 0, r["anterior"] or 0))
    out, vistas = set(), []
    for p in sorted(filas):
        f = filas[p]
        igual = sum(any(g == g2 and abs(a - a2) <= TOL and abs(b - b2) <= TOL for g2, a2, b2 in vistas)
                    for g, a, b in f)
        if len(f) >= 3 and igual >= minimo * len(f):
            out.add(p)
        else:
            vistas += f
    return out


def paginas_nucleo(rs, punt):
    """Paginas del estado: la que tiene mas renglones con montos reconocidos por la glosa y las contiguas
    que tambien tienen alguno. El lector puede dejar en el estado paginas de notas (cartera de inversiones,
    "Saldo final al 31 de diciembre" de otra nota); sin el XML como arbitro, sus glosas tomarian cuentas."""
    n = {}
    for r, p in zip(rs, punt):
        if p and max(p.values()) >= MIN_GLOSA and (r["actual"] is not None or r["anterior"] is not None):
            n[r["pagina"]] = n.get(r["pagina"], 0) + 1
    if not n:
        return None
    nucleo = {max(n, key=n.get)}
    for paso in (1, -1):
        q = next(iter(nucleo))
        while q + paso in n:
            q += paso
            nucleo.add(q)
    return nucleo
STOP = {"de", "del", "la", "las", "el", "los", "y", "en", "por", "a", "al", "con", "sobre", "o", "e"}
RUTA_GLOSARIO = Path(__file__).with_name("glosario.csv")


def cargar_glosario(ruta=RUTA_GLOSARIO):
    """[(codigo, {estados}, patron, excluir|None, puntaje)]; puntaje vacio = 1.0. Un puntaje menor sirve
    para una redaccion que es la cuenta solo si no hay otra mejor ("Total activos corrientes")."""
    with open(ruta, encoding="utf-8") as f:
        return [(r["codigo"], set(r["estado"].split("|")), re.compile(r["patron"]),
                 re.compile(r["excluir"]) if r["excluir"] else None, float(r.get("puntaje") or 1.0))
                for r in csv.DictReader(f)]


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
    for cod, ests, patron, excluir, pje in (GLOSARIO if glosario else []):
        if cod != codigo or estado not in ests:
            continue
        for t in textos:
            n = norm(t)
            if excluir and excluir.search(n):
                return 0.0
            if patron.search(n):
                return pje
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


def _por_posicion(rs, con_monto, punt, cods, can, orden, usados_c, cod_glosa):
    """Renglones con montos que quedaron sin codigo (su glosa la tomo otro renglon, o viene cortada).

    1. Rotulo repetido: la glosa es identica (mismo puntaje) a la de otro renglon que ya tiene esa cuenta,
       y en la plantilla falta la cuenta contigua (orden +-1). Los dos renglones se ordenan como la
       plantilla: el de mas arriba toma la cuenta de menor orden. Caso: "despues de distribucion" impreso
       dos veces; el primero, sobre la distribucion, es el "antes". No depende del XML: con el XML como
       desempate el "despues" podia quedar en el renglon de arriba si el XML trae los dos cruzados.
    2. Hueco en la plantilla: entre el vecino de arriba y el de abajo con codigo faltan cuentas, y UNA sola
       de ellas se parece a la glosa (>= MIN_POSICION). Casos: el subtotal de la operacion impreso en el
       titulo de financiamiento, una glosa cortada ("...originadas por").
    Las cuentas impresas sin montos ("Otros ingresos de operacion  -  -") cuentan como presentes: su
    glosa (cod_glosa) las ubica aunque no tengan codigo. Queda coincide "posicion" y, si la glosa del
    renglon es de otra cuenta, glosa_de (rotulo de otra cuenta)."""
    con = set(con_monto)
    # un titulo de seccion sin montos ("Flujos de efectivo originado por actividades de la operacion:")
    # se parece al subtotal de la seccion: los totales no cuentan como impresos sin montos
    tot = _totales()
    impresa = {j: cod_glosa[j] for j in range(len(rs)) if j not in con and cod_glosa[j] and can(cod_glosa[j]) not in tot}
    presentes = usados_c | {can(c) for c in impresa.values()}
    orden_c = {}
    for c in cods:
        if orden.get(c) is not None:
            orden_c.setdefault(can(c), orden[c])
    # metodo del EFE: si ninguna cuenta asignada por glosa es propia del indirecto, el estado es del directo
    # y la posicion no puede tomar cuentas del indirecto (su hueco en la plantilla no es de este estado)
    met = _metodo()
    indirecto = any(met.get(c) == "indirecto" for c in usados_c)
    admisibles = {x for x in orden_c if indirecto or met.get(x) != "indirecto"}

    def vecino(i, paso):
        j = i + paso
        while 0 <= j < len(rs):
            o = orden.get(rs[j].get("codigo") or impresa.get(j))
            if o is not None:
                return o
            j += paso
        return None

    def asignar(i, c, mejor):
        rs[i]["codigo"], rs[i]["coincide"] = c, "posicion"
        rs[i]["glosa_de"] = mejor if punt[i].get(mejor, 0) >= MIN_GLOSA and can(mejor) != can(c) else None
        usados_c.add(can(c))
        presentes.add(can(c))

    for i in con_monto:
        if rs[i]["codigo"] or not punt[i] or max(punt[i].values()) < MIN_POSICION:
            continue
        mejor = max(punt[i], key=punt[i].get)
        c = can(mejor)
        # 1. rotulo repetido
        k = next((k for k in con_monto if k != i and rs[k]["codigo"] and can(rs[k]["codigo"]) == c), None)
        if (k is not None and punt[i][mejor] >= MIN_GLOSA and c in orden_c
                and norm(rs[k]["glosa"]) == norm(rs[i]["glosa"])
                and abs(punt[k].get(rs[k]["codigo"], 0) - punt[i][mejor]) < 1e-9):
            m = [x for x, o in orden_c.items() if abs(o - orden_c[c]) == 1 and x not in presentes and x in admisibles]
            if len(m) == 1:
                arriba, abajo = sorted((i, k))
                bajo, alto = sorted((m[0], c), key=orden_c.get)
                cod = {c: rs[k]["codigo"], m[0]: m[0]}
                # el que recibe la cuenta contigua queda por posicion (rotulo de la otra); el otro, por glosa
                for fila, x in ((arriba, bajo), (abajo, alto)):
                    if x == c:
                        rs[fila]["codigo"], rs[fila]["coincide"], rs[fila]["glosa_de"] = cod[c], "glosa", None
                    else:
                        asignar(fila, x, mejor)
                usados_c.add(c)
                presentes.add(c)
                continue
        # 2. hueco en la plantilla
        lo, hi = vecino(i, -1), vecino(i, 1)
        lo = -1 if lo is None else lo
        hi = float("inf") if hi is None else hi
        # por concepto: su orden en la plantilla (el del codigo directo) y el mejor parecido entre sinonimos
        # (el titulo "...de financiamiento" excluye el codigo directo de la operacion en el glosario)
        sim = {}
        for x in cods:
            sim[can(x)] = max(sim.get(can(x), 0), punt[i].get(x, 0))
        faltan = {x for x, o in orden_c.items() if lo < o < hi and x not in presentes and sim.get(x, 0) >= MIN_POSICION}
        # una glosa de total ("Total pasivos corrientes") solo toma un total: no una linea del bloque
        faltan &= admisibles
        # una glosa de total ("Total pasivos corrientes") o un titulo con montos ("Ingresos de la operacion:")
        # solo toma un total: no una linea del bloque
        if RE_TOTAL.search(norm(rs[i]["glosa"])) or str(rs[i]["glosa"]).rstrip().endswith(":"):
            faltan &= tot
        if len(faltan) == 1:
            asignar(i, next(iter(faltan)), mejor)


def emparejar(rs, xml, estado, glosario=True, corridos=True, vocabulario=None, canon=None, orden=None):
    """rs: renglones de UN estado (de leer_estados, en orden); xml: {codigo: (actual, anterior)}
    del mismo estado. Agrega codigo y coincide a cada renglon (in place) y devuelve rs.
    glosario / corridos = False: sin esas mejoras (para medir cuanto aporta cada una).
    vocabulario (E7, en medicion): codigos candidatos del catalogo en vez de los del XML; el XML solo
    desempata glosas de igual puntaje y no asigna por valor (el XML deja de ser arbitro).
    canon: codigo -> concepto (sinonimos de las plantillas del EFE, catalogo alternativo_de). Con
    vocabulario, cada CONCEPTO se asigna a un solo renglon (un rotulo repetido no toma el sinonimo) y el
    XML se busca por concepto. Agrega monto_de: el codigo cuyo monto XML calza con el renglon cuando no
    es el de su glosa (montos de otra cuenta bajo esta glosa: intercambio o rotulo cruzado).
    orden: codigo -> posicion en la plantilla del catalogo. Con vocabulario, un renglon que queda sin
    codigo (su glosa ya la tomo otro renglon, o viene cortada) recibe por POSICION la unica cuenta que
    falta entre sus vecinos con codigo (coincide "posicion"; glosa_de si su glosa es de otra cuenta)."""
    can = (lambda c: canon.get(c, c)) if canon else (lambda c: c)
    cods = list(xml) if vocabulario is None else list(vocabulario)
    xml_todo = xml
    if vocabulario is not None:
        por_concepto = {}
        for k, val in xml.items():
            por_concepto.setdefault(can(k), val)
        xml = {c: por_concepto.get(can(c), (None, None)) for c in cods}
    # 1. codigo por glosa (sin mirar montos)
    punt = [{} if r["metodo"] == "encabezado" else {c: puntaje_glosa(r, c, estado, glosario) for c in cods}
            for r in rs]
    if vocabulario is not None:
        nucleo = paginas_nucleo(rs, punt)
        rep_ = paginas_repetidas(rs)
        for r in rs:
            r["pagina_repetida"] = r["pagina"] in rep_
        punt = [{} if duplicada(r["glosa"]) or (nucleo is not None and r["pagina"] not in nucleo) or r["pagina"] in rep_
                else p for r, p in zip(rs, punt)]
    cod_glosa = []
    for p in punt:
        c = max(p, key=p.get) if p else None
        cod_glosa.append(c if c is not None and p[c] >= MIN_GLOSA else None)
    # 2. montos corridos
    if corridos:
        _corregir_corridos(rs, cod_glosa, xml)
    # 3. uno a uno: glosa, luego valor
    for r in rs:
        r["codigo"], r["coincide"], r["glosa_de"], r["monto_de"] = None, None, None, None
        r["monto_de_vecino"] = False
    con_monto = [i for i, r in enumerate(rs) if (r["actual"] is not None or r["anterior"] is not None)
                 and r["metodo"] != "encabezado"]
    v = lambda i: (rs[i]["actual"], rs[i]["anterior"])
    if vocabulario is None:
        cand = [(sc + (0.1 if calza(v(i), xml[c]) else 0), 0, -i, c)
                for i in con_monto for c, sc in punt[i].items() if sc >= MIN_GLOSA]
    else:                                      # el valor solo desempata glosas de igual puntaje
        cand = [(sc, calza(v(i), xml[c]), -i, c)
                for i in con_monto for c, sc in punt[i].items() if sc >= MIN_GLOSA]
    usados_r, usados_c = set(), set()
    for _, _, mi, c in sorted(cand, reverse=True):
        i = -mi
        if i not in usados_r and can(c) not in usados_c:
            rs[i]["codigo"], rs[i]["coincide"] = c, "ambos" if calza(v(i), xml[c]) else "glosa"
            usados_r.add(i), usados_c.add(can(c))
    for i in (con_monto if vocabulario is None else []):
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
    if vocabulario is not None and orden:
        _por_posicion(rs, con_monto, punt, cods, can, orden, usados_c, cod_glosa)
    # XML como testigo (E7): el renglon no calza con su cuenta y TODOS sus montos calzan con otra
    if vocabulario is not None:
        for i in con_monto:
            c = rs[i]["codigo"]
            if c and rs[i]["coincide"] in ("posicion", "glosa"):
                ok = calza(v(i), xml.get(c, (None, None)))
                rs[i]["coincide"] = "ambos" if ok else rs[i]["coincide"]
            # solo si la cuenta de la glosa esta en el XML con OTRO monto: sin ella no hay cruce, solo
            # dos cuentas con el mismo monto (subtotal = flujo neto cuando no hay mas lineas)
            if c and rs[i]["coincide"] in ("glosa", "posicion") and any(x is not None for x in xml[c]):
                cand = [k for k, x in xml_todo.items() if can(k) != can(c) and calza_todo(v(i), x)]
                # si una de las cuentas que calzan es la de la glosa del renglon de al lado (sin montos), los
                # montos quedaron impresos una linea corridos: es esa (10383 2023: los del "antes de
                # distribucion", de tres lineas, impresos en la linea de "Distribucion de beneficios")
                sin_m = lambda j: 0 <= j < len(rs) and rs[j]["actual"] is None and rs[j]["anterior"] is None
                arriba = []
                j = i - 1
                while sin_m(j) and len(arriba) < 3:      # glosa de hasta 3 lineas sin montos justo encima
                    arriba.insert(0, rs[j]["glosa"])
                    j -= 1
                textos = [" ".join(arriba)] if arriba else []
                if sin_m(i + 1):
                    textos.append(rs[i + 1]["glosa"])
                junto = [k for k in cand if any(puntaje_glosa(dict(glosa=t, previa=""), k, estado) >= MIN_GLOSA
                                                for t in textos)]
                rs[i]["monto_de"] = (junto or cand or [None])[0]
                rs[i]["monto_de_vecino"] = bool(junto)
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


# E7: "catalogo" = la glosa decide entre los codigos del catalogo y el XML es testigo (monto_de);
# "xml" = como hasta v1 (candidatos del XML, el monto suma al puntaje, asignacion por valor).
MODO = "catalogo"


@lru_cache(maxsize=None)
def _catalogo(entidad="fm"):
    import catalogo
    c = catalogo.conceptos(entidad)
    canon = {k: (a or k) for k, a in zip(c["codigo"], c["alternativo_de"].fillna(""))}
    c = c[c["por_serie"] != "si"]
    return {e: tuple(g["codigo"]) for e, g in c.groupby("estado")}, canon


@lru_cache(maxsize=None)
def _totales(entidad="fm"):
    """Conceptos que son el total de una regla del catalogo (subtotales y totales de los estados)."""
    import catalogo
    r = catalogo.reglas(entidad)
    _, canon = _catalogo(entidad)
    return frozenset(canon.get(a.split(":", 1)[1], a.split(":", 1)[1]) for t in r["total"] for a in t.split("|"))


@lru_cache(maxsize=None)
def _metodo(entidad="fm"):
    """{concepto: "indirecto"} para las cuentas propias del metodo indirecto del EFE (sin sinonimo directo)."""
    import catalogo
    c = catalogo.conceptos(entidad)
    c = c[(c["metodo"].fillna("") == "indirecto") & (c["alternativo_de"].fillna("") == "")]
    return {k: "indirecto" for k in c["codigo"]}


@lru_cache(maxsize=None)
def _orden(entidad="fm"):
    """{estado: {codigo: orden en la plantilla}} (conceptos.csv; sin orden = fuera de la plantilla)."""
    import catalogo
    c = catalogo.conceptos(entidad)
    c = c[(c["por_serie"] != "si") & (c["orden"].astype(str) != "")]
    return {e: {k: float(o) for k, o in zip(g["codigo"], g["orden"])} for e, g in c.groupby("estado")}


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
        if MODO == "catalogo":
            voc, canon = _catalogo()
            emparejar(sub, xml_estado(c), est, vocabulario=voc.get(est, ()), canon=canon,
                      orden=_orden().get(est, {}))
            # Se informa el CONCEPTO (el codigo del metodo directo, el que usan las reglas y los XML):
            # la glosa elige entre sinonimos de las dos plantillas del EFE ("Aumento (disminucion) neto"
            # se parece mas al codigo del indirecto), y eso no debe mover la ubicacion de los subtotales.
            # El sinonimo elegido queda en codigo_plantilla (formato: que plantilla sigue la glosa).
            for r in sub:
                r["codigo_plantilla"] = r["codigo"]
                if r["codigo"]:
                    r["codigo"] = canon.get(r["codigo"], r["codigo"])
                if r.get("monto_de"):
                    r["monto_de"] = canon.get(r["monto_de"], r["monto_de"])
        else:
            emparejar(sub, xml_estado(c), est)
        out[est] = sub
    return out, paginas