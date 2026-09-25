import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
from docx import Document

logger = logging.getLogger(__name__)


class DocumentIngestError(Exception):
    pass


@dataclass
class PageText:
    filename: str
    page_number: int
    text: str

    def to_dict(self) -> dict:
        return {"filename": self.filename, "page_number": self.page_number, "text": self.text}


class DocumentIngester:
    def __init__(self, corpus_dir: str | Path):
        self.corpus_dir = Path(corpus_dir)

    def ingest_corpus(self) -> list[dict]:
        if not self.corpus_dir.exists():
            raise DocumentIngestError(f"El directorio del corpus no existe: {self.corpus_dir}")

        files = sorted(
            file_path
            for pattern in ("*.pdf", "*.docx", "*.md")
            for file_path in self.corpus_dir.glob(pattern)
        )
        if not files:
            logger.warning("No se encontraron archivos soportados en %s", self.corpus_dir)

        pages: list[dict] = []
        for file_path in files:
            try:
                pages.extend(page.to_dict() for page in self.ingest_file(file_path))
            except DocumentIngestError as exc:
                logger.error("Error al procesar %s: %s", file_path.name, exc)
                continue

        return pages

    def ingest_file(self, file_path: str | Path) -> list[PageText]:
        file_path = Path(file_path)

        if not file_path.exists():
            raise DocumentIngestError(f"El archivo no existe: {file_path}")

        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            return self._ingest_pdf(file_path)
        if suffix == ".docx":
            return self._ingest_docx(file_path)
        if suffix == ".md":
            return self._ingest_markdown(file_path)

        raise DocumentIngestError(f"Formato no soportado (solo PDF, DOCX, MD): {file_path.name}")

    def _ingest_pdf(self, file_path: Path) -> list[PageText]:
        pages: list[PageText] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page_number, page in enumerate(pdf.pages, start=1):
                    raw_text = page.extract_text() or ""
                    clean_text = self._clean_text(raw_text)
                    if not clean_text:
                        logger.warning("Pagina %s de %s sin texto extraible, se omite", page_number, file_path.name)
                        continue
                    pages.append(PageText(filename=file_path.name, page_number=page_number, text=clean_text))
        except Exception as exc:
            raise DocumentIngestError(f"No se pudo leer el PDF {file_path.name}: {exc}") from exc

        return pages

    def _ingest_docx(self, file_path: Path) -> list[PageText]:
        try:
            document = Document(file_path)
            raw_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        except Exception as exc:
            raise DocumentIngestError(f"No se pudo leer el DOCX {file_path.name}: {exc}") from exc

        clean_text = self._clean_text(raw_text)
        if not clean_text:
            logger.warning("%s sin texto extraible, se omite", file_path.name)
            return []

        return [PageText(filename=file_path.name, page_number=1, text=clean_text)]

    def _ingest_markdown(self, file_path: Path) -> list[PageText]:
        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            raise DocumentIngestError(f"No se pudo leer el Markdown {file_path.name}: {exc}") from exc

        clean_text = self._clean_text(raw_text)
        if not clean_text:
            logger.warning("%s sin texto extraible, se omite", file_path.name)
            return []

        return [PageText(filename=file_path.name, page_number=1, text=clean_text)]

    @staticmethod
    def _clean_text(text: str) -> str:
        text = text.replace("\xa0", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
