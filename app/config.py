"""Shared paths + limits for the BabelGrade app.

Single home for the filesystem paths and upload limits that were module-level
constants in main.py (2026-10-16 split). Import from here, never re-define.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR.parent / "static"
UPLOAD_DIR = BASE_DIR.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_AUDIO_BYTES = 100 * 1024 * 1024
MAX_DOC_PDF_BYTES = 25 * 1024 * 1024
MAX_DOC_PDF_PAGES = 20
MAX_PAGES = 20  # same cap as the photo uploader
# The student's work may also be a single PDF (2026-11-25): a handwritten
# copy exported/scanned as PDF, or a typed submission. Same 25 MB / 20 page
# caps as the task-context PDFs.
MAX_COPY_PDF_BYTES = 25 * 1024 * 1024
MAX_COPY_PDF_PAGES = 20

_SET_NULL = object()  # sentinel: force a column to NULL in teacher-update SQL
ALLOWED_IMAGE = {"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff", "heic"}
ALLOWED_AUDIO = {"wav", "mp3", "m4a", "aac", "ogg", "opus", "flac", "mp4"}
