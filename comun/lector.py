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
    "ERI": re.compile(r"estados?(intermedios?)?deresultados"),
    "ECP": re.compile(r"estados?(intermedios?)?decambios|cambios?en(el|los)?activos?netos?"),
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
RE_ENCABEZADO = re.compile(r"diciembre|ejercicios?terminad|anosterminad|notas?$|^notas?|pagina|^n(o|ro)?$"
                           r"|notasadjuntas")
# Cola de una glosa partida: "Saldo final de efectivo y efectivo" / "equivalente  196.824"
# (vacia o solo signos "(+)", "(+ o -)": la linea de los montos de una glosa de arriba)
RE_COLA = re.compile(r"^(y)?(efectivo)?equivalentes?(alfinal|alinicio)?$|^participes$|^decuotas$|^o?$")
# Glosa que quedo abierta: "... atribuible a partícipes originado por" / "actividades de la ..."
RE_ABIERTA = re.compile(r"(\b(de|del|y|e|la|las|el|los|en|por|a|al|o|u|sobre|con|neto|netos)|[(,-])$")


RE_CONECTOR = re.compile(r"^(de|del|la|las|el|los|y|e|en|por|a|al|o|sobre)\s", re.I)


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
    return bool(RE_ENCABEZADO.search(n)) and (anios or chicos)


def estado_por_anclas(filas):
    cuenta = {e: sum(1 for g, *_ in filas if rx.search(norm(g))) for e, rx in ANCLAS.items()}
    mejor = max(cuenta, key=cuenta.get)
    return mejor if cuenta[mejor] and list(cuenta.values()).count(cuenta[mejor]) == 1 else None


def leer_estados(coords, paginas):
    """Renglones del ESF, la ERI y el EFE de las paginas de estados (en orden).
    Devuelve (renglones, paginas_estado): paginas_estado = {pagina: [estados con montos]}.
    metodo: "espacial" | "encabezado" (fechas/anios/notas leidos como montos: no se emparejan)
    | "glosa_partida" (las lineas de una glosa partida unidas: montos en la primera, en la
    ultima o repartidos)."""
    out, pags = [], {}
    estado, n_por_estado = None, {}
    for p in paginas:
        pg = coords["paginas"].get(str(p)) if coords else None
        if not pg:
            continue
        filas, _ = filas_espaciales(pg)
        encab = [(a is None and b is None) or es_encabezado(g, a, b) for g, a, b, _ in filas]
        if not any(e and titulo(g) for (g, *_), e in zip(filas, encab)):
            estado = estado_por_anclas(filas) or estado
        previas = []
        for (glosa, act, ant, _), sin_cifras in zip(filas, encab):
            sin_monto = act is None and ant is None
            if sin_cifras:
                t = titulo(glosa)
                if t:
                    estado, previas = t, []
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
                        "metodo": "encabezado" if sin_cifras and not sin_monto else "espacial"})
            previas = (previas + [glosa.strip()])[-2:] if sin_monto else []
    return out, pags