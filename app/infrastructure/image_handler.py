import cv2
import numpy as np
import pytesseract
import base64
import pdfplumber
from pdf2image import convert_from_path
from PIL import Image
from io import BytesIO

from app.config import POPPLER_PATH


class ImageHandler:

    def __init__(self, tesseract_cmd=None):
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    def load_image(self, file_path: str):
        """Loads file. Returns (ImageObject, is_native_pdf)."""
        if file_path.lower().endswith('.pdf'):
            return file_path, True
        return Image.open(file_path), False

    def extract_text(self, file_input, is_pdf: bool, enhance: bool = False) -> str:
        """Hybrid Extraction: Tries Native PDF first, then OCR."""

        # STRATEGY 1: Native PDF
        # Con enhance=True se fuerza el OCR: si el PDF trae texto nativo no
        # hay imagen que mejorar, y el usuario pidio explicitamente reintentar.
        if is_pdf and not enhance:
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
            images = convert_from_path(file_input, dpi=300,
                                       poppler_path=POPPLER_PATH)
            pil_image = images[0]
        else:
            pil_image = file_input

        processed_img = (self._preprocess_strong(pil_image) if enhance
                         else self._preprocess_for_ocr(pil_image))

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

    def _preprocess_strong(self, pil_image: Image.Image) -> np.ndarray:
        """
        Pipeline agresivo para comprobantes ilegibles (enhance=True):
        gris -> reescalado que solo agranda -> reduccion de ruido conservando
        bordes -> umbral adaptativo -> correccion de inclinacion.
        """
        if pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")

        img = np.array(pil_image)
        if len(img.shape) == 3:
            img = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        objetivo = 3000
        escala = objetivo / img.shape[1]
        if escala > 1:
            img = cv2.resize(img, (objetivo, int(img.shape[0] * escala)),
                             interpolation=cv2.INTER_CUBIC)

        img = cv2.bilateralFilter(img, 9, 75, 75)
        img = cv2.adaptiveThreshold(
            img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 31, 15)

        return self._deskew(img)

    @staticmethod
    def _deskew(img):
        """Endereza el papel torcido. Ante cualquier duda devuelve el original."""
        try:
            coords = np.column_stack(np.where(img < 255))
            if coords.size == 0:
                return img
            angulo = cv2.minAreaRect(coords)[-1]
            angulo = -(90 + angulo) if angulo < -45 else -angulo
            if abs(angulo) < 0.5 or abs(angulo) > 20:
                return img
            alto, ancho = img.shape[:2]
            m = cv2.getRotationMatrix2D((ancho // 2, alto // 2), angulo, 1.0)
            return cv2.warpAffine(img, m, (ancho, alto),
                                  flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_REPLICATE)
        except Exception:
            return img

    def to_base64(self, file_input, is_pdf: bool) -> str:
        if is_pdf:
            images = convert_from_path(
                file_input,
                dpi=300,
                poppler_path=POPPLER_PATH
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
