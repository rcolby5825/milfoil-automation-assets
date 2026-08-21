#!/usr/bin/env python3
"""
milfoil_trace_markings.py — Inkscape extension (paired with .inx file)

Extensions > Milfoil > Trace Markings

Same rewrite rationale as milfoil_trace_pieces.py — only uses `inkex`
(built into Inkscape), delegates all opencv/pytesseract work to a separate
venv via subprocess. See INSTALL.md for setup.

Run this AFTER "Milfoil: Trace Pattern Pieces". Works on the same
labeled source images (hidden, not deleted, by that extension).

CONFIDENCE LEVELS:
    - circles: ON by default, reliable — the "sure bet" across pieces
    - grainline: OFF by default, experimental — tends to false-positive
      on straight piece outlines, verify before trusting
    - arrows: OFF by default, experimental — clean on isolated triangles
      in testing, expect more false positives on real photos
"""

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

import inkex
from inkex import Circle, Line, Polygon, Group, Transform


def safe_expanduser(path_str):
    """
    Path.expanduser() relies on the HOME environment variable (or a pwd
    database lookup as fallback) being available. Confirmed to crash with
    "Could not determine home directory" on macOS, because Inkscape's
    bundled Python subprocess doesn't always inherit HOME from the
    surrounding environment. This tries the same things Python's own
    expanduser() does, but fails with a clear, actionable message instead
    of a cryptic traceback if neither works.
    """
    if not path_str.startswith('~'):
        return path_str
    home = os.environ.get('HOME') or os.environ.get('USERPROFILE')
    if not home:
        try:
            import pwd
            home = pwd.getpwuid(os.getuid()).pw_dir
        except Exception:
            home = None
    if not home:
        raise RuntimeError(
            "Could not determine your home directory automatically (a known issue "
            "with Inkscape's Python environment on some Mac setups). Enter the FULL "
            "absolute path instead of using '~' in the Worker Python path field, e.g.\n"
            "  /Users/yourname/milfoil_env/bin/python3"
        )
    return path_str.replace('~', home, 1)

INKSCAPE_LABEL_ATTR = '{http://www.inkscape.org/namespaces/inkscape}label'
XLINK_HREF_ATTR = '{http://www.w3.org/1999/xlink}href'


def matches_prefix(img_el, prefix):
    """
    Matches against inkscape:label if one was explicitly set, otherwise
    falls back to the element's id attribute (Inkscape's own default
    "image1", "image2" naming) — see milfoil_trace_pieces.py for the
    same helper and full rationale.
    """
    label = img_el.get(INKSCAPE_LABEL_ATTR)
    identifier = label if label else (img_el.get('id') or '')
    return identifier.startswith(prefix)


def display_name(img_el):
    return img_el.get(INKSCAPE_LABEL_ATTR) or img_el.get('id') or '(unnamed)'


class MilfoilTraceMarkings(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--label_prefix", type=str, default="image")
        pars.add_argument("--detect_circles", type=inkex.Boolean, default=True)
        pars.add_argument("--detect_grainline", type=inkex.Boolean, default=False)
        pars.add_argument("--detect_arrows", type=inkex.Boolean, default=False)
        pars.add_argument("--venv_python", type=str, default="")

    def effect(self):
        venv_python = self.options.venv_python.strip()
        if not venv_python:
            inkex.errormsg(
                "No venv Python path set. Fill in the 'Worker Python path' field "
                "with the path to the venv you set up per INSTALL.md, e.g.\n"
                "  ~/milfoil_env/bin/python3"
            )
            return

        try:
            venv_python = safe_expanduser(venv_python)
        except RuntimeError as e:
            inkex.errormsg(str(e))
            return
        if not Path(venv_python).exists():
            inkex.errormsg(f"Worker Python not found at: {venv_python}\nCheck the path and try again.")
            return

        worker_script = Path(__file__).parent / "workers" / "worker_detect_markings.py"
        if not worker_script.exists():
            inkex.errormsg(f"Worker script missing: {worker_script}\n"
                            f"Make sure the whole 'workers' folder was copied alongside this extension.")
            return

        images = self.svg.xpath('//svg:image')
        targets = [img for img in images if matches_prefix(img, self.options.label_prefix)]

        if not targets:
            inkex.errormsg(
                f"No images found matching prefix '{self.options.label_prefix}' "
                "(checked both Object Properties labels and Inkscape's default image IDs).\n"
                "If your images show as \"image1\", \"image2\" etc. with no custom label set, "
                "try entering just \"image\" as the prefix."
            )
            return

        totals = {"circles": 0, "grainlines": 0, "arrows": 0}
        errors = []
        for img in targets:
            try:
                self.process_one(img, venv_python, str(worker_script), totals)
            except Exception as e:
                errors.append(f"{display_name(img)}: {e}")

        parts = []
        if self.options.detect_circles:
            parts.append(f"{totals['circles']} circle(s)")
        if self.options.detect_grainline:
            parts.append(f"{totals['grainlines']} grainline(s) — VERIFY against original")
        if self.options.detect_arrows:
            parts.append(f"{totals['arrows']} candidate arrow(s) — VERIFY against original")
        msg = "Added: " + ", ".join(parts) if parts else "Nothing was enabled to detect."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors)
        inkex.errormsg(msg)

    def process_one(self, img_el, venv_python, worker_script, totals):
        label = display_name(img_el)
        href = img_el.get(XLINK_HREF_ATTR) or img_el.get('href')

        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = self.materialize_image(href, tmpdir)
            output_json_path = str(Path(tmpdir) / "output.json")

            cmd = [venv_python, worker_script, image_path, output_json_path]
            if self.options.detect_circles:
                cmd.append("--circles")
            if self.options.detect_grainline:
                cmd.append("--grainline")
            if self.options.detect_arrows:
                cmd.append("--arrows")

            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "worker failed with no error message")

            data = json.loads(Path(output_json_path).read_text(encoding="utf-8"))

        img_w_px, img_h_px = data["img_w_px"], data["img_h_px"]
        disp_x = float(img_el.get('x', 0))
        disp_y = float(img_el.get('y', 0))
        disp_w = float(img_el.get('width', img_w_px))
        disp_h = float(img_el.get('height', img_h_px))
        scale_x = disp_w / img_w_px
        scale_y = disp_h / img_h_px

        existing_transform = Transform(img_el.get('transform', ''))
        alignment_transform = existing_transform @ Transform(f"translate({disp_x},{disp_y}) scale({scale_x},{scale_y})")

        wrapper = Group()
        wrapper.set(INKSCAPE_LABEL_ATTR, f"{label}_markings")
        wrapper.transform = alignment_transform
        added_anything = False

        for c in data.get("circles", []):
            el = Circle()
            el.set('cx', str(c["cx"])); el.set('cy', str(c["cy"])); el.set('r', str(c["r"]))
            el.style = "fill:none;stroke:#000000;stroke-width:1.5"
            wrapper.append(el)
            totals["circles"] += 1
            added_anything = True

        if data.get("grainline"):
            x1, y1, x2, y2 = data["grainline"]
            el = Line()
            el.set('x1', str(x1)); el.set('y1', str(y1))
            el.set('x2', str(x2)); el.set('y2', str(y2))
            el.style = "stroke:#000000;stroke-width:2;stroke-dasharray:4,2"
            wrapper.append(el)
            totals["grainlines"] += 1
            added_anything = True

        for tri in data.get("arrows", []):
            el = Polygon()
            el.set('points', " ".join(f"{x},{y}" for x, y in tri))
            el.style = "fill:#ff0000;fill-opacity:0.3;stroke:#ff0000;stroke-width:0.5"
            wrapper.append(el)
            totals["arrows"] += 1
            added_anything = True

        if added_anything:
            img_el.getparent().append(wrapper)

    def materialize_image(self, href, tmpdir):
        if href and href.startswith('data:'):
            _, b64data = href.split(',', 1)
            raw = base64.b64decode(b64data)
            path = Path(tmpdir) / "source.png"
            path.write_bytes(raw)
            return str(path)
        elif href:
            path = Path(href)
            if not path.is_absolute():
                doc_path = self.document_path()
                if doc_path:
                    path = Path(doc_path).parent / href
            return str(path)
        raise ValueError("image has no href/data to read")


if __name__ == '__main__':
    MilfoilTraceMarkings().run()
