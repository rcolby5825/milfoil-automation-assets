#!/usr/bin/env python3
"""
worker_correct_perspective.py — standalone worker, no Inkscape/inkex
dependency. Called by milfoil_correct_perspective.py as a subprocess,
running under a separate venv's Python.

Core logic is the same as the standalone correct_perspective.py script —
see that file's docstring for full detail on what this does and doesn't
correct, and why the confidence check exists. This version is adapted to
take its confidence threshold as a CLI arg (so the Inkscape extension can
expose it) and to always write SOME output file, tagging success/failure
in the JSON result rather than exiting non-zero, since it's driven by
another script rather than a person watching a terminal.

USAGE:
    python3 worker_correct_perspective.py input_path output_path result_json_path [--force] [--confidence-threshold N]

OUTPUT (written to result_json_path):
    {
      "success": true/false,
      "message": "...",
      "horiz_count": int, "vert_count": int,
      "horiz_std": float, "vert_std": float,
      "pre_horiz_dev": float, "pre_vert_dev": float
    }
    If success is true, the corrected image was written to output_path.
    If false, output_path was NOT written — caller should leave the
    original image alone.
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


MIN_LINE_COUNT = 50


def measure_grid_lines(gray, angle_window=10):
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLines(edges, 1, np.pi / 360, threshold=500)
    if lines is None:
        return None

    horiz_theta, vert_theta = [], []
    for l in lines:
        rho, theta = l[0]
        deg = np.degrees(theta)
        if abs(deg - 90) < angle_window:
            horiz_theta.append(theta)
        elif deg < angle_window:
            vert_theta.append(theta)
        elif deg > 180 - angle_window:
            vert_theta.append(theta - np.pi)
    return horiz_theta, vert_theta


def compute_correction(horiz_theta, vert_theta):
    h_theta_med = np.median(horiz_theta)
    v_theta_med = np.median(vert_theta)

    h_dir = np.array([-np.sin(h_theta_med), np.cos(h_theta_med)])
    v_dir = np.array([-np.sin(v_theta_med), np.cos(v_theta_med)])

    h_target = np.array([1.0 if h_dir[0] >= 0 else -1.0, 0.0])
    v_target = np.array([0.0, 1.0 if v_dir[1] >= 0 else -1.0])

    observed = np.column_stack([h_dir, v_dir])
    target = np.column_stack([h_target, v_target])
    return target @ np.linalg.inv(observed)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_path")
    ap.add_argument("output_path")
    ap.add_argument("result_json_path")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--confidence-threshold", type=float, default=4.0)
    args = ap.parse_args()

    result = {"success": False, "message": "", "horiz_count": 0, "vert_count": 0,
              "horiz_std": None, "vert_std": None, "pre_horiz_dev": None, "pre_vert_dev": None}

    img = cv2.imread(args.input_path)
    if img is None:
        result["message"] = f"Could not open image: {args.input_path}"
        _write_and_exit(args.result_json_path, result)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    lines_result = measure_grid_lines(gray)
    if lines_result is None:
        result["message"] = "No lines detected — check the photo actually shows the grid mat."
        _write_and_exit(args.result_json_path, result)

    horiz_theta, vert_theta = lines_result
    result["horiz_count"] = len(horiz_theta)
    result["vert_count"] = len(vert_theta)

    if (len(horiz_theta) < MIN_LINE_COUNT or len(vert_theta) < MIN_LINE_COUNT) and not args.force:
        result["message"] = (
            f"Not enough grid lines detected to trust a correction "
            f"(horizontal: {len(horiz_theta)}, vertical: {len(vert_theta)}, need >= {MIN_LINE_COUNT} each). "
            f"Usually means the piece covers too much of the frame."
        )
        _write_and_exit(args.result_json_path, result)

    h_std = float(np.degrees(np.std(horiz_theta))) if len(horiz_theta) > 1 else 999.0
    v_std = float(np.degrees(np.std(vert_theta))) if len(vert_theta) > 1 else 999.0
    result["horiz_std"] = h_std
    result["vert_std"] = v_std
    result["pre_horiz_dev"] = float(np.degrees(np.median(horiz_theta)) - 90)
    result["pre_vert_dev"] = float(np.degrees(np.median(vert_theta)))

    if (h_std > args.confidence_threshold or v_std > args.confidence_threshold) and not args.force:
        result["message"] = (
            f"Detected lines too inconsistent to trust (spread {h_std:.1f}°/{v_std:.1f}°, "
            f"threshold {args.confidence_threshold}°). Likely fabric wrinkles/folds being mistaken "
            f"for grid lines. No correction applied — recapture with more open grid visible, "
            f"straighten manually, or re-run with force enabled."
        )
        _write_and_exit(args.result_json_path, result)

    A = compute_correction(horiz_theta, vert_theta)
    det = np.linalg.det(A)

    cx, cy = w / 2, h / 2
    M = np.zeros((2, 3))
    M[:2, :2] = A
    M[:, 2] = [cx, cy] - A @ [cx, cy]

    corrected = cv2.warpAffine(img, M, (w, h))
    cv2.imwrite(args.output_path, corrected)

    result["success"] = True
    result["message"] = f"Corrected (pre-correction deviation: {result['pre_horiz_dev']:.2f}°/{result['pre_vert_dev']:.2f}°)"
    if det < 0.9 or det > 1.1:
        result["message"] += f" WARNING: correction matrix determinant {det:.3f} unusual, review result."

    _write_and_exit(args.result_json_path, result)


def _write_and_exit(path, result):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f)
    print(result["message"])
    sys.exit(0)  # always exit 0 — success/failure communicated via JSON, not exit code


if __name__ == "__main__":
    main()
