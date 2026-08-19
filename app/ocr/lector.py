"""
Lectura del documento: PDF con texto, PDF imagen o foto.

Estrategia
----------
1. Si el PDF trae texto embebido, se usa TAL CUAL (pdfplumber). Es exacto y
   cuesta milisegundos; ningun OCR le gana.
2. Si no, se rasteriza y se pasa por Tesseract en CASCADA: varias pasadas con
   distinta configuracion, de la mas barata a la mas cara, y se corta apenas
   una entrega todos los campos criticos.

Por que en cascada y no una sola pasada
---------------------------------------
Se midio sobre facturas reales (ver test_ocr.py). Con la configuracion que
tenia el servicio —ingles, PSM 6— el RUC del emisor y el importe salian en
0 de 4 documentos: el idioma equivocado rompe las palabras y PSM 6 asume un
bloque uniforme de texto, asi que descarta la caja del encabezado y la
columna de importes.

    configuracion              RUC emisor   serie-numero   importe
    ingles, PSM 6 (anterior)      0/4           4/4          0/4
    espanol, PSM 4                4/4           4/4          0/4
    espanol, PSM 3                4/4           4/4          4/4

PSM 3 (segmentacion automatica) es el que respeta las regiones del documento.
Las pasadas siguientes —binarizacion Otsu, correccion de inclinacion, 400
dpi— no aportan nada en PDF limpios, pero son las que rescatan las fotos de
celular torcidas o con sombra, asi que quedan como respaldo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import cv2
import numpy as np
import pytesseract
from PIL import Image

try:
    import pdfplumber
except ImportError:                                  # pragma: no cover
    pdfplumber = None

from pdf2image import convert_from_path

#: Minimo de caracteres para considerar que un PDF trae texto de verdad.
MIN_CHARS_TEXTO_NATIVO = 80

#: Ancho al que se reescala antes de reconocer (Tesseract rinde mejor con
#: texto grande; por debajo de ~1800px se degrada notoriamente).
ANCHO_OBJETIVO = 2500


@dataclass
class Pasada:
    """Una configuracion de reconocimiento."""
    nombre: str
    dpi: int
    preproceso: str          # "escala" | "otsu" | "otsu_deskew"
    psm: int
    idioma: str = "spa"

    @property
    def config(self) -> str:
        return f"--oem 3 --psm {self.psm}"


#: Orden de las pasadas. La primera resuelve la gran mayoria de los casos.
PASADAS: List[Pasada] = [
    Pasada("spa-psm3",             300, "escala",      3),
    Pasada("spa-psm4-otsu",        300, "otsu",        4),
    Pasada("spa-psm3-otsu-deskew", 400, "otsu_deskew", 3),
    Pasada("spa-psm11-sparse",     300, "otsu",       11),
]


@dataclass
class Lectura:
    texto: str = ""
    origen: str = ""                 # "pdf-nativo" | nombre de la pasada
    pasadas: List[str] = field(default_factory=list)
    paginas: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.texto and self.texto.strip())


class Lector:
    """Convierte un archivo (PDF o imagen) en texto."""

    def __init__(self, tesseract_cmd: Optional[str] = None,
                 poppler_path: Optional[str] = None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.poppler_path = poppler_path

    # ---------------------------------------------------------------- PDF
    def texto_nativo(self, ruta: str) -> Optional[str]:
        """Texto embebido del PDF, o None si es un PDF de imagen."""
        if pdfplumber is None:
            return None
        try:
            partes = []
            with pdfplumber.open(ruta) as pdf:
                for pagina in pdf.pages:
                    t = pagina.extract_text(x_tolerance=2, y_tolerance=2)
                    if t:
                        partes.append(t)
            texto = "\n".join(partes)
            return texto if len(texto.strip()) >= MIN_CHARS_TEXTO_NATIVO else None
        except Exception:
            return None

    def _rasterizar(self, ruta: str, dpi: int) -> List[Image.Image]:
        kwargs = {"dpi": dpi}
        if self.poppler_path:
            kwargs["poppler_path"] = self.poppler_path
        return convert_from_path(ruta, **kwargs)

    # -------------------------------------------------------- preproceso
    @staticmethod
    def preprocesar(imagen: Image.Image, modo: str) -> np.ndarray:
        img = np.array(imagen.convert("RGB"))
        img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        if img.shape[1] < ANCHO_OBJETIVO:
            escala = ANCHO_OBJETIVO / img.shape[1]
            img = cv2.resize(img, (ANCHO_OBJETIVO, int(img.shape[0] * escala)),
                             interpolation=cv2.INTER_CUBIC)

        if modo in ("otsu", "otsu_deskew"):
            img = cv2.GaussianBlur(img, (3, 3), 0)
            img = cv2.threshold(img, 0, 255,
                                cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        if modo == "otsu_deskew":
            img = Lector._enderezar(img)

        return img

    @staticmethod
    def _enderezar(img: np.ndarray) -> np.ndarray:
        """Corrige la inclinacion de una foto tomada a mano."""
        coords = np.column_stack(np.where(img < 255))
        if len(coords) < 100:
            return img

        angulo = cv2.minAreaRect(coords)[-1]
        angulo = -(90 + angulo) if angulo < -45 else -angulo

        if abs(angulo) < 0.3 or abs(angulo) > 15:
            return img                      # ruido, o algo que no es inclinacion

        alto, ancho = img.shape
        M = cv2.getRotationMatrix2D((ancho // 2, alto // 2), angulo, 1.0)
        return cv2.warpAffine(img, M, (ancho, alto), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)

    # ------------------------------------------------------------ lectura
    def leer(self, ruta: str,
             suficiente: Optional[Callable[[str], bool]] = None,
             forzar_ocr: bool = False,
             pasadas_pesadas_primero: bool = False,
             max_pasadas: int = len(PASADAS)) -> Lectura:
        """
        Devuelve el texto del documento.

        `suficiente` decide cuando parar: recibe el texto acumulado y responde
        si ya alcanza. Lo provee el extractor, que es quien sabe si los campos
        criticos estan completos. Sin el, se corta en la primera pasada.

        `pasadas_pesadas_primero` invierte el orden: es lo que hace el boton
        "Mejorar la imagen" de la vista, cuando el usuario ya vio que la
        lectura normal no alcanzo.
        """
        lectura = Lectura()
        es_pdf = ruta.lower().endswith(".pdf")

        if es_pdf and not forzar_ocr:
            nativo = self.texto_nativo(ruta)
            if nativo:
                lectura.texto = nativo
                lectura.origen = "pdf-nativo"
                lectura.pasadas = ["pdf-nativo"]
                lectura.paginas = nativo.count("\f") + 1
                if suficiente is None or suficiente(nativo):
                    return lectura
                # si el texto nativo esta incompleto (PDF mixto), se sigue con OCR

        mejor_texto = lectura.texto
        mejor_origen = lectura.origen

        orden = list(reversed(PASADAS)) if pasadas_pesadas_primero else list(PASADAS)

        cache_paginas = {}
        for pasada in orden[:max_pasadas]:
            try:
                if pasada.dpi not in cache_paginas:
                    cache_paginas[pasada.dpi] = (
                        self._rasterizar(ruta, pasada.dpi) if es_pdf
                        else [Image.open(ruta)])
                paginas = cache_paginas[pasada.dpi]

                textos = []
                for pagina in paginas:
                    img = self.preprocesar(pagina, pasada.preproceso)
                    textos.append(pytesseract.image_to_string(
                        img, lang=pasada.idioma, config=pasada.config))

                texto = "\n".join(textos)
                lectura.pasadas.append(pasada.nombre)
                lectura.paginas = len(paginas)

                if len(texto.strip()) > len(mejor_texto.strip()):
                    mejor_texto, mejor_origen = texto, pasada.nombre

                if suficiente is not None and suficiente(texto):
                    lectura.texto, lectura.origen = texto, pasada.nombre
                    return lectura

            except Exception as e:                    # pragma: no cover
                lectura.pasadas.append(f"{pasada.nombre} (fallo: {e})")

        lectura.texto, lectura.origen = mejor_texto, mejor_origen
        return lectura

    # ------------------------------------------------------------ vista previa
    def previsualizacion_base64(self, ruta: str, calidad: int = 70) -> str:
        """JPEG en base64 de la primera pagina, para mostrar en la vista."""
        import base64
        from io import BytesIO

        if ruta.lower().endswith(".pdf"):
            imagen = self._rasterizar(ruta, 300)[0]
        else:
            imagen = Image.open(ruta)

        if imagen.mode in ("RGBA", "LA", "P"):
            imagen = imagen.convert("RGB")

        buffer = BytesIO()
        imagen.save(buffer, format="JPEG", quality=calidad)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
