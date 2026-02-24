import cv2
import numpy as np
import pytesseract
import base64
import pdfplumber
from pdf2image import convert_from_path
from PIL import Image
from io import BytesIO


class ImageHandler:

    def __init__(self, tesseract_cmd=None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def load_image(self, file_path: str):
        """Loads file. Returns (ImageObject, is_native_pdf)."""
        if file_path.lower().endswith('.pdf'):
            return file_path, True
        return Image.open(file_path), False

    def extract_text(self, file_input, is_pdf: bool) -> str:
        """Hybrid Extraction: Tries Native PDF first, then OCR."""

        # STRATEGY 1: Native PDF
        if is_pdf:
            try:
                text = ""
                with pdfplumber.open(file_input) as pdf:
                    for page in pdf.pages:
                        page_text = page.extract_text(x_tolerance=2, y_tolerance=2)
                        if page_text:
                            text += page_text + "\n"

                if len(text.strip()) > 50:
                    print("✅ Used Native PDF Extraction")
                    return text

            except Exception as e:
                print(f"⚠️ Native PDF failed, falling back to OCR: {e}")

        # STRATEGY 2: OCR
        if is_pdf:
            images = convert_from_path(file_input, dpi=300)
            pil_image = images[0]
        else:
            pil_image = file_input

        processed_img = self._preprocess_for_ocr(pil_image)

        print("🔍 Running OCR...")
        return pytesseract.image_to_string(processed_img, config="--psm 6")

    # ---- CORREGIDO (sin staticmethod y sin self duplicado)
    def _preprocess_for_ocr(self, pil_image: Image.Image) -> np.ndarray:

        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        img = np.array(pil_image)

        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        # Reescalar (mejora OCR)
        target_width = 2500
        scale = target_width / img.shape[1]
        dim = (target_width, int(img.shape[0] * scale))

        resized = cv2.resize(img, dim, interpolation=cv2.INTER_CUBIC)

        return resized

    def to_base64(self, file_input, is_pdf: bool) -> str:
        if is_pdf:
            images = convert_from_path(
                file_input,
                dpi=300,
                poppler_path=r"C:\poppler\Library\bin"
            )
            pil_image = images[0]
        else:
            pil_image = file_input

        # --- FIX RGBA -> RGB (error cannot write mode RGBA as JPEG)
        if pil_image.mode in ("RGBA", "LA", "P"):
            pil_image = pil_image.convert("RGB")

        buffered = BytesIO()
        pil_image.save(buffered, format="JPEG", quality=70)

        return (
            "data:image/jpeg;base64,"
            + base64.b64encode(buffered.getvalue()).decode("utf-8")
        )
