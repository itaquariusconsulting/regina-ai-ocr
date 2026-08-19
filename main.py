import os
import glob
import uuid
import shutil
import tempfile
import uvicorn
import gc
import time

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.utils.file_mover import FileMover
from app.core.extractor import DataExtractor
from app.ocr.lector import Lector
from app.network.backend_client import BackendClient
from app.domain import ScannedDocument
from app.config import INPUT_FOLDER, PROCESSED_FOLDER, ERROR_FOLDER, SUPPORTED_EXTENSIONS


app = FastAPI()

# -------------------------------
# CORS
# -------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------------
# Dependencias
# -------------------------------
# El lector resuelve PDF con texto, PDF imagen y fotos; el extractor saca los
# campos. Si Tesseract o Poppler no estan en el PATH del servidor, se indican
# aca (en Windows suele hacer falta el poppler_path).
lector = Lector(
    tesseract_cmd=os.environ.get("TESSERACT_CMD"),
    poppler_path=os.environ.get("POPPLER_PATH"),
)
extractor = DataExtractor()
client = BackendClient()


# -------------------------------
# Utilidades
# -------------------------------
def ensure_folders():
    for folder in (INPUT_FOLDER, PROCESSED_FOLDER, ERROR_FOLDER):
        os.makedirs(folder, exist_ok=True)


def extension_supported(filename: str) -> bool:
    return filename.lower().endswith(tuple(SUPPORTED_EXTENSIONS))


# -------------------------------
# Pipeline común
# -------------------------------
def process_file(path: str, ruc_consultante: str = None):
    """
    Lee el documento y extrae sus campos.

    Devuelve (documento, datos_completos, lectura):
      - documento: ScannedDocument con los campos historicos
      - datos_completos: todo lo que saco el extractor, incluidos los campos
        nuevos (razon social, IGV, moneda, confianza y advertencias)
      - lectura: de donde salio el texto (PDF nativo o que pasada de OCR)

    El lector para apenas tiene los campos criticos, asi que un PDF con texto
    o una imagen limpia se resuelven en la primera pasada; las pasadas caras
    (binarizacion, enderezado, 400 dpi) solo corren cuando hacen falta.
    """
    lectura = lector.leer(path, suficiente=extractor.campos_criticos_completos)

    data = extractor.extract_data(lectura.texto, ruc_consultante) or {}

    doc = ScannedDocument(
        documentType=data.get("documentType"),
        documentNumber=data.get("documentNumber"),
        documentDate=data.get("documentDate"),
        issuerRuc=data.get("issuerRuc"),
        issuerAddress=data.get("issuerAddress"),
        amount=data.get("amount") or 0.0,
        rawText=lectura.texto,
        imageBase64=lector.previsualizacion_base64(path),
    )

    return doc, data, lectura


# -------------------------------
# Lógica batch
# -------------------------------
def main():

    print("Iniciando proceso de OCR en batch...")

    ensure_folders()

    files = [
        f for f in glob.glob(os.path.join(INPUT_FOLDER, "*"))
        if os.path.isfile(f) and extension_supported(f)
    ]

    print(f"📂 Encontrados {len(files)} documentos en '{INPUT_FOLDER}'")

    for i, file_path in enumerate(files, start=1):

        filename = os.path.basename(file_path)
        print(f"\n--- Procesando [{i}/{len(files)}]: {filename} ---")

        try:
            doc, _datos, _lectura = process_file(file_path)

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


# -------------------------------
# Endpoint batch
# -------------------------------
@app.post("/ocr/run-batch")
def run_batch():
    main()
    return {"status": "ok"}


# -------------------------------
# Endpoint para Angular / móvil
# Devuelve siempre los datos detectados
# Solo guarda si es válido
# -------------------------------
@app.post("/ocr/scan")
async def scan_from_front(file: UploadFile = File(...),
                          ruc_consultante: str = Form(None)):
    """
    `ruc_consultante` es opcional: si la vista manda el RUC de la empresa, el
    extractor lo descarta al elegir el RUC del emisor (en una factura de
    compra ese RUC es siempre el del cliente). Sin el, igual funciona: la
    deteccion se apoya en la vecindad del titulo y la serie.
    """

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

        doc, datos, lectura = process_file(tmp_path, ruc_consultante)

        response = {
            "success": doc.is_valid(),
            "detectedData": {
                # --- claves de siempre ---
                "documentType": doc.documentType,
                "documentNumber": doc.documentNumber,
                "documentDate": doc.documentDate,
                "issuerRuc": doc.issuerRuc,
                "issuerAddress": doc.issuerAddress,
                "amount": doc.amount,
                "rawText": doc.rawText,

                # --- nuevas, aditivas: la vista las usa si quiere ---
                "issuerName": datos.get("issuerName"),
                "clientRuc": datos.get("clientRuc"),
                "currency": datos.get("currency"),
                "subtotal": datos.get("subtotal"),
                "igv": datos.get("igv"),
                "igvRate": datos.get("igvRate"),
                "detalle": datos.get("detalle"),
            },
            "lectura": {
                "origen": lectura.origen,
                "pasadas": lectura.pasadas,
                "paginas": lectura.paginas,
            },
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


# -------------------------------
# Arranque
# -------------------------------
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=6701, reload=True)
