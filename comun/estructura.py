"""
Estructura de un estado leido del PDF: que renglones forman cada subtotal (por POSICION).

Hasta ahora la usaba solo el 03b (componentes): los renglones con montos sobre el subtotal, dentro del
estado, hasta el renglon de otro subtotal o identidad o una linea "total/subtotal" sin cuenta propia.
Aqui queda como funcion comun para que el motor sume las mismas lineas que el 03b (lectura por
posicion) ademas de la suma por codigo (D-CU19: dos lecturas independientes).

    lineas(renglones)         renglones con montos de un estado, en orden (sin encabezados)
    miembros(L, i_sub, ...)   indices (en L) de las lineas que forman el subtotal L[i_sub]
    bloques(renglones, ...)   por renglon: rol (subtotal | linea | otro) y bloque (subtotal al que suma)

Linea de L: (glosa, actual, anterior, glosa_ext, pagina, codigo, coincide, metodo); actual ausente = 0.
"""
import re

# Las regex se aplican sobre el texto SIN espacios: hay PDFs que se extraen pegados.
RE_SUBTOTAL = re.compile(r"flujos?netos?|aumento|disminuci|saldo(inicial|final)|total")
RE_AJENA = re.compile(r"activos?netos?atribuible")


def norm(s):
    return re.sub(r"\s+", "", s).lower()


def lineas(rs):
    """Renglones con montos de un estado (sin encabezados), en orden:
    (glosa, actual, anterior, glosa_ext, pagina, codigo, coincide, metodo)."""
    out = []
    for r in rs:
        if r["metodo"] == "encabezado" or (r["actual"] is None and r["anterior"] is None):
            continue
        out.append((r["glosa"], r["actual"] if r["actual"] is not None else 0, r["anterior"],
                    (r.get("previa", "") + " " + r["glosa"]).strip(), r["pagina"], r["codigo"], r["coincide"],
                    r["metodo"]))
    return out


def miembros(L, i_sub, cortes, fechas=frozenset(), partes=frozenset()):
    """Indices (en L, en orden) de las lineas con montos sobre el subtotal L[i_sub], dentro del estado,
    hasta el renglon de otro subtotal o identidad (cortes: sus codigos) o una linea "subtotal/total" sin
    cuenta propia. Esa linea se salta si esta justo encima y repite los montos del subtotal (o va en 0).
    fechas: anios del documento y dias de cierre; una linea sin cuenta cuyos montos son solo eso es un
    encabezado de fecha que el lector no marco ("31 | 2015", "2012") y no se suma."""
    propios = {abs(v) for v in L[i_sub][1:3] if v}
    idx = []
    for j in range(i_sub - 1, -1, -1):
        glosa, a, b, _, _, cod, _, _ = L[j]
        if cod in cortes:
            break
        # el activo neto atribuible no es parte de ningun subtotal del ESF/ERI/EFE: es una linea del
        # ECP (o del ESF) que quedo dentro del estado (pagina compartida sin titulo)
        if RE_AJENA.search(norm(glosa)):
            break
        # una linea "total/subtotal/flujo neto" que no es parte de este subtotal corta, aunque el
        # emparejador le haya dado otra cuenta ("Total activos" sobre el bloque del pasivo)
        if cod not in partes and RE_SUBTOTAL.search(norm(glosa)):
            nums = {abs(v) for v in (a, b) if v}
            if not idx and nums <= propios:
                continue
            break
        vals = {abs(v) for v in (a, b) if v}
        if not cod and vals and vals <= fechas:
            continue
        idx.append(j)
    return list(reversed(idx))


def ubicar(L, codigo):
    """Indice del primer renglon con ese codigo (el subtotal ubicado), o None."""
    return next((k for k, l in enumerate(L) if l[5] == codigo), None)


def bloques(L, subtotales, cortes, anio=None):
    """Por linea de L: rol y bloque. subtotales: {clave: dict(codigo, partes)} de UN estado;
    cortes: codigos que cortan en ese estado. Devuelve lista de dict(i, rol, bloque). Una linea puede
    quedar en dos bloques cuando el corte falla (el bloque del pasivo que sube hasta los activos): bloque
    = "total_activo|total_pasivo", igual que el 03b, que suma cada subtotal por separado."""
    fechas = {anio, anio - 1, anio + 1, 28, 29, 30, 31} if anio else set()
    rol = {k: ("otro", "") for k in range(len(L))}
    for clave, cfg in subtotales.items():
        i = ubicar(L, cfg["codigo"])
        if i is None:
            continue
        rol[i] = ("subtotal", clave)
        for j in miembros(L, i, cortes - {cfg["codigo"]}, fechas, set(cfg["partes"])):
            if rol[j][0] == "otro":
                rol[j] = ("linea", clave)
            elif rol[j][0] == "linea":
                rol[j] = ("linea", rol[j][1] + "|" + clave)
    return [dict(i=k, rol=r, bloque=b) for k, (r, b) in rol.items()]


# --- definiciones desde el catalogo ---------------------------------------------------------------
POSICIONALES = ("operacion", "financiamiento", "total_activo", "total_pasivo", "total_ingresos", "total_gastos")


def subtotales(entidad="fm"):
    """{clave: dict(estado, codigo, partes)} de los subtotales que se reconstruyen por posicion."""
    import catalogo
    return {k: catalogo.subtotal_03b(k, entidad) for k in POSICIONALES}


def cortes(entidad="fm"):
    """Codigos que cortan un bloque, por estado: el total de cada subtotal posicional y todos los terminos
    de las identidades no posicionales del mismo estado (EFE: aumento neto y evolucion del efectivo, con el
    saldo inicial y la diferencia de cambio). Es la lista que el 03b tenia escrita a mano (prueba)."""
    import catalogo
    r = catalogo.reglas(entidad)
    r = r[(r["clave_03b"] != "") & (r["activa"] == "si")]
    out = {}
    for clave, total, partes in zip(r["clave_03b"], r["total"], r["partes"]):
        est = total.split(":")[0]
        out.setdefault(est, set()).add(catalogo.sin_estado(total))
        if clave not in POSICIONALES:
            out[est] |= {catalogo.sin_estado(t) for _, t in catalogo.terminos(partes)}
    return out
