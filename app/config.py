import os

# File System Paths
INPUT_FOLDER = "./input"
PROCESSED_FOLDER = "./processed"
ERROR_FOLDER = "./error"

# Processing Settings
SUPPORTED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.pdf')

# Network Settings
BACKEND_URL = "http://localhost:8080/api/documents"
# Ruta de Poppler (pdf2image). Sobreescribible por variable de entorno
# para no depender de una ruta fija en el codigo.
POPPLER_PATH = os.getenv("POPPLER_PATH", r"C:\poppler\Library\bin")

# Si esa carpeta no existe (otro servidor, otra instalacion, o Linux), se deja
# en None y pdf2image busca Poppler en el PATH del sistema. Antes, una ruta
# equivocada hacia fallar la conversion de PDF con "Is poppler installed?"
if POPPLER_PATH and not os.path.isdir(POPPLER_PATH):
    POPPLER_PATH = None

# URL del backend Java que recibe los documentos escaneados.
BACKEND_URL = os.getenv("BACKEND_URL", BACKEND_URL)
