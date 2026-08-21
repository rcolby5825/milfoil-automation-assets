#!/usr/bin/env python3
"""
milfoil_correct_perspective.py — Inkscape extension (paired with .inx file)

Extensions > Milfoil > Correct Perspective

Run this BEFORE Trace Pattern Pieces / Trace Markings — corrects
rotation/skew in the source photo using the grid mat's own lines as
ground truth, so downstream tracing works from a properly-aligned image.

Same architecture as the other Milfoil extensions: this script only uses
`inkex` (already provided by Inkscape). All actual image processing
(opencv) happens in a separate venv via subprocess — see INSTALL.md.

WHAT THIS CORRECTS: rotation + shear. NOT full perspective/keystone warp
— confirmed during testing that this setup's actual distortion is
rotation-with-shear, not keystone, so this fully resolves it. See
worker_correct_perspective.py docstring for the reliability check details
— it will refuse to "correct" a photo where the grid lines can't be
detected reliably (e.g. a large piece with heavy fabric wrinkles, which
get mistaken for grid lines) rather than silently making it worse.

CONVENTION: none — processes every image in the document unconditionally.
No label/ID filtering (unlike the other two Milfoil extensions).

WHAT IT DOES TO THE DOCUMENT: replaces each matched image's embedded
data with the corrected version in place. The original is NOT kept as a
separate hidden layer (unlike Trace Pieces) — if you want to keep an
untouched copy, duplicate the image before running this.
"""

import base64
import json
import os
import subprocess
import tempfile
from pathlib import Path

import inkex

INKSCAPE_LABEL_ATTR = '{http://www.inkscape.org/namespaces/inkscape}label'
XLINK_HREF_ATTR = '{http://www.w3.org/1999/xlink}href'


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


class MilfoilCorrectPerspective(inkex.EffectExtension):

    def add_arguments(self, pars):
        pars.add_argument("--confidence_threshold", type=float, default=4.0)
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

        worker_script = Path(__file__).parent / "workers" / "worker_correct_perspective.py"
        if not worker_script.exists():
            inkex.errormsg(f"Worker script missing: {worker_script}\n"
                            f"Make sure the whole 'workers' folder was copied alongside this extension.")
            return

        images = self.svg.xpath('//svg:image')
        targets = images

        if not targets:
            inkex.errormsg("No images found in this document.")
            return

        corrected, refused, failed = 0, [], []
        for img in targets:
            label = display_name(img)
            try:
                status = self.correct_one(img, venv_python, str(worker_script))
                if status["success"]:
                    corrected += 1
                else:
                    refused.append(f"{label}: {status['message']}")
            except Exception as e:
                failed.append(f"{label}: {e}")

        summary = f"Corrected {corrected} of {len(targets)} image(s)."
        if refused:
            summary += "\n\nRefused (confidence check failed):\n" + "\n".join(refused)
        if failed:
            summary += "\n\nErrors:\n" + "\n".join(failed)
        inkex.errormsg(summary)

    def correct_one(self, img_el, venv_python, worker_script):
        href = img_el.get(XLINK_HREF_ATTR) or img_el.get('href')

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = self.materialize_image(href, tmpdir)
            output_path = str(Path(tmpdir) / "corrected.png")
            result_json_path = str(Path(tmpdir) / "result.json")

            cmd = [venv_python, worker_script, input_path, output_path, result_json_path,
                   "--confidence-threshold", str(self.options.confidence_threshold)]
            if self.options.force:
                cmd.append("--force")

            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr.strip() or "worker failed with no error message")

            status = json.loads(Path(result_json_path).read_text(encoding="utf-8"))

            if status["success"]:
                corrected_bytes = Path(output_path).read_bytes()
                b64 = base64.b64encode(corrected_bytes).decode('ascii')
                img_el.set(XLINK_HREF_ATTR, f"data:image/png;base64,{b64}")

            return status

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
    MilfoilCorrectPerspective().run()
