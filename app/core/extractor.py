import re
from datetime import datetime

try:                                    # import normal dentro del paquete
    from .doc_number import parse_nro_comprobante
except ImportError:                     # si se ejecuta el archivo suelto
    from doc_number import parse_nro_comprobante


class DataExtractor:

    def extract_data(self, text: str) -> dict:

        if not text:
            return {}

        tipo = self._determine_type(text)

        return {
            "documentType": tipo,
            "documentNumber": self._extract_doc_number(text, tipo),
            "documentDate": self._extract_date(text),
            "issuerRuc": self._extract_issuer_ruc(text),
            "issuerAddress": self._extract_address(text),
            "amount": self._extract_amount(text)
        }

    # -------------------------------------------------
    # Tipo de documento
    # -------------------------------------------------
    @staticmethod
    def _determine_type(text: str) -> str:

        t = text.upper()

        if "FACTURA" in t or "F A C T U R A" in t:
            return "FACTURA"

        if "BOLETA" in t or "B O L E T A" in t:
            return "BOLETA"

        if "NOTA DE CRÉDITO" in t or "N O T A   D E   C R É D I T O" in t:
            return "NOTA DE CRÉDITO"

        return "TIPO DESCONOCIDO"

    # -------------------------------------------------
    # RUC emisor
    # -------------------------------------------------
    @staticmethod
    def _extract_issuer_ruc(text: str) -> str:

        header = text[:1500]

        rucs = re.findall(
            r'(?:RUC|R\.U\.C\.?)\s*[:\-]?\s*(\d{11})',
            header,
            re.IGNORECASE
        )

        if rucs:
            return rucs[0]

        loose = re.search(r'\b(10|20)\d{9}\b', header)
        if loose:
            return loose.group(0)

        return None

    # -------------------------------------------------
    # Número de documento
    # -------------------------------------------------
    @staticmethod
    def _extract_doc_number(text: str, tipo_doc: str = None) -> str:
        """
        Devuelve "SERIE-NUMERO" (p.ej. "F002-11092") o None.

        Toda la casuistica vive en `doc_number.parse_nro_comprobante`:
        separadores raros, etiquetas N°/Nro/NUMERO, serie pegada al numero,
        saltos de linea, ceros a la izquierda, confusiones del OCR (O/0, I/1,
        S/5, B/8) y descarte de RUC, fechas e importes.
        """
        resultado = parse_nro_comprobante(text, tipo_doc)
        return f"{resultado.serie}-{resultado.numero}" if resultado.ok else None

    @staticmethod
    def extraer_nro_comprobante_detallado(text: str, tipo_doc: str = None) -> dict:
        """
        Igual que `_extract_doc_number` pero devuelve el detalle completo
        (confianza, patron que lo encontro, advertencias). Util para depurar
        por que un comprobante no se leyo bien, sin volver a pasar el OCR.
        """
        return parse_nro_comprobante(text, tipo_doc).to_dict()

    # -------------------------------------------------
    # Fecha
    # -------------------------------------------------
    @staticmethod
    def _extract_date(text: str) -> str:

        m = re.search(r'\b(\d{2})[/-](\d{2})[/-](\d{4})\b', text)
        if m:
            d, mth, y = m.groups()
            try:
                return datetime(int(y), int(mth), int(d)).date().isoformat()
            except:
                pass

        m = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', text)
        if m:
            try:
                return datetime.strptime(m.group(0), "%Y-%m-%d").date().isoformat()
            except:
                pass

        return None

    # -------------------------------------------------
    # Dirección del emisor
    # -------------------------------------------------
    @staticmethod
    def _extract_address(text: str) -> str:

        lines = [l.strip() for l in text.splitlines() if l.strip()]

        capture = False

        for line in lines:
            up = line.upper()

            # acepta DIRECCION sin tilde y con errores OCR
            if re.search(r'\bDIREC+I+O+N\b', up) or "DIRECCION" in up:
                capture = True
                continue

            if capture:
                # corta cuando empieza otro campo
                if re.search(r'\b(RUC|FECHA|SEÑOR|CLIENTE|TIPO|GUIA|MONEDA)\b', up):
                    break

                # devuelve directamente la siguiente línea útil
                return line.strip()

        # fallback
        m = re.search(
            r'\b(JR\.?|JR|AV\.?|AV|CALLE|PSJ\.?|PASAJE)\s+[A-Z0-9 .\-]{6,}',
            text.upper()
        )

        if m:
            return m.group(0).strip()

        return None


    # -------------------------------------------------
    # Importe total
    # -------------------------------------------------
    def _extract_amount(self, text: str) -> float:

        # primero buscamos el bloque donde aparece "importe total"
        m = re.search(
            r'IMPORTE\s*TOTAL([\s\S]{0,40})',
            text,
            re.IGNORECASE
        )

        if m:
            block = m.group(1)

            n = re.search(r'([\d]{1,3}(?:[.,][\d]{3})*(?:[.,]\d{2})?)', block)
            if n:
                return self._normalize_float(n.group(1))

        # respaldo
        m = re.search(
            r'TOTAL\s+A\s+PAGAR([\s\S]{0,40})',
            text,
            re.IGNORECASE
        )

        if m:
            block = m.group(1)
            n = re.search(r'([\d]{1,3}(?:[.,][\d]{3})*(?:[.,]\d{2})?)', block)
            if n:
                return self._normalize_float(n.group(1))

        return 0.0


    # -------------------------------------------------
    # Normalización
    # -------------------------------------------------
    @staticmethod
    def _normalize_float(value: str) -> float:

        if not value:
            return 0.0

        clean = value.strip()
        clean = clean.replace("S/", "")
        clean = clean.replace("S/.", "")
        clean = clean.replace(" ", "")

        if "," in clean and "." in clean:
            if clean.find(",") < clean.find("."):
                clean = clean.replace(",", "")
            else:
                clean = clean.replace(".", "").replace(",", ".")
        elif "," in clean:
            clean = clean.replace(",", ".")

        try:
            return float(clean)
        except:
            return 0.0
