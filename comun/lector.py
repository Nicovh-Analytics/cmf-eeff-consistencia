"""
Lector unificado de los estados del PDF (paso 1: ESF, ERI y EFE)
================================================================

Una sola lectura del PDF para todas las etapas. NO usa el XML ni el resultado de
ninguna validacion. Paso 1: envuelve `filas_espaciales` sin cambiarlo (la lectura
base queda identica a la de hoy) y agrega:

  1. Estado de cada linea por TITULO ("Estado(s) de situacion financiera", ...):
     el estado cambia en la linea del titulo y sigue en las paginas siguientes
     hasta el proximo titulo. Una pagina sin titulo hereda el estado de la anterior.
  2. Renglones con su contexto: `previa` = hasta 2 lineas sin montos justo antes
     (glosa partida: "Aumento neto de efectivo y" / "efectivo equivalente (1.234)").
  3. Las lineas sin montos tambien se devuelven (titulos, encabezados de seccion,
     primera mitad de una glosa partida): el emparejador las necesita para los
     montos corridos.

El ECP se lee aparte (paso 1b): sus paginas se clasifican pero no se devuelven
renglones, porque la lectura de 2 columnas confunde series con columnas.

Salida de leer_estados: lista de dicts
  pagina, estado, renglon (orden dentro del estado), glosa, previa, actual, anterior,
  metodo ("espacial"; el emparejador agrega "corrido").
"""
import re
import unicodedata

from comun.lector_espacial import filas_espaciales

ESTADOS = ("ESF", "ERI", "ECP", "EFE")

# Sobre norm(): minusculas, sin tildes, solo letras y digitos. En cualquier parte de una linea
# corta sin montos (o con solo fecha/anios): hay titulos precedidos del nombre del fondo.
TITULOS = {
    "ESF": re.compile(r"estados?(intermedios?)?de(situacion|posicion)financiera|balancegeneral"),
    "ERI": re.compile(r"estados?(intermedios?)?deresultados?"),          # tambien "Estado de Resultado Integral"
    "ECP": re.compile(r"estados?(intermedios?)?decambios?|cambios?en(el|los)?activos?netos?"),
    "EFE": re.compile(r"estados?(intermedios?)?de(los)?flujos?deefectivo"),
}
MAX_TITULO = 120       # caracteres (norm): una linea mas larga es texto, no titulo
# Pagina sin titulo: el estado se reconoce por lineas tipicas (la que mas anclas tenga).
# Si no hay anclas, hereda el estado de la pagina anterior.
ANCLAS = {
    "ESF": re.compile(r"^totalactivos?$|^totalpasivos?|^activostotales|^totaldeactivos"),
    "ERI": re.compile(r"totalgastos|totalingresos|comisiondeadministracion|antesdeimpuesto"),
    "ECP": re.compile(r"aportesdecuotas|^aportes$|originadoportransacciones|transaccionesdecuotas"
                      r"|activonetoatribuible.*(alinicio|al1deenero|alprincipio|inicial)"),
    "EFE": re.compile(r"flujos?netos?(originado|utilizado|usado|procedente)|actividadesde(la)?operacion$"),
}
# Linea de encabezado leida como montos: "Notas 2022 2021", "Al 31 de diciembre de", "Pagina 3".
RE_ENCABEZADO = re.compile(r"diciembre|ejercicios?terminad|anosterminad|notas?$|^notas?|pagina|^pag$|^n(o|ro)?$|^(m|ms|mm|m\$)+$"
                           r"|notasadjuntas")
# Encabezado de seccion (con un anio en la linea se lee como monto): "ACTIVOS 2019",
# "INGRESOS/(PERDIDAS) DE LA OPERACION 2018", "Flujos de efectivo originados por actividades de...".
RE_SECCION = re.compile(r"^(activos?|pasivos?)(notas?|ms|mus|m)*$|^(ingresos|perdidas)+(netos?)?(dela)?(operacion)?$"
                        r"|^gastos(deoperacion)?$|^flujos?deefectivo|actividadesde(la)?(operacion|financ|inversi)\w*$"
                        r"|expresad|milesde|^notas?")
RE_NO_CUENTA = re.compile(r"periodocomprendido|porelperiodo|desdeel(\d+)?de|expresad|milesde(pesos|dolares|us)")
RE_FECHA_GLOSA = re.compile(r"\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*(19|20)\d\d")
# Cola de una glosa partida: "Saldo final de efectivo y efectivo" / "equivalente  196.824"
# (vacia o solo signos "(+)", "(+ o -)": la linea de los montos de una glosa de arriba)
RE_COLA = re.compile(r"^(y)?(efectivo)?equivalentes?(alfinal|alinicio)?$|^participes$|^decuotas$|^o?$")
# Glosa que quedo abierta: "... atribuible a partícipes originado por" / "actividades de la ..."
RE_ABIERTA = re.compile(r"(\b(de|del|y|e|la|las|el|los|en|por|a|al|o|u|sobre|con|neto|netos)|[(,-])$")


# el conector va seguido de una palabra (>= 2 letras): en un PDF con letras separadas
# "O t r o s ingresos" empieza con "O " y no es continuacion de nada
RE_CONECTOR = re.compile(r"^(de|del|la|las|el|los|y|e|en|por|a|al|o|sobre)\s+[^\W\d_]{2,}", re.I)


def es_cola(glosa):
    """Segunda linea de una glosa partida: minuscula, "EQUIVALENTE" o un conector inicial
    ("DE LA OPERACION" bajo "FLUJO NETO ORIGINADO POR ACTIVIDADES")."""
    g = glosa.strip()
    return g[:1].islower() or bool(RE_COLA.match(norm(g))) or bool(RE_CONECTOR.match(g))


def norm(s):
    t = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def titulo(glosa):
    """Estado cuyo titulo esta en esta linea, o None."""
    n = norm(glosa)
    if not n or len(n) > MAX_TITULO:
        return None
    return next((e for e, rx in TITULOS.items() if rx.search(n)), None)


def es_encabezado(glosa, act, ant):
    """Fila de fechas, anios, notas o numero de pagina que el lector tomo como montos."""
    vals = [abs(v) for v in (act, ant) if v]
    if not vals:
        return False
    anios = all(1990 <= v <= 2035 for v in vals)
    chicos = all(v < 100 for v in vals)
    n = norm(glosa)
    if not n:
        return anios                                   # "2019  2018" sin glosa
    # Texto que nunca es una cuenta, sea cual sea el numero que lleve al lado: periodo del estado
    # ("Por el periodo comprendido entre...", "Desde el 2 de septiembre al..."), unidad ("Expresado
    # en miles de pesos"), datos de contacto del auditor ("+56 ...", "contacto@..."), y una linea
    # con el titulo de un estado y un numero chico (entrada de indice: "Estados de Flujos ... 7").
    if (RE_NO_CUENTA.search(n) or "@" in glosa or "www." in glosa.lower() or re.match(r"\s*\+\d", glosa)
            or (chicos and titulo(glosa))):
        return True
    if len(vals) == 2 and anios and vals[0] - vals[1] == 1:
        return True                                    # "INGRESOS/(PERDIDAS) DE LA OPERACION  2024  2023"
    # "N° 03.06.2024": la fecha de la columna leida como monto (1.012.025), cualquiera sea el valor
    if RE_FECHA_GLOSA.search(glosa) and re.fullmatch(r"(n|no|nro|notas?|al|de|del)*",
                                                      re.sub(r"\d", "", n)):
        return True
    # fecha en la glosa ("N° 31.12.2018", "De 01-01-2019") o "MUS$ MUS$" con un anio como monto
    if anios and (RE_FECHA_GLOSA.search(glosa) or re.fullmatch(r"(n|no|nro|notas?)?(m|ms|mus|us|mm)*", n)):
        return True
    if anios and (titulo(glosa) or RE_SECCION.search(n)):
        return True                                    # "ESTADOS DE FLUJOS DE EFECTIVO  2023  2022", "ACTIVOS  2019"
    fecha = all(v <= 31 or 1990 <= v <= 2035 for v in vals)          # "Al 31 de diciembre de 2015": 31 | 2015
    return bool(RE_ENCABEZADO.search(n)) and (anios or chicos or fecha)


def contar_anclas(filas):
    return {e: sum(1 for g, *_ in filas if rx.search(norm(g))) for e, rx in ANCLAS.items()}


def anclas_fuertes(filas, minimo=2, cuenta=None):
    """Estado con >= 2 lineas tipicas en la pagina, si es uno solo; si no, None.
    Sirve para una pagina agregada sin titulo (un EFE bajo "Notas a los estados financieros")
    y para un titulo equivocado (un ESF impreso bajo "Estado de Resultados Integrales")."""
    cuenta = cuenta or contar_anclas(filas)
    fuertes = [e for e, n in cuenta.items() if n >= minimo]
    return fuertes[0] if len(fuertes) == 1 else None


def estado_por_anclas(filas):
    cuenta = {e: sum(1 for g, *_ in filas if rx.search(norm(g))) for e, rx in ANCLAS.items()}
    mejor = max(cuenta, key=cuenta.get)
    return mejor if cuenta[mejor] and list(cuenta.values()).count(cuenta[mejor]) == 1 else None


MAX_FILAS_TITULO = 10    # en una pagina agregada, el titulo tiene que estar arriba (no en un parrafo)
# Nota de transicion a NIIF (2011): concilia el ERI o el ESF bajo PCGA con el NIIF, con las
# mismas lineas y montos de un estado ("Saldos segun PCGA | Efecto de la transicion | Saldos
# segun NIIF"). El 03 la toma por contenido y el lector la leia como ERI (revision 03c: 8773 2011,
# utilidad tomada de la nota). Una pagina con esto arriba no es un estado.
RE_TRANSICION = re.compile(r"transicion\w{0,6}niif|segunpcga|efectodelatransicion")


def es_transicion(filas):
    return any(RE_TRANSICION.search(norm(g)) for g, *_ in filas[:MAX_FILAS_TITULO + 5])


def paginas_lector(paginas_estados, n_paginas=None):
    """Paginas que lee el lector: las del 03 mas los huecos entre ellas y una antes y una
    despues. El 03 ubica paginas por CONTENIDO (>= N cifras del XML) y pierde las que calzan
    poco: fondos con montos chicos o estados con errores, justo los que interesan.
    Con menos de 4 paginas del 03, 3 antes y 3 despues. El 03a extrae estas mismas
    paginas (una sola definicion)."""
    ps = sorted({int(p) for p in paginas_estados})
    if not ps:
        return []
    # Con menos de 4 paginas el 03 vio solo parte de los estados (hay 4): se mira mas lejos.
    margen = 1 if len(ps) >= 4 else 3
    return [p for p in range(max(1, ps[0] - margen), ps[-1] + margen + 1) if n_paginas is None or p <= n_paginas]


def paginas_de(paginas_estados, coords):
    """(paginas a leer, base) de un reporte. Con paginas del 03: paginas_lector. Sin ellas
    (03 "sin_paginas_de_estados" o "sin_texto"): todas las del cache, como agregadas (cada una
    se usa solo si trae titulo o lineas tipicas de un estado)."""
    if coords is None:
        return [], set()
    if paginas_estados is not None and not (isinstance(paginas_estados, float) and paginas_estados != paginas_estados):
        if isinstance(paginas_estados, float):
            paginas_estados = str(int(paginas_estados))      # una sola pagina leida como numero
        base = [int(p) for p in str(paginas_estados).split(",") if p.strip().isdigit()]
        if base:
            return [p for p in paginas_lector(base) if str(p) in coords["paginas"]], set(base)
    return sorted(int(p) for p in coords["paginas"]), set()


def leer_estados(coords, paginas, base=None):
    """Renglones del ESF, la ERI y el EFE de las paginas de estados (en orden).
    Devuelve (renglones, paginas_estado): paginas_estado = {pagina: [estados con montos]}.
    metodo: "espacial" | "encabezado" (fechas/anios/notas leidos como montos: no se emparejan)
    | "glosa_partida" (las lineas de una glosa partida unidas: montos en la primera, en la
    ultima o repartidos).
    base: paginas del 03. Las demas (de paginas_lector) se leen solo si traen el titulo de un
    estado en sus primeras lineas; si no, se saltan sin tocar el estado vigente (notas,
    informe del auditor, indice)."""
    out, pags = [], {}
    estado, n_por_estado = None, {}
    for p in paginas:
        pg = coords["paginas"].get(str(p)) if coords else None
        if not pg:
            continue
        filas, _ = filas_espaciales(pg)
        encab = [(a is None and b is None) or es_encabezado(g, a, b) for g, a, b, _ in filas]
        titulos = {titulo(g) for (g, *_), e in zip(filas, encab) if e} - {None}
        cuenta = contar_anclas(filas)
        por_contenido = anclas_fuertes(filas, cuenta=cuenta)
        rotulo = None                         # titulo impreso cuando el contenido es de otro estado
        indice = len(titulos) >= 3            # indice o informe del auditor: nombra 3+ estados
        if es_transicion(filas):              # nota de transicion a NIIF: no cambia el estado vigente
            continue
        if base is not None and p not in base and (indice or not (any(
                e and titulo(g) for (g, *_), e in list(zip(filas, encab))[:MAX_FILAS_TITULO])
                or por_contenido)):
            continue
        if indice or not titulos:
            estado = estado_por_anclas(filas) or estado
        previas = []
        for (glosa, act, ant, _), sin_cifras in zip(filas, encab):
            sin_monto = act is None and ant is None
            # un titulo con montos que no son anios es una entrada de indice: no cambia el estado
            solo_anios = all(1990 <= abs(v) <= 2035 for v in (act, ant) if v)
            if sin_cifras and not indice and (sin_monto or solo_anios):
                t = titulo(glosa)
                if t:
                    # Titulo de otro estado sobre una pagina cuyo contenido es inequivoco
                    # (>= 2 lineas tipicas de un solo estado y ninguna del titulado): manda el
                    # contenido y el titulo impreso queda en "rotulo" (es un hallazgo del PDF).
                    if por_contenido and por_contenido != t and not cuenta.get(t) and len(titulos) == 1:
                        estado, rotulo = por_contenido, t
                    else:
                        estado = t
                    previas = []
                    continue
            if not sin_cifras:                      # estados con montos en la pagina
                pags.setdefault(p, [])
                if estado not in pags[p]:
                    pags[p].append(estado)
            if estado in (None, "ECP"):
                continue
            q = out[-1] if out else None
            misma = q is not None and q["pagina"] == p and q["estado"] == estado
            q_monto = misma and (q["actual"] is not None or q["anterior"] is not None)
            # Glosa partida con los montos en la PRIMERA linea: "Aumento de activo neto atribuible
            # a partícipes originado por  733" / "actividades de la operacion antes de ...".
            if (sin_monto and q_monto and q["metodo"] in ("espacial", "glosa_partida") and es_cola(glosa)
                    and glosa.strip() and (glosa.strip()[:1].islower() or RE_ABIERTA.search(q["glosa"].lower()))):
                q["glosa"] = (q["glosa"] + " " + glosa.strip()).strip()
                q["metodo"] = "glosa_partida"
                continue
            # Montos en la ULTIMA linea de la glosa, que esta vacia o es una cola ("(+)",
            # "entregados en garantia", "EQUIVALENTE"): se unen a la linea de arriba sin montos.
            if (not sin_monto and not sin_cifras and misma and not q_monto and q["metodo"] == "espacial"
                    and q["glosa"] and es_cola(glosa)):
                q["glosa"] = (q["glosa"] + " " + glosa.strip()).strip()
                q["actual"], q["anterior"] = act, ant
                # pie "Las notas adjuntas numeros 1 al 30..." con sus numeros en la linea de abajo
                q["metodo"] = "encabezado" if es_encabezado(q["glosa"], act, ant) else "glosa_partida"
                previas = []
                continue
            # Glosa partida con los montos repartidos en sus dos lineas ("Diferencias de cambio
            # ... efectivo y efectivo  -" / "equivalente  (858)"): se unen si no chocan.
            if (q_monto and not sin_monto and not sin_cifras and es_cola(glosa) and q["metodo"] == "espacial"
                    and not (q["actual"] and act) and not (q["anterior"] and ant)):
                q["glosa"] = (q["glosa"] + " " + glosa.strip()).strip()
                q["actual"] = q["actual"] or act
                q["anterior"] = q["anterior"] or ant
                q["metodo"] = "glosa_partida"
                continue
            n = n_por_estado.get(estado, 0)
            n_por_estado[estado] = n + 1
            out.append({"pagina": p, "estado": estado, "renglon": n, "glosa": glosa.strip(),
                        "previa": " ".join(previas).strip(), "actual": act, "anterior": ant,
                        "metodo": "encabezado" if sin_cifras and not sin_monto else "espacial",
                        "rotulo": rotulo})
            previas = (previas + [glosa.strip()])[-2:] if sin_monto else []
    return out, pags