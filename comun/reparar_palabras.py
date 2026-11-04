"""Reparaciones de las palabras de una pagina antes de leerla (las aplica cargar_coords)."""
import re

RE_INCOMPLETO = re.compile(r"\d{1,3}(?:\.\d{3})*\.\d{1,2}")   # "3.150.44": le falta el ultimo digito
RE_CORTO = re.compile(r"\d{1,2}")                              # "51", "1": montos < 1.000 sin separador


def _monto_de_fila(w, palabras):
    """Texto del monto que termina en la palabra w: une hacia la izquierda los trozos pegados."""
    texto, cur = w[0], w
    while True:
        prev = [o for o in palabras if o is not cur and abs(o[3] - w[3]) <= 2 and -1.5 < cur[1] - o[2] < 2.0
                and re.fullmatch(r"[\d.()\-]+", o[0])]
        if not prev:
            return texto.strip("()-")
        cur = max(prev, key=lambda o: o[2])
        texto = cur[0] + texto


def reparar_apilados(palabras, ancho_max=1.8, tol_x=3.0, salto_max=30.0):
    """Digitos finales apilados (BICE 2023-2025): el ultimo digito de cada monto de una columna
    viene como UNA palabra de k digitos, con el ancho de un solo caracter ("28776[476-481]").
    Se reparte en orden de altura entre las filas de esa columna cuyo monto termina justo a la
    izquierda (x1 ~ x0 de la palabra apilada) y esta INCOMPLETO: ultimo grupo de 1-2 digitos
    ("3.150.44") o monto corto sin separador ("51"). Un monto completo ("83.797") no recibe.
    Si no hay exactamente k filas receptoras, o no van seguidas, no se toca.
    Acotado tras dos corridas (diag_apilados):
      - ancho por digito < 1.8 pt (BICE: 1.0-1.67, '785[477-482]' en 8819 2023; glifos duplicados
        de otras plantillas: ~2). El filtro de montos incompletos es el que protege.
      - receptoras seguidas (saltos <= 30 pt) y la primera a <= 30 pt de la palabra apilada
      - al menos una receptora con separador de miles incompleto (los cortos solos no bastan)
      - 8819 2023: la regla anterior (1a receptora = fila de la apilada) le dio un digito al
        efectivo completo y le quito el suyo al total de activos."""
    out = list(palabras)
    apiladas = [w for w in palabras if re.fullmatch(r"\d{2,}", w[0]) and (w[2] - w[1]) / len(w[0]) < ancho_max]
    for a in apiladas:
        filas = {}
        for w in palabras:
            if w is a or w[3] < a[3] - 2:
                continue
            if abs(w[2] - a[1]) <= tol_x and re.search(r"\d$", w[0]):
                filas.setdefault(round(w[3]), w)      # una por fila: el fragmento que termina ahi
        recept = []
        for k in sorted(filas):
            m = _monto_de_fila(filas[k], palabras)
            if RE_INCOMPLETO.fullmatch(m) or RE_CORTO.fullmatch(m):
                recept.append((filas[k], m))
            if len(recept) == len(a[0]):
                break
        if len(recept) != len(a[0]) or recept[0][0][3] - a[3] > salto_max:
            continue
        if any(f2[0][3] - f1[0][3] > salto_max for f1, f2 in zip(recept, recept[1:])):
            continue
        if not any(RE_INCOMPLETO.fullmatch(m) for _, m in recept):
            continue
        out.remove(a)
        for d, (w, _) in zip(a[0], recept):
            n = list(w)
            n[0], n[1], n[2] = d, a[1], a[2]
            out.append(type(w)(n) if isinstance(w, tuple) else n)
    return out