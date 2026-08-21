# Milfoil Automation Assets

Tools for preparing photographed sewing patterns in Inkscape and creating printable A4/A0 tile guides.

## Contents

- `MifoilExtensions/` - Inkscape extensions for perspective correction, scale detection, pattern tracing, and marking detection.
- `Tiling Template Generator A0 A4/` - standalone generator for SVG tile-guide templates.

## Milfoil Inkscape Extensions

The Inkscape-facing files use Inkscape's built-in Python environment. Image processing runs in a separate Python environment so that Inkscape's bundled Python does not need additional packages installed into it.

### Requirements

- Inkscape
- Python 3
- Homebrew on macOS
- Python packages: OpenCV, NumPy, and pytesseract
- System tools: Potrace and Tesseract OCR

### Installation

1. Create the worker environment in Terminal:

   ```bash
   python3 -m venv ~/milfoil_env
   ~/milfoil_env/bin/pip install opencv-python-headless numpy pytesseract
   brew install potrace tesseract
   ```

   If Python 3 or Homebrew is not installed, install them first from [python.org](https://www.python.org/downloads/) and [brew.sh](https://brew.sh/).

2. Verify the environment:

   ```bash
   ~/milfoil_env/bin/python3 -c "import cv2, pytesseract; print('OK')"
   potrace --version
   tesseract --version
   ```

3. In Inkscape, open `Edit > Preferences > System` and locate **User extensions**. Open that folder.

4. Copy the complete contents of `MifoilExtensions/` into the User extensions folder. Keep each worker file in its matching `workers/` or `Workers/` subfolder.

5. Restart Inkscape. The extensions are available under `Extensions > Milfoil`:

   - Trace Pattern Pieces
   - Trace Markings
   - Correct Perspective
   - Determine Scale

### Using the extensions

When an extension asks for **Worker Python path**, use:

```text
~/milfoil_env/bin/python3
```

Inkscape usually remembers the last-used value.

For a new photograph, the recommended order is:

1. Correct Perspective, when the reference grid is skewed.
2. Determine Scale.
3. Trace Pattern Pieces.
4. Trace Markings, when markings need to be detected separately.

Run the extensions on a duplicate of the original pattern file until the workflow has been verified.

By default, source images are matched by their Inkscape IDs, such as `image1` or `image2`, using the prefix `image`. To use custom matching, label the image object itself through `Object > Object Properties > Label`, then set the matching prefix in the extension.

## Tile Template Generator

The generator creates an SVG guide made of A4 or A0 page outlines. Each page is an Inkscape layer named `tile_A4_N` or `tile_A0_N`, numbered left-to-right and then top-to-bottom. Printable-margin guides, page numbers, and neighboring-page connector labels are included by default.

The generator has no third-party Python dependencies.

### Generate a fixed grid

From Terminal, run the generator with an output SVG path, page size, number of columns, and number of rows:

```bash
python3 "Tiling Template Generator A0 A4/generate_tile_template.py" output.svg --page-size a4 --cols 3 --rows 2
```

For an A0 guide:

```bash
python3 "Tiling Template Generator A0 A4/generate_tile_template.py" output.svg --page-size a0 --cols 2 --rows 1
```

### Calculate the grid from piece dimensions

Provide the piece width and height in millimetres. The generator calculates how many printable pages are needed using the selected page size and margins:

```bash
python3 "Tiling Template Generator A0 A4/generate_tile_template.py" output.svg --page-size a4 --piece-width-mm 550 --piece-height-mm 380
```

### Generator options

- `--page-size a4` or `--page-size a0` - select the page format; A4 is the default.
- `--cols` and `--rows` - define a fixed grid. Both are required together.
- `--piece-width-mm` and `--piece-height-mm` - calculate the grid from real-world dimensions. Both are required together.
- `--margin-mm` - set the printer-safe margin on each page; the default is 10 mm.
- `--page-gap-mm` - set the visual gap between page outlines; the default is 5 mm.
- `--no-connectors` - omit neighboring-page arrows and labels while retaining page numbers.

The generated guide assumes adjacent tiles do not overlap. Any overlap for taping or registration must be added separately.

## Troubleshooting

- **Worker Python not found**: confirm the Worker Python path is exactly `~/milfoil_env/bin/python3`.
- **Worker script missing**: copy the entire extension directory, including its worker subfolders.
- **Extension missing from the menu**: confirm each `.inx` file has its matching `.py` file, check Inkscape's extension error log, and verify file permissions.
- **Text detected as circular markings**: verify that both `pytesseract` and the `tesseract` command are installed. OCR is used to mask text before circle detection.

For the full installation notes, see [MifoilExtensions/INSTALL.md](MifoilExtensions/INSTALL.md).
