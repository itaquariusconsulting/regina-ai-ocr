"""
Importes del comprobante, con verificacion cruzada.

Por que no basta con buscar "Importe total"
-------------------------------------------
Es el campo mas fragil del OCR: son cifras chicas, alineadas a la derecha, y
cualquier corte de layout se lleva la columna entera (asi devolvia 0.0 el
extractor viejo). Pero un comprobante peruano trae el mismo numero DOS veces:
en digitos y en letras.

    Total valor venta gravado : S/ 39.68
    Sumatoria otros cargos    : S/  2.38
    Sumatoria IGV             : S/  7.14
    Importe total             : S/ 49.20
    SON: CUARENTA Y NUEVE Y 20/100 SOLES

Eso permite tres lecturas independientes del total —la etiquetada, la de
letras y la suma de sus componentes— y quedarse con la que coincide con las
otras. Si las tres discrepan, el modulo lo dice en vez de devolver un numero
inventado.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional

#: Tasas de IGV validas en Peru. Ademas del 18% general, la Ley 31556 dejo
#: una tasa reducida para restaurantes y hoteles — que es justo el rubro de la
#: mayoria de las rendiciones de movilidad y representacion. El catalogo de
#: documentos del ERP ya la contempla ("FACTURA HOTEL Y REST 10.5%").
TASAS_IGV_VALIDAS = (0.18, 0.105, 0.08, 0.10)

#: Tasa por defecto cuando no se puede deducir del documento.
TASA_IGV = 0.18

#: Tolerancia al comparar importes (redondeos del emisor).
TOLERANCIA = 0.05

UNIDADES: Dict[str, int] = {
    "CERO": 0, "UN": 1, "UNO": 1, "UNA": 1, "DOS": 2, "TRES": 3, "CUATRO": 4,
    "CINCO": 5, "SEIS": 6, "SIETE": 7, "OCHO": 8, "NUEVE": 9, "DIEZ": 10,
    "ONCE": 11, "DOCE": 12, "TRECE": 13, "CATORCE": 14, "QUINCE": 15,
    "DIECISEIS": 16, "DIECISIETE": 17, "DIECIOCHO": 18, "DIECINUEVE": 19,
    "VEINTE": 20, "VEINTIUN": 21, "VEINTIUNO": 21, "VEINTIUNA": 21,
    "VEINTIDOS": 22, "VEINTITRES": 23, "VEINTICUATRO": 24, "VEINTICINCO": 25,
    "VEINTISEIS": 26, "VEINTISIETE": 27, "VEINTIOCHO": 28, "VEINTINUEVE": 29,
}

DECENAS: Dict[str, int] = {
    "TREINTA": 30, "CUARENTA": 40, "CINCUENTA": 50, "SESENTA": 60,
    "SETENTA": 70, "OCHENTA": 80, "NOVENTA": 90,
}

CENTENAS: Dict[str, int] = {
    "CIEN": 100, "CIENTO": 100, "DOSCIENTOS": 200, "DOSCIENTAS": 200,
    "TRESCIENTOS": 300, "TRESCIENTAS": 300, "CUATROCIENTOS": 400,
    "CUATROCIENTAS": 400, "QUINIENTOS": 500, "QUINIENTAS": 500,
    "SEISCIENTOS": 600, "SEISCIENTAS": 600, "SETECIENTOS": 700,
    "SETECIENTAS": 700, "OCHOCIENTOS": 800, "OCHOCIENTAS": 800,
    "NOVECIENTOS": 900, "NOVECIENTAS": 900,
}

#: Etiquetas del importe total, de la mas especifica a la mas generica.
ETIQUETAS_TOTAL = (
    r"IMPORTE\s+TOTAL",
    r"TOTAL\s+A\s+PAGAR",
    r"TOTAL\s+COMPROBANTE",
    r"IMPORTE\s+NETO",
    r"TOTAL\s+VENTA",
    r"\bTOTAL\b",
)

#: Etiquetas del valor gravado, EN ORDEN DE PREFERENCIA. El orden importa:
#: en los tickets de supermercado "SUBTOTAL" es el total CON IGV, mientras que
#: el gravado real esta en "OP. GRAVADA". Si se toma el subtotal como gravado,
#: la tasa de IGV sale mal y la verificacion cruzada reporta un falso error.
ETIQUETAS_GRAVADO = (
    r"OP\.?\s*GRAVADAS?",
    r"OPERACION(?:ES)?\s+GRAVADAS?",
    r"(?:TOTAL\s+)?VALOR\s+VENTA\s+GRAVAD[OA]",
    r"BASE\s+IMPONIBLE",
    r"SUB\s*-?\s*TOTAL",
)
ETIQUETA_IGV = r"(?:SUMATORIA\s+)?I\.?G\.?V\.?"
ETIQUETA_CARGOS = r"SUMATORIA\s+OTROS\s+CARGOS"
ETIQUETA_ISC = r"SUMATORIA\s+ISC"
ETIQUETA_ICBPER = r"(?:SUMATORIA\s+)?ICBPER"

#: Numero con miles y decimales: 1,234.56 | 1.234,56 | 49.20 | 123
RE_NUMERO = r"-?\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2})?|-?\d+(?:[.,]\d{1,2})?"


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t or "")
                   if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    return _sin_tildes(texto).upper()


def a_float(valor: str) -> Optional[float]:
    """
    Convierte "1,234.56", "1.234,56", "S/ 49.20" o "49,20" a float.
    Devuelve None si no se puede: preferimos ausencia a un numero inventado.
    """
    if valor is None:
        return None

    limpio = re.sub(r"[^\d.,\-]", "", str(valor))
    if not limpio:
        return None

    if "," in limpio and "." in limpio:
        # el separador decimal es el ultimo que aparece
        if limpio.rfind(",") > limpio.rfind("."):
            limpio = limpio.replace(".", "").replace(",", ".")
        else:
            limpio = limpio.replace(",", "")
    elif "," in limpio:
        entero, _, dec = limpio.rpartition(",")
        limpio = f"{entero.replace(',', '')}.{dec}" if len(dec) <= 2 else limpio.replace(",", "")
    else:
        # varios puntos = separadores de miles (1.234.567)
        if limpio.count(".") > 1:
            limpio = limpio.replace(".", "")

    try:
        return float(limpio)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Monto escrito en letras
# --------------------------------------------------------------------------

def _palabras_a_entero(palabras: List[str]) -> Optional[int]:
    """Convierte ['CUARENTA','Y','NUEVE'] en 49. None si algo no se entiende."""
    total = 0
    parcial = 0
    reconocio = False

    for p in palabras:
        if p in ("Y", "CON", "DE"):
            continue

        if p in UNIDADES:
            parcial += UNIDADES[p]
            reconocio = True
        elif p in DECENAS:
            parcial += DECENAS[p]
            reconocio = True
        elif p in CENTENAS:
            parcial += CENTENAS[p]
            reconocio = True
        elif p in ("MIL", "MILES"):
            parcial = parcial if parcial else 1
            total += parcial * 1000
            parcial = 0
            reconocio = True
        elif p in ("MILLON", "MILLONES"):
            parcial = parcial if parcial else 1
            total += parcial * 1_000_000
            parcial = 0
            reconocio = True
        else:
            # palabra desconocida: se corta, ya salimos del numero
            break

    if not reconocio:
        return None
    return total + parcial


def _numerales_finales(palabras: List[str]) -> List[str]:
    """
    Se queda con las ultimas palabras que son numerales.

    En un ticket la linea del monto en letras viene pegada a otras cosas
    ("TARJ BANC TREINTA Y CINCO Y 70/100"), asi que se recorre desde el final
    hacia atras mientras las palabras sigan siendo parte del numero.
    """
    vocabulario = set(UNIDADES) | set(DECENAS) | set(CENTENAS) | {
        "Y", "CON", "MIL", "MILES", "MILLON", "MILLONES"}

    fin = len(palabras)
    ini = fin
    while ini > 0 and palabras[ini - 1] in vocabulario:
        ini -= 1

    numerales = palabras[ini:fin]
    # "Y" suelto al inicio no aporta
    while numerales and numerales[0] in ("Y", "CON"):
        numerales.pop(0)
    return numerales


def parse_monto_en_letras(texto: str) -> Optional[float]:
    """
    Lee el importe escrito en palabras y lo devuelve como numero:

        SON: CUARENTA Y NUEVE Y 20/100 SOLES   ->  49.20
        TREINTA Y CINCO Y 70/100 SOLES         ->  35.70   (tickets, sin "SON")

    Es la verificacion independiente mas valiosa que trae el documento: son
    palabras largas, que el OCR lee mucho mejor que una columna de cifras
    chicas alineadas a la derecha.
    """
    if not texto:
        return None

    t = normalizar(texto)

    # Todas las apariciones de "NN/100" son candidatas. Se prefiere la que
    # viene precedida de "SON", y si no hay, cualquiera cuyas palabras previas
    # formen un numero.
    candidatos = []
    for m in re.finditer(r"(.{0,140}?)(\d{1,2})\s*/\s*100", t, re.DOTALL):
        previo, centavos = m.group(1), int(m.group(2))
        con_son = "SON" in previo[-60:]

        # el texto entre "SON" y el "NN/100", o los ultimos 140 caracteres
        trozo = previo.rsplit("SON", 1)[-1] if con_son else previo
        palabras = _numerales_finales(re.findall(r"[A-Z]+", trozo))
        if not palabras:
            continue

        entero = _palabras_a_entero(palabras)
        if entero is None:
            continue
        candidatos.append((con_son, round(entero + centavos / 100.0, 2)))

    if candidatos:
        con_son = [v for marcado, v in candidatos if marcado]
        return con_son[0] if con_son else candidatos[0][1]

    # variante sin centavos: "SON: CIEN SOLES"
    m2 = re.search(r"\bSON\s*[:\-]?\s*(.{3,180}?)\s+(?:SOLES|NUEVOS\s+SOLES|DOLARES)",
                   t, re.DOTALL)
    if m2:
        entero = _palabras_a_entero(_numerales_finales(re.findall(r"[A-Z]+", m2.group(1))))
        if entero is not None:
            return float(entero)

    return None


# --------------------------------------------------------------------------
# Importes etiquetados
# --------------------------------------------------------------------------

def _buscar_etiquetado(texto: str, etiqueta: str) -> Optional[float]:
    """
    Numero que sigue a una etiqueta, en la misma linea o en la siguiente.
    El simbolo de moneda entre medio (S/, $, US$) se ignora.
    """
    patron = re.compile(
        rf"(?:{etiqueta})\s*[:\.]?\s*(?:S\s*/\.?|\$|US\$|PEN|USD)?\s*({RE_NUMERO})",
        re.IGNORECASE,
    )
    m = patron.search(texto)
    if m:
        return a_float(m.group(1))
    return None


def detectar_moneda(texto: str) -> str:
    """Devuelve 'PEN' o 'USD'. Ante la duda, PEN."""
    t = normalizar(texto)
    m = re.search(r"TIPO\s+DE\s+MONEDA\s*[:\.]?\s*([A-Z$/ ]{2,12})", t)
    if m:
        v = m.group(1)
        if "DOL" in v or "USD" in v or "$" in v:
            return "USD"
        if "SOL" in v or "PEN" in v or "S/" in v:
            return "PEN"
    if re.search(r"US\$|\bUSD\b|DOLARES", t):
        return "USD"
    return "PEN"


@dataclass
class Montos:
    total: Optional[float] = None
    gravado: Optional[float] = None
    igv: Optional[float] = None
    otros_cargos: Optional[float] = None
    isc: Optional[float] = None
    icbper: Optional[float] = None
    en_letras: Optional[float] = None
    #: Tasa de IGV deducida del propio documento (0.18, 0.105...). None si no
    #: se pudo calcular. Sirve para pre-llenar el % de IGV en la vista.
    tasa_igv: Optional[float] = None
    moneda: str = "PEN"
    origen: str = ""                 # de donde salio el total elegido
    confianza: int = 0               # 0-100
    advertencias: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.total is not None and self.total > 0


def extraer_montos(texto: str) -> Montos:
    """
    Extrae los importes y elige el total cruzando tres lecturas
    independientes: la etiquetada, la escrita en letras y la suma de los
    componentes (gravado + IGV + otros cargos + ISC + ICBPER).

    La confianza sale del acuerdo entre ellas, no de una corazonada:
      100  dos o mas lecturas coinciden
       70  una sola lectura disponible
       40  hay lecturas y NO coinciden (se elige la de letras y se avisa)
    """
    m = Montos()
    if not texto:
        m.advertencias.append("no se recibio texto")
        return m

    t = normalizar(texto)
    m.moneda = detectar_moneda(t)

    for etiqueta in ETIQUETAS_GRAVADO:
        m.gravado = _buscar_etiquetado(t, etiqueta)
        if m.gravado is not None:
            break
    m.igv = _buscar_etiquetado(t, ETIQUETA_IGV)
    m.otros_cargos = _buscar_etiquetado(t, ETIQUETA_CARGOS)
    m.isc = _buscar_etiquetado(t, ETIQUETA_ISC)
    m.icbper = _buscar_etiquetado(t, ETIQUETA_ICBPER)
    m.en_letras = parse_monto_en_letras(t)

    etiquetado = None
    for etiqueta in ETIQUETAS_TOTAL:
        etiquetado = _buscar_etiquetado(t, etiqueta)
        if etiquetado is not None and etiquetado > 0:
            break

    componentes = [v for v in (m.gravado, m.igv, m.otros_cargos, m.isc, m.icbper)
                   if v is not None]
    suma = round(sum(componentes), 2) if m.gravado is not None else None

    lecturas = [
        ("etiqueta 'importe total'", etiquetado),
        ("monto en letras", m.en_letras),
        ("suma de componentes", suma),
    ]
    disponibles = [(nombre, val) for nombre, val in lecturas
                   if val is not None and val > 0]

    if not disponibles:
        m.advertencias.append("no se encontro ningun importe en el documento")
        return m

    # acuerdo: alguna pareja que coincida dentro de la tolerancia
    for i, (nombre_a, val_a) in enumerate(disponibles):
        for nombre_b, val_b in disponibles[i + 1:]:
            if abs(val_a - val_b) <= TOLERANCIA:
                m.total = val_a
                m.origen = f"{nombre_a} + {nombre_b} coinciden"
                m.confianza = 100
                break
        if m.total is not None:
            break

    if m.total is None:
        if len(disponibles) == 1:
            nombre, val = disponibles[0]
            m.total, m.origen, m.confianza = val, nombre, 70
            m.advertencias.append(
                f"solo se pudo leer el importe por '{nombre}'; no hay con que contrastarlo")
        else:
            # discrepan: el monto en letras es el mas confiable de leer
            preferido = next((x for x in disponibles if x[0] == "monto en letras"),
                             disponibles[0])
            m.total, m.origen, m.confianza = preferido[1], preferido[0], 40
            detalle = ", ".join(f"{n}={v}" for n, v in disponibles)
            m.advertencias.append(f"los importes no coinciden entre si ({detalle})")

    # Coherencia del IGV. No se asume 18%: se deduce la tasa del propio
    # documento y se acepta si cae en alguna de las vigentes. Asi las facturas
    # de restaurante (10.5%) dejan de reportarse como error.
    if m.gravado and m.igv and m.gravado > 0:
        tasa = m.igv / m.gravado
        cercana = min(TASAS_IGV_VALIDAS, key=lambda t: abs(t - tasa))

        if abs(cercana - tasa) <= 0.006:
            m.tasa_igv = cercana
        else:
            porcentaje = round(tasa * 100, 1)
            m.advertencias.append(
                f"el IGV leido ({m.igv}) es el {porcentaje}% del valor gravado "
                f"({m.gravado}); no coincide con ninguna tasa vigente")

    # Ultima verificacion: gravado + IGV + cargos deberia dar el total.
    if m.total and m.gravado is not None and m.igv is not None:
        suma = round(m.gravado + m.igv + (m.otros_cargos or 0)
                     + (m.isc or 0) + (m.icbper or 0), 2)
        if abs(suma - m.total) > TOLERANCIA:
            m.advertencias.append(
                f"los componentes suman {suma} pero el total dice {m.total}")

    return m
