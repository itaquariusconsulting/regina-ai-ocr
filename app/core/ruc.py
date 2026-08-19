"""
RUC peruano: deteccion, validacion y decision de cual es el EMISOR.

El bug que motivo este modulo: el extractor tomaba el primer numero de 11
digitos del texto, que en una factura es casi siempre el RUC del CLIENTE
(aparece despues de "Senor(es)"), no el del emisor. Resultado: todas las
facturas llegaban con el RUC de la propia empresa.

Como se decide cual es el emisor
--------------------------------
NO por posicion. Se probo y falla: Tesseract emite las regiones en el orden
en que las detecta, y la caja del encabezado (donde vive el RUC del emisor)
suele salir DESPUES del bloque del cliente. Lo que si es estable es la
VECINDAD: en todo comprobante peruano el RUC del emisor comparte caja con el
titulo ("FACTURA ELECTRONICA") y con la serie-numero, mientras que el del
cliente cuelga de "Senor(es)" / "Adquiriente".

Por eso cada RUC se puntua mirando las lineas a su alrededor:

    FACTURA ELECTRONICA        <- titulo         (+)
    RUC: 20600775317           <- el emisor
    F002-11092                 <- serie-numero   (+)

    Senor(es) : AQUARIUS ...   <- marcador de cliente (-)
    RUC : 20503271592          <- el cliente

Ademas todo candidato pasa por el digito verificador (modulo 11), asi que un
numero de 11 digitos mal leido por el OCR se cae solo.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

#: Factores del digito verificador (SUNAT, modulo 11).
FACTORES = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

#: Prefijos validos: 10 persona natural, 15/16/17 casos especiales,
#: 20 persona juridica.
PREFIJOS_VALIDOS = ("10", "15", "16", "17", "20")

#: Cuantas lineas alrededor del RUC se miran para clasificarlo.
VENTANA_LINEAS = 2

#: Marcadores de que el RUC vecino es del CLIENTE.
MARCADORES_CLIENTE = (
    "SENOR(ES)", "SENORES", "SENOR :", "CLIENTE", "ADQUIRIENTE", "ADQUIRENTE",
    "RECEPTOR", "COMPRADOR", "RAZON SOCIAL DEL CLIENTE", "DATOS DEL CLIENTE",
    "FACTURAR A", "DESTINATARIO",
)

#: Marcadores de que el RUC vecino es del EMISOR (van en la misma caja).
MARCADORES_EMISOR = (
    "FACTURA ELECTRONICA", "FACTURA DE VENTA", "BOLETA DE VENTA",
    "BOLETA ELECTRONICA", "NOTA DE CREDITO", "NOTA DE DEBITO",
    "RECIBO POR HONORARIOS", "COMPROBANTE DE PERCEPCION", "TICKET",
)

#: Serie-numero: si esta pegado al RUC, ese RUC es del emisor.
RE_SERIE_NUMERO = re.compile(r"\b[A-Z][A-Z0-9]{2,3}\s*-\s*\d{1,15}\b")


def _sin_tildes(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t)
                   if not unicodedata.combining(c))


def normalizar(texto: str) -> str:
    """Mayusculas y sin tildes, conservando los saltos de linea (importan)."""
    return _sin_tildes(texto or "").upper()


def digito_verificador(ruc: str) -> Optional[int]:
    """Digito que le corresponde a los 10 primeros digitos, o None."""
    if not ruc or len(ruc) < 10 or not ruc[:10].isdigit():
        return None
    suma = sum(int(d) * f for d, f in zip(ruc[:10], FACTORES))
    resto = 11 - (suma % 11)
    if resto == 10:
        return 0
    if resto == 11:
        return 1
    return resto


def es_ruc_valido(ruc: str) -> bool:
    """True si tiene 11 digitos, prefijo conocido y checksum correcto."""
    if not ruc or len(ruc) != 11 or not ruc.isdigit():
        return False
    if not ruc.startswith(PREFIJOS_VALIDOS):
        return False
    return digito_verificador(ruc) == int(ruc[10])


@dataclass
class RucEncontrado:
    ruc: str
    linea_idx: int
    linea: str
    valido: bool
    puntaje: int
    lado: str          # "emisor" | "cliente" | "indefinido"

    def __repr__(self) -> str:  # pragma: no cover - solo para depurar
        return f"<RUC {self.ruc} {self.lado} pts={self.puntaje} valido={self.valido}>"


def buscar_rucs(texto: str, nro_documento: Optional[str] = None) -> List[RucEncontrado]:
    """
    Devuelve todos los RUC del texto, clasificados y puntuados de mayor a
    menor probabilidad de ser el EMISOR.

    `nro_documento` (p.ej. "F002-11092") refuerza la deteccion: el RUC que
    comparte vecindad con la serie-numero es el del emisor.
    """
    if not texto:
        return []

    lineas = normalizar(texto).splitlines()
    # el OCR mete espacios y puntos dentro de los numeros largos
    lineas_limpias = [re.sub(r"(?<=\d)[ .\-](?=\d)", "", l) for l in lineas]

    serie_buscada = normalizar(nro_documento or "").strip()
    encontrados: List[RucEncontrado] = []

    for i, linea in enumerate(lineas_limpias):
        for m in re.finditer(r"(?<!\d)(\d{11})(?!\d)", linea):
            ruc = m.group(1)
            valido = es_ruc_valido(ruc)

            ini = max(0, i - VENTANA_LINEAS)
            fin = min(len(lineas_limpias), i + VENTANA_LINEAS + 1)
            ventana = "\n".join(lineas_limpias[ini:fin])

            puntaje = 45 if valido else -60
            lado = "indefinido"

            hay_cliente = any(mk in ventana for mk in MARCADORES_CLIENTE)
            hay_emisor = any(mk in ventana for mk in MARCADORES_EMISOR)
            hay_serie = bool(RE_SERIE_NUMERO.search(ventana)) or (
                serie_buscada and serie_buscada in ventana)

            if hay_emisor:
                puntaje += 35
                lado = "emisor"
            if hay_serie:
                puntaje += 30
                if lado == "indefinido":
                    lado = "emisor"
            if hay_cliente:
                puntaje -= 45
                # un marcador de cliente pesa mas que la cercania al titulo
                lado = "cliente"

            if "RUC" in linea:
                puntaje += 10

            encontrados.append(RucEncontrado(ruc, i, linea, valido, puntaje, lado))

    encontrados.sort(key=lambda r: (-r.puntaje, r.linea_idx))
    return encontrados


def ruc_emisor(texto: str,
               nro_documento: Optional[str] = None,
               ruc_consultante: Optional[str] = None) -> Optional[str]:
    """
    RUC del EMISOR del comprobante, o None si no hay ninguno confiable.

    Devolver None es una respuesta valida y preferible a devolver el RUC
    equivocado: la vista pide el dato al usuario en vez de arrastrar un error
    hasta la validacion de SUNAT.

    `ruc_consultante` es el RUC de la empresa que escanea. Si se pasa, se
    descarta: en una factura de compra ese RUC es siempre el del cliente.
    """
    candidatos = [r for r in buscar_rucs(texto, nro_documento) if r.valido]

    if ruc_consultante:
        propio = re.sub(r"\D", "", ruc_consultante)
        candidatos = [r for r in candidatos if r.ruc != propio]

    candidatos = [r for r in candidatos if r.lado != "cliente"]

    return candidatos[0].ruc if candidatos else None


def ruc_cliente(texto: str, nro_documento: Optional[str] = None) -> Optional[str]:
    """
    RUC del cliente/adquiriente. Sirve para verificar que el comprobante esta
    emitido a nombre de la empresa que lo esta rindiendo.
    """
    candidatos = [r for r in buscar_rucs(texto, nro_documento)
                  if r.valido and r.lado == "cliente"]
    if not candidatos:
        return None
    candidatos.sort(key=lambda r: r.linea_idx)
    return candidatos[0].ruc
