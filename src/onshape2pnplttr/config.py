"""Conversion options and page/workspace presets."""
from __future__ import annotations

from dataclasses import dataclass, field

from .merge import DEFAULT_TOLERANCE_MM

# 1 PDF point = 1/72 inch; 1 inch = 25.4 mm.
PT_TO_MM = 25.4 / 72.0

#: Usable plotter areas in millimetres (mirrors PenPlotterApp's WORKSPACE_PRESETS).
WORKSPACE_PRESETS: dict[str, tuple[float, float]] = {
    "V1": (185.0, 265.0),
    "V2": (200.0, 285.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
}
DEFAULT_WORKSPACE = "V2"

#: Page sizes in millimetres (portrait unless suffixed).
PAGE_PRESETS: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "A6": (105.0, 148.0),
    "Letter": (215.9, 279.4),
    "Letter-landscape": (279.4, 215.9),
}

FIT_MODES = ("fit", "actual", "scale")
ELEMENT_MODES = ("drawing", "path")
ROTATE_CHOICES = (0, 90, 180, 270)


@dataclass
class ConvertOptions:
    """Everything tunable about a conversion.

    ``fit='fit'`` scales the drawing to fill the workspace (leaving ``margin``
    on each side); ``fit='actual'`` keeps 1:1 millimetres; ``fit='scale'``
    applies ``scale`` directly. An explicit ``page`` overrides the derived page
    size and centres the artwork within it.

    ``rotate`` turns the artwork clockwise by 0/90/180/270 degrees *before*
    fitting. ``rotate=90`` is the default because portrait CAD title blocks
    plot best on landscape plotter workspaces.

    ``outline`` (default ``True``) appends a rectangular outline around the
    fitted artwork bounds as the last element, using the first pen.
    """

    workspace: tuple[float, float] = WORKSPACE_PRESETS[DEFAULT_WORKSPACE]
    margin: float = 0.02
    fit: str = "fit"
    scale: float = 1.0
    page: tuple[float, float] | None = None

    element_mode: str = "drawing"  # "drawing" (flatten) | "path" (lossless curves)
    bezier_segments: int = 16
    round_mm: int = 3

    pen_width_mm: float = 0.4
    pen_color: str = "#000000"
    layer_colors: dict[str, str] = field(default_factory=dict)

    include_fills: bool = True
    drop_layers: tuple[str, ...] = ()
    page_index: int = 0
    rotate: int = 90  # clockwise degrees; one of ROTATE_CHOICES
    outline: bool = True  # append a rectangular outline around the artwork

    merge_continuations: bool = True  # join polylines whose endpoints touch
    merge_tolerance_mm: float = DEFAULT_TOLERANCE_MM

    def __post_init__(self) -> None:
        if self.fit not in FIT_MODES:
            raise ValueError(f"fit must be one of {FIT_MODES}, got {self.fit!r}")
        if self.element_mode not in ELEMENT_MODES:
            raise ValueError(f"element_mode must be one of {ELEMENT_MODES}, got {self.element_mode!r}")
        if self.rotate not in ROTATE_CHOICES:
            raise ValueError(f"rotate must be one of {ROTATE_CHOICES}, got {self.rotate!r}")
        if not 0.0 <= self.margin < 0.5:
            raise ValueError("margin must be in [0, 0.5)")
        if self.bezier_segments < 1:
            raise ValueError("bezier_segments must be >= 1")
        if self.scale <= 0:
            raise ValueError("scale must be > 0")
        if self.merge_tolerance_mm < 0:
            raise ValueError("merge_tolerance_mm must be >= 0")

    # -- helpers ---------------------------------------------------------
    @classmethod
    def with_workspace_name(cls, name: str, **kwargs) -> "ConvertOptions":
        try:
            workspace = WORKSPACE_PRESETS[name]
        except KeyError as exc:
            raise ValueError(f"unknown workspace preset {name!r}") from exc
        return cls(workspace=workspace, **kwargs)

    @classmethod
    def with_page_name(cls, name: str, **kwargs) -> "ConvertOptions":
        try:
            page = PAGE_PRESETS[name]
        except KeyError as exc:
            raise ValueError(f"unknown page preset {name!r}") from exc
        return cls(page=page, fit="fit", **kwargs)