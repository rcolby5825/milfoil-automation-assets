#!/usr/bin/env python3
"""
worker_determine_scale.py — standalone worker, no Inkscape/inkex dependency.

Measures the grid mat's actual spacing in the photo (multi-region Hough
line sampling, confirmed reliable during testing: 4 independent regions
on a real photo landed within 64-75px of each other, median 69.5px, std
~3-4px) and computes the correct display width/height for the image so
that one grid square equals a known real-world size (default 25.4mm/1
inch) in the document.

USAGE:
    python3 worker_determine_scale.py image_path result_json_path \
        --grid-size-mm 25.4 [--force]

OUTPUT (written to result_json_path):
    {
      "success": true/false,
      "message": "...",
      "img_w_px": int, "img_h_px": int,
      "px_per_grid_square": float or null,
      "target_display_w": float or null,   # in document user units
      "target_display_h": float or null,
      "region_measurements": [...],         # for diagnostics
      "confidence_std": float or null
    }

CONFIDENCE CHECK: samples grid spacing in several regions across the
photo. If measurements disagree too much (std too high relative to the
median), refuses rather than guessing — same philosophy as
worker_correct_perspective.py. Run Correct Perspective BEFORE this for
best reliability (a skewed grid makes spacing measurement noisier).
"""

import argparse
import json
import sys

try:
    import cv2
    import numpy as np
except ImportError:
    print("ERROR: opencv/numpy not installed in this environment. "
          "Run: pip install opencv-python-headless numpy", file=sys.stderr)
    sys.exit(1)


CONFIDENCE_STD_RATIO_THRESHOLD = 0.15  # std/median above this = too inconsistent to trust
MIN_REGIONS_WITH_DATA = 3


def measure_region_spacing(region, gap=30):
    """Returns (h_spacing, v_spacing) in px for one image region, or (None, None)."""
    edges = cv2.Canny(region, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 360, threshold=300)
    if lines is None:
        return None, None

    horiz, vert = [], []
    for l in lines:
        rho, theta = l[0]
        deg = np.degrees(theta)
        if abs(deg - 90) < 10:
            horiz.append((rho, theta))
        elif deg < 10 or deg > 170:
            vert.append((rho, theta if deg < 10 else theta - np.pi))

    def cluster(candidates):
        if not candidates:
            return []
        candidates = sorted(candidates, key=lambda x: x[0])
        clusters = []
        current = [candidates[0]]
        for c in candidates[1:]:
            if c[0] - current[-1][0] < gap:
                current.append(c)
            else:
                clusters.append(current)
                current = [c]
        clusters.append(current)
        return [np.mean([c[0] for c in cl]) for cl in clusters]

    h_rhos = sorted(cluster(horiz))
    v_rhos = sorted(cluster(vert))
    h_sp = np.diff(h_rhos) if len(h_rhos) > 1 else []
    v_sp = np.diff(v_rhos) if len(v_rhos) > 1 else []

    h_med = float(np.median(h_sp)) if len(h_sp) else None
    v_med = float(np.median(v_sp)) if len(v_sp) else None
    return h_med, v_med


def sample_regions(gray, n_regions_per_side=2, margin_frac=0.15, region_frac=0.2):
    """Yields (y1,y2,x1,x2) boxes spread across the image, away from the edges
    (where ruler/piece/mat-seam are more likely to contaminate the measurement)."""
    h, w = gray.shape
    region_h = int(h * region_frac)
    region_w = int(w * region_frac)
    y_positions = np.linspace(h * margin_frac, h * (1 - margin_frac) - region_h, n_regions_per_side)
    x_positions = np.linspace(w * margin_frac, w * (1 - margin_frac) - region_w, n_regions_per_side)
    for y in y_positions:
        for x in x_positions:
            y1, x1 = int(y), int(x)
            yield (y1, y1 + region_h, x1, x1 + region_w)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image_path")
    ap.add_argument("result_json_path")
    ap.add_argument("--grid-size-mm", type=float, default=25.4)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    result = {
        "success": False, "message": "", "img_w_px": 0, "img_h_px": 0,
        "px_per_grid_square": None, "target_display_w": None, "target_display_h": None,
        "region_measurements": [], "confidence_std": None,
    }

    img = cv2.imread(args.image_path)
    if img is None:
        result["message"] = f"Could not open image: {args.image_path}"
        _write_and_exit(args.result_json_path, result)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    result["img_w_px"] = w
    result["img_h_px"] = h

    measurements = []
    for (y1, y2, x1, x2) in sample_regions(gray):
        region = gray[y1:y2, x1:x2]
        h_sp, v_sp = measure_region_spacing(region)
        if h_sp:
            measurements.append(h_sp)
        if v_sp:
            measurements.append(v_sp)
        result["region_measurements"].append({"box": [y1, y2, x1, x2], "h": h_sp, "v": v_sp})

    if len(measurements) < MIN_REGIONS_WITH_DATA:
        result["message"] = (
            f"Only got {len(measurements)} usable spacing measurement(s), need at least "
            f"{MIN_REGIONS_WITH_DATA}. Check the photo shows clear, unobstructed grid in "
            f"multiple areas."
        )
        _write_and_exit(args.result_json_path, result)

    median_spacing = float(np.median(measurements))
    std_spacing = float(np.std(measurements))
    std_ratio = std_spacing / median_spacing if median_spacing else 999
    result["confidence_std"] = std_spacing

    if std_ratio > CONFIDENCE_STD_RATIO_THRESHOLD and not args.force:
        result["message"] = (
            f"Grid spacing measurements too inconsistent across the photo to trust "
            f"(median {median_spacing:.1f}px, std {std_spacing:.1f}px, ratio {std_ratio:.2f} > "
            f"threshold {CONFIDENCE_STD_RATIO_THRESHOLD}). Try running Correct Perspective first, "
            f"or recapture with the grid more clearly visible."
        )
        _write_and_exit(args.result_json_path, result)

    result["px_per_grid_square"] = median_spacing

    px_per_mm = median_spacing / args.grid_size_mm
    result["target_display_w"] = w / px_per_mm
    result["target_display_h"] = h / px_per_mm

    result["success"] = True
    result["message"] = (
        f"Grid spacing: {median_spacing:.2f}px = {args.grid_size_mm}mm "
        f"(std {std_spacing:.2f}px across {len(measurements)} measurements). "
        f"Target display size: {result['target_display_w']:.2f} x {result['target_display_h']:.2f} "
        f"document units."
    )

    _write_and_exit(args.result_json_path, result)


def _write_and_exit(path, result):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f)
    print(result["message"])
    sys.exit(0)


if __name__ == "__main__":
    main()
