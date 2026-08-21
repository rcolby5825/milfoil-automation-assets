#!/usr/bin/env python3
"""
generate_tile_template.py

Generates a tile-guide template as an SVG: a grid of page outlines (A4 or
A0), optionally with connector arrows/labels at every edge where an
adjacent tile exists (e.g. "-> Page 3" on a right edge), so you know
which printed pages to match together when assembling a large tiled
pattern piece.

Output layers are named tile_A4_N or tile_A0_N (N = page number,
row-major reading order: left-to-right, then top-to-bottom) — matching
the convention batch_export.py already expects, so this slots directly
into the existing pipeline as the "tile guide layer" step: import this
template's layers into your pattern SVG as a visual guide while placing
your actual tile breaks by hand, then once your artwork is organized
into matching layers, run batch_export.py as usual.

USAGE:
    Specify the grid directly:
        python3 generate_tile_template.py output.svg --page-size a4 --cols 3 --rows 2
        python3 generate_tile_template.py output.svg --page-size a0 --cols 2 --rows 1 --no-connectors

    Or let it compute the grid from a real-world piece size (mm),
    accounting for margins:
        python3 generate_tile_template.py output.svg --page-size a4 --piece-width-mm 550 --piece-height-mm 380

OPTIONS:
    --page-size       a4 or a0 (default a4)
    --no-connectors   Skip the arrow/page-number connector labels entirely
                       — just page outlines and the printable-margin guide.
                       Page number in the corner is still shown either way.
    --margin-mm       Printer-safe margin on each page (default 10mm for
                       A4; A0 is usually printed at a print shop with its
                       own margin handling, but the option still applies)
    --page-gap-mm     Visual gap between page outlines in the generated
                       guide (default 5mm, purely for readability in
                       Inkscape — doesn't affect the actual tile size)

NOTE ON ASSUMPTIONS:
    This lays out a clean grid with NO overlap between tiles (each page's
    printable area is treated as exactly adjacent to the next, no shared
    overlap strip for taping). If you prefer an overlap margin, that
    would need a small modification — ask if you want that instead.
"""

import argparse
import math


PAGE_SIZES_MM = {
    "a4": (210.0, 297.0),
    "a0": (841.0, 1189.0),
}


def compute_grid(piece_w, piece_h, printable_w, printable_h):
    cols = math.ceil(piece_w / printable_w)
    rows = math.ceil(piece_h / printable_h)
    return cols, rows


def build_svg(cols, rows, page_w, page_h, margin_mm, page_gap_mm, layer_prefix, show_connectors):
    printable_w = page_w - 2 * margin_mm
    printable_h = page_h - 2 * margin_mm

    total_w = cols * page_w + (cols - 1) * page_gap_mm
    total_h = rows * page_h + (rows - 1) * page_gap_mm

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        f'width="{total_w}mm" height="{total_h}mm" '
        f'viewBox="0 0 {total_w} {total_h}">'
    ]

    def page_number(row, col):
        return row * cols + col + 1

    for row in range(rows):
        for col in range(cols):
            n = page_number(row, col)
            x = col * (page_w + page_gap_mm)
            y = row * (page_h + page_gap_mm)

            svg_parts.append(
                f'<g inkscape:groupmode="layer" inkscape:label="{layer_prefix}{n}" id="{layer_prefix}{n}">'
            )

            svg_parts.append(
                f'<rect x="{x}" y="{y}" width="{page_w}" height="{page_h}" '
                f'fill="none" stroke="#999999" stroke-width="0.3" stroke-dasharray="2,2"/>'
            )
            svg_parts.append(
                f'<rect x="{x+margin_mm}" y="{y+margin_mm}" '
                f'width="{printable_w}" height="{printable_h}" '
                f'fill="none" stroke="#cccccc" stroke-width="0.2"/>'
            )

            svg_parts.append(
                f'<text x="{x + page_w - margin_mm - 2}" y="{y + page_h - margin_mm - 2}" '
                f'font-size="6" text-anchor="end" fill="#333333">Page {n}</text>'
            )

            if show_connectors:
                if col + 1 < cols:
                    right_n = page_number(row, col + 1)
                    cx = x + page_w - margin_mm - 1
                    cy = y + page_h / 2
                    svg_parts.append(
                        f'<text x="{cx}" y="{cy}" font-size="7" font-weight="bold" text-anchor="end" '
                        f'fill="#0066cc" transform="rotate(-90 {cx} {cy})">\u2192 Page {right_n}</text>'
                    )
                if col - 1 >= 0:
                    left_n = page_number(row, col - 1)
                    cx = x + margin_mm + 1
                    cy = y + page_h / 2
                    svg_parts.append(
                        f'<text x="{cx}" y="{cy}" font-size="7" font-weight="bold" text-anchor="start" '
                        f'fill="#0066cc" transform="rotate(-90 {cx} {cy})">\u2190 Page {left_n}</text>'
                    )
                if row + 1 < rows:
                    down_n = page_number(row + 1, col)
                    svg_parts.append(
                        f'<text x="{x + page_w/2}" y="{y + page_h - margin_mm - 1}" '
                        f'font-size="7" font-weight="bold" text-anchor="middle" fill="#0066cc">\u2193 Page {down_n}</text>'
                    )
                if row - 1 >= 0:
                    up_n = page_number(row - 1, col)
                    svg_parts.append(
                        f'<text x="{x + page_w/2}" y="{y + margin_mm + 7}" '
                        f'font-size="7" font-weight="bold" text-anchor="middle" fill="#0066cc">\u2191 Page {up_n}</text>'
                    )

            svg_parts.append('</g>')

    svg_parts.append('</svg>')
    return ''.join(svg_parts)


def main():
    ap = argparse.ArgumentParser(description="Generate a tile-guide template with optional page connector labels")
    ap.add_argument("output", help="Path to save the generated .svg template")
    ap.add_argument("--page-size", choices=["a4", "a0"], default="a4", help="Page size (default a4)")
    ap.add_argument("--no-connectors", action="store_true",
                     help="Skip arrow/connector labels — just page outlines and page numbers")

    grid_group = ap.add_mutually_exclusive_group(required=True)
    grid_group.add_argument("--cols", type=int, help="Number of columns (use with --rows)")
    grid_group.add_argument("--piece-width-mm", type=float, help="Real-world piece width in mm (auto-computes grid)")

    ap.add_argument("--rows", type=int, help="Number of rows (required with --cols)")
    ap.add_argument("--piece-height-mm", type=float, help="Real-world piece height in mm (required with --piece-width-mm)")

    ap.add_argument("--margin-mm", type=float, default=10.0, help="Printer-safe margin per page (default 10mm)")
    ap.add_argument("--page-gap-mm", type=float, default=5.0, help="Visual gap between pages in the guide (default 5mm)")

    args = ap.parse_args()

    page_w, page_h = PAGE_SIZES_MM[args.page_size]
    layer_prefix = f"tile_{args.page_size.upper()}_"

    if args.cols is not None:
        if args.rows is None:
            ap.error("--rows is required when using --cols")
        cols, rows = args.cols, args.rows
    else:
        if args.piece_height_mm is None:
            ap.error("--piece-height-mm is required when using --piece-width-mm")
        printable_w = page_w - 2 * args.margin_mm
        printable_h = page_h - 2 * args.margin_mm
        cols, rows = compute_grid(args.piece_width_mm, args.piece_height_mm, printable_w, printable_h)
        print(f"Computed grid: {cols} columns x {rows} rows "
              f"(printable area per page: {printable_w:.1f}mm x {printable_h:.1f}mm)")

    svg = build_svg(cols, rows, page_w, page_h, args.margin_mm, args.page_gap_mm,
                     layer_prefix, show_connectors=not args.no_connectors)
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(svg)

    print(f"Generated {cols}x{rows} = {cols*rows} page ({args.page_size.upper()}) template: {args.output}")
    print(f"Layers named {layer_prefix}1 through {layer_prefix}{cols*rows}, ready for batch_export.py's convention.")


if __name__ == "__main__":
    main()

