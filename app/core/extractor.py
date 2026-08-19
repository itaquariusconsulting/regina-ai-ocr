"""
Extraccion de los campos del comprobante.

Este modulo NO reconoce texto: recibe texto (venga del PDF nativo o de
Tesseract) y saca los campos, cada uno con su propia validacion. La lectura
del archivo vive en app/ocr/lector.py.

Campos y como se validan
------------------------
    numero de documento  doc_number.py     patron serie-numero, tolerante a
                                           confusiones del OCR
    RUC del emisor       ruc.py            digito verificador modulo 11 +
                                           vecindad (emisor vs cliente)
    importes             montos.py         tres lecturas cruzadas: etiqueta,
                                           monto en letras y suma de partes
    fecha de emision     aca               formato + rango razonable
    razon social         aca               linea con forma juridica (S.A.C.,
                                           E.I.R.L., ...)
    direccion            aca               linea de via publica del emisor,
                                           descartando la del cliente
    tipo de documento    aca               titulo + coherencia con la letra
                                           de la serie

Se mantiene `DataExtractor.extract_data(texto)` con la misma firma y las
mismas claves de siempre para no romper a quien ya lo llama; ademas devuelve
claves nuevas (issuerName, currency, igvRate, detalle) que la vista puede
aprovechar cuando quiera, sin obligarla a cambiar.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    from .doc_number import parse_nro_comprobante
    from .ruc import ruc_cliente, ruc_emisor
    from .montos import extraer_montos
except ImportError:                                   # ejecucion suelta
    from doc_number import parse_nro_comprobante
    from ruc import ruc_cliente, ruc_emisor
    from montos import extraer_montos

#: Formas juridicas que delatan la razon social del emisor. Va como regex con
#: limites de palabra a proposito: buscar "SA" como subcadena hacia match
#: dentro de "SANTA CONSTANZA" y devolvia la direccion como razon social.
RE_FORMA_JURIDICA = re.compile(
    r"\b("
    r"S\.?\s?A\.?\s?C\.?|S\.?\s?A\.?\s?A\.?|S\.?\s?A\.?|"
    r"E\.?\s?I\.?\s?R\.?\s?L\.?|S\.?\s?R\.?\s?L\.?|S\.?\s?C\.?R\.?L\.?|"
    r"SOCIEDAD\s+ANONIMA(?:\s+CERRADA|\s+ABIERTA)?|"
    r"SOCIEDAD\s+COMERCIAL\s+DE\s+RESPONSABILIDAD\s+LIMITADA|"
    r"EMPRESA\s+INDIVIDUAL\s+DE\s+RESPONSABILIDAD\s+LIMITADA|"
    r"ASOCIACION|COOPERATIVA|FUNDACION"
    r")\b")

#: Prefijos de via publica peruana.
VIAS = (
    "AV", "AVENIDA", "JR", "JIRON", "CALLE", "CAL", "PSJ", "PASAJE", "MZ",
    "URB", "CARRETERA", "CAR", "PROLONGACION", "PROL", "ALAMEDA", "AL",
    "PLAZA", "PZA", "OVALO", "PARQUE",
)

#: Titulos de documento y el tipo que representan.
TITULOS = (
    ("NOTA DE CREDITO", "NOTA DE CREDITO"),
    ("NOTA DE DEBITO", "NOTA DE DEBITO"),
    ("BOLETA DE VENTA", "BOLETA"),
    ("BOLETA ELECTRONICA", "BOLETA"),
    ("BOLETA", "BOLETA"),
    ("FACTURA ELECTRONICA", "FACTURA"),
    ("FACTURA", "FACTURA"),
    ("RECIBO POR HONORARIOS", "RECIBO POR HONORARIOS"),
    ("TICKET", "TICKET"),
)

#: Letra de serie que corresponde a cada tipo.
LETRA_ESPERADA = {
    "FACTURA": ("F", "E"),
    "BOLETA": ("B", "E"),
    "NOTA DE CREDITO": ("F", "B", "E"),
    "NOTA DE DEBITO": ("F", "B", "E"),
    "RECIBO POR HONORARIOS": ("E", "R"),
}

#: Cuantos anios hacia atras se acepta una fecha de emision.
ANIOS_ATRAS = 6


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t or "")
                   if not unicodedata.combining(c))


def normalizar(t: str) -> str:
    return _sin_tildes(t).upper()


class DataExtractor:
    """Extrae los campos del comprobante a partir del texto."""

    # ------------------------------------------------------------ publico
    def extract_data(self, text: str, ruc_consultante: Optional[str] = None) -> Dict[str, Any]:
        """
        Devuelve el diccionario de campos. Mantiene las claves historicas
        (documentType, documentNumber, documentDate, issuerRuc, issuerAddress,
        amount) y agrega las nuevas.
        """
        if not text:
            return {}

        tipo = self._tipo_documento(text)
        doc = parse_nro_comprobante(text, tipo)
        nro = f"{doc.serie}-{doc.numero}" if doc.ok else None

        emisor = ruc_emisor(text, nro, ruc_consultante)
        cliente = ruc_cliente(text, nro)
        montos = extraer_montos(text)
        fecha = self._fecha_emision(text)
        razon = self._razon_social(text)
        direccion = self._direccion(text)

        tipo = self._afinar_tipo(tipo, doc.serie)

        advertencias: List[str] = []
        advertencias += doc.advertencias
        advertencias += montos.advertencias
        if not emisor:
            advertencias.append("no se pudo leer el RUC del emisor")
        if not nro:
            advertencias.append("no se pudo leer la serie y numero")
        if not fecha:
            advertencias.append("no se pudo leer la fecha de emision")

        return {
            # --- claves historicas (no cambiar: las consume la vista) ---
            "documentType": tipo,
            "documentNumber": nro,
            "documentDate": fecha,
            "issuerRuc": emisor,
            "issuerAddress": direccion,
            "amount": montos.total if montos.total is not None else 0.0,

            # --- claves nuevas, aditivas ---
            "issuerName": razon,
            "clientRuc": cliente,
            "currency": montos.moneda,
            "subtotal": montos.gravado,
            "igv": montos.igv,
            "igvRate": montos.tasa_igv,
            "detalle": {
                "numero": doc.to_dict(),
                "montos": {
                    "origen": montos.origen,
                    "confianza": montos.confianza,
                    "enLetras": montos.en_letras,
                },
                "advertencias": advertencias,
            },
        }

    def campos_criticos_completos(self, text: str) -> bool:
        """
        True si el texto ya alcanza para llenar la vista y validar en SUNAT:
        serie-numero, RUC del emisor e importe. Lo usa el lector para decidir
        si vale la pena otra pasada de OCR.
        """
        if not text:
            return False
        d = self.extract_data(text)
        return bool(d.get("documentNumber")) and bool(d.get("issuerRuc")) \
            and float(d.get("amount") or 0) > 0

    # ------------------------------------------------------------ campos
    @staticmethod
    def _tipo_documento(text: str) -> str:
        t = normalizar(text)
        # el OCR a veces separa las letras: "F A C T U R A"
        t_compacto = re.sub(r"(?<=\b[A-Z]) (?=[A-Z]\b)", "", t)
        for titulo, tipo in TITULOS:
            if titulo in t or titulo in t_compacto:
                return tipo
        return "TIPO DESCONOCIDO"

    @staticmethod
    def _afinar_tipo(tipo: str, serie: str) -> str:
        """
        Si el titulo no se leyo pero la serie si, la letra lo delata:
        F = factura, B = boleta. No pisa un titulo que si se leyo.
        """
        if tipo != "TIPO DESCONOCIDO" or not serie:
            return tipo
        letra = serie[0]
        if letra == "F":
            return "FACTURA"
        if letra == "B":
            return "BOLETA"
        return tipo

    @staticmethod
    def _fecha_emision(text: str) -> Optional[str]:
        """
        Fecha de emision en ISO. Prefiere la que esta etiquetada; descarta
        fechas imposibles (futuras o de hace mas de ANIOS_ATRAS anios), que es
        como se cuela el OCR leyendo mal un digito.
        """
        t = normalizar(text)
        hoy = date.today()
        limite_viejo = hoy - timedelta(days=365 * ANIOS_ATRAS)
        limite_futuro = hoy + timedelta(days=2)      # margen por zona horaria

        def valida(d: date) -> bool:
            return limite_viejo <= d <= limite_futuro

        etiquetadas = re.findall(
            r"FECHA\s*(?:DE\s*)?(?:EMISION|EMISI0N)?\s*[:\.]?\s*"
            r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2,4})", t)

        sueltas = re.findall(r"\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})\b", t)
        iso = re.findall(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)

        for d_, m_, y_ in etiquetadas + sueltas:
            try:
                anio = int(y_)
                if anio < 100:
                    anio += 2000
                f = date(anio, int(m_), int(d_))
                if valida(f):
                    return f.isoformat()
            except ValueError:
                continue

        for y_, m_, d_ in iso:
            try:
                f = date(int(y_), int(m_), int(d_))
                if valida(f):
                    return f.isoformat()
            except ValueError:
                continue

        return None

    @staticmethod
    def _razon_social(text: str) -> Optional[str]:
        """
        Razon social del emisor: la primera linea con forma juridica que no
        sea la del cliente. Sirve para pre-llenar el campo Proveedor.
        """
        lineas = [l.strip() for l in (text or "").splitlines() if l.strip()]
        corte = len(lineas)

        for i, l in enumerate(lineas):
            if re.search(r"SE[NÑ]OR|CLIENTE|ADQUIRIENTE", normalizar(l)):
                corte = i
                break

        patron_via = re.compile(
            r"^\s*(?:" + "|".join(VIAS) + r")\b[\. ]", re.IGNORECASE)

        def es_direccion(linea: str) -> bool:
            return bool(patron_via.match(_sin_tildes(linea)))

        for l in lineas[:corte]:
            u = normalizar(l)
            if es_direccion(l):
                continue
            if RE_FORMA_JURIDICA.search(u) and len(l) > 6:
                return re.sub(r"\s{2,}", " ", l).strip(" .:-")

        # sin forma juridica: la primera linea con pinta de nombre propio
        for l in lineas[:corte]:
            u = normalizar(l)
            if es_direccion(l):
                continue
            if len(l) > 6 and not re.search(r"\d{6,}|RUC|FACTURA|BOLETA", u):
                return re.sub(r"\s{2,}", " ", l).strip(" .:-")
        return None

    @staticmethod
    def _direccion(text: str) -> Optional[str]:
        """
        Direccion del EMISOR. Se descarta explicitamente la del cliente, que
        en el layout suele quedar cerca y era una fuente de confusion.
        """
        lineas = [l.strip() for l in (text or "").splitlines() if l.strip()]

        corte = len(lineas)
        for i, l in enumerate(lineas):
            if re.search(r"DIRECCION\s+DEL\s+CLIENTE|SE[NÑ]OR|ADQUIRIENTE",
                         normalizar(l)):
                corte = i
                break

        patron_via = re.compile(
            r"^\s*(?:" + "|".join(VIAS) + r")\b[\. ]", re.IGNORECASE)

        for l in lineas[:corte]:
            if patron_via.match(_sin_tildes(l)):
                return re.sub(r"\s{2,}", " ", l).strip(" .:-")

        # respaldo: cualquier linea con via publica en todo el documento
        for l in lineas:
            if patron_via.match(_sin_tildes(l)):
                return re.sub(r"\s{2,}", " ", l).strip(" .:-")
        return None

    # --------------------------------------------------- compatibilidad
    @staticmethod
    def extraer_nro_comprobante_detallado(text: str, tipo_doc: str = None) -> dict:
        """Detalle completo del parseo de serie-numero, para depurar."""
        return parse_nro_comprobante(text, tipo_doc).to_dict()
