# Installing the Milfoil Inkscape Extensions

## Why this changed

The first version of these extensions tried to install opencv directly
into Inkscape's own bundled Python. On Mac, that Python is locked down
(code-signed, restricted) and killed pip outright (`Killed: 9`). So the
extensions now work differently:

- The part that talks to Inkscape (`milfoil_trace_pieces.py`,
  `milfoil_trace_markings.py`) only uses `inkex`, which Inkscape already
  provides. **Nothing to install for this part.**
- The actual image processing (opencv, potrace, OCR) runs in a completely
  separate, ordinary Python environment that you set up yourself with
  your regular Mac Python — no fighting Inkscape's restrictions at all.

## Step 1 — Create the separate environment (one-time, ~2 minutes)

Open Terminal (Applications > Utilities > Terminal) and run:

```bash
python3 -m venv ~/milfoil_env
~/milfoil_env/bin/pip install opencv-python-headless numpy pytesseract
```

If `python3 -m venv` fails or you don't have Python 3 at all, install it
first via [python.org](https://www.python.org/downloads/) or Homebrew
(`brew install python3`), then re-run the two lines above.

Also install two system tools this needs — a normal Homebrew install,
nothing unusual:

```bash
brew install potrace tesseract
```

(No Homebrew? Install it from [brew.sh](https://brew.sh) first — one
command, standard for Mac dev tools.)

## Step 2 — Verify it worked

```bash
~/milfoil_env/bin/python3 -c "import cv2, pytesseract; print('OK')"
potrace --version
tesseract --version
```

If all of those print output instead of errors, you're set.

## Step 3 — Find your Inkscape user extensions folder

In Inkscape: `Edit > Preferences > System` → look for **"User
extensions"**, with a folder icon next to it you can click to open it
directly. (Some newer Inkscape versions don't show a separate "Python
interpreter" field — that's fine, you don't need it anymore with this
setup.)

## Step 4 — Copy everything in

Copy the **entire folder structure** below into that user extensions
folder — the `workers/` subfolder must come along, not just the top-level
files:

```
milfoil_trace_pieces.inx
milfoil_trace_pieces.py
milfoil_trace_markings.inx
milfoil_trace_markings.py
milfoil_correct_perspective.inx
milfoil_correct_perspective.py
milfoil_determine_scale.inx
milfoil_determine_scale.py
workers/
    worker_trace_piece.py
    worker_detect_markings.py
    worker_correct_perspective.py
    worker_determine_scale.py
```

## Step 5 — Restart Inkscape

Extensions only load on startup. After restarting, you should see:

`Extensions > Milfoil > Trace Pattern Pieces`
`Extensions > Milfoil > Trace Markings`
`Extensions > Milfoil > Correct Perspective`
`Extensions > Milfoil > Determine Scale`

Suggested order for a new photo: Correct Perspective (if the grid looks
skewed) → Determine Scale → Trace Pattern Pieces.

## Step 6 — Set the Worker Python path

When you run either extension, there's a field called **"Worker Python
path"** — set it to:

```
~/milfoil_env/bin/python3
```

(This is the one thing you set per-use, since Inkscape extensions can't
reliably auto-detect it. You can leave it filled in and it'll remember
your last-used value in most Inkscape versions.)

## Step 7 — First run: use a throwaway copy

Try both extensions on a duplicate of a real pattern file first, not your
only copy — this is the first time the extension harness itself runs
inside real Inkscape (the underlying image-processing logic was tested
standalone and works).

## Convention reminder

Both extensions match against each image's Inkscape ID by default —
Inkscape auto-assigns `image1`, `image2`, etc. to imported images, so
this works out of the box with no manual labeling needed (default prefix
is `image`).

If you'd rather use custom names, label the source-photo IMAGE OBJECT
(not the layer — the image itself) via `Object > Object Properties >
Label`, and set the "Images whose label/ID starts with" field to match
your own prefix.

## Troubleshooting

- **"Worker Python not found at: ..."** — double check the path in Step 6
  matches exactly what you created in Step 1.
- **"Worker script missing"** — the `workers/` folder didn't get copied
  alongside the `.inx`/`.py` files. Go back to Step 4.
- **Extension doesn't appear in the menu at all** — check `Edit >
  Preferences > System` for an extensions error log; usually means a
  `.py` file is missing next to its `.inx`, or a permissions issue (try
  `chmod +x` on the `.py` files).
- **Circle detection picks up letters as dots** — this was a real bug
  caught during testing and fixed by masking text out first via OCR
  before circle detection runs. If it's still happening, confirm
  `pytesseract`/`tesseract` installed correctly in Step 1–2 — without
  them, the worker still runs but skips text-masking and warns you.
