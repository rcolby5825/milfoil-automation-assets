#!/usr/bin/env python3
"""
worker_trace_piece.py — standalone worker, no Inkscape/inkex dependency.

Called by milfoil_trace_pieces.py as a subprocess, running under a
separate venv's Python (not Inkscape's bundled one) so opencv/potrace
issues never touch Inkscape's own restricted environment.

USAGE:
    python3 worker_trace_piece.py image_path threshold output_json_path [--isolate-paper]

OUTPUT (written to output_json_path):
    {
      "img_w_px": int, "img_h_px": int,
      "potrace_group_transform": "translate(...) scale(...)" or "",
      "paths": ["M...Z", "M...Z", ...]
    }
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    print("ERROR: opencv/numpy not installed in this environment. "
          "Run: pip install opencv-python-headless numpy", file=sys.stderr)
    sys.exit(1)


def find_potrace():
    """
    Locates the potrace binary without relying on inherited PATH.

    When Inkscape is launched by double-clicking (Finder/Dock) rather than
    from a Terminal, macOS GUI apps don't inherit the shell's PATH — so
    even though `potrace --version` works fine in Terminal, the same
    lookup fails inside a subprocess spawned from Inkscape. Confirmed as
    the cause of "potrace not found on PATH" errors during testing.
    Checking known install locations directly sidesteps this entirely.
    """
    found = shutil.which("potrace")
    if found:
        return found

    candidates = [
        "/opt/homebrew/bin/potrace",   # Homebrew on Apple Silicon
        "/usr/local/bin/potrace",      # Homebrew on Intel Mac
        "/usr/bin/potrace",            # Linux system package
        "/opt/local/bin/potrace",      # MacPorts
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def find_piece_seed_candidates(gray, brightness_threshold=100, area_ratio_threshold=0.15,
                                 frame_span_threshold=0.9):
    """
    Finds rough candidate regions likely to be real paper piece(s), for
    use as GrabCut seed rectangles. Does NOT need to be precise — GrabCut
    refines the actual edges afterward. This only needs to roughly locate
    where each piece is.

    Erosion breaks a critical real-world failure mode found during
    testing: a piece's bright region can be directly PIXEL-CONNECTED to
    the surrounding mat's bright regions (subtle lighting gradients,
    blur softening the paper's edge), merging them into one blob that
    naive brightness+connectivity treats as a single indistinguishable
    shape spanning most of the photo. Eroding first breaks these thin
    bridging connections, isolating each piece's solid core reliably —
    confirmed against a real photo during development.

    Frame-spanning rejection catches the connected grid MESH itself
    (lines touching at intersections span nearly the whole frame even
    though their actual pixel coverage is sparse).

    Area-ratio filtering (relative to the largest candidate) keeps
    multiple real pieces of comparable size while dropping small
    unrelated bright objects in frame (e.g. a metal ruler used for scale
    reference — confirmed in testing to fall well below this ratio
    relative to a real piece).
    """
    _, bright = cv2.threshold(gray, brightness_threshold, 255, cv2.THRESH_BINARY)
    h, w = gray.shape
    kernel = np.ones((9, 9), np.uint8)
    eroded = cv2.erode(bright, kernel, iterations=2)

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(eroded, connectivity=8)

    candidates = []
    for i in range(1, n_labels):
        bbox_w_frac = stats[i, cv2.CC_STAT_WIDTH] / w
        bbox_h_frac = stats[i, cv2.CC_STAT_HEIGHT] / h
        if bbox_w_frac > frame_span_threshold and bbox_h_frac > frame_span_threshold:
            continue
        candidates.append(stats[i])

    if not candidates:
        return []

    max_area = max(c[cv2.CC_STAT_AREA] for c in candidates)
    kept = [c for c in candidates if c[cv2.CC_STAT_AREA] >= max_area * area_ratio_threshold]
    return kept


def isolate_paper_via_grabcut(img_bgr, brightness_threshold=100, area_ratio_threshold=0.15,
                                working_max_dim=900, rect_margin=0.4):
    """
    Isolates real paper piece(s) from mat/grid using OpenCV's GrabCut —
    a proper foreground/background color-model segmentation, rather than
    a simple brightness comparison. Switched to this after simple
    brightness+connectivity was confirmed to break down on a real photo
    (the piece's bright region was directly pixel-connected to the
    surrounding mat, not just similarly-bright — no threshold value can
    fix that, since it's a connectivity problem, not a threshold
    problem). GrabCut models actual color distributions and doesn't have
    this failure mode.

    Runs at reduced resolution (GrabCut is expensive; full-resolution
    photos can exhaust available memory) and the resulting mask is
    upscaled back to the original resolution afterward. This trades a
    small amount of edge precision in the isolation mask for reliability
    — fine detail is still captured later from the FULL-resolution ink
    threshold, only the coarse "is this paper or mat" decision uses the
    downscaled mask.

    Fully automatic: seed rectangles for GrabCut come from
    find_piece_seed_candidates() rather than requiring the person to
    manually crop or select each piece.

    Returns a full-resolution paper mask (or None if no candidates
    found) plus counts for diagnostic output.
    """
    h, w = img_bgr.shape[:2]
    scale = min(1.0, working_max_dim / max(h, w))
    small = cv2.resize(img_bgr, (int(w * scale), int(h * scale))) if scale < 1.0 else img_bgr.copy()
    sh, sw = small.shape[:2]
    small_gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    seeds = find_piece_seed_candidates(small_gray, brightness_threshold, area_ratio_threshold)
    if not seeds:
        return None, 0

    combined_mask = np.zeros((sh, sw), np.uint8)

    for seed in seeds:
        x, y, bw, bh = seed[0], seed[1], seed[2], seed[3]
        pad_x, pad_y = int(bw * rect_margin), int(bh * rect_margin)
        rx = max(0, x - pad_x)
        ry = max(0, y - pad_y)
        rw = min(sw - rx, bw + 2 * pad_x)
        rh = min(sh - ry, bh + 2 * pad_y)
        rect = (rx, ry, rw, rh)

        gc_mask = np.zeros((sh, sw), np.uint8)
        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)
        try:
            cv2.grabCut(small, gc_mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)
        except cv2.error:
            continue  # degenerate rect (too small/thin) — skip this candidate rather than crash

        piece_mask = np.where((gc_mask == 2) | (gc_mask == 0), 0, 255).astype('uint8')
        combined_mask = cv2.bitwise_or(combined_mask, piece_mask)

    if not combined_mask.any():
        return None, len(seeds)

    full_res_mask = cv2.resize(combined_mask, (w, h), interpolation=cv2.INTER_NEAREST)
    return full_res_mask, len(seeds)


def write_pbm_p4(path, binary_mask):
    """
    Writes a bilevel PBM (P4 binary format) manually, bypassing
    cv2.imwrite's PBM writer entirely.

    CONFIRMED REAL BUG: cv2.imwrite's PBM output was verified byte-correct
    via its own round-trip (write then read back with cv2.imread produced
    an identical array), yet potrace interpreted the SAME file completely
    differently — tracing a large rectangle in the wrong location instead
    of the actual mask shape. This only showed up for large solid mask
    regions (like a GrabCut piece mask), not the thin sparse ink masks
    used elsewhere, suggesting an edge case in OpenCV's PBM encoder that
    potrace's stricter reader doesn't tolerate. Writing the well-defined
    P4 format directly (magic number, dimensions, then packed bits, 1 bit
    per pixel MSB-first, foreground=1) sidesteps the incompatibility
    entirely — confirmed fixed during testing against a real photo.
    """
    h, w = binary_mask.shape
    packed = np.packbits((binary_mask > 0).astype(np.uint8), axis=1)
    with open(path, 'wb') as f:
        f.write(f'P4\n{w} {h}\n'.encode('ascii'))
        f.write(packed.tobytes())


def main():
    if len(sys.argv) < 4:
        print("Usage: worker_trace_piece.py image_path threshold output_json_path [--remove-grid]", file=sys.stderr)
        sys.exit(1)

    image_path, threshold_str, output_json_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    isolate_paper = "--isolate-paper" in sys.argv[4:]

    area_ratio = 0.15
    if "--area-ratio" in sys.argv:
        idx = sys.argv.index("--area-ratio")
        area_ratio = float(sys.argv[idx + 1])

    paper_brightness = 100
    if "--paper-brightness" in sys.argv:
        idx = sys.argv.index("--paper-brightness")
        paper_brightness = int(sys.argv[idx + 1])

    potrace_path = find_potrace()
    if potrace_path is None:
        print(
            "ERROR: potrace not found. Checked PATH and common install locations:\n"
            "  /opt/homebrew/bin/potrace, /usr/local/bin/potrace, /usr/bin/potrace, /opt/local/bin/potrace\n"
            "Run 'which potrace' in Terminal to find your actual install path, then tell Claude "
            "so it can be added to the search list.",
            file=sys.stderr
        )
        sys.exit(1)

    img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        print(f"ERROR: could not read image: {image_path}", file=sys.stderr)
        sys.exit(1)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

    _, binary = cv2.threshold(gray, threshold_str, 255, cv2.THRESH_BINARY_INV)

    if isolate_paper:
        # Identifies real paper piece(s) via GrabCut color-model
        # segmentation BEFORE combining with the ink mask, so mat/grid
        # content is excluded regardless of its own darkness. Switched
        # from a simpler brightness+connectivity approach after that was
        # confirmed to break down on a real photo — see
        # isolate_paper_via_grabcut() docstring for details.
        img_for_grabcut = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img
        paper_mask, n_pieces = isolate_paper_via_grabcut(img_for_grabcut, paper_brightness, area_ratio)
        print(f"Isolate paper: found {n_pieces} piece candidate(s)", file=sys.stderr)
        if paper_mask is not None:
            # IMPORTANT: real antique pattern pieces don't have a drawn ink
            # outline — the paper's own physically die-cut edge IS the
            # cutting line. Ink-only tracing captures interior markings
            # (text, dots, notches) but misses the actual outer boundary
            # entirely — confirmed by inspecting a real traced result
            # during testing, which had all the interior detail but no
            # continuous outer border. So the paper mask's own silhouette
            # is traced separately here and merged with the ink detail,
            # giving both the true cutting line AND the interior markings.
            binary = cv2.bitwise_and(binary, paper_mask)
        else:
            print("WARNING: no paper regions found — check --paper-brightness matches your lighting", file=sys.stderr)
            paper_mask = None
    else:
        paper_mask = None

    img_h_px, img_w_px = binary.shape[:2]

    def trace_to_paths(bilevel_img):
        """Runs potrace on a bilevel image, returns (paths, group_transform)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pbm_path = Path(tmpdir) / "trace_input.pbm"
            svg_path = Path(tmpdir) / "trace_output.svg"
            write_pbm_p4(pbm_path, bilevel_img)

            result = subprocess.run(
                [potrace_path, str(pbm_path), "-s", "-o", str(svg_path)],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                return [], ""

            svg_text = svg_path.read_text(encoding="utf-8")

        import re
        transform_match = re.search(r'<g\s+transform="([^"]*)"', svg_text)
        transform = transform_match.group(1) if transform_match else ""
        paths = re.findall(r'<path\s+d="([^"]*)"', svg_text)
        return paths, transform

    ink_paths, potrace_transform = trace_to_paths(binary)

    outline_paths = []
    if paper_mask is not None:
        # Trace the paper mask's own silhouette separately — this is the
        # true cutting-line outline (see note above on why ink-only
        # tracing misses it entirely for real antique pieces).
        outline_paths, outline_transform = trace_to_paths(paper_mask)
        if not potrace_transform:
            potrace_transform = outline_transform

    paths = outline_paths + ink_paths

    if not paths:
        print("ERROR: potrace produced no path data (image may be blank, or threshold needs adjusting)", file=sys.stderr)
        sys.exit(1)

    output = {
        "img_w_px": img_w_px,
        "img_h_px": img_h_px,
        "potrace_group_transform": potrace_transform,
        "paths": paths,
    }
    Path(output_json_path).write_text(json.dumps(output), encoding="utf-8")
    print(f"OK: {len(paths)} path(s) traced")


if __name__ == "__main__":
    main()
