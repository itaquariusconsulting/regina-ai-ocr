import os
import glob
import uuid
import shutil
import tempfile
import uvicorn
import gc
import time
import re

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.utils.file_mover import FileMover
from app.core.extractor import DataExtractor
from app.core.mobility_extractor import (
    MobilityExtractor, calcular_legibilidad,
    extraer_importe, extraer_fecha, extraer_numero, extraer_moneda,
)
from app.infrastructure.image_handler import ImageHandler
from app.ocr.lector import Lector
from app.network.backend_client import BackendClient
from app.domain import ScannedDocument
from app.config import INPUT_FOLDER, PROCESSED_FOLDER, ERROR_FOLDER, SUPPORTED_EXTENSIONS

import sys
sys.stdout.reconfigure(encoding='utf-8')

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

image_handler = ImageHandler()

# El lector resuelve PDF con texto (pdfplumber), PDF imagen y fotos, con OCR
# en cascada: espanol + PSM 3 primero y, solo si faltan campos, binarizacion,
# enderezado y 400 dpi. Se midio sobre facturas reales: con la configuracion
# anterior (ingles, PSM 6) el RUC del emisor y el importe salian en 0 de 4.
# Si Tesseract o Poppler no estan en el PATH del servicio, se indican por
# variable de entorno y no hay que tocar codigo.
lector = Lector(
    tesseract_cmd=os.environ.get("TESSERACT_CMD"),
    poppler_path=os.environ.get("POPPLER_PATH"),
)
extractor = DataExtractor()
mobility = MobilityExtractor()
client = BackendClient()

def ensure_folders():
    for folder in (INPUT_FOLDER, PROCESSED_FOLDER, ERROR_FOLDER):
        os.makedirs(folder, exist_ok=True)

def extension_supported(filename: str) -> bool:
    return filename.lower().endswith(tuple(SUPPORTED_EXTENSIONS))

def process_file(path: str, enhance: bool = False):
    """Devuelve (documento, extra). `extra` trae los campos de movilidad
    y el puntaje de legibilidad; no se toca el contrato de ScannedDocument."""

    file_input, is_pdf = image_handler.load_image(path)

    # `enhance` (el boton "Mejorar la imagen" de la vista) salta la vuelta
    # barata: fuerza OCR aunque el PDF traiga texto y arranca por las pasadas
    # con binarizacion y enderezado.
    lectura = lector.leer(
        path,
        suficiente=extractor.campos_criticos_completos,
        forzar_ocr=enhance,
        pasadas_pesadas_primero=enhance,
    )
    raw_text = lectura.texto
    print(f"[OCR] origen={lectura.origen} pasadas={lectura.pasadas}")

    data = extractor.extract_data(raw_text) or {}

    preview_image_b64 = image_handler.to_base64(file_input, is_pdf)

    if not is_pdf and hasattr(file_input, "close"):
        try:
            file_input.close()
        except:
            pass

    doc = ScannedDocument(
        documentType=data.get("documentType"),
        documentNumber=data.get("documentNumber"),
        documentCurrency=data.get("documentCurrency"),
        documentDate=data.get("documentDate"),
        issuerRuc=data.get("issuerRuc") or [],
        issuerName=data.get("issuerName"),
        issuerAddress=data.get("issuerAddress"),
        amount=data.get("amount") or 0.0,
        items=data.get("items") or [],
        igv=data.get("igv") or 0.0,
        rawText = raw_text,
        imageBase64=preview_image_b64
    )

    extra = mobility.extract(raw_text)
    extra["legibilityScore"] = calcular_legibilidad(raw_text)

    # Trazabilidad de la lectura y de los importes: de donde salio cada dato y
    # que no cuadro. Es aditivo; la vista lo usa si quiere.
    extra["igvRate"] = data.get("igvRate")
    extra["subtotal"] = data.get("subtotal")
    extra["detalle"] = data.get("detalle")
    extra["lectura"] = {
        "origen": lectura.origen,
        "pasadas": lectura.pasadas,
        "paginas": lectura.paginas,
    }

    # Complementos: el extractor principal esta hecho para comprobantes
    # SUNAT en espanol. Si no encontro importe, fecha, numero o moneda,
    # reintentamos con patrones mas amplios (recibos de apps, en ingles).
    if not doc.amount:
        doc.amount = extraer_importe(raw_text) or doc.amount
    if not doc.documentDate:
        doc.documentDate = extraer_fecha(raw_text)
    if not doc.documentNumber:
        doc.documentNumber = extraer_numero(raw_text)
    if not doc.documentCurrency:
        doc.documentCurrency = extraer_moneda(raw_text)

    return doc, extra


def main():

    print("Iniciando proceso de OCR en batch...")

    ensure_folders()

    rucs_detectados = []

    files = [
        f for f in glob.glob(os.path.join(INPUT_FOLDER, "*"))
        if os.path.isfile(f) and extension_supported(f)
    ]

    print(f"📂 Encontrados {len(files)} documentos en '{INPUT_FOLDER}'")

    for i, file_path in enumerate(files, start=1):

        filename = os.path.basename(file_path)
        print(f"\n--- Procesando [{i}/{len(files)}]: {filename} ---")

        try:
            doc, _ = process_file(file_path)

            rucs_detectados.extend(doc.issuerRuc)

            if not doc.is_valid():
                print("   [SKIP] Datos inválidos (Faltan Monto o RUC)")
                FileMover.move(file_path, ERROR_FOLDER)
                continue

            is_transmitted = client.send_document(doc.to_dict())

            if is_transmitted:
                FileMover.move(file_path, PROCESSED_FOLDER)
            else:
                FileMover.move(file_path, ERROR_FOLDER)

        except Exception as e:
            print(f"   [FALLA CRÍTICA] Error procesando {filename}: {e}")
            try:
                if os.path.exists(file_path):
                    FileMover.move(file_path, ERROR_FOLDER)
            except Exception as move_error:
                print(f"   [MOVE ERROR] {filename}: {move_error}")

    return rucs_detectados


@app.post("/ocr/run-batch")
def run_batch():
    rucs = main()
    return {
        "status": "ok",
        "rucs": rucs
    }


@app.post("/ocr/scan")
async def scan_from_front(file: UploadFile = File(...), enhance: bool = False):

    ensure_folders()

    if not file.filename:
        raise HTTPException(status_code=400, detail="Archivo inválido")

    if not extension_supported(file.filename):
        raise HTTPException(status_code=400, detail="Formato no soportado")

    tmp_path = None

    try:
        suffix = os.path.splitext(file.filename)[1].lower()

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        await file.close()

        doc, extra = process_file(tmp_path, enhance)

        response = {
            "success": doc.is_valid(),
            "detectedData": {
                "documentType": doc.documentType,
                "documentNumber": doc.documentNumber,
                "documentCurrency": doc.documentCurrency,
                "documentDate": doc.documentDate,
                "issuerRuc": doc.issuerRuc,
                "issuerName": doc.issuerName,
                "issuerAddress": doc.issuerAddress,
                "amount": doc.amount,
                "rawText": doc.rawText,
                "items": doc.items,
                "igv": doc.igv,

                # ---- MOVILIDAD: lo consume edit-planilla-movilidad ----
                "isMobility": extra.get("isMobility"),
                "driverName": extra.get("driverName"),
                "vehicle": extra.get("vehicle"),
                "serviceType": extra.get("serviceType"),
                "pickupAddress": extra.get("pickupAddress"),
                "dropoffAddress": extra.get("dropoffAddress"),
                "pickupTime": extra.get("pickupTime"),
                "dropoffTime": extra.get("dropoffTime"),
                "distance": extra.get("distance"),
                "commercialName": extra.get("commercialName"),
                "glosaSugerida": extra.get("glosaSugerida"),
                "legibilityScore": extra.get("legibilityScore"),

                # ---- Aditivos: importes verificados y trazabilidad ----
                # La vista puede pre-llenar el % de IGV con igvRate (18% o
                # 10.5% de restaurantes, deducido del propio documento) y
                # mostrar en detalle de donde salio cada dato.
                "igvRate": extra.get("igvRate"),
                "subtotal": extra.get("subtotal"),
                "detalle": extra.get("detalle"),
                "lectura": extra.get("lectura"),
            },
            "legibilityScore": extra.get("legibilityScore"),
            "enhanced": enhance,
            "imageBase64": doc.imageBase64
        }

        if not doc.is_valid():
            return response

        final_name = f"{uuid.uuid4()}{suffix}"
        final_path = os.path.join(PROCESSED_FOLDER, final_name)

        shutil.move(tmp_path, final_path)
        tmp_path = None

        ok = client.send_document(doc.to_dict())
        response["sentToBackend"] = ok

        return response

    except Exception as e:
        print("ERROR /ocr/scan:", e)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        gc.collect()
        time.sleep(0.1)

        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except PermissionError:
                pass


if __name__ == "__main__":
    # El puerto lo define el entorno. `regina-ia` (Java) busca el OCR en
    # su ocr.api.url; hoy en produccion es el 11001.
    puerto = int(os.getenv("OCR_PORT", "11001"))
    uvicorn.run("main:app", host="0.0.0.0", port=puerto)
