"""Prepare the exact PP-StructureV3 model cache used by ClinicalExtractor.

The build BAT sets PADDLE_PDX_CACHE_HOME to a project-local staging folder.
Constructing the pipeline makes PaddleOCR fetch every enabled OCR, layout and
table model.  The folder is then copied verbatim into the Portable edition.
"""
from __future__ import annotations

from paddleocr import PPStructureV3


def main() -> None:
    print("Preparing PP-StructureV3 models. This is needed only while building.")
    PPStructureV3(
        use_doc_orientation_classify=True,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        use_formula_recognition=False,
        device="cpu",
    )
    print("Offline PP-StructureV3 model cache is ready.")


if __name__ == "__main__":
    main()
