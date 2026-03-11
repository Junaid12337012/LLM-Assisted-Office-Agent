from __future__ import annotations

from pathlib import Path


def read_text_hint(image_path: str | Path) -> dict[str, str | float]:
    source = Path(image_path)
    return {"ocr_text": source.stem, "ocr_confidence": 0.95}
