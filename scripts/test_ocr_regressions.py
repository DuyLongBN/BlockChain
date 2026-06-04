"""Small OCR regression checks that do not require loading EasyOCR models."""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import inference
from inference import LicensePlateRecognizer


class FakeTopRowReader:
    def readtext(self, *_args, **_kwargs):
        return [
            (
                [[0, 0], [80, 0], [80, 24], [0, 24]],
                "59-V2",
                0.82,
            )
        ]


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def main():
    recognizer = LicensePlateRecognizer(use_yolo=False)
    inference.EASYOCR_AVAILABLE = True
    recognizer.ocr = FakeTopRowReader()

    assert_equal(
        recognizer._normalize_vietnamese_plate_candidate("59-V2-08217"),
        "59-V2-08217",
        "direct V series must be preserved",
    )

    original = {
        "method": "easyocr",
        "strategy": "direct",
        "plate_number": "59-V2-08217",
        "confidence": 0.69,
        "raw_text": "59-V2-08217",
    }
    square_crop = np.zeros((100, 100, 3), dtype=np.uint8)
    assert_equal(
        recognizer._correct_two_line_plate_top_with_ocr(original, square_crop),
        original,
        "an inferred top-row read must not replace a direct series letter",
    )

    inferred = {
        "method": "easyocr",
        "strategy": "direct",
        "plate_number": "59-T2-08217",
        "confidence": 0.67,
        "raw_text": "59-12-08217",
    }
    corrected = recognizer._correct_two_line_plate_top_with_ocr(inferred, square_crop)
    assert_equal(
        corrected["plate_number"],
        "59-V2-08217",
        "direct top-row consensus must replace inferred 1 -> T series",
    )

    print("OCR regression checks passed: 3/3")


if __name__ == "__main__":
    main()
