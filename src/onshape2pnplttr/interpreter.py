"""Execute a PDF content stream into a list of painted :class:`Path` objects.

Only the graphics operators relevant to line art are modelled; text/image
operators are ignored. Curves are preserved as moves so the caller can choose
to flatten them (``Drawing`` elements) or keep them (``Path`` elements).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .content import Token, tokenize
from .geometry import IDENTITY, Mat, apply_mat, mat_mul
from .model import CubicMove, LineMove, Path, PathKind, Subpath

_NUMBER = (int, float)


@dataclass
class GraphicsState:
    ctm: Mat = IDENTITY
    line_width: float = 1.0
    stroke_color: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fill_color: tuple[float, float, float] = (0.0, 0.0, 0.0)

    def copy(self) -> "GraphicsState":
        return GraphicsState(self.ctm, self.line_width, self.stroke_color, self.fill_color)


@dataclass
class Interpreter:
    """Stateful interpreter; call :meth:`run` for each content stream."""

    layer_names: dict[str, str] = field(default_factory=dict)
    default_layer: str = "Default"

    def __post_init__(self) -> None:
        self._state = GraphicsState()
        self._stack: list[GraphicsState] = []
        self._operands: list[object] = []
        self._subpaths: list[Subpath] = []
        self._current: Subpath | None = None
        self._layer = self.default_layer
        self._paths: list[Path] = []

    # -- public API ------------------------------------------------------
    def run(self, content: bytes) -> list[Path]:
        for token in tokenize(content):
            self._feed(token)
        return self._paths

    # -- token handling --------------------------------------------------
    def _feed(self, token: Token) -> None:
        kind = token.kind
        if kind in ("num", "name", "str", "hex", "[", "]", "<<", ">>"):
            self._operands.append(token.value)
            return
        self._operate(token.value, self._operands)  # type: ignore[arg-type]
        self._operands = []

    def _num(self, index: int = -1) -> float:
        value = self._operands[index]
        if not isinstance(value, _NUMBER):
            raise ValueError(f"expected a number, got {value!r}")
        return float(value)

    # -- operators -------------------------------------------------------
    def _operate(self, op: str, args: list[object]) -> None:
        state = self._state
        if op == "q":
            self._stack.append(state.copy())
        elif op == "Q":
            if self._stack:
                self._state = self._stack.pop()
        elif op == "cm":
            m = tuple(self._num(i) for i in range(-6, 0))
            state.ctm = mat_mul(m, state.ctm)  # type: ignore[arg-type]
        elif op == "w":
            state.line_width = self._num()
        elif op == "RG":
            state.stroke_color = (self._num(-3), self._num(-2), self._num(-1))
        elif op == "rg":
            state.fill_color = (self._num(-3), self._num(-2), self._num(-1))
        elif op == "G":
            state.stroke_color = (self._num(),) * 3
        elif op == "g":
            state.fill_color = (self._num(),) * 3
        elif op in ("BDC", "BMC"):
            self._enter_marked(args)
        elif op == "EMC":
            self._layer = self.default_layer
        elif op == "m":
            self._move_to(self._num(-2), self._num(-1))
        elif op == "l":
            self._line_to(self._num(-2), self._num(-1))
        elif op == "c":
            self._curve_to(*[self._num(i) for i in range(-6, 0)])
        elif op == "v":
            self._curve_v(self._num(-4), self._num(-3), self._num(-2), self._num(-1))
        elif op == "y":
            self._curve_y(self._num(-4), self._num(-3), self._num(-2), self._num(-1))
        elif op == "h":
            self._close()
        elif op == "re":
            self._rect(self._num(-4), self._num(-3), self._num(-2), self._num(-1))
        elif op in ("S", "s"):
            self._paint(PathKind.STROKE)
        elif op in ("f", "f*", "B", "B*", "b", "b*"):
            self._paint(PathKind.FILL)
        elif op == "n":
            self._discard()
        # Everything else (text, shading, colour spaces, ...) is ignored.

    # -- marked content (layers) -----------------------------------------
    def _enter_marked(self, args: list[object]) -> None:
        for arg in args:
            if isinstance(arg, str) and arg in self.layer_names:
                self._layer = self.layer_names[arg]
                return

    # -- path construction -------------------------------------------
    def _xf(self, x: float, y: float) -> tuple[float, float]:
        return apply_mat(self._state.ctm, x, y)

    def _start_subpath(self, x: float, y: float) -> None:
        self._current = Subpath(start=(x, y))
        self._subpaths.append(self._current)

    def _move_to(self, x: float, y: float) -> None:
        self._start_subpath(*self._xf(x, y))

    def _line_to(self, x: float, y: float) -> None:
        if self._current is None:
            self._start_subpath(*self._xf(x, y))
            return
        ax, ay = self._current.end
        bx, by = self._xf(x, y)
        self._current.moves.append(LineMove(ax, ay, bx, by))

    def _curve_to(self, cx1: float, cy1: float, cx2: float, cy2: float, x: float, y: float) -> None:
        self._ensure_current()
        assert self._current is not None
        ax, ay = self._current.end
        p1 = self._xf(cx1, cy1)
        p2 = self._xf(cx2, cy2)
        p3 = self._xf(x, y)
        self._current.moves.append(CubicMove(ax, ay, p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]))

    def _curve_v(self, cx2: float, cy2: float, x: float, y: float) -> None:
        self._ensure_current()
        assert self._current is not None
        ax, ay = self._current.end
        p2 = self._xf(cx2, cy2)
        p3 = self._xf(x, y)
        self._current.moves.append(CubicMove(ax, ay, ax, ay, p2[0], p2[1], p3[0], p3[1]))

    def _curve_y(self, cx1: float, cy1: float, x: float, y: float) -> None:
        self._ensure_current()
        assert self._current is not None
        ax, ay = self._current.end
        p1 = self._xf(cx1, cy1)
        p3 = self._xf(x, y)
        self._current.moves.append(CubicMove(ax, ay, p1[0], p1[1], p3[0], p3[1], p3[0], p3[1]))

    def _close(self) -> None:
        if self._current is None:
            return
        ax, ay = self._current.end
        sx, sy = self._current.start
        if (ax, ay) != (sx, sy):
            self._current.moves.append(LineMove(ax, ay, sx, sy))

    def _rect(self, x: float, y: float, w: float, h: float) -> None:
        corners = [
            self._xf(x, y),
            self._xf(x + w, y),
            self._xf(x + w, y + h),
            self._xf(x, y + h),
            self._xf(x, y),
        ]
        sub = Subpath(start=corners[0])
        for (ax, ay), (bx, by) in zip(corners, corners[1:]):
            sub.moves.append(LineMove(ax, ay, bx, by))
        self._subpaths.append(sub)
        self._current = sub

    def _ensure_current(self) -> None:
        if self._current is None:
            self._start_subpath(0.0, 0.0)

    # -- painting --------------------------------------------------------
    def _paint(self, kind: PathKind) -> None:
        state = self._state
        color = state.stroke_color if kind is PathKind.STROKE else state.fill_color
        path = Path(
            layer=self._layer,
            kind=kind,
            width=state.line_width,
            color=color,
            subpaths=self._subpaths,
        )
        if not path.is_empty:
            self._paths.append(path)
        self._subpaths = []
        self._current = None

    def _discard(self) -> None:
        self._subpaths = []
        self._current = None