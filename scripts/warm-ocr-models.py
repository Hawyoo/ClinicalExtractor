"""Prepare the exact PP-OCRv5 + SLANet_plus cache used by ClinicalExtractor.

The build BAT sets PADDLE_PDX_CACHE_HOME to a project-local staging folder.
Explicitly prepare both the primary OCR and the lazy table fallback models.
The folder is then copied verbatim into the Portable edition.
"""
from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from clinical_extractor.parser import ReportParser


def main() -> None:
    print("Preparing PP-OCRv5 + SLANet_plus offline models.")
    pipeline = ReportParser()._get_pipeline(table_mode=True)
    pipeline.prepare_fallback_model()
    print("Offline OCR model cache is ready.")


if __name__ == "__main__":
    main()
