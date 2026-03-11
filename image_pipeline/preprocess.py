from __future__ import annotations

import shutil
from pathlib import Path


def normalize_for_ocr(image_path: str | Path, output_path: str | Path) -> dict[str, str]:
    source = Path(image_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return {"preprocessed_path": str(target)}
