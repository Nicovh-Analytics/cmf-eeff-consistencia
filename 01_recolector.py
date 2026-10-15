"""
Recolector de Estados Financieros de Fondos Mutuos - CMF Chile (v2)
====================================================================

Baja, por fondo-anio, el XML de EEFF y el PDF de EEFF (FMNO) que las AGF
envian a la CMF, mas el HTML crudo de la consulta.

NO analiza nada. Solo recolecta y guarda a disco.

Flujo de la fuente (verificado en DevTools, 2026-09-24):
  1. GET  listado  -> rut + row de cada fondo
  2. POST pestania=3 con mm/aa -> HTML con la tabla y los enlaces
  3. GET  ifrs_xml_verarchivo -> el archivo binario

Cambios v2 (pensados para la corrida completa):
  - REANUDABLE: si el HTML de un fondo-anio ya esta en disco, no se
    repite el POST; los enlaces se leen del HTML guardado. Una segunda
    corrida sobre datos completos hace cero peticiones.
  - Recorre ANIO -> FONDO, del mas reciente al mas antiguo: cada anio
    terminado es un corte transversal completo y analizable.
  - Manifiesto incremental (append + flush por fila): no se pierde nada
    si la corrida se corta.
  - Pausa adaptativa: espera al menos el doble de lo que tardo el
    servidor en responder.
  - Opcion para incluir fondos no vigentes (sesgo de supervivencia).

Sugerencia: correrlo de noche y guardar el log desde Git Bash:
    python 01_recolector.py | tee -a data/log_recolector.txt
"""

import csv
import random
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import pandas as pd

# ---------------------------------------------------------------------------
# CONFIGURACION
# ---------------------------------------------------------------------------

BASE = "https://www.cmfchile.cl"
URL_LISTADO = f"{BASE}/institucional/mercados/consulta.php"
URL_ENTIDAD = f"{BASE}/institucional/mercados/entidad.php"

TIPOS_A_BAJAR = {"FMEF": "eeff_xml", "FMNO": "eeff_pdf"}

USER_AGENT = (
    "nicovh-research-bot/0.2 "
    "(proyecto personal de analisis de datos publicos; "
    "nicovh.analytics@gmail.com)"
)

# --- Alcance ---
# Desde 2011 los EEFF son IFRS y anuales (circular 1997). Del mas
# reciente al mas antiguo.
ANIOS = list(range(2025, 2010, -1))
MAX_FONDOS = None            # None = todos. Pon un numero para probar.

# Fondos no vigentes: evitan el sesgo de supervivencia, pero NO esta
# verificado que el POST funcione con vig=NV. Antes de activarlo, prueba
# a mano un fondo no vigente en el navegador y revisa el payload en
# DevTools igual que hicimos con los vigentes.
INCLUIR_NO_VIGENTES = False

# --- Ritmo ---
PAUSA_POST = (1.5, 2.5)      # rango aleatorio tras cada consulta (la cara)
PAUSA_ARCHIVO = (0.5, 1.0)   # rango tras cada descarga (la barata)
FACTOR_ADAPTATIVO = 2.0      # pausa minima = 2x lo que tardo la respuesta
MAX_REINTENTOS = 3
BACKOFF_BASE = 10            # 10s, 20s, 40s ante error transitorio
TIMEOUT = 30
STATUS_RETRY = {429, 500, 502, 503, 504}
MAX_FALLOS_SEGUIDOS = 3

# --- Rutas (ancladas al script, no al directorio de trabajo) ---
DIR_DATA = Path(__file__).resolve().parent / "data"
DIR_HTML = DIR_DATA / "html"
DIR_ARCHIVOS = DIR_DATA / "archivos"
MANIFIESTO = DIR_DATA / "manifiesto.csv"
CAMPOS_MANIFIESTO = ["rut", "vig", "nombre", "administradora", "anio",
                     "tipo", "archivo", "ruta", "estado", "origen_html"]

# --- Campos fijos del CMS (verificados identicos en dos fondos distintos) ---
FORM_CMS = {
    "HTTP_REFERER": "",
    "HTTP_REFERER_PREV": "",
    "referer": "/portal/principal/623/w4-channel.html",
    "service": "newtenberg-kila-cmf",
    "cid": "515",
    "context_cid": "515",
    "action": "exeResponse",
    "context_iid": "613",
    "fdid": "530",
}


# ---------------------------------------------------------------------------
# INFRAESTRUCTURA
# ---------------------------------------------------------------------------

class ServidorEstresado(Exception):
    """Se lanza cuando conviene abortar la corrida completa."""


_ultima_respuesta_seg = 0.0   # lo que tardo la ultima peticion exitosa


def crear_sesion() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT,
                      "Accept-Language": "es-CL,es;q=0.9"})
    return s


def dormir(rango):
    """Pausa aleatoria en el rango, pero nunca menos que FACTOR x el
    tiempo de la ultima respuesta. Si el servidor se pone lento, nosotros
    tambien."""
    espera = max(random.uniform(*rango), FACTOR_ADAPTATIVO * _ultima_respuesta_seg)
    time.sleep(espera)


def pedir(sesion, metodo, url, **kwargs):
    """GET/POST con reintentos y backoff exponencial."""
    global _ultima_respuesta_seg
    kwargs.setdefault("timeout", TIMEOUT)

    for intento in range(MAX_REINTENTOS):
        try:
            r = sesion.request(metodo, url, **kwargs)
        except requests.RequestException as e:
            espera = BACKOFF_BASE * (2 ** intento)
            print(f"    ! red: {e.__class__.__name__}. Espero {espera}s...")
            time.sleep(espera)
            continue

        if r.status_code == 429:
            raise ServidorEstresado("El servidor devolvio 429 (demasiadas peticiones)")

        if r.status_code in STATUS_RETRY:
            espera = BACKOFF_BASE * (2 ** intento)
            print(f"    ! HTTP {r.status_code}. Espero {espera}s...")
            time.sleep(espera)
            continue

        if r.ok:
            _ultima_respuesta_seg = r.elapsed.total_seconds()
            return r

        print(f"    ! HTTP {r.status_code} (sin reintento)")
        return None

    print("    ! agotados los reintentos")
    return None


# ---------------------------------------------------------------------------
# PASO 1 - LISTADO DE FONDOS
# ---------------------------------------------------------------------------

def obtener_fondos(sesion, estado):
    """Devuelve [{rut, row, vig, nombre, administradora}, ...]."""
    r = pedir(sesion, "GET", URL_LISTADO,
              params={"mercado": "V", "Estado": estado, "entidad": "RGFMU"})
    if r is None:
        raise RuntimeError(f"No se pudo obtener el listado ({estado})")

    soup = BeautifulSoup(r.text, "lxml")
    fondos, vistos = [], set()

    for a in soup.select("a[href*='entidad.php']"):
        qs = parse_qs(urlparse(a["href"]).query)
        rut = (qs.get("rut") or [None])[0]
        row = (qs.get("row") or [None])[0]
        if not rut or not row or rut in vistos:
            continue
        vistos.add(rut)

        fila = a.find_parent("tr")
        celdas = [td.get_text(strip=True) for td in fila.find_all("td")] if fila else []
        fondos.append({
            "rut": rut,
            "row": row,
            # Tomamos 'vig' del propio enlace en vez de asumirlo.
            "vig": (qs.get("vig") or [estado])[0],
            "nombre": celdas[1] if len(celdas) > 1 else "",
            "administradora": celdas[2] if len(celdas) > 2 else "",
        })
    return fondos


# ---------------------------------------------------------------------------
# PASO 2 - CONSULTA DEL PERIODO (con cache en disco)
# ---------------------------------------------------------------------------

def obtener_html(sesion, fondo, anio, mes=12):
    """Devuelve (html, origen). origen = 'cache' | 'red' | None si fallo.

    Si el HTML ya esta guardado, se usa ese y NO se hace el POST. Esto es
    lo que hace reanudable la corrida."""
    ruta = DIR_HTML / f"{fondo['rut']}_{anio}{mes:02d}.html"
    if ruta.exists() and ruta.stat().st_size > 0:
        return ruta.read_text(encoding="utf-8"), "cache"

    params = {
        "mercado": "V", "rut": fondo["rut"], "grupo": "",
        "tipoentidad": "RGFMU", "row": fondo["row"], "vig": fondo["vig"],
        "control": "svs", "pestania": "3",
    }
    data = {"mm": str(mes), "aa": str(anio), **FORM_CMS}

    r = pedir(sesion, "POST", URL_ENTIDAD, params=params, data=data)
    if r is None:
        return None, None

    # Guardar SIEMPRE antes de parsear: si el parser falla, se arregla
    # sin volver a molestar al servidor.
    ruta.write_text(r.text, encoding="utf-8")
    return r.text, "red"


def extraer_enlaces(html):
    """Enlaces de descarga del XML de EEFF y del PDF FMNO."""
    soup = BeautifulSoup(html, "lxml")
    enlaces = []
    for a in soup.select("a[href*='ifrs_xml_verarchivo']"):
        href = a["href"]
        qs = parse_qs(urlparse(href).query)
        archivo = (qs.get("archivo") or [None])[0]
        tipo = TIPOS_A_BAJAR.get((archivo or "")[:4].upper())
        if tipo and archivo:
            enlaces.append({"url": urljoin(URL_ENTIDAD, href),
                            "archivo": archivo, "tipo": tipo})
    return enlaces


# ---------------------------------------------------------------------------
# PASO 3 - DESCARGA
# ---------------------------------------------------------------------------

def descargar(sesion, enlace, destino: Path):
    """Baja un archivo si no existe ya. Escribe a un .part y renombra al
    final: si la descarga se corta a la mitad, no queda un archivo
    truncado que el cache confunda con uno completo."""
    if destino.exists() and destino.stat().st_size > 0:
        return "cache"

    r = pedir(sesion, "GET", enlace["url"], stream=True)
    if r is None:
        return "error"

    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(destino.suffix + ".part")
    with open(temporal, "wb") as f:
        for bloque in r.iter_content(8192):
            f.write(bloque)
    temporal.replace(destino)
    return "ok"


# ---------------------------------------------------------------------------
# ORQUESTACION
# ---------------------------------------------------------------------------

def abrir_manifiesto():
    """Abre el manifiesto en modo agregar; escribe el encabezado solo si
    el archivo es nuevo."""
    nuevo = not MANIFIESTO.exists()
    f = open(MANIFIESTO, "a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=CAMPOS_MANIFIESTO)
    if nuevo:
        w.writeheader()
    return f, w


def main():
    for d in (DIR_HTML, DIR_ARCHIVOS):
        d.mkdir(parents=True, exist_ok=True)

    sesion = crear_sesion()

    print("[1/2] Bajando listado de fondos mutuos...")
    fondos = obtener_fondos(sesion, "VI")
    if INCLUIR_NO_VIGENTES:
        vistos = {f["rut"] for f in fondos}
        fondos += [f for f in obtener_fondos(sesion, "NV") if f["rut"] not in vistos]
    if MAX_FONDOS:
        fondos = fondos[:MAX_FONDOS]
    print(f"      {len(fondos)} fondos x {len(ANIOS)} anios "
          f"= {len(fondos) * len(ANIOS)} fondo-anio\n")

    f_man, w_man = abrir_manifiesto()
    fallos_seguidos = 0
    stats = {"post": 0, "cache_html": 0, "bajados": 0, "sin_datos": 0}
    inicio = time.time()

    print("[2/2] Recolectando (ANIO -> FONDO)...")
    try:
        for anio in ANIOS:
            print(f"\n=== {anio} ===")
            for i, fondo in enumerate(fondos, 1):
                html, origen = obtener_html(sesion, fondo, anio)

                if origen == "red":
                    stats["post"] += 1
                    dormir(PAUSA_POST)
                elif origen == "cache":
                    stats["cache_html"] += 1

                if html is None:
                    fallos_seguidos += 1
                    print(f"  [{i}] {fondo['rut']} ! sin respuesta ({fallos_seguidos} seguidos)")
                    if fallos_seguidos >= MAX_FALLOS_SEGUIDOS:
                        raise ServidorEstresado(f"{fallos_seguidos} fallos seguidos")
                    continue
                fallos_seguidos = 0

                enlaces = extraer_enlaces(html)
                if not enlaces:
                    # El fondo no existia ese anio (o no presento). Normal.
                    stats["sin_datos"] += 1
                    continue

                for enlace in enlaces:
                    destino = DIR_ARCHIVOS / fondo["rut"] / str(anio) / enlace["archivo"]
                    estado = descargar(sesion, enlace, destino)
                    if estado == "ok":
                        stats["bajados"] += 1
                        dormir(PAUSA_ARCHIVO)

                    if estado != "cache":
                        w_man.writerow({
                            "rut": fondo["rut"], "vig": fondo["vig"],
                            "nombre": fondo["nombre"],
                            "administradora": fondo["administradora"],
                            "anio": anio, "tipo": enlace["tipo"],
                            "archivo": enlace["archivo"], "ruta": str(destino),
                            "estado": estado, "origen_html": origen,
                        })
                f_man.flush()

                # Progreso cada 25 fondos, para no inundar la consola.
                if i % 25 == 0 or i == len(fondos):
                    min_ = (time.time() - inicio) / 60
                    print(f"  {anio}: {i}/{len(fondos)} | POST {stats['post']} "
                          f"| html en cache {stats['cache_html']} "
                          f"| archivos nuevos {stats['bajados']} "
                          f"| sin datos {stats['sin_datos']} | {min_:.0f} min")

    except ServidorEstresado as e:
        print(f"\n!! ABORTADO: {e}")
        print("   Relanza mas tarde: lo ya bajado no se vuelve a pedir.")
    except KeyboardInterrupt:
        print("\n!! Interrumpido. Relanza cuando quieras: retoma donde quedo.")
    finally:
        f_man.close()

    print(f"\nResumen: {stats} | {(time.time() - inicio) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())

m = pd.read_csv("data/manifiesto.csv", dtype={"rut": str}).drop_duplicates("archivo")
print(m.groupby(["rut", "anio", "tipo"]).size().unstack(fill_value=0).to_string())