"""
Extraccion de datos de comprobantes de MOVILIDAD.

Criterio de diseno: lo mas abierto posible. No asume ningun formato ni idioma.

  - Etiquetas en espanol e ingles, con muchos sinonimos.
  - Tolera errores tipicos del OCR (O/0, I/1/L, S/5, E/3, A/4).
  - Trabaja por BLOQUES: la etiqueta puede traer el valor en la misma linea o
    en las siguientes (formato tipico de recibos de apps de taxi).
  - Cuando no hay etiqueta, cae a patrones posicionales: placas, horas
    sueltas, "de X a Y".

Ningun metodo lanza excepcion. Un comprobante ilegible produce un diccionario
con todo en None, nunca un error.
"""

import re
import unicodedata


# ---------------------------------------------------------------------------
# Normalizacion
# ---------------------------------------------------------------------------

def _sin_tildes(s: str) -> str:
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm(s: str) -> str:
    return _sin_tildes(s or "").upper()


# Confusiones frecuentes del OCR, aplicadas al construir el patron de etiqueta.
_CONFUSIONES = {
    "O": "[O0Q]", "I": "[I1L|]", "L": "[LI1]", "S": "[S5$]", "E": "[E3]",
    "A": "[A4@]", "B": "[B8]", "G": "[G6]", "Z": "[Z2]", "T": "[T7]",
}


def _patron_etiqueta(etiqueta: str) -> str:
    """'HORA SALIDA' -> patron tolerante a espacios, puntuacion y OCR."""
    partes = []
    for palabra in _norm(etiqueta).split():
        chars = []
        for ch in palabra:
            if ch in _CONFUSIONES:
                chars.append(_CONFUSIONES[ch])
            elif ch.isalnum():
                chars.append(re.escape(ch))
            else:
                chars.append(r"\W?")
        partes.append("".join(chars))
    return r"[\s\.\-_']*".join(partes)


_TODAS_LAS_ETIQUETAS = []


def _reg(etiquetas):
    _TODAS_LAS_ETIQUETAS.extend(etiquetas)
    return etiquetas


ET_CHOFER = _reg([
    "driver's name", "drivers name", "driver name", "driver",
    "chofer", "conductor", "taxista", "piloto", "motorista", "operador",
    "nombre del chofer", "nombre del conductor", "sr chofer",
    "atendido por", "brindado por", "prestador", "transportista",
])

ET_VEHICULO = _reg([
    "car details", "vehicle details", "car model", "vehicle", "car",
    "placa", "nro placa", "numero de placa", "n de placa",
    "vehiculo", "unidad", "movil", "auto", "carro", "coche", "patente",
    "marca y modelo", "tarjeta de propiedad",
])

ET_ORIGEN = _reg([
    "pick-up", "pickup", "pick up", "from", "origin", "start address",
    "origen", "partida", "punto de partida", "punto de origen",
    "recojo", "recogida", "lugar de recojo", "salida", "lugar de salida",
    "direccion de origen", "dir origen", "desde",
])

ET_DESTINO = _reg([
    "drop-off", "dropoff", "drop off", "destination", "end address",
    "destino", "llegada", "punto de llegada", "punto de destino",
    "bajada", "direccion de destino", "dir destino", "lugar de llegada",
    "hacia", "hasta",
])

ET_HORA_SALIDA = _reg([
    "hora de salida", "hora salida", "h salida", "hora inicio",
    "hora de inicio", "start time", "pick-up time", "inicio", "desde las",
    "hora de recojo", "hora recojo",
])

ET_HORA_LLEGADA = _reg([
    "hora de llegada", "hora llegada", "h llegada", "hora fin",
    "hora de fin", "end time", "drop-off time", "termino", "hasta las",
    "hora de bajada",
])

ET_DISTANCIA = _reg([
    "distance", "trip distance", "distancia", "recorrido",
    "km recorridos", "kilometraje", "trayecto",
])

ET_TIPO_SERVICIO = _reg([
    "order type", "service type", "ride type", "trip type",
    "tipo de servicio", "tipo de viaje", "tipo de orden", "servicio",
])

ET_NOMBRE_COMERCIAL = _reg([
    "nombre comercial", "razon comercial", "denominacion comercial",
    "company", "merchant",
])

# Etiquetas que NO extraemos pero que sirven para cortar bloques.
ET_CORTE = _reg([
    "invoice number", "payment method", "total amount", "description",
    "amount", "ride date", "date", "subtotal", "ride fare", "receipt",
    "numero de factura", "metodo de pago", "importe total", "descripcion",
    "fecha", "total", "igv", "observaciones", "glosa", "motivo", "concepto",
])


_PALABRAS_MOVILIDAD = [
    "taxi", "remis", "remise", "uber", "cabify", "didi", "indrive", "indriver",
    "beat", "mototaxi", "moto taxi", "colectivo", "combi", "movilidad",
    "traslado", "transporte", "pasaje", "viaje", "carrera", "flete",
    "chofer", "conductor", "placa", "recorrido", "origen", "destino",
    "ride", "driver", "pick-up", "pickup", "drop-off", "dropoff", "trip",
    "fare", "car", "city ride", "service",
]

_TIPOS_SERVICIO = [
    ("uber", "UBER"), ("cabify", "CABIFY"), ("didi", "DIDI"),
    ("indrive", "INDRIVE"), ("beat", "BEAT"),
    ("mototaxi", "MOTOTAXI"), ("moto taxi", "MOTOTAXI"),
    ("colectivo", "COLECTIVO"), ("combi", "COMBI"),
    ("remise", "REMISE"), ("remis", "REMISE"),
    ("taxi", "TAXI"), ("city ride", "TAXI"), ("ride", "TAXI"),
    ("grua", "GRUA"), ("bus", "BUS"),
    ("movilidad", "MOVILIDAD"), ("traslado", "MOVILIDAD"),
    ("transporte", "TRANSPORTE"),
]

_PATRONES_PLACA = [
    r"\b([A-Z]{3}[-\s]?\d{3})\b",
    r"\b([A-Z]\d[A-Z][-\s]?\d{3})\b",
    r"\b([A-Z]{2}[-\s]?\d{4})\b",
    r"\b([A-Z]{3}[-\s]?\d{2}[A-Z])\b",
    r"\b(\d{3}[-\s]?[A-Z]{3})\b",
]

_PATRON_HORA = r"\b(([01]?\d|2[0-3])\s*[:\.]\s*([0-5]\d))\s*(?:(A|P)\.?\s*M\.?)?"
# Solo con dos puntos: se usa al barrer texto libre, para no confundir un
# importe como "18.00" con una hora.
_PATRON_HORA_ESTRICTA = r"\b(([01]?\d|2[0-3])\s*:\s*([0-5]\d))\s*(?:(A|P)\.?\s*M\.?)?"

_PATRON_DISTANCIA = (
    r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:K\.?\s?M\.?S?|KIL[OÓ]METRO?S?|MILLAS?|MI)\b"
)


class MobilityExtractor:

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------
    def extract(self, texto: str) -> dict:

        datos = {
            "isMobility": False,
            "driverName": None,
            "vehicle": None,
            "serviceType": None,
            "pickupAddress": None,
            "dropoffAddress": None,
            "pickupTime": None,
            "dropoffTime": None,
            "distance": None,
            "commercialName": None,
            "glosaSugerida": None,
        }

        if not texto or not texto.strip():
            return datos

        try:
            datos["driverName"] = self._chofer(texto)
            datos["vehicle"] = self._vehiculo(texto)

            origen, hora_origen = self._bloque_lugar(texto, ET_ORIGEN)
            destino, hora_destino = self._bloque_lugar(texto, ET_DESTINO)

            if not origen or not destino:
                o2, d2 = self._de_x_a_y(texto)
                origen = origen or o2
                destino = destino or d2

            datos["pickupAddress"] = origen
            datos["dropoffAddress"] = destino

            salida, llegada = self._horas(texto, hora_origen, hora_destino)
            datos["pickupTime"] = salida
            datos["dropoffTime"] = llegada

            datos["distance"] = self._distancia(texto)
            datos["serviceType"] = self._tipo_servicio(texto)
            datos["commercialName"] = self._nombre_comercial(texto)
            datos["isMobility"] = self._es_movilidad(texto, datos)
            datos["glosaSugerida"] = self._glosa(datos)
        except Exception as e:
            print(f"[MobilityExtractor] fallo no critico: {e}")

        return datos

    # ------------------------------------------------------------------
    # Motor de etiquetas y bloques
    # ------------------------------------------------------------------
    @staticmethod
    def _lineas(texto):
        return (texto or "").splitlines()

    @staticmethod
    def _es_linea_etiqueta(linea) -> bool:
        """True si la linea empieza con alguna etiqueta conocida de >=4 letras."""
        n = _norm(linea).strip()
        for e in _TODAS_LAS_ETIQUETAS:
            if len(e) < 4:
                continue
            if re.match(r"^\W*" + _patron_etiqueta(e) + r"(?![A-Z0-9])\s*[:\-=]?\s+\S", n):
                return True
        return False

    def _bloque(self, texto, etiquetas, max_lineas=4):
        """
        Devuelve la lista de fragmentos que siguen a la etiqueta: el resto de
        su propia linea (si tiene) y las lineas posteriores, hasta toparse con
        otra etiqueta conocida o agotar max_lineas.
        """
        lineas = self._lineas(texto)
        normalizadas = [_norm(l) for l in lineas]

        for etiqueta in etiquetas:
            # El separador es opcional: hay comprobantes que escriben
            # "HORA LLEGADA 9:40" sin dos puntos. El lookahead evita que
            # "car" matchee dentro de "carrera".
            patron = re.compile(
                r"(?:^|[\|\-•\*\s])" + _patron_etiqueta(etiqueta)
                + r"(?![A-Z0-9])\s*[:\-=]?\s*(.+)$"
            )

            for i, ln in enumerate(normalizadas):
                m = patron.search(ln)
                if not m:
                    continue

                fragmentos = []

                resto = lineas[i][m.start(1):] if m.start(1) < len(lineas[i]) else ""
                resto = resto.strip(" \t:-=|.*•")
                if resto:
                    fragmentos.append(resto)

                for j in range(i + 1, min(i + 1 + max_lineas, len(lineas))):
                    siguiente = lineas[j].strip()
                    if not siguiente:
                        continue
                    if self._es_linea_etiqueta(siguiente):
                        break
                    fragmentos.append(siguiente)
                    if len(fragmentos) >= max_lineas:
                        break

                if fragmentos:
                    return fragmentos
        return []

    def _valor(self, texto, etiquetas, largo_max=120):
        """Primer fragmento util del bloque, recortado."""
        for frag in self._bloque(texto, etiquetas, max_lineas=2):
            limpio = self._limpiar(frag, largo_max)
            if limpio:
                return limpio
        return None

    @staticmethod
    def _limpiar(crudo, largo_max):
        if not crudo:
            return None
        valor = re.sub(r"\s{2,}", " ", crudo.strip(" \t:-=|.*•"))[:largo_max].strip()
        if len(valor) < 2 or not re.search(r"[A-Za-z0-9]", valor):
            return None
        return valor

    # ------------------------------------------------------------------
    # Campos
    # ------------------------------------------------------------------
    def _chofer(self, texto):
        valor = self._valor(texto, ET_CHOFER, 80)
        if valor:
            valor = re.sub(r"^(SR|SRA|SRTA|DON|DONA|DOÑA|MR|MRS)\.?\s+", "",
                           valor, flags=re.IGNORECASE).strip()
            if valor:
                return valor

        m = re.search(
            r"\b(?:SR|SRA|SRTA|DON|MR)\.?\s+([A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+"
            r"(?:\s+[A-ZÁÉÍÓÚÑ][\wÁÉÍÓÚÑáéíóúñ]+){1,3})",
            texto,
        )
        return m.group(1).strip() if m else None

    def _vehiculo(self, texto):
        valor = self._valor(texto, ET_VEHICULO, 70)
        if valor:
            return valor
        arriba = _norm(texto)
        for patron in _PATRONES_PLACA:
            m = re.search(patron, arriba)
            if m:
                return m.group(1).replace(" ", "-")
        return None

    def _bloque_lugar(self, texto, etiquetas):
        """
        Para 'Pick-up:' / 'Drop-off:' el bloque suele traer la direccion en una
        linea y la hora en la siguiente. Separa ambas cosas.
        """
        fragmentos = self._bloque(texto, etiquetas, max_lineas=3)
        direccion = None
        hora = None

        for frag in fragmentos:
            limpio = self._limpiar(frag, 160)
            if not limpio:
                continue

            tiene_hora = re.search(_PATRON_HORA, _norm(limpio))
            solo_fecha_hora = tiene_hora and len(re.sub(
                r"[\d\s:,\.\-]|AM|PM|A\.M\.|P\.M\.", "", _norm(limpio))) <= 12

            if tiene_hora and hora is None:
                hora = self._hora_normalizada(limpio)

            if direccion is None and not solo_fecha_hora:
                # una direccion tiene letras y algo de longitud
                if len(limpio) >= 5 and re.search(r"[A-Za-zÁÉÍÓÚÑ]{3,}", limpio):
                    direccion = limpio

        return direccion, hora

    @staticmethod
    def _de_x_a_y(texto):
        m = re.search(
            r"\b(?:DE|DESDE|FROM)\s+(.{4,80}?)\s+(?:A|AL|HASTA|HACIA|TO)\s+(.{4,80}?)"
            r"(?:[\.\n\r]|$)",
            texto, re.IGNORECASE,
        )
        if m:
            origen = m.group(1).strip()
            # "servicio de traslado de Av. X" -> nos quedamos con lo posterior
            # al ultimo " de ", que es donde suele empezar la direccion real.
            partes = re.split(r"\s+(?:DE|DESDE|FROM)\s+", origen, flags=re.IGNORECASE)
            if len(partes) > 1 and len(partes[-1]) >= 4:
                origen = partes[-1].strip()
            return origen, m.group(2).strip()
        return None, None

    def _horas(self, texto, hora_origen, hora_destino):
        salida = hora_origen or self._hora_normalizada(
            self._valor(texto, ET_HORA_SALIDA, 25))
        llegada = hora_destino or self._hora_normalizada(
            self._valor(texto, ET_HORA_LLEGADA, 25))

        if salida and llegada:
            return salida, llegada

        encontradas = []
        for m in re.finditer(_PATRON_HORA_ESTRICTA, _norm(texto)):
            h = self._hora_normalizada(m.group(0))
            if h and h not in encontradas:
                encontradas.append(h)

        if not salida and encontradas:
            salida = encontradas[0]
        if not llegada and len(encontradas) > 1:
            llegada = encontradas[-1]

        return salida, llegada

    @staticmethod
    def _hora_normalizada(valor):
        if not valor:
            return None
        m = re.search(_PATRON_HORA, _norm(valor))
        if not m:
            return None

        hora = int(m.group(2))
        minutos = m.group(3)
        meridiano = m.group(4)

        if meridiano == "P" and hora < 12:
            hora += 12
        if meridiano == "A" and hora == 12:
            hora = 0
        if hora > 23:
            return None

        return f"{hora:02d}:{minutos}"

    def _distancia(self, texto):
        for frag in self._bloque(texto, ET_DISTANCIA, max_lineas=2):
            m = re.search(_PATRON_DISTANCIA, _norm(frag))
            if not m:
                m = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)", frag)
            if m:
                try:
                    return float(m.group(1).replace(",", "."))
                except ValueError:
                    pass

        m = re.search(_PATRON_DISTANCIA, _norm(texto))
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                return None
        return None

    def _tipo_servicio(self, texto):
        etiquetado = self._valor(texto, ET_TIPO_SERVICIO, 40)
        candidato = _norm(etiquetado) if etiquetado else _norm(texto)

        for clave, valor in _TIPOS_SERVICIO:
            if re.search(_patron_etiqueta(clave), candidato):
                return valor

        n = _norm(texto)
        for clave, valor in _TIPOS_SERVICIO:
            if re.search(_patron_etiqueta(clave), n):
                return valor

        return etiquetado.upper()[:40] if etiquetado else None

    def _nombre_comercial(self, texto):
        valor = self._valor(texto, ET_NOMBRE_COMERCIAL, 90)
        if valor:
            return valor

        for linea in self._lineas(texto)[:6]:
            limpia = linea.strip()
            if len(limpia) < 4:
                continue
            if re.search(r"\bR\.?U\.?C\.?\b|\d{11}", _norm(limpia)):
                break
            if self._es_linea_etiqueta(limpia):
                continue
            if re.search(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", limpia):
                return limpia[:90]
        return None

    @staticmethod
    def _es_movilidad(texto, datos):
        n = _norm(texto)
        aciertos = sum(1 for p in _PALABRAS_MOVILIDAD if _norm(p) in n)

        if aciertos >= 2:
            return True
        if datos.get("serviceType"):
            return True
        if datos.get("pickupAddress") and datos.get("dropoffAddress"):
            return True
        if datos.get("driverName") and datos.get("vehicle"):
            return True
        return aciertos >= 1

    @staticmethod
    def _glosa(datos):
        # Si el OCR no saco ni un dato util, no inventamos una glosa.
        utiles = ("driverName", "vehicle", "pickupAddress", "dropoffAddress",
                  "pickupTime", "distance", "serviceType")
        if not any(datos.get(k) for k in utiles):
            return None

        partes = []
        servicio = datos.get("serviceType") or "MOVILIDAD"
        origen = datos.get("pickupAddress")
        destino = datos.get("dropoffAddress")

        if origen and destino:
            partes.append(f"SERVICIO DE {servicio} DE {origen} A {destino}")
        elif destino:
            partes.append(f"SERVICIO DE {servicio} A {destino}")
        elif origen:
            partes.append(f"SERVICIO DE {servicio} DESDE {origen}")
        else:
            partes.append(f"SERVICIO DE {servicio}")

        if datos.get("driverName"):
            partes.append(f"Chofer: {datos['driverName']}")
        if datos.get("vehicle"):
            partes.append(f"Vehiculo: {datos['vehicle']}")

        salida, llegada = datos.get("pickupTime"), datos.get("dropoffTime")
        if salida and llegada:
            partes.append(f"Horario: {salida} a {llegada}")
        elif salida:
            partes.append(f"Hora: {salida}")

        if datos.get("distance"):
            partes.append(f"Distancia: {datos['distance']} km")

        return " | ".join(partes)


# ---------------------------------------------------------------------------
# Puntaje de legibilidad (0 a 100). El frontend considera legible >= 60.
# ---------------------------------------------------------------------------

def calcular_legibilidad(texto: str) -> int:
    if not texto or not texto.strip():
        return 0

    limpio = texto.strip()
    total = len(limpio)

    utiles = sum(1 for c in limpio
                 if c.isalnum() or c.isspace() or c in ".,:-/()$%")
    proporcion = utiles / total if total else 0

    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", limpio)

    puntaje = 0
    puntaje += min(40, int(proporcion * 40))
    puntaje += min(30, len(palabras) * 2)
    puntaje += 15 if re.search(r"\d{2,}", limpio) else 0
    puntaje += 15 if total >= 120 else int(total / 8)

    return max(0, min(100, puntaje))


# ---------------------------------------------------------------------------
# Complementos genericos
#
# El extractor principal (DataExtractor) esta escrito para comprobantes SUNAT
# en espanol: busca "IMPORTE TOTAL" y fechas dd/mm/yyyy. Los recibos de apps
# de taxi vienen en ingles y con otro formato, asi que aca reintentamos importe,
# fecha, numero y moneda de la forma mas amplia posible. Solo se usan cuando el
# extractor principal no encontro nada.
# ---------------------------------------------------------------------------

_MESES = {
    "JANUARY": 1, "ENERO": 1, "JAN": 1, "ENE": 1,
    "FEBRUARY": 2, "FEBRERO": 2, "FEB": 2,
    "MARCH": 3, "MARZO": 3, "MAR": 3,
    "APRIL": 4, "ABRIL": 4, "APR": 4, "ABR": 4,
    "MAY": 5, "MAYO": 5,
    "JUNE": 6, "JUNIO": 6, "JUN": 6,
    "JULY": 7, "JULIO": 7, "JUL": 7,
    "AUGUST": 8, "AGOSTO": 8, "AUG": 8, "AGO": 8,
    "SEPTEMBER": 9, "SETIEMBRE": 9, "SEPTIEMBRE": 9, "SEP": 9, "SET": 9,
    "OCTOBER": 10, "OCTUBRE": 10, "OCT": 10,
    "NOVEMBER": 11, "NOVIEMBRE": 11, "NOV": 11,
    "DECEMBER": 12, "DICIEMBRE": 12, "DEC": 12, "DIC": 12,
}

_ET_TOTAL = [
    "total amount", "amount due", "total fare", "grand total",
    "importe total", "total a pagar", "monto total", "total pagado",
    "total", "importe", "amount", "monto", "precio", "cobro",
]

_ET_NUMERO = [
    "invoice number", "receipt number", "order id", "trip id", "invoice",
    "numero de comprobante", "nro comprobante", "numero de documento",
    "nro documento", "n documento", "comprobante", "recibo n", "boleta n",
    "factura n", "serie y numero",
]

_MONEDAS = [
    (r"\bS/\.?|\bSOLES?\b|\bPEN\b", "PEN"),
    (r"\bUS\$|\bUSD\b|\bDOLARES?\b|\bDOLLARS?\b", "USD"),
    (r"\bEUR\b|€", "EUR"),
]


def _a_float(texto):
    if not texto:
        return None
    limpio = re.sub(r"[^\d.,]", "", texto)
    if not limpio:
        return None
    if "," in limpio and "." in limpio:
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        # coma decimal solo si quedan 1 o 2 digitos detras
        limpio = (limpio.replace(",", ".") if re.search(r",\d{1,2}$", limpio)
                  else limpio.replace(",", ""))
    try:
        return float(limpio)
    except ValueError:
        return None


def extraer_importe(texto):
    """El mayor monto asociado a una etiqueta de total. Si no hay etiqueta,
    el mayor monto con simbolo de moneda del documento."""
    if not texto:
        return None

    candidatos = []
    for linea in texto.splitlines():
        n = _norm(linea)
        for etiqueta in _ET_TOTAL:
            m = re.search(_patron_etiqueta(etiqueta) + r"(?![A-Z0-9])\s*[:\-=]?\s*(.+)$", n)
            if not m:
                continue
            for num in re.finditer(r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|\d+[.,]\d{1,2}", m.group(1)):
                v = _a_float(num.group(0))
                if v and v > 0:
                    candidatos.append(v)
            break

    if candidatos:
        return max(candidatos)

    montos = []
    for m in re.finditer(r"(?:S/\.?|US\$|\$|PEN|USD)\s*(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?)",
                         _norm(texto)):
        v = _a_float(m.group(1))
        if v and v > 0:
            montos.append(v)
    return max(montos) if montos else None


def extraer_fecha(texto):
    """Devuelve ISO yyyy-mm-dd. Acepta dd/mm/yyyy, yyyy-mm-dd,
    'June 2, 2026' y '2 de junio de 2026'."""
    if not texto:
        return None

    m = re.search(r"\b(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\b", texto)
    if m:
        d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mes <= 12 and 1 <= d <= 31:
            return f"{a:04d}-{mes:02d}-{d:02d}"

    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", texto)
    if m:
        return m.group(0)

    n = _norm(texto)

    m = re.search(r"\b([A-Z]{3,10})\s+(\d{1,2})\s*,?\s*(\d{4})\b", n)
    if m and m.group(1) in _MESES:
        return f"{int(m.group(3)):04d}-{_MESES[m.group(1)]:02d}-{int(m.group(2)):02d}"

    m = re.search(r"\b(\d{1,2})\s+(?:DE\s+)?([A-Z]{3,10})\s+(?:DE(?:L)?\s+)?(\d{4})\b", n)
    if m and m.group(2) in _MESES:
        return f"{int(m.group(3)):04d}-{_MESES[m.group(2)]:02d}-{int(m.group(1)):02d}"

    return None


def extraer_numero(texto):
    """Serie-numero peruano si existe; si no, el identificador que traiga
    cualquier etiqueta de numero de comprobante."""
    if not texto:
        return None

    m = re.search(r"\b([FBE]\d{3})\s*[-\s]\s*(\d{1,10})\b", _norm(texto))
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    ex = MobilityExtractor()
    valor = ex._valor(texto, _ET_NUMERO, 40)
    if valor:
        limpio = valor.strip().split()[0].strip(".,;")
        if len(limpio) >= 4:
            return limpio[:30]
    return None


def extraer_moneda(texto):
    if not texto:
        return None
    n = _norm(texto)
    for patron, codigo in _MONEDAS:
        if re.search(patron, n):
            return codigo
    return None
