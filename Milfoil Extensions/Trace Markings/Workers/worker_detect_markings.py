#!/usr/bin/env python3
"""
worker_detect_markings.py — standalone worker, no Inkscape/inkex dependency.

Called by milfoil_trace_markings.py as a subprocess, running under a
separate venv's Python (not Inkscape's bundled one).

USAGE:
    python3 worker_detect_markings.py image_path output_json_path \
        --circles --grainline --arrows

    Flags are optional; only requested detections run.

OUTPUT (written to output_json_path):
    {
      "img_w_px": int, "img_h_px": int,
      "circles": [{"cx":.., "cy":.., "r":..}, ...],
      "grainline": [x1, y1, x2, y2] or null,
      "arrows": [[[x,y],[x,y],[x,y]], ...]
    }

CONFIDENCE NOTES (same as before — worth repeating here since this is the
part doing the actual detection):
    - circles: reliable
    - grainline: experimental, tends to false-positive on straight piece
      outlines — verify before trusting
    - arrows: experimental, works cleanly on isolated clean triangles in
      testing, expect more false positives on real faded/textured photos
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    print("ERROR: opencv/numpy not installed in this environment. "
          "Run: pip install opencv-python-headless numpy", file=sys.stderr)
    sys.exit(1)

try:
    import pytesseract
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


DOT_MIN_RADIUS = 4
DOT_MAX_RADIUS = 15
GRAINLINE_MIN_LENGTH = 150
GRAINLINE_MAX_SPAN_RATIO = 0.85
ARROW_MIN_AREA = 20
ARROW_MAX_AREA = 400
TEXT_MASK_CONFIDENCE = 40


def mask_out_text(gray):
    """
    Paints over detected text regions before circle detection.

    Without this, letters with circular strokes (O, D, B, etc.) get
    misdetected as dot markings — confirmed during testing on a text-heavy
    sample. Falls back to returning the image unchanged (with a warning)
    if pytesseract/tesseract isn't installed in this environment, since
    circle detection alone is still useful, just less reliable near text.
    """
    if not HAS_OCR:
        print("WARNING: pytesseract not installed — skipping text-masking step. "
              "Circle detection may false-positive on text (letters like O, D, B). "
              "Install with: pip install pytesseract (plus the tesseract-ocr system package)",
              file=sys.stderr)
        return gray

    data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
    masked = gray.copy()
    pad = 3
    for i in range(len(data["text"])):
        if not data["text"][i].strip():
            continue
        conf = int(data["conf"][i]) if data["conf"][i] != "-1" else -1
        if conf < TEXT_MASK_CONFIDENCE:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        cv2.rectangle(masked, (max(0, x - pad), max(0, y - pad)), (x + w + pad, y + h + pad), 255, -1)
    return masked


def detect_dots(gray):
    text_masked = mask_out_text(gray)
    blurred = cv2.medianBlur(text_masked, 5)
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1, minDist=20,
        param1=50, param2=10, minRadius=DOT_MIN_RADIUS, maxRadius=DOT_MAX_RADIUS
    )
    if circles is None:
        return []
    return [{"cx": float(x), "cy": float(y), "r": float(r)} for x, y, r in circles[0]]


def detect_grainline(gray):
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=80,
        minLineLength=GRAINLINE_MIN_LENGTH, maxLineGap=10
    )
    if lines is None:
        return None
    h, w = gray.shape
    best, best_len = None, 0
    for line in lines:
        x1, y1, x2, y2 = line[0]
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if abs(x2 - x1) / w > GRAINLINE_MAX_SPAN_RATIO or abs(y2 - y1) / h > GRAINLINE_MAX_SPAN_RATIO:
            continue
        if length > best_len:
            best_len, best = length, [int(x1), int(y1), int(x2), int(y2)]
    return best


def detect_arrows(gray):
    _, binary = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    results = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (ARROW_MIN_AREA <= area <= ARROW_MAX_AREA):
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)
        if len(approx) == 3:
            results.append([[int(pt[0][0]), int(pt[0][1])] for pt in approx])
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image_path")
    ap.add_argument("output_json_path")
    ap.add_argument("--circles", action="store_true")
    ap.add_argument("--grainline", action="store_true")
    ap.add_argument("--arrows", action="store_true")
    args = ap.parse_args()

    img = cv2.imread(args.image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        print(f"ERROR: could not read image: {args.image_path}", file=sys.stderr)
        sys.exit(1)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    h, w = gray.shape[:2]

    output = {"img_w_px": w, "img_h_px": h, "circles": [], "grainline": None, "arrows": []}

    if args.circles:
        output["circles"] = detect_dots(gray)
    if args.grainline:
        output["grainline"] = detect_grainline(gray)
    if args.arrows:
        output["arrows"] = detect_arrows(gray)

    Path(args.output_json_path).write_text(json.dumps(output), encoding="utf-8")
    print(f"OK: {len(output['circles'])} circle(s), "
          f"grainline {'found' if output['grainline'] else 'none'}, "
          f"{len(output['arrows'])} candidate arrow(s)")


if __name__ == "__main__":
    main()
