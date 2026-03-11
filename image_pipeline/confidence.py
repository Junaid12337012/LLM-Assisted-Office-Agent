from __future__ import annotations


def combine_confidence(ocr_confidence: float, matched: bool) -> float:
    return round(ocr_confidence if matched else max(0.0, ocr_confidence - 0.35), 3)
