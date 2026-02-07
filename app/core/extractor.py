import re
from datetime import datetime


class DataExtractor:

    def extract_data(self, text: str) -> dict:

        if not text:
            return {}

        return {
            "documentType": self._determine_type(text),
            "documentNumber": self._extract_doc_number(text),
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
    def _extract_doc_number(text: str) -> str:

        m = re.search(
            r'\b([FBE]\d{3})\s*(?:N[°ºo]?\.?|NRO\.?)\s*([0-9]{4,10})\b',
            text,
            re.IGNORECASE
        )

        if m:
            return f"{m.group(1)}-{m.group(2)}"

        m = re.search(r'\b([FBE]\d{3})[-\s]+([0-9]{4,10})\b', text)
        if m:
            return f"{m.group(1)}-{m.group(2)}"

        return None

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
