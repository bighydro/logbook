"""The owner's own chart as the paper of `logbook export world --chart FILE --control-points FILE`: the
control points read, the transform from a position to a pixel of the chart fitted, and the fit checked.

A control point ties a pixel of the image (`x` to the right, `y` down, from the top-left corner, in the
pixels of the file as the owner gives it) to a position (`lat`, `lon`). The positions are taken to
Mercator's plane first — east the longitude, north ln tan(45° + lat/2), both in degrees — since a sea
chart is drawn on Mercator's projection (a rhumb line is straight on it); on a chart of a few degrees
any projection is that close to it, and a chart that is not is refused by its residuals, below.

Each point's **residual** is how far the fit of the *other* points puts it from the pixel the owner
gives (leave one out). A fit whose worst residual is more than `RESIDUAL_LIMIT` of the image's diagonal
is refused, naming the worst point: a point mistyped by a tenth of a degree is caught, and so is a chart
drawn in a projection the track cannot honestly be laid on.

The transform is the simplest one the points check. Three points: the affine transform through them,
which they fit exactly and so cannot check (no residual, `None`). Four or more: the **affine** transform
by least squares (a flat chart scanned: turned, scaled, sheared), when every point's residual is within
the limit. When it is not, and there are `PROJECTIVE_POINTS` or more: the **projective** transform (a
homography: a chart photographed at an angle), by least squares in pixels, held to the same check. A
homography through four or five points is never fitted: it has eight parameters, so the fit of the
others would pass through them exactly and bend to every error of a click — a check of nothing, and a
chart warped by its own mistakes. A thin-plate spline is not offered for the same reason: it passes
through every point whatever the point says and bends the track towards it, the one thing the track
may not be. Nothing here smooths or moves a position: one transform takes every position of the record
to the chart, and a position is where the chart's own geometry puts it.

Refused too, whatever the residuals: points nearly in a line, a fit that mirrors the chart (a latitude
and a longitude swapped), and a homography whose horizon crosses the image (it would fold the chart).
`ChartFitError` says which, and nothing is written.

The fit is a function of the points alone; `Fit.to_json` is what the page carries and `world_chart.js`
evaluates (`chartTransform`), the same arithmetic as `Fit.to_pixel`."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESIDUAL_LIMIT = 0.01  # the worst residual, as a fraction of the image's diagonal, a fit may have
MAX_LAT = 85.0  # Mercator's plane: a control point or a position nearer a pole than this is off it
MAX_POINTS = 200
NAME_CHARS = 80  # a control point's name, at most
MIN_SPREAD = 0.01  # three points: the triangle they make, at least this share of the image's area
PROJECTIVE_POINTS = 6  # a homography is fitted only to this many points, so each is checked by five
REFINE_STEPS = 20  # Gauss-Newton steps from the algebraic fit to the least squares in pixels
AFFINE, PROJECTIVE = "affine", "projective"


class ChartFitError(ValueError):
    """Control points the fit refuses, or a file of them that is not one; the message says why."""


@dataclass(frozen=True)
class Point:
    name: str
    x: float
    y: float
    lat: float
    lon: float


def read_points(path: Path) -> list[Point]:
    """The control points of `path`: `{"points": [{"x", "y", "lat", "lon", "name"?}, …]}`, or the bare
    list. `ChartFitError` for a file that is not one, a value that is not a number, a position off
    Mercator's plane, or fewer than three points."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ChartFitError(f"--control-points {path}: {e}") from e
    found = data.get("points") if isinstance(data, dict) else data
    if not isinstance(found, list):
        raise ChartFitError(f'--control-points {path}: not {{"points": [...]}} or a list of points')
    return points_of(found, str(path))


def points_of(found: Sequence[Any], where: str = "--control-points") -> list[Point]:
    """The points of a parsed list, checked as `read_points` checks them."""
    out: list[Point] = []
    for n, raw in enumerate(found, 1):
        if not isinstance(raw, dict):
            raise ChartFitError(f"{where}: point {n} is not an object with x, y, lat and lon")
        values = {}
        for key in ("x", "y", "lat", "lon"):
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
                raise ChartFitError(f"{where}: point {n} has no number {key!r}")
            values[key] = float(value)
        name = raw.get("name")
        label = " ".join(name.split()) if isinstance(name, str) and name.strip() else str(n)
        if len(label) > NAME_CHARS:
            raise ChartFitError(f"{where}: point {n}'s name is {len(label)} characters; at most {NAME_CHARS}")
        if not -MAX_LAT < values["lat"] < MAX_LAT:
            raise ChartFitError(
                f"{where}: point {label} is at latitude {values['lat']}, off Mercator's chart"
                f" (|lat| < {MAX_LAT:g})"
            )
        if not -180.0 <= values["lon"] <= 180.0:
            raise ChartFitError(f"{where}: point {label} has longitude {values['lon']}, not in -180 to 180")
        out.append(Point(label, values["x"], values["y"], values["lat"], values["lon"]))
    if len(out) < 3:
        raise ChartFitError(f"{where}: {len(out)} control points; the fit needs three or more")
    if len(out) > MAX_POINTS:
        raise ChartFitError(f"{where}: {len(out)} control points; at most {MAX_POINTS}")
    return out


# -- the plane ----------------------------------------------------------------------------------------------


def wrap(degrees: float) -> float:
    """A difference of longitudes as -180 to 180."""
    return (degrees + 180.0) % 360.0 - 180.0


def north(lat: float) -> float:
    """Mercator's northing of `lat`, in degrees: ln tan(45° + lat/2)."""
    return math.log(math.tan(math.pi / 4 + lat * math.pi / 360)) * 180 / math.pi


def central_lon(points: Sequence[Point]) -> float:
    """The longitude the points gather round, so a chart over the antimeridian is one piece."""
    s = sum(math.sin(math.radians(p.lon)) for p in points)
    c = sum(math.cos(math.radians(p.lon)) for p in points)
    return round(math.degrees(math.atan2(s, c)), 6) if s or c else 0.0


def _normaliser(pairs: Sequence[tuple[float, float]]) -> tuple[float, float, float] | None:
    """Hartley's normalisation: the centroid to the origin, the mean distance from it to √2."""
    cx = sum(p[0] for p in pairs) / len(pairs)
    cy = sum(p[1] for p in pairs) / len(pairs)
    spread = sum(math.hypot(p[0] - cx, p[1] - cy) for p in pairs) / len(pairs)
    if not spread > 1e-12:
        return None
    return cx, cy, math.sqrt(2) / spread


# -- the transform ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Transform:
    """A position to a pixel: east and north on Mercator's plane, less `src`'s centroid, times its scale;
    then `h` (a homography whose last entry is 1; an affine one has h6 = h7 = 0); then the pixel, back
    through `dst`'s scale and centroid. A position beyond the homography's horizon has no pixel."""

    kind: str
    lon0: float
    src: tuple[float, float, float]
    dst: tuple[float, float, float]
    h: tuple[float, ...]

    def plane(self, lat: float, lon: float) -> tuple[float, float]:
        return (wrap(lon - self.lon0) - self.src[0]) * self.src[2], (north(lat) - self.src[1]) * self.src[2]

    def to_pixel(self, lat: float, lon: float) -> tuple[float, float] | None:
        if not -MAX_LAT < lat < MAX_LAT:
            return None
        e, n = self.plane(lat, lon)
        h = self.h
        w = h[6] * e + h[7] * n + 1
        if not w > 0:
            return None
        return (
            (h[0] * e + h[1] * n + h[2]) / w / self.dst[2] + self.dst[0],
            (h[3] * e + h[4] * n + h[5]) / w / self.dst[2] + self.dst[1],
        )

    def jacobian_sign(self) -> float:
        """The sign of the determinant of the transform at the points' centroid: negative for a chart
        with north up the image (y runs down), whatever its rotation; positive for a mirror image."""
        h = self.h
        u, v = h[2], h[5]
        return (h[0] - h[6] * u) * (h[4] - h[7] * v) - (h[1] - h[7] * u) * (h[3] - h[6] * v)

    def folds(self, width: float, height: float) -> bool:
        """Whether the horizon of the homography crosses the image: some pixel of the chart would be a
        position at infinity. The inverse's denominator, linear in the pixel, keeps one sign over the
        image or it does not; its corners say which."""
        h = self.h
        sx, tx = self.dst[2], self.dst[0]
        ty = self.dst[1]
        # The pixel to the normalised plane of `h`: (x - tx) * s, (y - ty) * s, then h's inverse; its
        # third row is the cross product of h's first two columns.
        a = h[3] * h[7] - h[4] * h[6]
        b = h[1] * h[6] - h[0] * h[7]
        c = h[0] * h[4] - h[1] * h[3]
        signs = set()
        for x, y in ((0.0, 0.0), (width, 0.0), (0.0, height), (width, height)):
            w = a * (x - tx) * sx + b * (y - ty) * sx + c
            signs.add(w > 0 if abs(w) > 1e-12 else None)
        return len(signs) != 1 or None in signs

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "lon0": self.lon0,
            "src": list(self.src),
            "dst": list(self.dst),
            "h": list(self.h),
        }


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """`a x = b` by Gaussian elimination with partial pivoting; None when `a` is singular."""
    n = len(a)
    m = [[*row, b[i]] for i, row in enumerate(a)]
    scale = max((abs(v) for row in a for v in row), default=0.0) or 1.0
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) <= 1e-12 * scale:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            if f:
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def _least_squares(rows: Sequence[Sequence[float]], values: Sequence[float]) -> list[float] | None:
    """The `x` that minimises |rows x - values|², by the normal equations (the rows are normalised)."""
    k = len(rows[0])
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    atb = [sum(r[i] * v for r, v in zip(rows, values, strict=True)) for i in range(k)]
    return _solve(ata, atb)


def _setup(
    points: Sequence[Point], lon0: float
) -> (
    tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        list[tuple[float, float]],
        list[tuple[float, float]],
    ]
    | None
):
    plane = [(wrap(p.lon - lon0), north(p.lat)) for p in points]
    pixels = [(p.x, p.y) for p in points]
    src, dst = _normaliser(plane), _normaliser(pixels)
    if src is None or dst is None:
        return None
    e_n = [((e - src[0]) * src[2], (n - src[1]) * src[2]) for e, n in plane]
    u_v = [((x - dst[0]) * dst[2], (y - dst[1]) * dst[2]) for x, y in pixels]
    return src, dst, e_n, u_v


def _affine(points: Sequence[Point], lon0: float) -> Transform | None:
    """The affine transform by least squares (through three points exactly); None when the points are
    in a line."""
    found = _setup(points, lon0)
    if found is None:
        return None
    src, dst, e_n, u_v = found
    rows = [(e, n, 1.0) for e, n in e_n]
    first = _least_squares(rows, [u for u, _v in u_v])
    second = _least_squares(rows, [v for _u, v in u_v])
    if first is None or second is None:
        return None
    h = (first[0], first[1], first[2], second[0], second[1], second[2], 0.0, 0.0)
    return Transform(AFFINE, lon0, src, dst, h)


def _apply(h: Sequence[float], e: float, n: float) -> tuple[float, float, float]:
    w = h[6] * e + h[7] * n + 1
    return (h[0] * e + h[1] * n + h[2]) / w, (h[3] * e + h[4] * n + h[5]) / w, w


def _projective(points: Sequence[Point], lon0: float) -> Transform | None:
    """The homography by the normalised direct linear transform, then refined to the least squares in
    pixels by Gauss-Newton; through four points exactly. None when the points do not fix one."""
    found = _setup(points, lon0)
    if found is None:
        return None
    src, dst, e_n, u_v = found
    rows: list[tuple[float, ...]] = []
    values: list[float] = []
    for (e, n), (u, v) in zip(e_n, u_v, strict=True):
        rows.append((e, n, 1.0, 0.0, 0.0, 0.0, -e * u, -n * u))
        values.append(u)
        rows.append((0.0, 0.0, 0.0, e, n, 1.0, -e * v, -n * v))
        values.append(v)
    solved = _least_squares(rows, values)
    if solved is None:
        return None
    h = list(solved)

    def cost(hh: Sequence[float]) -> float:
        total = 0.0
        for (e, n), (u, v) in zip(e_n, u_v, strict=True):
            pu, pv, w = _apply(hh, e, n)
            if not w > 0:
                return math.inf
            total += (pu - u) ** 2 + (pv - v) ** 2
        return total

    best = cost(h)
    for _ in range(REFINE_STEPS):
        if not best > 1e-24:
            break
        jac: list[tuple[float, ...]] = []
        res: list[float] = []
        for (e, n), (u, v) in zip(e_n, u_v, strict=True):
            pu, pv, w = _apply(h, e, n)
            jac.append((e / w, n / w, 1 / w, 0.0, 0.0, 0.0, -e * pu / w, -n * pu / w))
            res.append(u - pu)
            jac.append((0.0, 0.0, 0.0, e / w, n / w, 1 / w, -e * pv / w, -n * pv / w))
            res.append(v - pv)
        step = _least_squares(jac, res)
        if step is None:
            break
        trial = [a + b for a, b in zip(h, step, strict=True)]
        trial_cost = cost(trial)
        if not trial_cost < best:
            break
        h, best = trial, trial_cost
    if best == math.inf:
        return None
    return Transform(PROJECTIVE, lon0, src, dst, tuple(h))


# -- the fit ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fit:
    """The transform of the chart, the points it was fitted to, and each point's residual in pixels
    (None for three points: they fit exactly and cannot be checked)."""

    transform: Transform
    points: tuple[Point, ...]
    residuals: tuple[float | None, ...]
    width: int
    height: int

    @property
    def kind(self) -> str:
        return self.transform.kind

    @property
    def diagonal(self) -> float:
        return math.hypot(self.width, self.height)

    @property
    def limit_px(self) -> float:
        return RESIDUAL_LIMIT * self.diagonal

    @property
    def checked(self) -> bool:
        return all(r is not None for r in self.residuals)

    @property
    def worst(self) -> float | None:
        found = [r for r in self.residuals if r is not None]
        return max(found) if found else None

    def to_pixel(self, lat: float, lon: float) -> tuple[float, float] | None:
        return self.transform.to_pixel(lat, lon)

    def spans(self, pixel: tuple[float, float]) -> bool:
        """Whether a pixel lies within the control points' spread (their convex hull, a pixel's slack):
        where the residuals vouch for the fit. Beyond it, the fit extrapolates."""
        ring = hull([(p.x, p.y) for p in self.points])
        x, y = pixel
        return all(
            (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]) >= -math.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(ring, [*ring[1:], ring[0]], strict=True)
        )

    def to_json(self) -> dict[str, Any]:
        return {
            **self.transform.to_json(),
            "width": self.width,
            "height": self.height,
            "limit_px": round(self.limit_px, 2),
            "points": [
                {
                    "name": p.name,
                    "x": p.x,
                    "y": p.y,
                    "lat": p.lat,
                    "lon": p.lon,
                    "residual_px": None if r is None else round(r, 2),
                }
                for p, r in zip(self.points, self.residuals, strict=True)
            ],
        }


Model = Callable[[Sequence[Point], float], Transform | None]


def hull(pixels: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """The convex hull of `pixels`, counter-clockwise as the image's axes run (x right, y down):
    Andrew's monotone chain."""
    found = sorted(set(pixels))
    if len(found) < 3:
        return found

    def turn(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    upper: list[tuple[float, float]] = []
    for p in found:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(found):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _residual(points: Sequence[Point], i: int, lon0: float, model: Model) -> float:
    """How far `model` fitted to every point but the `i`th puts it from its own pixel; infinite when
    the others fix no transform, or put it beyond their horizon."""
    others = [p for j, p in enumerate(points) if j != i]
    found = model(others, lon0)
    p = points[i]
    at = None if found is None else found.to_pixel(p.lat, p.lon)
    return math.inf if at is None else math.hypot(at[0] - p.x, at[1] - p.y)


def _shape(model: Transform | None, width: int, height: int) -> str | None:
    """Why a transform cannot be the chart's, whatever its residuals; None when it can."""
    if model is None:
        return "the control points are nearly in a line, or two of them are one: they fix no transform"
    if model.jacobian_sign() > 0:
        return (
            "the control points make a mirror image of the chart: a point's lat and lon may be swapped, or"
            " its x and y, or y measured up from the bottom edge (it is measured down from the top)"
        )
    if model.folds(width, height):
        return (
            "the control points fold the chart: the transform they fix sends part of it to infinity; check"
            " each point, or spread them over the chart"
        )
    return None


def fit(points: Sequence[Point], width: int, height: int) -> Fit:
    """The fit of `points` on an image `width` × `height`, checked; `ChartFitError` when it is refused."""
    for p in points:
        if not (0 <= p.x <= width and 0 <= p.y <= height):
            raise ChartFitError(
                f"control point {p.name} is at pixel {p.x:g}, {p.y:g}, off the chart's {width} × {height}"
            )
    lon0 = central_lon(points)
    if len(points) == 3:
        a, b, c = points
        area = abs((b.x - a.x) * (c.y - a.y) - (c.x - a.x) * (b.y - a.y)) / 2
        if area < MIN_SPREAD * width * height:
            raise ChartFitError(
                "the three control points are nearly in a line on the chart: spread them over it, or give"
                " a fourth"
            )
        exact = _affine(points, lon0)
        problem = _shape(exact, width, height)
        if problem is not None or exact is None:
            raise ChartFitError(problem or "the control points fix no transform")
        return Fit(exact, tuple(points), (None, None, None), width, height)
    tried: Fit | None = None
    models: list[Model] = [_affine]
    if len(points) >= PROJECTIVE_POINTS:
        models.append(_projective)
    for model in models:
        transform = model(points, lon0)
        problem = _shape(transform, width, height)
        if transform is None or problem is not None:
            if tried is None:
                raise ChartFitError(problem or "the control points fix no transform")
            continue
        residuals = tuple(_residual(points, i, lon0, model) for i in range(len(points)))
        tried = Fit(transform, tuple(points), residuals, width, height)
        worst = tried.worst
        if worst is not None and worst <= tried.limit_px:
            return tried
    assert tried is not None
    raise ChartFitError(_refusal(tried))


def _refusal(tried: Fit) -> str:
    points, residuals = tried.points, tried.residuals
    worst = tried.worst or 0.0
    n = max(range(len(points)), key=lambda i: residuals[i] or 0.0)
    where = (
        f"control point {points[n].name} cannot be placed by the others (they are in a line, or put it"
        " beyond their horizon)"
        if math.isinf(worst)
        else f"the control points disagree by up to {worst:,.1f} px (the others place {points[n].name} worst)"
    )
    few = (
        " Checked as a flat chart (affine): a chart photographed at an angle needs"
        f" {PROJECTIVE_POINTS} points or more to be fitted as one."
        if len(points) < PROJECTIVE_POINTS
        else ""
    )
    return (
        f"the fit is refused: {where}, over the limit of {RESIDUAL_LIMIT:.0%} of the chart's diagonal"
        f" ({tried.limit_px:,.1f} px), fitted as {'an' if tried.kind == AFFINE else 'a'}"
        f" {tried.kind} transform."
        " Check every point's pixel and position:"
        f" one wrong point raises the others' residuals too.{few} Residuals: "
        + "; ".join(f"{p.name} {_px(r)}" for p, r in zip(points, residuals, strict=True))
    )


def _px(r: float | None) -> str:
    return "unchecked" if r is None else ("∞" if math.isinf(r) else f"{r:,.1f} px")


def residual_rows(found: Fit) -> list[Mapping[str, str]]:
    """The residuals as the page's corner lists them: name, residual in pixels and in the diagonal."""
    rows: list[Mapping[str, str]] = []
    for p, r in zip(found.points, found.residuals, strict=True):
        share = "" if r is None else f"{r / found.diagonal:.2%}"
        rows.append({"name": p.name, "px": _px(r), "share": share})
    return rows
