import os
import glob
import uuid
import shutil
import tempfile
import uvicorn
import gc
import time

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.utils.file_mover import FileMover
from app.core.extractor import DataExtractor
from app.infrastructure.image_handler import ImageHandler
from app.network.backend_client import BackendClient
from app.domain import ScannedDocument
from app.config import INPUT_FOLDER, PROCESSED_FOLDER, ERROR_FOLDER, SUPPORTED_EXTENSIONS


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

image_handler = ImageHandler()
extractor = DataExtractor()
client = BackendClient()

def ensure_folders():
    for folder in (INPUT_FOLDER, PROCESSED_FOLDER, ERROR_FOLDER):
        os.makedirs(folder, exist_ok=True)

def extension_supported(filename: str) -> bool:
    return filename.lower().endswith(tuple(SUPPORTED_EXTENSIONS))

def process_file(path: str) -> ScannedDocument:

    file_input, is_pdf = image_handler.load_image(path)

    raw_text = image_handler.extract_text(file_input, is_pdf)

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
        rawText = raw_text,
        imageBase64=preview_image_b64
    )

    return doc


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
            doc = process_file(file_path)

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
async def scan_from_front(file: UploadFile = File(...)):

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

        doc = process_file(tmp_path)

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
                "items": doc.items
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


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=6701, reload=True)
