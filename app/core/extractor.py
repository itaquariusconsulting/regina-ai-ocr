import re
from datetime import datetime


class DataExtractor:
    @staticmethod
    def _extract_items(text: str) -> list[dict]:

        if not text:
            return []

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        print("Lineas : ", lines)

        items = []
        in_table = False

        header_re = re.compile(
            r'(CANT|UND|CODIGO|COD|DESCRIP|DETALLE|ITEM|PRECIO|UNITARIO|VALOR|TOTAL).*(CANT|UND|CODIGO|COD|DESCRIP|DETALLE|ITEM|PRECIO|UNITARIO|VALOR|TOTAL)',
            re.IGNORECASE
        )

        stop_re = re.compile(
            r'\b(SUBTOTAL|TOTAL|IGV|IMPORTE|SON:)\b',
            re.IGNORECASE
        )

        # patrón original
        row_re = re.compile(
            r'(\d+(?:[.,]\d+)?)\s+([\d.,]+)\s+([\d.,]+)$',
            re.IGNORECASE
        )

        # patrón flexible OCR
        fallback_re = re.compile(
            r'(.+?)\s+(\d+(?:[.,]\d+)?)\s+(\d+(?:[.,]\d+)?)$'
        )

        for line in lines:

            line = line.replace("|", " ")
            line = line.replace("$", "")
            line = line.replace("S/", "")
            line = re.sub(r'\s{2,}', ' ', line).strip()

            up = line.upper()

            if not in_table:
                if header_re.search(up):
                    in_table = True
                continue

            if stop_re.search(up):
                break

            m = row_re.match(line)

            if m:

                cantidad = m.group(1)
                precio = m.group(2)
                total = m.group(3)

                descripcion = ""
                if items:
                    descripcion = items[-1]["Descripción"]
                precio = m.group(5)
                total = m.group(6)

                items.append({
                    "Cantidad": float(cantidad.replace(",", "")),
                    "Unidad": "",
                    "Código": "",
                    "Descripción": descripcion,
                    "Precio Unitario": float(precio.replace(",", "")),
                    "Valor": float(total.replace(",", ""))
                })

                continue

            # fallback OCR
            m2 = fallback_re.match(line)

            if m2:

                left = m2.group(1)
                precio = m2.group(2)
                total = m2.group(3)

                tokens = left.split()

                cantidad = 1
                unidad = ""
                codigo = ""
                descripcion = left

                for t in tokens:
                    if re.match(r'^\d+(?:[.,]\d+)?$', t):
                        cantidad = t
                        break

                for t in tokens:
                    if re.match(r'^[A-Z]{2,5}$', t):
                        unidad = t
                        break

                for t in tokens:
                    if re.match(r'^\d{3,}$', t):
                        codigo = t
                        break

                items.append({
                    "Cantidad": float(str(cantidad).replace(",", ".")),
                    "Unidad": unidad,
                    "Código": codigo,
                    "Descripción": descripcion.strip(),
                    "Precio Unitario": float(precio.replace(",", ".")),
                    "Valor": float(total.replace(",", "."))
                })

        return items

    def extract_data(self, text: str) -> dict:
        if not text:
            return {}
        return {
            "documentType": self._determine_type(text),
            "documentNumber": self._extract_doc_number(text),
            "documentCurrency": self._extract_currency(text),
            "documentDate": self._extract_date(text),
            "issuerRuc": self._extract_all_rucs(text),
            "issuerName": self._extract_issuer_name(text),
            "issuerAddress": self._extract_address(text),
            "amount": self._extract_amount(text),
            "items": self._extract_items(text),
            "igv": self._extract_igv(text)
        }

    @staticmethod
    def _extract_igv(text: str) -> float:
        pattern = r"I\.?\s*G\.?\s*V\.?[:\s]*[S/.$]*\s*([\d,]+\.\d{2})"

        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            value_str = match.group(1).replace(',', '')
            return float(value_str)

        return 0.0

    @staticmethod
    def _determine_type(text: str) -> str:

        t = text.upper()

        if "FACTURA" in t or "F A C T U R A" in t:
            return "FACTURA"

        if "BOLETA" in t or "B O L E T A" in t:
            return "BOLETA"

        if "NOTA DE CRÉDITO" in t or "N O T A   D E   C R É D I T O" in t:
            return "NOTA DE CRÉDITO"
        
        if "RECIBO" in t or "R E C I B O" in t:
            return "RECIBO"

        return "TIPO DESCONOCIDO"

    @staticmethod
    def _extract_all_rucs(text: str) -> list[str]:
        if not text:
            return []

        text_clean = text.upper()
        text_clean = text_clean.replace("O", "0").replace("I", "1").replace("S", "5")

        raw_matches = re.findall(r'(?:\d[\s\.-]?){11,}', text_clean)

        rucs = []
        seen = set()

        for m in raw_matches:

            digits = re.sub(r'\D', '', m)

            if len(digits) >= 11:

                candidate = digits[:11]

                if candidate not in seen and DataExtractor._is_valid_ruc(candidate):
                    seen.add(candidate)
                    rucs.append(candidate)

        return rucs

    @staticmethod
    def _is_valid_ruc(ruc: str) -> bool:
        if not ruc or not ruc.isdigit() or len(ruc) != 11:
            return False

        #valid_prefixes = ("10", "15", "16", "17", "20")
        #if ruc[:2] not in valid_prefixes:
        #    return False

        factores = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
        suma = sum(int(ruc[i]) * factores[i] for i in range(10))
        resto = suma % 11
        dig = 11 - resto

        if dig == 10:
            dig = 0
        elif dig == 11:
            dig = 1

        return dig == int(ruc[10])

    @staticmethod
    def _extract_issuer_name(text: str) -> str | None:
        if not text:
            return None

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        top_lines = lines[:12]

        junk_patterns = [
            r'(?i)FACTURA\s*ELECTR[OÓ]NICA',
            r'(?i)BOLETA\s*ELECTR[OÓ]NICA',
            r'(?i)RUC\s*[:\-]?\s*\d+',
            r'(?i)TEL[EÉ]F[OÓ]NO.*',
            r'(?i)P[AÁ]GINA\s*\d+.*'
        ]

        stop_keywords = ("SEÑOR", "CLIENTE", "DIRECCIÓN", "DOMICILIO")

        for line in top_lines:
            up = line.upper()

            if any(k in up for k in stop_keywords):
                break

            current_candidate = line
            for pattern in junk_patterns:
                current_candidate = re.sub(pattern, '', current_candidate).strip()

            if len(current_candidate) > 4:
                if not re.search(r'(?i)\b(AV|JR|CALLE|URB|MZ|LT)\b', current_candidate):
                    return current_candidate.strip()

        return None

    @staticmethod
    def _extract_doc_number(text: str) -> str | None:
        if not text:
            return None

        # Normalizar texto para OCR defectuoso
        clean = text.upper()
        clean = clean.replace("O", "0")
        clean = clean.replace("I", "1")
        clean = clean.replace("S", "5")

        # Eliminar caracteres raros pero mantener separadores útiles
        clean = re.sub(r'[^\w\s\-°º.]', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean)

        # Lista de patrones (de más específico a más flexible)
        patterns = [
            # Formato: F001 N° 000123
            r'\b([FBE]\d{3})\s*(?:N[°ºO]?\.?|NRO\.?)\s*[-]?\s*(\d{1,10})\b',

            # Formato: F001-000123 o E001 - 137
            r'\b([FBE]\d{3})\s*[-]\s*(\d{1,10})\b',

            # Formato: F001 000123
            r'\b([FBE]\d{3})\s+(\d{1,10})\b',

            # Formato ultra flexible OCR: F001000123
            r'\b([FBE]\d{3})(\d{1,10})\b',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, clean, re.IGNORECASE)

            if matches:
                # Tomar el match más consistente (último suele ser el correcto)
                serie, numero = matches[-1]

                # Normalizar número (quitar ceros innecesarios a la izquierda)
                numero = str(int(numero))

                return f"{serie}-{numero}"

    @staticmethod
    def _extract_currency(text: str) -> str | None:

        if not text:
            return None

        if re.search(r'\b(s/|soles?)\b', text, re.IGNORECASE):
            return "PEN"

        if re.search(r'\b(us\$|u\$|d[oó]lares?(?:\s+americanos?)?)\b', text, re.IGNORECASE):
            return "USD"

        return None

    @staticmethod
    def _extract_date(text: str) -> str | None:

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

    @staticmethod
    def _extract_address(text: str) -> str | None:

        if not text:
            return None

        upper = text.upper()

        m = re.search(
            r'([A-ZÁÉÍÓÚÑ0-9 .\-]{3,}\s+\d{1,5}\s*'
            r'(?:INT\.?|DPTO\.?|DEP\.?|OF\.?)?\s*\d*\s*-\s*'
            r'URB\.?\s*[A-ZÁÉÍÓÚÑ0-9 .\-]{3,}\s*-\s*'
            r'[A-ZÁÉÍÓÚÑ ]{3,})',
            upper
        )

        if m:
            return m.group(1).title().strip()

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        capture = False

        for line in lines:

            up = line.upper()

            if "DIRECCION" in up or "DIRECCIÓN" in up:
                capture = True
                continue

            if capture:
                if re.search(r'\b(RUC|FECHA|SEÑOR|CLIENTE|TOTAL|MONEDA)\b', up):
                    break

                return line.strip()

        m = re.search(
            r'\b(JR\.?|AV\.?|CALLE|PASAJE|PSJ\.?)\s+[A-ZÁÉÍÓÚÑ0-9 .\-]{6,}',
            upper
        )

        if m:
            return m.group(0).title().strip()

        return None

    def _extract_amount(self, text: str) -> float:

        m = re.search(r'IMPORTE\s*TOTAL([\s\S]{0,40})', text, re.IGNORECASE)

        if m:
            block = m.group(1)
            n = re.search(r'([\d]{1,3}(?:[.,][\d]{3})*(?:[.,]\d{2})?)', block)
            if n:
                return self._normalize_float(n.group(1))

        m = re.search(r'TOTAL\s+A\s+PAGAR([\s\S]{0,40})', text, re.IGNORECASE)

        if m:
            block = m.group(1)
            n = re.search(r'([\d]{1,3}(?:[.,][\d]{3})*(?:[.,]\d{2})?)', block)
            if n:
                return self._normalize_float(n.group(1))

        return 0.0

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