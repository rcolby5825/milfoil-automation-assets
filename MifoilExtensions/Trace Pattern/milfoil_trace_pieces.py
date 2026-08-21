#!/usr/bin/env python3
"""
milfoil_trace_pieces.py — Inkscape extension (paired with .inx file)

Extensions > Milfoil > Trace Pattern Pieces

REWRITTEN to avoid needing opencv/potrace inside Inkscape's own bundled
Python (which is locked-down on Mac and killed pip installs outright).
This script only uses `inkex` — already provided by Inkscape, nothing to
install here. All actual image processing (opencv, potrace) happens in a
SEPARATE venv you set up with your regular system Python, called via
subprocess. See INSTALL.md for the one-time venv setup.

CONVENTION: label each source-photo IMAGE OBJECT (Object > Object
Properties > Label), or Inkscape's default image ID (image1, image2,
...) works automatically too. Only matching objects are
touched.

SCOPE: outline only — see "Milfoil: Trace Markings" for grainline/dots/
arrows, run as a separate pass afterward.
"""

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

import inkex
from inkex import Group, Transform


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
    falls back to the element's id attribute — Inkscape auto-assigns ids
    like "image1", "image2" to imported images even when no label was
    ever set. This lets un-labeled imports work too (e.g. prefix "image"
    matches Inkscape's own default naming) without requiring every piece
    to be manually labeled first.
    """
    label = img_el.get(INKSCAPE_LABEL_ATTR)
    identifier = label if label else (img_el.get('id') or '')
    return identifier.startswith(prefix)


def display_name(img_el):
    return img_el.get(INKSCAPE_LABEL_ATTR) or img_el.get('id') or '(unnamed)'


class MilfoilTracePieces(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--threshold", type=int, default=128)
        pars.add_argument("--label_prefix", type=str, default="image")
        pars.add_argument("--fill_solid", type=inkex.Boolean, default=False)
        pars.add_argument("--border_width", type=int, default=1)
        pars.add_argument("--isolate_paper", type=inkex.Boolean, default=True)
        pars.add_argument("--paper_brightness", type=int, default=100)
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

        worker_script = Path(__file__).parent / "workers" / "worker_trace_piece.py"
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
                "If your images show as \"image1\", \"image2\" etc. in the Objects panel with "
                "no custom label set, try entering just \"image\" as the prefix."
            )
            return

        traced, failed = 0, []
        for img in targets:
            label = display_name(img)
            try:
                self.trace_one(img, venv_python, str(worker_script))
                traced += 1
            except Exception as e:
                failed.append(f"{label}: {e}")

        summary = f"Traced {traced} of {len(targets)} labeled image(s)."
        if failed:
            summary += "\n\nFailed:\n" + "\n".join(failed)
        inkex.errormsg(summary)

    def trace_one(self, img_el, venv_python, worker_script):
        label = display_name(img_el)
        href = img_el.get(XLINK_HREF_ATTR) or img_el.get('href')

        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = self.materialize_image(href, tmpdir)
            output_json_path = str(Path(tmpdir) / "output.json")

            cmd = [venv_python, worker_script, image_path, str(self.options.threshold), output_json_path]
            if self.options.isolate_paper:
                cmd.extend(["--isolate-paper", "--paper-brightness", str(self.options.paper_brightness)])

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
        alignment_transform = Transform(f"translate({disp_x},{disp_y}) scale({scale_x},{scale_y})")
        wrapper_transform = existing_transform @ alignment_transform
        if data.get("potrace_group_transform"):
            wrapper_transform = wrapper_transform @ Transform(data["potrace_group_transform"])

        wrapper = Group()
        wrapper.set(INKSCAPE_LABEL_ATTR, f"{label}_traced")
        wrapper.transform = wrapper_transform

        for d in data["paths"]:
            path_el = inkex.PathElement()
            path_el.set('d', d)
            if self.options.fill_solid:
                path_el.style = "fill:#000000;stroke:none"
            else:
                # Border only, transparent interior — thickness is user-set
                # via border_width so you can get a bold, visible edge
                # without filling the whole shape solid. non-scaling-stroke
                # keeps thickness visually consistent even though this path
                # sits inside a scaled wrapper group.
                path_el.style = (
                    f"fill:none;stroke:#000000;stroke-width:{self.options.border_width};"
                    "vector-effect:non-scaling-stroke"
                )
            wrapper.append(path_el)

        img_el.getparent().append(wrapper)
        self.hide_element(img_el)

    def hide_element(self, el):
        """
        Sets display:none in a way guaranteed to persist to the actual SVG
        file. Mutating el.style['display'] in place doesn't reliably write
        back to the XML attribute across all inkex versions — if it
        silently doesn't persist, the ORIGINAL photo (grid lines and all)
        stays fully visible underneath the new trace, which looks exactly
        like "the grid isn't transparent" even though the trace itself is
        fine. Setting the raw style attribute directly sidesteps that.
        """
        current = el.get('style', '') or ''
        current = current.rstrip(';')
        new_style = f"{current};display:none" if current else "display:none"
        el.set('style', new_style)

    def materialize_image(self, href, tmpdir):
        """Write the source image out to a real file the worker subprocess can read."""
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
    MilfoilTracePieces().run()
