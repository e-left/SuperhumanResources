"""Extract text from an uploaded CV (PDF, TXT or Markdown)."""

import io
import pathlib

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARS = 20_000
SUFFIXES = {".pdf", ".txt", ".md"}


class CvError(Exception):
    pass


def suffix(filename: str) -> str:
    found = pathlib.Path(filename or "").suffix.lower()
    if found not in SUFFIXES:
        raise CvError("the CV must be a PDF, TXT or MD file")
    return found


def extract_text(filename: str, data: bytes) -> str:
    kind = suffix(filename)
    if len(data) > MAX_BYTES:
        raise CvError("the CV is larger than 5 MB")
    if kind == ".pdf":
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:  # pypdf raises many types on damaged files
            raise CvError("the CV could not be read as a PDF") from exc
    else:
        text = data.decode("utf-8", errors="replace")
    text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    if not text:
        raise CvError("the CV contains no readable text (a scanned PDF needs OCR first)")
    return text[:MAX_CHARS]
