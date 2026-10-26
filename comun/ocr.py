"""
OCR de paginas de estados financieros publicados como imagen
=============================================================

Convierte una pagina del PDF en palabras con coordenadas en puntos, en el MISMO
formato que guarda 03a_coordenadas.py ([texto, x0, x1, top, bottom]), mas la
confianza de Tesseract como sexto elemento. Asi lector_espacial lee una pagina
OCR igual que una pagina con texto; la pagina queda marcada con origen="ocr".

Calibracion (EFE sinteticos con cifras conocidas, 2026-10-23):
  - 300 dpi, imagen limpia: 100% de montos exactos; escaneo simulado: ~99%.
  - Ninguna "suma falsa": cuando el OCR erra un digito, el subtotal deja de
    sumar. Por eso un no-suma en pagina OCR se clasifica como lectura, nunca
    como error del PDF (03b).
  - Binarizar empeora (98%): no se usa. psm 6 y psm 4 rinden igual.

Requiere Tesseract instalado (en Windows: instalador UB-Mannheim, con el idioma
spa). Ruta por variable TESSERACT_CMD o la ruta por defecto de Windows.
"""
import os
import re
import shutil

import pypdfium2 as pdfium
import pytesseract

PT = 72.0
DPI = 300
PSM = 6
_WIN = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def configurar():
    """Ubica tesseract y elige idioma (spa+eng si esta spa; si no, eng)."""
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract") or (_WIN if os.path.exists(_WIN) else None)
    if not cmd:
        raise RuntimeError("No se encontro Tesseract: instalalo o define TESSERACT_CMD")
    pytesseract.pytesseract.tesseract_cmd = cmd
    langs = set(pytesseract.get_languages(config=""))
    return "spa+eng" if "spa" in langs else "eng"


def rasterizar(doc, pagina, dpi=DPI):
    """Imagen en escala de grises de la pagina (1-based) y su ancho en pt."""
    pg = doc[pagina - 1]
    return pg.render(scale=dpi / PT).to_pil().convert("L"), pg.get_width()


def ocr_pagina(img, ancho_pt, lang="eng", dpi=DPI, psm=PSM):
    """Palabras [texto, x0, x1, top, bottom, conf] en pt."""
    d = pytesseract.image_to_data(img, lang=lang, config=f"--psm {psm}",
                                  output_type=pytesseract.Output.DICT)
    f = PT / dpi
    pal = []
    for t, x, y, w, h, c in zip(d["text"], d["left"], d["top"], d["width"], d["height"], d["conf"]):
        t = t.strip()
        if t:
            pal.append([t, round(x * f, 1), round((x + w) * f, 1), round(y * f, 1),
                        round((y + h) * f, 1), round(float(c), 1)])
    return {"ancho": ancho_pt, "palabras": pal, "origen": "ocr"}


# Variantes que se prueban si la primera lectura tiene baja confianza en los numeros.
# Se elige por CONFIANZA de Tesseract, no por "la que suma": elegir la lectura que
# cuadra sesgaria el resultado hacia no ver errores (el XML/la suma como arbitro).
VARIANTES = [(DPI, PSM), (400, PSM), (DPI, 4), (400, 4)]
CONF_OK = 90.0
RE_NUM = re.compile(r"\d")


def conf_numerica(datos):
    """Confianza media de las palabras con digitos (lo que importa para sumar)."""
    cs = [w[5] for w in datos["palabras"] if RE_NUM.search(w[0]) and w[5] >= 0]
    return sum(cs) / len(cs) if cs else 0.0


def ocr_mejor(doc, pagina, lang="eng"):
    """Primera variante; si su confianza numerica es baja, prueba las demas y se queda
    con la de mayor confianza. Registra variante y confianza en los datos."""
    mejor = None
    for k, (dpi, psm) in enumerate(VARIANTES):
        img, ancho = rasterizar(doc, pagina, dpi)
        datos = ocr_pagina(img, ancho, lang, dpi, psm)
        datos["conf_num"] = round(conf_numerica(datos), 1)
        datos["variante"] = f"{dpi}dpi-psm{psm}"
        if mejor is None or datos["conf_num"] > mejor["conf_num"]:
            mejor = datos
        if k == 0 and datos["conf_num"] >= CONF_OK:
            break
    return mejor


def ocr_pdf(ruta_pdf, paginas, lang="eng", multipasada=False):
    """{pagina: datos} para las paginas pedidas."""
    doc = pdfium.PdfDocument(str(ruta_pdf))
    try:
        out = {}
        for p in paginas:
            if 1 <= p <= len(doc):
                if multipasada:
                    out[str(p)] = ocr_mejor(doc, p, lang)
                else:
                    img, ancho = rasterizar(doc, p, DPI)
                    out[str(p)] = ocr_pagina(img, ancho, lang, DPI)
        return out
    finally:
        doc.close()