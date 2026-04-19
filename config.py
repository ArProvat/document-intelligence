from pathlib import Path
from typing import Set

BASE_DIR    = Path(__file__).parent.parent
UPLOAD_DIR  = BASE_DIR / "uploads"
PROCESSED_DIR = BASE_DIR / "processed"

UPLOAD_DIR.mkdir(exist_ok=True)
PROCESSED_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS: Set[str] = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
MAX_FILE_SIZE_MB = 50

OCR_CONFIDENCE_THRESHOLD = 0.6   
OCR_DPI = 300                     
TESSERACT_LANG = "eng"
TESSERACT_CONFIG = "--oem 3 --psm 3"  

MIN_TEXT_LENGTH_PER_PAGE = 30     
NATIVE_TEXT_MIN_CHARS = 100       


CHUNK_SIZE_TOKENS   = 400         
CHUNK_OVERLAP_TOKENS = 80
CHARS_PER_TOKEN     = 4           

CHUNK_SIZE_CHARS    = CHUNK_SIZE_TOKENS * CHARS_PER_TOKEN
CHUNK_OVERLAP_CHARS = CHUNK_OVERLAP_TOKENS * CHARS_PER_TOKEN
