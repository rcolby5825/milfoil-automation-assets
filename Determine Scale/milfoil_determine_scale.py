#!/usr/bin/env python3
"""
milfoil_determine_scale.py — Inkscape extension (paired with .inx file)

Extensions > Milfoil > Determine Scale

Run this AFTER "Milfoil: Correct Perspective" and BEFORE "Milfoil: Trace
Pattern Pieces" — measures the grid mat's actual spacing in each photo and
sets the image's display width/height so one grid square equals a known
real-world size (default 25.4mm / 1 inch) in the document. Everything
downstream (tracing) inherits correct real-world scale automatically from
the image's own corrected size.

Same architecture as the other Milfoil extensions: only uses `inkex`
(built into Inkscape), delegates actual image measurement to a separate
venv via subprocess. See INSTALL.md.

CONVENTION: none — processes every image in the document unconditionally,
same as Correct Perspective.

RELIABILITY: samples grid spacing across several regions of the photo and
checks how consistent they are before trusting the result — refuses
rather than silently applying a bad scale if the measurements disagree
too much. See worker_determine_scale.py docstring for details.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import inkex

XLINK_HREF_ATTR = '{http://www.w3.org/1999/xlink}href'
INKSCAPE_LABEL_ATTR = '{http://www.inkscape.org/namespaces/inkscape}label'


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


def display_name(img_el):
    return img_el.get(INKSCAPE_LABEL_ATTR) or img_el.get('id') or '(unnamed)'


class MilfoilDetermineScale(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--grid_size_mm", type=float, default=25.4)
        pars.add_argument("--force", type=inkex.Boolean, default=False)
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

        worker_script = Path(__file__).parent / "workers" / "worker_determine_scale.py"
        if not worker_script.exists():
            inkex.errormsg(f"Worker script missing: {worker_script}\n"
                            f"Make sure the whole 'workers' folder was copied alongside this extension.")
            return

        images = self.svg.xpath('//svg:image')
        if not images:
            inkex.errormsg("No images found in this document.")
            return

        scaled, refused, failed = 0, [], []
        for img in images:
            label = display_name(img)
            try:
                status = self.scale_one(img, venv_python, str(worker_script))
                if status["success"]:
                    scaled += 1
                else:
                    refused.append(f"{label}: {status['message']}")
            except Exception as e:
                failed.append(f"{label}: {e}")

        summary = f"Scaled {scaled} of {len(images)} image(s)."
        if refused:
            summary += "\n\nRefused (confidence check failed):\n" + "\n".join(refused)
        if failed:
            summary += "\n\nErrors:\n" + "\n".join(failed)
        inkex.errormsg(summary)

    def scale_one(self, img_el, venv_python, worker_script):
        href = img_el.get(XLINK_HREF_ATTR) or img_el.get('href')

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self.materialize_image(href, tmpdir)
            result_json_path = str(Path(tmpdir) / "result.json")

            cmd = [venv_python, worker_script, input_path, result_json_path,
                   "--grid-size-mm", str(self.options.grid_size_mm)]
            if self.options.force:
                cmd.append("--force")

            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or "worker failed with no error message")

            status = json.loads(Path(result_json_path).read_text(encoding="utf-8"))

            if status["success"]:
                # Set the image's display size directly so it (and anything
                # traced from it downstream) reflects true real-world scale.
                img_el.set('width', str(status["target_display_w"]))
                img_el.set('height', str(status["target_display_h"]))

            return status

    def materialize_image(self, href, tmpdir):
        import base64
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
    MilfoilDetermineScale().run()
