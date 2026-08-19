"""
Extraccion robusta de SERIE y NUMERO de un comprobante de pago peruano.

Este modulo concentra toda la casuistica que se ha visto en los documentos que
pasan por el OCR de REGINA. La idea es una sola funcion de entrada,
`parse_nro_comprobante`, que recibe cualquier cosa (el texto completo del OCR,
una linea suelta, o lo que el usuario tipeo en el campo "Nro. Documento") y
devuelve la serie y el numero ya normalizados, con un puntaje de confianza y el
detalle de que se hizo, para poder auditarlo despues.

CASUISTICA CUBIERTA
-------------------
1.  Separadores:      F002-11092 | F002 - 11092 | F002–11092 (guion largo)
                      F002_11092 | F002/11092 | F002:11092
2.  Etiquetas:        F002 N° 11092 | F002 Nro. 11092 | F002 NUMERO 11092
                      SERIE F002 NUMERO 11092 | Serie y numero: F002-11092
3.  Sin separador:    F00211092  (serie de 4 + correlativo)
4.  Saltos de linea:  "F002\n11092"  (muy comun cuando el OCR corta la celda)
5.  Ceros a la izq.:  F002-000011092  ->  numero 11092
6.  Ruido en el nro.: F002-11.092 | F002-11 092 | F002-11,092
7.  Confusiones OCR:  O/Q/D -> 0 ; I/L/| -> 1 ; Z -> 2 ; S -> 5 ; G -> 6 ;
                      T -> 7 ; B -> 8 ; en la parte numerica.
                      FOO2 -> F002 en la serie (posiciones 2-4).
8.  Serie fisica:     001-0001234 (serie numerica de 3-4 digitos, preimpresos)
9.  Texto completo:   se buscan TODOS los candidatos y se elige el mejor por
                      puntaje (cercania al titulo del documento, coherencia con
                      el tipo de comprobante, longitud del correlativo).
10. Falsos positivos: se descartan RUC (11 digitos), fechas (19-08-2026),
                      importes, y numeros pegados a "RUC"/"DNI"/"TELF".

LIMITES DE SUNAT
----------------
- Serie electronica: 1 letra + 3 alfanumericos (F002, FF01, B001, E001, EB01).
- Serie fisica:      3 o 4 digitos (001, 0001).
- Correlativo:       hasta 8 digitos, sin ceros a la izquierda para la API de
                     validacion de comprobantes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

# --------------------------------------------------------------------------
# Constantes
# --------------------------------------------------------------------------

#: Largo maximo del correlativo que acepta SUNAT.
MAX_LARGO_NUMERO = 8

#: Largo al que el sistema rellena el numero para mostrarlo/guardarlo.
LARGO_PADDING = 15

#: Letras con las que arranca una serie electronica valida en Peru.
LETRAS_SERIE_VALIDAS = set("FBERTNPGC")

#: Letra esperada segun el tipo de comprobante detectado.
LETRA_POR_TIPO = {
    "FACTURA": {"F", "E"},
    "BOLETA": {"B", "E"},
    "NOTA DE CREDITO": {"F", "B", "E"},
    "NOTA DE DEBITO": {"F", "B", "E"},
    "RECIBO": {"R", "E"},
}

#: Confusiones tipicas del OCR cuando lo que deberia haber es un DIGITO.
CONFUSION_A_DIGITO = {
    "O": "0", "Q": "0", "D": "0", "U": "0",
    "I": "1", "L": "1", "|": "1", "!": "1", "]": "1", "[": "1",
    "Z": "2",
    "E": "3",
    "A": "4",
    "S": "5", "$": "5",
    "G": "6", "C": "6",
    "T": "7", "?": "7",
    "B": "8", "&": "8",
    "P": "9", "9": "9",
}

#: Confusiones que SI se corrigen dentro de la serie. Es un subconjunto chico
#: a proposito: series como FF01, EB01 o BB01 son legitimas, asi que letras
#: como B, S, G o T NUNCA se tocan ahi; solo las que no existen como serie.
CONFUSION_SERIE = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1"}

#: Caracteres que se ignoran dentro de la parte numerica (ruido de impresion).
RUIDO_NUMERICO = " .,'`·-–—_/\\"

#: Guiones unicode que se normalizan a "-".
GUIONES_UNICODE = "‐‑‒–—―−­"

#: Palabras que, si preceden al candidato, lo descalifican.
PREFIJOS_PROHIBIDOS = (
    "RUC", "R.U.C", "DNI", "TELF", "TELEFONO", "CEL", "CELULAR",
    "CUENTA", "CTA", "CCI", "IGV", "TOTAL", "SUBTOTAL", "FECHA",
    "HORA", "CAJA", "MESA", "PEDIDO", "ORDEN", "GUIA",
)

#: Palabras que suben el puntaje si aparecen cerca del candidato.
PALABRAS_TITULO = (
    "FACTURA", "BOLETA", "NOTA DE CREDITO", "NOTA DE DEBITO",
    "RECIBO", "COMPROBANTE", "ELECTRONICA", "SERIE",
)

# --------------------------------------------------------------------------
# Resultado
# --------------------------------------------------------------------------


@dataclass
class NroComprobante:
    """Resultado del parseo. `ok` indica si se puede mandar a SUNAT."""

    serie: str = ""
    numero: str = ""                 # sin ceros a la izquierda (lo que quiere SUNAT)
    numero_padded: str = ""          # relleno a 15, para mostrar/guardar
    confianza: int = 0               # 0-100
    patron: str = ""                 # que regla lo encontro
    reparado: bool = False           # hubo correccion de caracteres OCR
    advertencias: List[str] = field(default_factory=list)
    crudo: str = ""                  # el fragmento original que se matcheo

    @property
    def ok(self) -> bool:
        return bool(self.serie) and bool(self.numero)

    @property
    def formateado(self) -> str:
        """Formato interno del sistema: SERIE-000000000000001."""
        return f"{self.serie}-{self.numero_padded}" if self.ok else ""

    def to_dict(self) -> dict:
        return {
            "serie": self.serie,
            "numero": self.numero,
            "numeroPadded": self.numero_padded,
            "formateado": self.formateado,
            "confianza": self.confianza,
            "patron": self.patron,
            "reparado": self.reparado,
            "advertencias": list(self.advertencias),
            "ok": self.ok,
        }


# --------------------------------------------------------------------------
# Normalizacion de texto
# --------------------------------------------------------------------------


def _sin_tildes(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def normalizar_texto(texto: str) -> str:
    """Mayusculas, sin tildes, guiones unicode a '-', espacios raros a ' '."""
    if not texto:
        return ""
    t = _sin_tildes(str(texto))
    for g in GUIONES_UNICODE:
        t = t.replace(g, "-")
    t = t.replace(" ", " ").replace("\t", " ")
    t = t.upper()
    # "N°", "Nº", "N o", "NRO", "NUMERO" -> marcador unico "N#"
    t = re.sub(r"\bN\s*[°º*]\s*", "N# ", t)
    t = re.sub(r"\bNRO\s*\.?\s*", "N# ", t)
    t = re.sub(r"\bNUM(?:ERO)?\s*\.?\s*", "N# ", t)
    t = re.sub(r"\bN\s*\.\s*(?=[A-Z0-9])", "N# ", t)
    t = re.sub(r"\bN\b\s*[.:]?\s*(?=[0-9OQDUILZEASGCTB]{3})", "N# ", t)
    return t


def _reparar_digitos(fragmento: str) -> tuple[str, bool]:
    """Convierte a digitos el fragmento numerico, corrigiendo confusiones OCR."""
    salida = []
    reparado = False
    for ch in fragmento:
        if ch in RUIDO_NUMERICO:
            continue
        if ch.isdigit():
            salida.append(ch)
            continue
        mapeado = CONFUSION_A_DIGITO.get(ch)
        if mapeado:
            salida.append(mapeado)
            reparado = True
        else:
            # caracter imposible dentro del correlativo -> corta aca
            break
    return "".join(salida), reparado


def _reparar_serie(fragmento: str) -> tuple[str, bool]:
    """
    Normaliza la serie. La primera posicion debe ser letra (o digito si es una
    serie fisica); las siguientes suelen ser digitos, asi que ahi si se corrige
    O->0, I->1, etc.
    """
    limpio = re.sub(r"[^A-Z0-9]", "", fragmento.upper())
    if not limpio:
        return "", False

    if limpio.isdigit():                       # serie fisica: 001 / 0001
        return limpio, False

    cabeza, cola = limpio[0], limpio[1:]
    reparado = False

    # "0" o "8" en la cabeza cuando deberia haber letra: intento inverso
    if cabeza.isdigit():
        inverso = {"0": "O", "8": "B", "5": "S", "1": "I", "6": "G", "7": "T"}
        if cabeza in inverso and inverso[cabeza] in LETRAS_SERIE_VALIDAS:
            cabeza = inverso[cabeza]
            reparado = True

    cola_reparada = []
    for ch in cola:
        if ch.isdigit():
            cola_reparada.append(ch)
        elif ch in CONFUSION_SERIE:
            # ojo: series como "FF01" o "EB01" son legitimas; solo se repara si
            # el caracter NO puede ser parte de una serie alfanumerica valida.
            cola_reparada.append(ch)
        else:
            cola_reparada.append(ch)
    return cabeza + "".join(cola_reparada), reparado


def _corregir_serie_ambigua(serie: str) -> tuple[str, bool]:
    """
    Segunda pasada sobre la serie: si tiene letras en las posiciones 2-4 que son
    confusiones tipicas (O, I, S, B) y el resultado con digitos es una serie
    mucho mas probable, se corrige. FOO2 -> F002.
    """
    if len(serie) < 2 or serie.isdigit():
        return serie, False
    cabeza, cola = serie[0], serie[1:]
    if cola.isdigit():
        return serie, False
    convertida = "".join(CONFUSION_SERIE.get(c, c) for c in cola)
    if convertida.isdigit():
        return cabeza + convertida, True
    return serie, False


# --------------------------------------------------------------------------
# Candidatos
# --------------------------------------------------------------------------

# clase de caracteres que pueden aparecer donde deberia haber digitos
_CI = r"0-9OQDUILZEASGCTB|!$&"      # interior de la clase, sin corchetes
_C = rf"[{_CI}]"                    # un "digito" tolerante
_NUM = rf"{_C}[{_CI} .,]{{0,19}}"   # correlativo con ruido de impresion
_SERIE = r"[A-Z][A-Z0-9]{2,3}"

_PATRONES = [
    # (nombre, regex, puntaje base)
    (
        "serie-guion-numero",
        rf"\b({_SERIE})\s*-\s*({_NUM})",
        100,
    ),
    (
        "serie-etiqueta-numero",
        rf"\b({_SERIE})\s*N#[\s:.\-]*({_NUM})",
        95,
    ),
    (
        "etiqueta-serie-numero",
        rf"\bSERIE\s*[:.]?\s*({_SERIE})[^0-9]{{0,16}}?({_NUM})",
        95,
    ),
    (
        "serie-espacio-numero",
        rf"\b({_SERIE})[ \n\r]+({_C}{{3,19}})\b",
        75,
    ),
    (
        "serie-pegada-numero",
        rf"\b([A-Z][A-Z0-9]{{3}})({_C}{{4,15}})\b",
        70,
    ),
    (
        "serie-fisica",
        r"\b(\d{3,4})\s*-\s*(\d{4,15})\b",
        60,
    ),
]

_RE_FECHA = re.compile(r"\d{1,2}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{2,4}")


def _contexto(texto: str, ini: int, fin: int, radio: int = 40) -> str:
    return texto[max(0, ini - radio): min(len(texto), fin + radio)]


def _es_falso_positivo(texto: str, ini: int, fin: int, serie: str, numero: str) -> Optional[str]:
    previo = texto[max(0, ini - 24): ini]
    previo_limpio = previo.replace(".", "").replace(":", "").replace(" ", "")

    for palabra in PREFIJOS_PROHIBIDOS:
        if previo_limpio.endswith(palabra.replace(".", "")):
            return f"precedido por {palabra}"

    if len(numero) == 11 and numero.startswith(("10", "15", "17", "20")):
        return "parece un RUC"

    # fechas: 19-08-2026 / 19/08/2026
    ventana = _contexto(texto, ini, fin, 6)
    if _RE_FECHA.search(ventana) and serie.isdigit():
        return "parece una fecha"

    # el candidato esta dentro de una corrida mas larga de digitos
    if ini > 0 and texto[ini - 1].isdigit():
        return "pegado a otro numero"
    if fin < len(texto) and texto[fin].isdigit() and len(numero) >= MAX_LARGO_NUMERO:
        return "correlativo demasiado largo"

    return None


def _puntuar(base: int, texto: str, ini: int, fin: int, serie: str,
             numero: str, reparado: bool, tipo_doc: Optional[str]) -> int:
    puntaje = base

    if serie and serie[0] in LETRAS_SERIE_VALIDAS:
        puntaje += 12
    elif serie.isdigit():
        puntaje -= 5

    if tipo_doc:
        esperadas = LETRA_POR_TIPO.get(tipo_doc.upper().strip(), set())
        if esperadas and serie and serie[0] in esperadas:
            puntaje += 12
        elif esperadas and serie and not serie.isdigit():
            puntaje -= 8

    ventana = _contexto(texto, ini, fin, 60)
    if any(p in ventana for p in PALABRAS_TITULO):
        puntaje += 10

    # los comprobantes electronicos tienen serie de 4 caracteres
    if len(serie) == 4:
        puntaje += 8
    elif len(serie) == 3:
        puntaje -= 6

    largo = len(numero)
    if 1 <= largo <= MAX_LARGO_NUMERO:
        puntaje += 6
    else:
        puntaje -= 30

    if reparado:
        puntaje -= 12

    # mientras mas arriba del documento, mas probable que sea la cabecera
    if ini < 400:
        puntaje += 5

    return puntaje


def _extraer_candidatos(texto: str, tipo_doc: Optional[str]) -> List[NroComprobante]:
    candidatos: List[NroComprobante] = []

    for nombre, patron, base in _PATRONES:
        for m in re.finditer(patron, texto):
            crudo_serie, crudo_numero = m.group(1), m.group(2)

            serie, rep_serie = _reparar_serie(crudo_serie)
            serie, rep_serie2 = _corregir_serie_ambigua(serie)
            numero_bruto, rep_num = _reparar_digitos(crudo_numero)

            if not serie or not numero_bruto:
                continue

            numero = numero_bruto.lstrip("0") or "0"

            motivo = _es_falso_positivo(texto, m.start(), m.end(), serie, numero_bruto)
            if motivo:
                continue

            if len(numero) > MAX_LARGO_NUMERO:
                continue
            if not re.fullmatch(r"(?:[A-Z][A-Z0-9]{1,2}\d|\d{3,4})", serie):
                continue

            reparado = rep_serie or rep_serie2 or rep_num
            puntaje = _puntuar(base, texto, m.start(), m.end(), serie,
                               numero, reparado, tipo_doc)

            advertencias = []
            if reparado:
                advertencias.append(
                    f"se corrigieron caracteres del OCR ('{m.group(0).strip()}')"
                )
            if len(serie) == 3:
                advertencias.append("la serie tiene 3 caracteres; SUNAT usa 4")

            candidatos.append(NroComprobante(
                serie=serie,
                numero=numero,
                numero_padded=numero.rjust(LARGO_PADDING, "0"),
                confianza=puntaje,
                patron=nombre,
                reparado=reparado,
                advertencias=advertencias,
                crudo=m.group(0).strip(),
            ))

    return candidatos


# --------------------------------------------------------------------------
# API publica
# --------------------------------------------------------------------------


def parse_nro_comprobante(entrada: str,
                          tipo_doc: Optional[str] = None) -> NroComprobante:
    """
    Devuelve la serie y el numero del comprobante encontrados en `entrada`.

    `entrada` puede ser el texto completo del OCR o un valor corto tipeado por
    el usuario. `tipo_doc` ("FACTURA", "BOLETA", ...) es opcional y solo se usa
    para desempatar candidatos.

    Nunca lanza excepcion: si no encuentra nada devuelve un NroComprobante con
    ok == False y la razon en `advertencias`.
    """
    if not entrada or not str(entrada).strip():
        return NroComprobante(advertencias=["no se recibio ningun texto"])

    texto = normalizar_texto(entrada)
    candidatos = _extraer_candidatos(texto, tipo_doc)

    if not candidatos:
        return NroComprobante(
            advertencias=["no se encontro un patron serie-numero en el texto"],
            crudo=texto[:80],
        )

    candidatos.sort(key=lambda c: (c.confianza, len(c.serie), -len(c.numero)),
                    reverse=True)
    mejor = candidatos[0]

    # si hay dos candidatos distintos con puntaje parecido, se avisa
    distintos = [c for c in candidatos[1:]
                 if (c.serie, c.numero) != (mejor.serie, mejor.numero)]
    if distintos and (mejor.confianza - distintos[0].confianza) <= 8:
        mejor.advertencias.append(
            f"habia otro candidato posible: {distintos[0].serie}-{distintos[0].numero}"
        )

    mejor.confianza = max(0, min(100, mejor.confianza))
    return mejor


def formatear_nro_comprobante(entrada: str, tipo_doc: Optional[str] = None) -> Optional[str]:
    """Compatibilidad con el extractor viejo: devuelve 'F002-11092' o None."""
    r = parse_nro_comprobante(entrada, tipo_doc)
    return f"{r.serie}-{r.numero}" if r.ok else None
