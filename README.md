# onshape2pnplttr

Convert **OnShape / CAD technical-drawing PDF exports** into
[PenPlotterApp](https://github.com/tomatencode/PenPlotterApp) `.pnplttr` documents.

Vector CAD exports (OnShape, ODA, etc.) are almost ideal source material: the
PDF content stream *is* plotter geometry, so conversion is a parsing problem
rather than an image-tracing one. There is **no OCR and no curve fitting** —
lines stay lines, cubic Béziers stay Béziers (or are flattened on request), and
CAD layers become pens.

```
PDF content stream  ->  tracked graphics state  ->  Path/Subpath model
                    ->  fit + y-flip             ->  .pnplttr (Drawing | Path)
```

## Requirements

* Python 3.10+ (tested on 3.12)
* **No runtime dependencies** — standard library only.
* `pytest` is optional; the test-suite uses the stdlib `unittest`.

## Running it

The package lives in `src/`. Either install it or run it straight from the tree:

```bash
# Option A - run without installing
PYTHONPATH=src python3 -m onshape2pnplttr Drawing.pdf -o Drawing.pnplttr

# Option B - install (inside a virtualenv; the system Python may be PEP 668 managed)
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
onshape2pnplttr Drawing.pdf -o Drawing.pnplttr
```

Or via `make`:

```bash
make test
make convert PDF=Drawing.pdf OUT=Drawing.pnplttr
```

## Command line

```
onshape2pnplttr INPUT.pdf [-o OUT.pnplttr] [options]
```

| Option | Default | Description |
|---|---|---|
| `-o, --output` | alongside input | Output `.pnplttr` path |
| `--workspace` | `V2` | Workspace preset: `V1`, `V2`, `A4`, `A5` |
| `--workspace-size WxH` | – | Explicit workspace in mm (overrides `--workspace`) |
| `--page` | – | Force an output page preset (`A4`, `Letter`, …); artwork is centred |
| `--fit` | `fit` | `fit` (fill workspace), `actual` (1:1 mm), `scale` |
| `--scale` | `1.0` | Scale factor when `--fit scale` |
| `--margin` | `0.02` | Fraction reserved on each side for `--fit fit` |
| `--mode` | `drawing` | `drawing` flattens curves; `path` keeps Béziers (needs app support) |
| `--bezier-segments` | `16` | Curve flattening resolution |
| `--pen-width` | `0.4` | Default pen width in mm |
| `--pen-color` | `#000000` | Default pen colour |
| `--layer-color L=#RRGGBB` | – | Per-layer pen colour (repeatable) |
| `--no-fills` | – | Drop filled regions (keep outlines only) |
| `--drop-layer NAME` | – | Exclude a layer (repeatable) |
| `--page-index` | `0` | Which PDF page to convert |
| `--rotate` | `90` | Rotate artwork clockwise: `0`, `90`, `180`, `270` |
| `--list-layers` | – | List detected layers and exit |
| `--compact` | – | Write minified JSON |
| `-q, --quiet` | – | Suppress the summary |

Examples:

```bash
# See which CAD layers the drawing contains
PYTHONPATH=src python3 -m onshape2pnplttr Drawing.pdf --list-layers

# Lossless curves, 1:1 size, A4 page
PYTHONPATH=src python3 -m onshape2pnplttr Drawing.pdf --mode path --fit actual --page A4

# Exclude the title block, colour the contour layer, drop fills
PYTHONPATH=src python3 -m onshape2pnplttr Drawing.pdf \
    --drop-layer TITLE_BLOCK --layer-color Visible=#2236b2 --no-fills
```

## Python API

```python
from onshape2pnplttr import ConvertOptions, convert_pdf, write_document

result = convert_pdf("Drawing.pdf", ConvertOptions(workspace=(200, 285)))
write_document(result.document, "Drawing.pnplttr")

print(result.stats.elements, result.stats.page_mm, result.stats.used_layers)
```
## How it works

| Module | Responsibility |
|---|---|
| `content.py` | Tokenizes a PDF content stream / object body |
| `pdfobjects.py` | Recursive parser for PDF objects (refs, arrays, dicts, strings) |
| `pdf.py` | Object/stream extraction, page + inherited resources, OCG layer names |
| `geometry.py` | Affine matrices, Bézier flattening, bounding boxes |
| `model.py` | `Subpath` / `Move` / `Path` — mirrors the app's `PlotterStroke` |
| `interpreter.py` | Executes graphics operators into painted `Path`s |
| `pnplttr.py` | Builds and writes the `.pnplttr` document (schema v2) |
| `config.py` | `ConvertOptions`, workspace/page presets |
| `convert.py` | The pipeline: PDF -> filtered paths -> fitted document (+ stats) |
| `cli.py` | Command-line front end |

Conversion steps:

1. Parse PDF objects; locate `/Page`; read inherited `/Resources`.
2. Resolve **Optional Content Groups** (`/OCn` marked content) to layer names.
3. Execute the content stream, tracking `q`/`Q`/`cm` and colours, emitting
   `Subpath`s with `Line` / `CubicBezier` / `QuadBezier` moves.
4. Filter (fills, dropped layers) and compute the artwork bounding box.
5. Rotate the box (`--rotate`, default `90` clockwise) then compute the fit
   scale and page size, then map points from PDF device space
   (points, y-up) to document space (mm, y-down): `y_doc = (max_y - y) * mm`
   composed with the rotation.
6. Emit one element per subpath, with pens in first-seen layer order.

### Output modes

* **`drawing`** (default) — each subpath becomes a `Drawing` element with a flat
  `points` polyline. Works with PenPlotterApp today.
* **`path`** — each subpath becomes a `Path` element carrying `strokes` of
  `Line` / `CubicBezier` / `QuadBezier` moves (`PlotterStroke` shape), i.e.
  lossless. This mirrors `PlotterMove` in the app and requires the matching
  element type to be added there before the app can consume it.

### Coordinates

* PDF: points (1/72 inch), **y-up**, origin bottom-left.
* `.pnplttr`: millimetres, **y-down**, origin top-left.

The converter anchors the artwork to its own bounding box, then optionally
scales it to the workspace and centres it on the page. PenPlotterApp applies
the final workspace centring when generating GCode (see its
`makeConverter`/`docToGcode`), so a `page` that fits the `workspace` is all
that is required.

## Limitations & refinement ideas

* **Fills are outlines.** A pen plotter cannot fill, so filled regions are
  emitted as their outlines. Real hatching support would be a natural extension.
* **`Path` element type.** `--mode path` emits a `Path` element the app does not
  model yet; adding it (plus a `case` in `renderElements.ts`) would enable
  lossless Bézier round-tripping.
* **Classic PDFs only.** XRef streams, object streams (`/ObjStm`) and
  incremental updates are not parsed; the scan is textual. Most CAD exports are
  classic PDFs, but a proper xref parser would be more robust.
* **Only line art.** Text (`Tj`/`TJ`), images (`Do`), shadings and non-`DeviceRGB`
  colour spaces are ignored. Dashes are currently ignored (widths and colours
  are honoured).
* **`Arc` moves** are not synthesised — circular arcs arrive as Béziers, which
  is how CAD exporters emit them.
* No support yet for multi-page selection beyond `--page-index`, or for
  mirroring / non-uniform scaling.

## Tests

```bash
python3 -m unittest discover -s tests -v      # or: make test
```

The suite covers the tokenizer, object parser, interpreter, document builders
and the full pipeline using synthetic in-memory PDFs (no fixtures needed).
`tests/test_convert.py::RealSampleTests` additionally runs against a real
export if present; override the path with:

```bash
ONSHAPE2PNPLTTR_SAMPLE=/path/to/Drawing.pdf python3 -m unittest discover -s tests
```

## Project layout

```
onshape2pnplttr/
├── pyproject.toml
├── Makefile
├── src/onshape2pnplttr/     # the package
└── tests/                   # unittest suite (stdlib only)
```
