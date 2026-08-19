# -*- coding: utf-8 -*-
"""Bateria de casos para parse_nro_comprobante."""
import os
import sys

# permite correrlo tanto desde la raiz del repo como desde tests/
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
try:
    from app.core.doc_number import parse_nro_comprobante
except ImportError:
    from doc_number import parse_nro_comprobante

TEXTO_FACTURA = """
DONDE WALTER - SURCO
MARGAL INVERSIONES S.A.C.
Av. Camino del Inca 1478 Urb. Chacarilla
LIMA-LIMA-SANTIAGO DE SURCO
                          FACTURA ELECTRONICA
                          RUC: 20600775317
                          F002-11092
Fecha de Emision : 19/08/2026
Senor(es) : AQUARIUS CONSULTING S.A.C.
RUC : 20512345678
Tipo de Moneda : SOL
Cantidad UNIDAD 0000036 Jarra de Limonada de la Casa (1 Lt.) 17.66
"""

TEXTO_BOLETA = """
POLLERIA EL RANCHO
R.U.C. 10456789012
BOLETA DE VENTA ELECTRONICA
B001 N 00000345
FECHA: 01/08/2026  HORA: 13:45
MESA 12  CAJA 03
TOTAL S/ 85.00
"""

TEXTO_OCR_SUCIO = """
FACTURA ELECTRONICA
RUC 20600775317
FOO2 - OOOO11O92
TOTAL 404.00
"""

CASOS = [
    # (entrada, tipo, serie esperada, numero esperado)
    ("F002-11092",                      None,      "F002", "11092"),
    ("F002 - 000011092",                None,      "F002", "11092"),
    ("F002–11092",                 None,      "F002", "11092"),   # guion largo
    ("F002—11092",                 None,      "F002", "11092"),   # raya
    ("F002 N° 11092",                   None,      "F002", "11092"),
    ("F002 Nro. 11092",                 None,      "F002", "11092"),
    ("F002 NUMERO 11092",               None,      "F002", "11092"),
    ("F00211092",                       None,      "F002", "11092"),
    ("F002\n11092",                     None,      "F002", "11092"),
    ("F002  11092",                     None,      "F002", "11092"),
    ("f002-11092",                      None,      "F002", "11092"),
    ("  F002-11092  ",                  None,      "F002", "11092"),
    ("FOO2-11092",                      None,      "F002", "11092"),   # letra O
    ("F002-11.092",                     None,      "F002", "11092"),
    ("F002-11 092",                     None,      "F002", "11092"),
    ("F002-000000000011092",            None,      "F002", "11092"),
    ("SERIE: F002 NUMERO: 11092",       None,      "F002", "11092"),
    ("Serie y numero: F002-11092",      None,      "F002", "11092"),
    ("N° F002-11092",                   None,      "F002", "11092"),
    ("B001-00000345",                   "BOLETA",  "B001", "345"),
    ("EB01-1234",                       None,      "EB01", "1234"),
    ("FF01-123",                        None,      "FF01", "123"),
    ("E001-9",                          None,      "E001", "9"),
    ("001-0001234",                     None,      "001",  "1234"),
    ("0001-00012345",                   None,      "0001", "12345"),
    ("F002-1I092",                      None,      "F002", "11092"),   # I por 1
    ("F002-11O92",                      None,      "F002", "11092"),   # O por 0
    ("F002-S5555",                      None,      "F002", "55555"),   # S por 5
    (TEXTO_FACTURA,                     "FACTURA", "F002", "11092"),
    (TEXTO_BOLETA,                      "BOLETA",  "B001", "345"),
    (TEXTO_OCR_SUCIO,                   "FACTURA", "F002", "11092"),
]

NEGATIVOS = [
    ("", "vacio"),
    ("   ", "solo espacios"),
    (None, "None"),
    ("RUC: 20600775317", "solo un RUC"),
    ("19-08-2026", "solo una fecha"),
    ("TOTAL S/ 404.00", "solo un importe"),
    ("Jarra de Limonada de la Casa", "texto libre"),
    ("F002-1234567890123", "correlativo imposible (13 digitos)"),
]


def main() -> int:
    fallos = 0
    print("=" * 78)
    print("CASOS QUE DEBEN RESOLVERSE")
    print("=" * 78)
    for entrada, tipo, serie_esp, num_esp in CASOS:
        r = parse_nro_comprobante(entrada, tipo)
        ok = r.serie == serie_esp and r.numero == num_esp
        etiqueta = (entrada if len(str(entrada)) < 32
                    else str(entrada).strip().splitlines()[0][:29] + "...")
        estado = "OK " if ok else "FALLA"
        print(f"[{estado}] {etiqueta!r:36} -> {r.serie}-{r.numero} "
              f"(conf {r.confianza}, {r.patron})")
        if not ok:
            fallos += 1
            print(f"         esperado {serie_esp}-{num_esp} | adv: {r.advertencias}")

    print()
    print("=" * 78)
    print("CASOS QUE NO DEBEN DEVOLVER NADA")
    print("=" * 78)
    for entrada, desc in NEGATIVOS:
        r = parse_nro_comprobante(entrada)
        ok = not r.ok
        estado = "OK " if ok else "FALLA"
        print(f"[{estado}] {desc:34} -> ok={r.ok} {r.serie}-{r.numero}")
        if not ok:
            fallos += 1

    print()
    print(f"RESULTADO: {len(CASOS) + len(NEGATIVOS) - fallos}"
          f"/{len(CASOS) + len(NEGATIVOS)} casos correctos")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
