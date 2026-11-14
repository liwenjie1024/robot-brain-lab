"""把模型画成一张图（SVG）：正面和侧面，外壳是半透明的，能看到里面的驱动器、电池和电脑。

不用显卡，也不用别的库：把每个形状投影到平面上，画成多边形。给报告用，也用来检查模型的样子对不对。
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import mujoco
import numpy as np

from nova_body.model import FLOOR, PART_STYLES, NovaModel, PartKind, PartStyle
from nova_body.skeleton import ROOT_LINK, Vector

PIXELS_PER_METER = 300.0
MARGIN_PX = 40.0
TITLE_HEIGHT_PX = 34.0
# 左边留给高度刻度的宽度；右边留给图例的宽度（最长的一行说明要放得下）。
SCALE_WIDTH_PX = 64.0
LEGEND_ROW_PX = 22.0
LEGEND_WIDTH_PX = 320.0
GUIDE_COLOR = "#d5d8de"
# 每个视图两边留的空（米）。
VIEW_PADDING_M = 0.12
ROUND_STEPS = 12
ELLIPSE_STEPS = 36
HEIGHT_TICK_M = 0.5
OUTLINE_COLOR = "#3a3f4a"
TEXT_COLOR = "#2b2f36"
FLOOR_COLOR = "#8a8f98"
BACKGROUND_COLOR = "#ffffff"
CENTER_OF_MASS_COLOR = "#d12d2d"
CENTER_OF_MASS_RADIUS_PX = 6.0
FONT = "font-family='sans-serif'"
COLOR_SCALE = 255
MIN_HULL_POINTS = 3


@dataclass(frozen=True)
class View:
    """从哪边看。right：世界里的哪个方向画在图的右边；toward_viewer：哪个方向离看的人近。"""

    title: str
    right: Vector
    toward_viewer: Vector


FRONT_VIEW = View("正面", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
SIDE_VIEW = View("侧面（从右边看）", (1.0, 0.0, 0.0), (0.0, -1.0, 0.0))
VIEWS: tuple[View, ...] = (FRONT_VIEW, SIDE_VIEW)


@dataclass(frozen=True)
class _Shape:
    """投影以后的一块：轮廓（米，x 向右、y 向上）、离看的人多近、是什么。"""

    outline: np.ndarray
    nearness: float
    kind: PartKind


@dataclass(frozen=True)
class _Frame:
    """一个视图在图上占的地方（像素）：左边、宽度、地面的线在哪、世界的原点画在哪。"""

    left_px: float
    width_px: float
    floor_px: float
    origin_px: float

    def to_px(self, point: np.ndarray) -> tuple[float, float]:
        """视图里的一个点（米，x 向右、y 向上）画在图上的哪里。"""
        return self.origin_px + point[0] * PIXELS_PER_METER, self.floor_px - point[1] * PIXELS_PER_METER


def draw_body(nova: NovaModel, qpos: Sequence[float] | None = None) -> str:
    """画出这个姿势下的身体，返回 SVG 的全文。不给姿势就画站姿。"""
    model = nova.model
    data = mujoco.MjData(model)
    data.qpos[:] = nova.stand.qpos if qpos is None else qpos
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    center_of_mass = data.subtree_com[model.body(ROOT_LINK).id]

    panels = []
    left_px = SCALE_WIDTH_PX
    height_px = TITLE_HEIGHT_PX + nova.dimensions.height * PIXELS_PER_METER + 2 * MARGIN_PX
    floor_px = height_px - MARGIN_PX
    for view in VIEWS:
        shapes = _project(nova, data, view)
        low = min(float(shape.outline[:, 0].min()) for shape in shapes) - VIEW_PADDING_M
        high = max(float(shape.outline[:, 0].max()) for shape in shapes) + VIEW_PADDING_M
        frame = _Frame(left_px, (high - low) * PIXELS_PER_METER, floor_px, left_px - low * PIXELS_PER_METER)
        panels.append(_panel(view, shapes, center_of_mass, frame))
        left_px += frame.width_px + MARGIN_PX
    legend = _legend(left_px, TITLE_HEIGHT_PX + MARGIN_PX)
    scale = _height_scale(nova.dimensions.height, floor_px, left_px - MARGIN_PX)
    width_px = left_px + LEGEND_WIDTH_PX
    return "\n".join(
        [
            f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width_px:.0f} {height_px:.0f}' "
            f"width='{width_px:.0f}' height='{height_px:.0f}'>",
            f"<rect width='100%' height='100%' fill='{BACKGROUND_COLOR}'/>",
            scale,
            *panels,
            legend,
            "</svg>",
            "",
        ]
    )


def _project(nova: NovaModel, data: mujoco.MjData, view: View) -> list[_Shape]:
    """把每个形状投影到这个视图上。外壳先画，里面的东西后画；各自远的先画。"""
    model = nova.model
    axes = np.array([view.right, (0.0, 0.0, 1.0)])
    shapes = []
    for geom in range(model.ngeom):
        name = model.geom(geom).name
        if name == FLOOR:
            continue
        center = data.geom_xpos[geom]
        rotation = data.geom_xmat[geom].reshape(3, 3)
        outline = _outline(model.geom_type[geom], model.geom_size[geom], center, rotation, axes)
        shapes.append(_Shape(outline, float(np.dot(view.toward_viewer, center)), nova.part_kinds[name]))
    return sorted(shapes, key=lambda shape: (shape.kind is not PartKind.SHELL, shape.nearness))


def _outline(geom_type: int, size: np.ndarray, center: np.ndarray, rotation: np.ndarray, axes: np.ndarray):
    """一个形状投影以后的轮廓。"""
    flat_center = axes @ center
    if geom_type == mujoco.mjtGeom.mjGEOM_SPHERE:
        return flat_center + size[0] * _unit_circle(ELLIPSE_STEPS)
    if geom_type == mujoco.mjtGeom.mjGEOM_CAPSULE:
        half_axis = rotation[:, 2] * size[1]
        return _stadium(axes @ (center - half_axis), axes @ (center + half_axis), size[0])
    if geom_type == mujoco.mjtGeom.mjGEOM_ELLIPSOID:
        # 椭球投影以后是椭圆：把单位圆按"投影 x 旋转 x 三个半径"变形。
        spread = axes @ rotation @ np.diag(size)
        lengths, directions = np.linalg.eigh(spread @ spread.T)
        return flat_center + _unit_circle(ELLIPSE_STEPS) * np.sqrt(lengths) @ directions.T
    if geom_type == mujoco.mjtGeom.mjGEOM_BOX:
        signs = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)])
        corners = center + (signs * size) @ rotation.T
        return _convex_hull(corners @ axes.T)
    raise ValueError(f"还不会画这种形状：{geom_type}")


def _unit_circle(steps: int) -> np.ndarray:
    angles = np.linspace(0.0, 2 * math.pi, steps, endpoint=False)
    return np.column_stack([np.cos(angles), np.sin(angles)])


def _stadium(start: np.ndarray, end: np.ndarray, radius: float) -> np.ndarray:
    """胶囊投影以后的样子：一条线段，周围鼓出一个半径。线段正对着看的人时就是一个圆。"""
    along = end - start
    length = float(np.linalg.norm(along))
    if length < radius * 1e-6:
        return start + radius * _unit_circle(ELLIPSE_STEPS)
    heading = math.atan2(along[1], along[0])
    around_end = heading - math.pi / 2 + np.linspace(0.0, math.pi, ROUND_STEPS + 1)
    around_start = around_end + math.pi

    def half_circle(center: np.ndarray, angles: np.ndarray) -> np.ndarray:
        return center + radius * np.column_stack([np.cos(angles), np.sin(angles)])

    return np.vstack([half_circle(end, around_end), half_circle(start, around_start)])


def _convex_hull(points: np.ndarray) -> np.ndarray:
    """一堆点的凸包（Andrew 的单调链算法），逆时针。"""
    ordered = sorted({(round(float(x), 9), round(float(y), 9)) for x, y in points})
    if len(ordered) < MIN_HULL_POINTS:
        return np.array(ordered)

    def turns_left(origin, first, second) -> bool:
        return (first[0] - origin[0]) * (second[1] - origin[1]) - (first[1] - origin[1]) * (second[0] - origin[0]) > 0

    def half(sequence):
        chain: list[tuple[float, float]] = []
        for point in sequence:
            while len(chain) > 1 and not turns_left(chain[-2], chain[-1], point):
                chain.pop()
            chain.append(point)
        return chain[:-1]

    return np.array(half(ordered) + half(reversed(ordered)))


def _panel(view: View, shapes: list[_Shape], center_of_mass: np.ndarray, frame: _Frame) -> str:
    """一个视图：标题、地面的线、身体、重心。"""
    right_px = frame.left_px + frame.width_px
    lines = [
        f"<text x='{frame.left_px + frame.width_px / 2:.1f}' y='{TITLE_HEIGHT_PX:.1f}' text-anchor='middle' "
        f"font-size='18' {FONT} fill='{TEXT_COLOR}'>{view.title}</text>",
        f"<line x1='{frame.left_px:.1f}' y1='{frame.floor_px:.1f}' x2='{right_px:.1f}' y2='{frame.floor_px:.1f}' "
        f"stroke='{FLOOR_COLOR}' stroke-width='2'/>",
    ]
    for shape in shapes:
        style = PART_STYLES[shape.kind]
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in map(frame.to_px, shape.outline))
        lines.append(
            f"<polygon points='{points}' fill='{_css_color(style)}' fill-opacity='{style.rgba[3]:.2f}' "
            f"stroke='{OUTLINE_COLOR}' stroke-width='0.8'/>"
        )
    x, y = frame.to_px(np.array([np.dot(view.right, center_of_mass), center_of_mass[2]]))
    radius = CENTER_OF_MASS_RADIUS_PX
    lines.append(
        f"<g stroke='{CENTER_OF_MASS_COLOR}' stroke-width='2' fill='none'>"
        f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{radius:.1f}'/>"
        f"<line x1='{x - 2 * radius:.1f}' y1='{y:.1f}' x2='{x + 2 * radius:.1f}' y2='{y:.1f}'/>"
        f"<line x1='{x:.1f}' y1='{y - 2 * radius:.1f}' x2='{x:.1f}' y2='{y + 2 * radius:.1f}'/></g>"
    )
    return "\n".join(lines)


def _css_color(style: PartStyle) -> str:
    red, green, blue, _ = style.rgba
    return f"rgb({red * COLOR_SCALE:.0f},{green * COLOR_SCALE:.0f},{blue * COLOR_SCALE:.0f})"


def _height_scale(height_m: float, floor_px: float, right_px: float) -> str:
    """左边的高度刻度：每 0.5 m 一格，再加上头顶；每个刻度有一条浅色的横线，画在身体的后面。"""
    marks = [index * HEIGHT_TICK_M for index in range(int(height_m / HEIGHT_TICK_M) + 1)] + [height_m]
    lines = []
    for mark in marks:
        y = floor_px - mark * PIXELS_PER_METER
        lines.append(
            f"<line x1='{SCALE_WIDTH_PX:.1f}' y1='{y:.1f}' x2='{right_px:.1f}' y2='{y:.1f}' "
            f"stroke='{GUIDE_COLOR}' stroke-width='1' stroke-dasharray='4 4'/>"
            f"<text x='{SCALE_WIDTH_PX - 8:.1f}' y='{y + 4:.1f}' text-anchor='end' font-size='11' {FONT} "
            f"fill='{FLOOR_COLOR}'>{mark:.2f} m</text>"
        )
    return "\n".join(lines)


def _legend(left_px: float, top_px: float) -> str:
    """右边的图例：每种颜色是什么，还有重心的记号。"""
    lines = []
    for row, style in enumerate(PART_STYLES.values()):
        y = top_px + row * LEGEND_ROW_PX
        lines.append(
            f"<rect x='{left_px:.1f}' y='{y:.1f}' width='14' height='14' fill='{_css_color(style)}' "
            f"fill-opacity='{style.rgba[3]:.2f}' stroke='{OUTLINE_COLOR}' stroke-width='0.8'/>"
            f"<text x='{left_px + 22:.1f}' y='{y + 12:.1f}' font-size='13' {FONT} "
            f"fill='{TEXT_COLOR}'>{style.name}</text>"
        )
    y = top_px + len(PART_STYLES) * LEGEND_ROW_PX
    lines.append(
        f"<circle cx='{left_px + 7:.1f}' cy='{y + 7:.1f}' r='5' stroke='{CENTER_OF_MASS_COLOR}' stroke-width='2' "
        f"fill='none'/><text x='{left_px + 22:.1f}' y='{y + 12:.1f}' font-size='13' {FONT} "
        f"fill='{TEXT_COLOR}'>重心</text>"
    )
    return "\n".join(lines)
