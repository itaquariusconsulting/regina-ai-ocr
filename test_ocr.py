# -*- coding: utf-8 -*-
"""
Banco de pruebas del OCR sobre documentos reales.

Los archivos de /pruebas-ocr se llaman RUC-tipo-serie-numero.pdf (es el nombre
con que SUNAT entrega el comprobante), asi que el nombre ES la respuesta
correcta: no hace falta etiquetar nada a mano.

    python test_ocr.py [carpeta]
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.extractor import DataExtractor
from app.ocr.lector import Lector

CARPETA = sys.argv[1] if len(sys.argv) > 1 else "pruebas"


def verdad(nombre):
    base = os.path.splitext(nombre)[0]
    partes = base.split("-")
    if len(partes) < 4:
        return None
    return {"ruc": partes[0], "serie": partes[2], "numero": partes[3]}


def main():
    archivos = sorted(f for f in os.listdir(CARPETA)
                      if f.lower().endswith((".pdf", ".jpg", ".jpeg", ".png")))
    if not archivos:
        print(f"No hay documentos en {CARPETA}")
        return 1

    lector, extractor = Lector(), DataExtractor()
    aciertos = {"nro": 0, "ruc": 0, "monto": 0, "fecha": 0, "razon": 0}
    total = 0

    for nombre in archivos:
        v = verdad(nombre)
        if not v:
            print(f"[SKIP] {nombre}: el nombre no trae la respuesta esperada")
            continue
        total += 1

        t0 = time.time()
        lectura = lector.leer(os.path.join(CARPETA, nombre),
                              suficiente=extractor.campos_criticos_completos)
        d = extractor.extract_data(lectura.texto)
        seg = time.time() - t0

        nro_esperado = f"{v['serie']}-{v['numero']}"
        ok_nro = d.get("documentNumber") == nro_esperado
        rucs = d.get("issuerRuc") or []
        primero = rucs[0] if isinstance(rucs, list) and rucs else rucs
        # la vista hace issuerRuc[0], asi que lo que importa es el PRIMERO
        ok_ruc = primero == v["ruc"]
        ok_monto = float(d.get("amount") or 0) > 0
        ok_fecha = bool(d.get("documentDate"))
        ok_razon = bool(d.get("issuerName"))

        aciertos["nro"] += ok_nro
        aciertos["ruc"] += ok_ruc
        aciertos["monto"] += ok_monto
        aciertos["fecha"] += ok_fecha
        aciertos["razon"] += ok_razon

        marca = lambda ok: "OK " if ok else "FALLA"
        print(f"\n--- {nombre}  [{lectura.origen}, {seg:.1f}s] ---")
        print(f"  [{marca(ok_nro)}] nro     {d.get('documentNumber')}  (esperado {nro_esperado})")
        print(f"  [{marca(ok_ruc)}] ruc     {primero}  (esperado {v['ruc']})  lista={rucs}")
        print(f"  [{marca(ok_monto)}] monto   {d.get('amount')} {d.get('documentCurrency')}"
              f"  (igv {d.get('igv')} @ {d.get('igvRate')}, items {len(d.get('items') or [])})")
        print(f"  [{marca(ok_fecha)}] fecha   {d.get('documentDate')}")
        print(f"  [{marca(ok_razon)}] emisor  {d.get('issuerName')}")
        print(f"        direccion {str(d.get('issuerAddress'))[:52]}")
        for a in d.get("detalle", {}).get("advertencias", []):
            print(f"        ! {a}")

    print("\n" + "=" * 60)
    print(f"{'campo':10} {'aciertos':>10}")
    print("-" * 60)
    for campo, n in aciertos.items():
        print(f"{campo:10} {n:>7}/{total}")
    return 0 if all(n == total for n in aciertos.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
