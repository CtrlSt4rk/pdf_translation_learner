"""PDF text extraction and self-contained sentence segmentation."""

import re
from pathlib import Path

import fitz  # PyMuPDF

ABBREVIATIONS = (
    r"(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bProf)(?<!\bSr)(?<!\bSra)"
    r"(?<!\bSt)(?<!\bvs)(?<!\betc)(?<!\be\.g)(?<!\bi\.e)(?<!\bFig)(?<!\bVol)"
)
SENTENCE_SPLIT_RE = re.compile(ABBREVIATIONS + r"(?<=[.!?…])\s+(?=[A-ZÁÉÍÓÚÀÂÊÔÃÕÜÇ\"'“‘(])")


def extract_sentences_from_pdf(pdf_path: Path) -> list[str]:
    """Extract text from PDF, stitch hyphenated line breaks, and split into sentences."""
    doc = fitz.open(pdf_path)
    raw_pages = []

    for page in doc:
        text = page.get_text("text")
        text = re.sub(r"-\s*\n\s*", "", text)
        text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
        raw_pages.append(text)

    full_text = "\n\n".join(raw_pages)
    full_text = re.sub(r"[ \t]+", " ", full_text)

    sentences = []
    for paragraph in full_text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for s in SENTENCE_SPLIT_RE.split(paragraph):
            s = s.strip()
            if len(s) > 3 and not s.isdigit():
                sentences.append(s)
    return sentences
