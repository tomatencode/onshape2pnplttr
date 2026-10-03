# onshape2pnplttr

Convert **OnShape / CAD technical-drawing PDF exports** into
[PenPlotterApp](https://github.com/tomatencode/PenPlotterApp) `.pnplttr` documents,
and clean up the result for a pen plotter.

Two tools:

| Tool | What it does |
|---|---|
| `onshape2pnplttr` | `PDF -> .pnplttr`: parse, fit, rotate, emit |
| `pnplttr-clean` | `.pnplttr -> .pnplttr`: remove the detail a pen cannot draw |

Vector CAD exports (OnShape, ODA, etc.) are almost ideal source material: the
PDF content stream *is* plotter geometry, so conversion is a parsing problem
rather than an image-tracing one. There is **no OCR and no curve fitting** —
lines stay lines, cubic Béziers stay Béziers (or are flattened on request), and
CAD layers become pens.

```
PDF content stream  ->  tracked graphics state  ->  Path/Subpath model
                    ->  fit + y-flip             ->  .pnplttr (Drawing | Path)
                    ->  pnplttr-clean             ->  .pnplttr with short edges gone
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
make tidy IN=Drawing.pnplttr OUT=Clean.pnplttr
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
| `--outline` / `--no-outline` | `--outline` | Draw a rectangular outline around the artwork |
| `--merge` / `--no-merge` | `--merge` | Join polylines whose endpoints touch, so the pen stays down |
| `--merge-tolerance` | `0.01` | Endpoint gap (mm) still counted as the same point |
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

```python
from onshape2pnplttr import CleanOptions, clean_document, clean_file

clean_file("Drawing.pnplttr", "Clean.pnplttr", CleanOptions(min_detail=0.2))

result = clean_document(document, CleanOptions(tolerance=0.1))
print(result.stats.segments_before, "->", result.stats.segments_after)
```

## Cleaning up the plot — `pnplttr-clean`

A detailed model turns every edge into a line. On a real OnShape export
(3259 elements) **73 % of the segments are shorter than 0.05 mm** — an order of
magnitude below a 0.4 mm pen. They cost plot time, they are invisible on their
own, and where many of them meet they blot the paper.

`pnplttr-clean` removes that detail and leaves the drawing alone:

```bash
PYTHONPATH=src python3 -m onshape2pnplttr.clean_cli Drawing.pnplttr --dry-run
```

```
Drawing.pnplttr -> Drawing.clean.pnplttr (dry run)
  elements : 3259 -> 2222 ( 31.8% gone)
  segments : 87401 -> 8155 ( 90.7% gone)
  points   : 90660 -> 10377 ( 88.6% gone)
  ink      : 10848 -> 10663 mm pen-down (  1.7% less)
  stray    : at most 0.100 mm per removed point
  pass     : collinear points     14418 point(s)
  pass     : duplicate points      5602 point(s)
  pass     : flat points          49361 point(s)
  pass     : simplified              81 point(s)
  dropped  : smaller than min_extent 1035 element(s)
  pen      : Visible               2300 -> 1446  element(s)
```

### The algorithm

Five local passes, in this order, each with a geometric guarantee. The promise
is deliberately narrow: **ink is only removed where the pen could not have
drawn it anyway.**

| Pass | Rule | Guarantee |
|---|---|---|
| `merge_points` | drop points that repeat their predecessor | zero-length edges only |
| `drop_collinear` | drop points on the straight run through their neighbours | the ink is identical |
| `drop_flat_points` | drop the flattest point while it strays `< min_detail` from the segment through its neighbours | that removal moves the ink by `< min_detail` |
| `simplify` | Douglas–Peucker over each stroke | the stroke stays within `tolerance` |
| micro elements | drop elements whose bounding box is `< min_extent` | the element is invisible to the pen |

`drop_flat_points` is the pass that answers *"remove short lines"*. It is a
**flatness** test, not a **length** test, and that distinction is the whole
design:

* A 0.05 mm edge has flat endpoints, a staircase is flat all the way down, and
  the tip of a spur is flat against the line between its neighbours — so all of
  them go.
* A 90° corner is never flat. A length test would happily cut a corner off just
  because a *short edge happened to follow it*; a flatness test cannot.

It runs as a priority queue over the vertices (flattest first), re-queueing
both neighbours after every removal, so a whole run of detail collapses in one
sweep. Closed rings are handled cyclically and never shrink below a triangle;
the ends of an open polyline — where the pen starts and stops — are never
removed.

`drop_flat_points` and `simplify` are both needed because they see different
things: Douglas–Peucker compares a point with the chord spanning a whole edge
and therefore keeps locally flat but globally significant detail, while
`drop_flat_points` compares it with the chord through its immediate neighbours.
Flat points go first, Douglas–Peucker last, so `tolerance` is measured against
what is actually left.

**Distance is measured to the chord _segment_, never to the infinite line.**
CAD geometry is full of paths that run out along a line and back along it again
(a centre-line, a dimension tick, a fill boundary); their tips are collinear but
sit far outside the segment between their neighbours. Both passes have
regression tests for this — measuring to the line deletes millimetres of real
ink.

The defaults are derived from the pen. With a 0.4 mm nib, `min_detail` 0.1 mm,
`tolerance` 0.05 mm and `min_extent` 0.2 mm all stay under the width of one
stroke, so nothing visible is lost. Measured over all 3224 cleanable elements
of the sample drawing, the largest distance between the original ink and the
cleaned ink is **0.13 mm** — a third of the pen width.

### `pnplttr-clean` command line

```
pnplttr-clean INPUT.pnplttr [-o OUT.pnplttr] [options]
```

| Option | Default | Description |
|---|---|---|
| `-o, --output` | `INPUT.clean.pnplttr` | Output path |
| `--min-detail MM` | `0.1` | Drop points whose removal moves the stroke less than `MM` (`0` disables) |
| `--tolerance MM` | `0.05` | Douglas–Peucker tolerance (`0` disables) |
| `--min-extent MM` | `0.2` | Drop elements smaller than this bounding box (`0` disables) |
| `--epsilon MM` | `1e-06` | Points closer than `MM` count as the same spot |
| `--dedupe-segments` | – | Also drop ink another element already drew (lightens overlaps) |
| `--quantise MM` | `0.001` | Coordinate quantum for `--dedupe-segments` |
| `--path-mode {skip,flatten}` | `skip` | How to treat `Path` elements; `flatten` turns curves into polylines first |
| `--bezier-segments N` | `16` | Curve flattening resolution for `--path-mode flatten` |
| `--protect-pen N` | – | Leave elements of pen `N` untouched (repeatable) |
| `--in-place` | – | Overwrite the input file |
| `--dry-run` | – | Report only, write nothing |
| `--compact` | – | Write minified JSON |
| `-q, --quiet` | – | Suppress the summary |

```bash
# how much would the defaults remove?
pnplttr-clean Drawing.pnplttr --dry-run

# be more aggressive: sub-0.3 mm detail, 0.1 mm of waviness
pnplttr-clean Drawing.pnplttr --min-detail 0.3 --tolerance 0.1 -o Fast.pnplttr

# keep the title block exactly as it is
pnplttr-clean Drawing.pnplttr --protect-pen 4
```

Cleaning is element-local: element order, pens, page and meta are preserved,
and ids and `z` indices are renumbered so the document stays valid. The
converter's `--merge` already joins touching polylines, so the cleaner never
merges — it only ever shortens strokes or drops them.
## How it works

| Module | Responsibility |
|---|---|
| `content.py` | Tokenizes a PDF content stream / object body |
| `pdfobjects.py` | Recursive parser for PDF objects (refs, arrays, dicts, strings) |
| `pdf.py` | Object/stream extraction, page + inherited resources, OCG layer names |
| `geometry.py` | Affine matrices, Bézier flattening, bounding boxes |
| `model.py` | `Subpath` / `Move` / `Path` — mirrors the app's `PlotterStroke` |
| `interpreter.py` | Executes graphics operators into painted `Path`s |
| `merge.py` | Joins touching polylines so the pen stays down |
| `pnplttr.py` | Builds and writes the `.pnplttr` document (schema v2) |
| `config.py` | `ConvertOptions`, workspace/page presets |
| `convert.py` | The pipeline: PDF -> filtered paths -> fitted document (+ stats) |
| `cli.py` | Command-line front end |
| `clean.py` | The cleaner: flatness / Douglas-Peucker passes over `.pnplttr` |
| `clean_cli.py` | Command-line front end of `pnplttr-clean` |

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
6. Emit one element per stroke, with pens in first-seen layer order. In
   `drawing` mode, polylines whose endpoints touch are joined first so the
   plotter does not lift the pen at a line break (see *Continuous lines*).
7. Append a rectangular `outline` element around the fitted artwork bounds
   (last element, first pen) unless `--no-outline` is given.

### Continuous lines

A PDF moveto starts a new subpath, and CAD exporters use one even where a
single visible line continues, so a naive conversion splits that line into
several elements — and the plotter lifts the pen at every break. On the sample
drawing 3771 elements contain 335 such splits.

`--merge` (default) joins them: polylines whose endpoints coincide within
`--merge-tolerance` are chained into one stroke, reversing a piece when
needed. Only the pen lifts change — every segment is still drawn exactly once,
in the same direction of travel along the line, so the plotted result is
identical (at `--merge-tolerance 0` the segment multiset is bit-for-bit
unchanged). Merging never joins across layers, and it never re-draws a segment
to force continuity, which would ink it twice. Where three or more polylines
meet at a junction the stroke stops there and a new one begins.

In `--mode path` the merging is skipped: each element keeps one subpath's
Bézier strokes.

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

The suite covers the tokenizer, object parser, interpreter, document builders,
the cleaner and the full pipeline using synthetic in-memory PDFs (no fixtures
needed). `tests/test_convert.py::RealSampleTests` additionally runs against a
real export if present; override the path with:

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
