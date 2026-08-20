import re
from datetime import date, datetime, timedelta

# Modulos de campo, cada uno con su propia validacion. Se agregaron sin tocar
# el resto del extractor: los metodos historicos siguen existiendo y solo
# delegan, asi que el contrato con main.py y con la vista no cambia.
try:
    from .doc_number import parse_nro_comprobante
    from .ruc import buscar_rucs
    from .montos import extraer_montos
except ImportError:                                   # ejecucion suelta
    from doc_number import parse_nro_comprobante
    from ruc import buscar_rucs
    from montos import extraer_montos


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
            "igv": self._extract_igv(text),

            # --- aditivos: la vista los usa si quiere, nadie se rompe si no ---
            "igvRate": self._montos(text).tasa_igv,
            "subtotal": self._montos(text).gravado,
            "detalle": self._detalle(text),
        }

    # ------------------------------------------------------------------
    # Apoyo
    # ------------------------------------------------------------------
    _cache_montos = None
    _cache_texto = None

    def _montos(self, text: str):
        """Los importes se calculan una sola vez por texto."""
        if DataExtractor._cache_texto is not text:
            DataExtractor._cache_texto = text
            DataExtractor._cache_montos = extraer_montos(text)
        return DataExtractor._cache_montos

    def _detalle(self, text: str) -> dict:
        """Trazabilidad: de donde salio cada dato y que no cuadro."""
        m = self._montos(text)
        doc = parse_nro_comprobante(text, self._determine_type(text))
        return {
            "numero": doc.to_dict(),
            "montos": {
                "origen": m.origen,
                "confianza": m.confianza,
                "enLetras": m.en_letras,
            },
            "advertencias": list(doc.advertencias) + list(m.advertencias),
        }

    def campos_criticos_completos(self, text: str) -> bool:
        """
        True si el texto ya alcanza para llenar la vista: numero, RUC del
        emisor e importe. Lo usa el lector para decidir si vale otra pasada
        de OCR o ya puede cortar.
        """
        if not text:
            return False
        rucs = self._extract_all_rucs(text)
        return bool(self._extract_doc_number(text)) and bool(rucs) \
            and float(self._extract_amount(text) or 0) > 0

    def _extract_igv(self, text: str) -> float:
        """IGV del documento. montos.py ademas deduce la TASA (18% general,
        10.5% de restaurantes y hoteles) en vez de asumirla."""
        montos = self._montos(text)
        if montos.igv is not None:
            return montos.igv
        return self._extract_igv_legacy(text)

    @staticmethod
    def _extract_igv_legacy(text: str) -> float:
        pattern = r"I\.?\s*G\.?\s*V\.?[:\s]*[S/.$]*\s*([\d,]+\.\d{2})"

        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            value_str = match.group(1).replace(',', '')
            return float(value_str)

        return 0.0

    @staticmethod
    def _determine_type(text: str) -> str:
        text = re.sub(r'\S+@\S+', '', text)

        text = re.sub(r'WWW\.\S+|HTTP\S+', '', text, flags=re.IGNORECASE)

        t = text.upper()

        if "NOTA DE CREDITO" in t or "NOTA" in t or "N O T A" in t:
            return "N"

        if "RECIBO POR HONORARIOS" in t or "RECIBO" in t or "R E C I B O" in t:
            return "R"

        if "BOLETA DE VENTA" in t or "BOLETA" in t or "B O L E T A" in t:
            return "B"

        if "FACTURA ELECTRONICA" in t or "FACTURA" in t or "F A C T U R A" in t:
            return "F"

        return "X"

    @staticmethod
    def _extract_all_rucs(text: str) -> list[str]:
        """
        RUC del documento, validados con digito verificador y ORDENADOS: el
        del emisor primero.

        El orden importa porque la vista hace `this.ruc = issuerRuc[0]`. Antes
        se devolvian en el orden en que aparecen en el texto, y en una factura
        el primero es el del CLIENTE (va debajo de "Senor(es)"), asi que el
        formulario se llenaba con el RUC de la propia empresa. Ese es el bug
        que hacia fallar la validacion en SUNAT.

        La clasificacion emisor/cliente esta en ruc.py y se decide por
        vecindad: el RUC del emisor comparte caja con el titulo del
        comprobante y con la serie-numero.
        """
        if not text:
            return []

        nro = DataExtractor._extract_doc_number(text)
        encontrados = [r for r in buscar_rucs(text, nro) if r.valido]

        emisores = [r.ruc for r in encontrados if r.lado != "cliente"]
        clientes = [r.ruc for r in encontrados if r.lado == "cliente"]

        ordenados = []
        for ruc in emisores + clientes:
            if ruc not in ordenados:
                ordenados.append(ruc)
        return ordenados

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
        """
        Serie y numero. Delega en doc_number.py, que tolera separadores raros,
        etiquetas N/Nro, serie pegada al numero, saltos de linea y las
        confusiones del OCR (O/0, I/1, S/5), y descarta RUC, fechas e
        importes. La normalizacion anterior reemplazaba O->0 e I->1 en TODO el
        texto, lo que rompia palabras y series legitimas como EB01.
        """
        if not text:
            return None
        r = parse_nro_comprobante(text)
        return f"{r.serie}-{r.numero}" if r.ok else None

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
        """
        Fecha de emision en ISO.

        Acepta anio de 4 y de 2 digitos: los tickets de caja imprimen
        "25/06/26" y con el patron anterior, que exigia cuatro digitos, la
        fecha salia vacia. Se descartan fechas imposibles —futuras o de hace
        mas de seis anios—, que es como se cuela una mala lectura del OCR.
        """
        if not text:
            return None

        hoy = date.today()
        mas_viejo = hoy - timedelta(days=365 * 6)
        mas_nuevo = hoy + timedelta(days=2)      # margen por zona horaria

        def valida(f: date) -> bool:
            return mas_viejo <= f <= mas_nuevo

        candidatas: list[date] = []

        # dd/mm/aaaa y dd/mm/aa (tambien con - o .)
        for d_, m_, y_ in re.findall(
                r'\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2,4})\b', text):
            try:
                anio = int(y_)
                if anio < 100:
                    anio += 2000
                f = date(anio, int(m_), int(d_))
                if valida(f):
                    candidatas.append(f)
            except ValueError:
                continue

        # aaaa-mm-dd
        for y_, m_, d_ in re.findall(r'\b(\d{4})-(\d{2})-(\d{2})\b', text):
            try:
                f = date(int(y_), int(m_), int(d_))
                if valida(f):
                    candidatas.append(f)
            except ValueError:
                continue

        if not candidatas:
            return None

        # La fecha etiquetada manda; si no hay etiqueta, la primera valida.
        etiquetada = re.search(
            r'FECHA\s*(?:DE\s*)?EMISION\s*[:\.]?\s*(\d{1,2})\s*[/\-.]\s*'
            r'(\d{1,2})\s*[/\-.]\s*(\d{2,4})', text, re.IGNORECASE)
        if etiquetada:
            try:
                anio = int(etiquetada.group(3))
                if anio < 100:
                    anio += 2000
                f = date(anio, int(etiquetada.group(2)), int(etiquetada.group(1)))
                if valida(f):
                    return f.isoformat()
            except ValueError:
                pass

        return candidatas[0].isoformat()

    @staticmethod
    def _extract_address(text: str) -> str | None:
        """
        Direccion del EMISOR.

        Se corta el texto en cuanto aparece el bloque del cliente
        ("Direccion del Cliente", "Senor(es)"), porque en el layout de una
        factura las dos direcciones quedan a pocas lineas de distancia y la
        version anterior devolvia la del cliente, o un pedazo suelto de la
        tabla de items.
        """
        if not text:
            return None

        lineas = [l.strip() for l in text.splitlines() if l.strip()]

        corte = len(lineas)
        for i, l in enumerate(lineas):
            u = DataExtractor._sin_tildes(l).upper()
            if re.search(r"DIRECCION\s+DEL\s+CLIENTE|SE[NN]OR|ADQUIRIENTE|CANTIDAD\s+UNIDAD", u):
                corte = i
                break

        vias = ("AV", "AVENIDA", "JR", "JIRON", "CALLE", "CAL", "PSJ", "PASAJE",
                "MZ", "URB", "CARRETERA", "CAR", "PROLONGACION", "PROL",
                "ALAMEDA", "PLAZA", "PZA", "OVALO", "PARQUE")
        patron = re.compile(r"^\s*(?:" + "|".join(vias) + r")\b[\. ]", re.IGNORECASE)

        for l in lineas[:corte]:
            if patron.match(DataExtractor._sin_tildes(l)):
                return re.sub(r"\s{2,}", " ", l).strip(" .:-")
        return None

    @staticmethod
    def _sin_tildes(s: str) -> str:
        import unicodedata
        return "".join(c for c in unicodedata.normalize("NFKD", s or "")
                       if not unicodedata.combining(c))

    def _extract_amount(self, text: str) -> float:
        """
        Importe total. Delega en montos.py, que cruza tres lecturas
        independientes —la etiquetada, el monto en letras y la suma de
        componentes— y se queda con la que coincide con otra. El monto en
        letras rescata el importe cuando la columna de cifras se pierde en el
        OCR, que era el caso que devolvia 0.0.
        """
        montos = self._montos(text)
        if montos.total:
            return montos.total
        return self._extract_amount_legacy(text)

    def _extract_amount_legacy(self, text: str) -> float:
        """Busqueda anterior, como ultimo respaldo."""

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