"""把身体画成一张图（SVG）：正面和侧面。给报告用，也用来检查模型的样子对不对。

不用显卡，也不用别的库：把每个形状投影到平面上，画成多边形，颜色用模型里写的。
Nova 的外壳是半透明的，能看到里面的驱动器、电池和电脑。
现成的模型（基线）画的是它看得见的外形：每个网格画成它的凸包，所以只有大的轮廓，没有细节。
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import mujoco
import numpy as np

from nova_body.bench import FLOOR
from nova_body.body import Body

PIXELS_PER_METER = 300.0
MARGIN_PX = 40.0
TITLE_HEIGHT_PX = 34.0
TITLE_FONT_PX = 18
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
CENTER_OF_MASS_HALO_PX = 5.0
FONT = "font-family='sans-serif'"
COLOR_SCALE = 255
MIN_HULL_POINTS = 3
# 网格的点很多：先在一圈方向上各取最远的那个点，再求这些点的凸包。
HULL_DIRECTIONS = 180
FREE_JOINT_DOF = 6

# 并排画的图：每个身体上面有三行字（名字；身高、质量、自由度；视图的名字）。
LINEUP_NAME_PX = 30.0
LINEUP_FACTS_PX = 52.0
LINEUP_VIEW_TITLE_PX = 76.0
LINEUP_CAPTION_PX = 84.0
LINEUP_FACTS_FONT_PX = 13
LINEUP_VIEW_FONT_PX = 13
# 身体和身体之间留的空，图的右边留的空。
LINEUP_GAP_PX = 50.0
LINEUP_RIGHT_MARGIN_PX = 24.0

Rgba = tuple[float, float, float, float]
LegendEntry = tuple[str, Rgba]


@dataclass(frozen=True)
class View:
    """从哪边看。right：世界里的哪个方向画在图的右边；toward_viewer：哪个方向离看的人近。"""

    title: str
    right: tuple[float, float, float]
    toward_viewer: tuple[float, float, float]


FRONT_VIEW = View("正面", (0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
SIDE_VIEW = View("侧面（从右边看）", (1.0, 0.0, 0.0), (0.0, -1.0, 0.0))
VIEWS: tuple[View, ...] = (FRONT_VIEW, SIDE_VIEW)


@dataclass(frozen=True)
class _Shape:
    """投影以后的一块：轮廓（米，x 向右、y 向上）、颜色、在第几层、离看的人多近。"""

    outline: np.ndarray
    rgba: Rgba
    layer: int
    nearness: float


@dataclass(frozen=True)
class _Frame:
    """一个视图在图上占的地方（像素）：左边、宽度、地面的线在哪、世界的原点画在哪、标题写在哪、字多大。"""

    left_px: float
    width_px: float
    floor_px: float
    origin_px: float
    title_px: float
    title_font_px: int

    def to_px(self, point: np.ndarray) -> tuple[float, float]:
        """视图里的一个点（米，x 向右、y 向上）画在图上的哪里。"""
        return self.origin_px + point[0] * PIXELS_PER_METER, self.floor_px - point[1] * PIXELS_PER_METER


@dataclass(frozen=True)
class _Row:
    """一排视图画在哪：地面的线在哪，每个视图的标题写在哪、字多大。"""

    floor_px: float
    title_px: float
    title_font_px: int


def draw_body(body: Body, qpos: Sequence[float] | None = None, legend: Sequence[LegendEntry] = ()) -> str:
    """画出这个姿势下的身体，返回 SVG 的全文。不给姿势就画站姿。legend 是右边的图例：每种颜色是什么。"""
    data = _posed(body, qpos)
    height_px = TITLE_HEIGHT_PX + body.height_m * PIXELS_PER_METER + 2 * MARGIN_PX
    row = _Row(height_px - MARGIN_PX, TITLE_HEIGHT_PX, TITLE_FONT_PX)
    panels, left_px = _views(body, data, SCALE_WIDTH_PX, row)
    parts = [
        _height_scale([body.height_m], row.floor_px, left_px - MARGIN_PX),
        *panels,
        _legend(legend, left_px, TITLE_HEIGHT_PX + MARGIN_PX),
    ]
    return _svg(left_px + LEGEND_WIDTH_PX, height_px, parts)


def draw_lineup(bodies: Sequence[Body]) -> str:
    """把几个身体按同一个比例并排画在同一条地面上，都是站姿。

    每个身体画正面和侧面，上面写名字、身高、质量、自由度。左边的刻度上标着每个身体的身高。
    """
    if not bodies:
        raise ValueError("至少要有一个身体才能画")
    heights = [body.height_m for body in bodies]
    height_px = LINEUP_CAPTION_PX + max(heights) * PIXELS_PER_METER + 2 * MARGIN_PX
    row = _Row(height_px - MARGIN_PX, LINEUP_VIEW_TITLE_PX, LINEUP_VIEW_FONT_PX)
    parts = []
    left_px = SCALE_WIDTH_PX
    for body in bodies:
        panels, after_px = _views(body, _posed(body, None), left_px, row)
        parts += [_caption(body, (left_px + after_px - MARGIN_PX) / 2), *panels]
        left_px = after_px - MARGIN_PX + LINEUP_GAP_PX
    right_px = left_px - LINEUP_GAP_PX
    return _svg(right_px + LINEUP_RIGHT_MARGIN_PX, height_px, [_height_scale(heights, row.floor_px, right_px), *parts])


def _posed(body: Body, qpos: Sequence[float] | None) -> mujoco.MjData:
    """摆在这个姿势上的状态（只算位置）。"""
    data = mujoco.MjData(body.model)
    data.qpos[:] = body.stand.qpos if qpos is None else qpos
    mujoco.mj_kinematics(body.model, data)
    mujoco.mj_comPos(body.model, data)
    return data


def _svg(width_px: float, height_px: float, parts: Sequence[str]) -> str:
    return "\n".join(
        [
            f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {width_px:.0f} {height_px:.0f}' "
            f"width='{width_px:.0f}' height='{height_px:.0f}'>",
            f"<rect width='100%' height='100%' fill='{BACKGROUND_COLOR}'/>",
            *parts,
            "</svg>",
            "",
        ]
    )


def _views(body: Body, data: mujoco.MjData, left_px: float, row: _Row) -> tuple[list[str], float]:
    """从 left_px 开始，一个挨一个地画这个身体的每个视图。返回画好的视图，和下一个视图该从哪开始。"""
    center_of_mass = data.subtree_com[body.model.body(body.anatomy.root).id]
    panels = []
    for view in VIEWS:
        shapes = _project(body, data, view)
        low = min(float(shape.outline[:, 0].min()) for shape in shapes) - VIEW_PADDING_M
        high = max(float(shape.outline[:, 0].max()) for shape in shapes) + VIEW_PADDING_M
        width_px = (high - low) * PIXELS_PER_METER
        origin_px = left_px - low * PIXELS_PER_METER
        frame = _Frame(left_px, width_px, row.floor_px, origin_px, row.title_px, row.title_font_px)
        panels.append(_panel(view, shapes, center_of_mass, frame))
        left_px += width_px + MARGIN_PX
    return panels, left_px


def _project(body: Body, data: mujoco.MjData, view: View) -> list[_Shape]:
    """把要画的每个形状投影到这个视图上。组号小的先画（外壳在里面的东西下面）；同一组里远的先画。"""
    model = body.model
    axes = np.array([view.right, (0.0, 0.0, 1.0)])
    shapes = []
    for geom in range(model.ngeom):
        if model.geom_group[geom] not in body.drawn_groups or model.geom(geom).name == FLOOR:
            continue
        outline = _geom_outline(model, data, geom, axes)
        nearness = float(np.dot(view.toward_viewer, data.geom_xpos[geom]))
        shapes.append(_Shape(outline, shape_color(model, geom), int(model.geom_group[geom]), nearness))
    return sorted(shapes, key=lambda shape: (shape.layer, shape.nearness))


def shape_color(model: mujoco.MjModel, geom: int) -> Rgba:
    """这个形状的颜色：有材质用材质的，没有用它自己的。"""
    material = model.geom_matid[geom]
    rgba = model.geom_rgba[geom] if material < 0 else model.mat_rgba[material]
    return tuple(float(value) for value in rgba)


def _geom_outline(model: mujoco.MjModel, data: mujoco.MjData, geom: int, axes: np.ndarray) -> np.ndarray:
    """模型里一个形状投影以后的轮廓。"""
    center = data.geom_xpos[geom]
    rotation = data.geom_xmat[geom].reshape(3, 3)
    if model.geom_type[geom] == mujoco.mjtGeom.mjGEOM_MESH:
        mesh = model.geom_dataid[geom]
        start = model.mesh_vertadr[mesh]
        points = model.mesh_vert[start : start + model.mesh_vertnum[mesh]] @ rotation.T + center
        return _hull_of_many(points @ axes.T)
    return _outline(model.geom_type[geom], model.geom_size[geom], center, rotation, axes)


def _outline(geom_type: int, size: np.ndarray, center: np.ndarray, rotation: np.ndarray, axes: np.ndarray):
    """一个简单的形状（球、胶囊、椭球、盒子）投影以后的轮廓。"""
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


def _hull_of_many(points: np.ndarray) -> np.ndarray:
    """很多个点的凸包（差不多的）：在一圈方向上各取最远的那个点，再求这些点的凸包。

    漏掉的只是相邻两个方向之间的小角，画图看不出来。
    """
    farthest = np.unique(np.argmax(points @ _unit_circle(HULL_DIRECTIONS).T, axis=0))
    return _convex_hull(points[farthest])


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
        f"<text x='{frame.left_px + frame.width_px / 2:.1f}' y='{frame.title_px:.1f}' text-anchor='middle' "
        f"font-size='{frame.title_font_px}' {FONT} fill='{TEXT_COLOR}'>{view.title}</text>",
        f"<line x1='{frame.left_px:.1f}' y1='{frame.floor_px:.1f}' x2='{right_px:.1f}' y2='{frame.floor_px:.1f}' "
        f"stroke='{FLOOR_COLOR}' stroke-width='2'/>",
    ]
    for shape in shapes:
        points = " ".join(f"{x:.1f},{y:.1f}" for x, y in map(frame.to_px, shape.outline))
        lines.append(
            f"<polygon points='{points}' fill='{_css_color(shape.rgba)}' fill-opacity='{shape.rgba[3]:.2f}' "
            f"stroke='{OUTLINE_COLOR}' stroke-width='0.8'/>"
        )
    x, y = frame.to_px(np.array([np.dot(view.right, center_of_mass), center_of_mass[2]]))
    radius = CENTER_OF_MASS_RADIUS_PX
    mark = (
        f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{radius:.1f}'/>"
        f"<line x1='{x - 2 * radius:.1f}' y1='{y:.1f}' x2='{x + 2 * radius:.1f}' y2='{y:.1f}'/>"
        f"<line x1='{x:.1f}' y1='{y - 2 * radius:.1f}' x2='{x:.1f}' y2='{y + 2 * radius:.1f}'/>"
    )
    # 先画一圈白边：重心落在红色的东西上面时也看得清。
    lines.append(f"<g stroke='{BACKGROUND_COLOR}' stroke-width='{CENTER_OF_MASS_HALO_PX:g}' fill='none'>{mark}</g>")
    lines.append(f"<g stroke='{CENTER_OF_MASS_COLOR}' stroke-width='2' fill='none'>{mark}</g>")
    return "\n".join(lines)


def _caption(body: Body, center_px: float) -> str:
    """并排画时每个身体上面的两行字：名字；身高、质量、自由度。"""
    joints = body.model.nv - FREE_JOINT_DOF
    facts = f"身高 {body.height_m:.2f} m · 质量 {body.mass_kg:.1f} kg · {joints} 个自由度"
    return (
        f"<text x='{center_px:.1f}' y='{LINEUP_NAME_PX:.1f}' text-anchor='middle' font-size='{TITLE_FONT_PX}' "
        f"font-weight='bold' {FONT} fill='{TEXT_COLOR}'>{body.name}</text>"
        f"<text x='{center_px:.1f}' y='{LINEUP_FACTS_PX:.1f}' text-anchor='middle' "
        f"font-size='{LINEUP_FACTS_FONT_PX}' {FONT} fill='{TEXT_COLOR}'>{facts}</text>"
    )


def _css_color(rgba: Rgba) -> str:
    red, green, blue, _ = rgba
    return f"rgb({red * COLOR_SCALE:.0f},{green * COLOR_SCALE:.0f},{blue * COLOR_SCALE:.0f})"


def _height_scale(heights_m: Sequence[float], floor_px: float, right_px: float) -> str:
    """左边的高度刻度：每 0.5 m 一格，再加上每个身体的头顶；每个刻度有一条浅色的横线，画在身体的后面。"""
    ticks = [index * HEIGHT_TICK_M for index in range(int(max(heights_m) / HEIGHT_TICK_M) + 1)]
    lines = []
    for mark in [*ticks, *sorted(heights_m)]:
        y = floor_px - mark * PIXELS_PER_METER
        lines.append(
            f"<line x1='{SCALE_WIDTH_PX:.1f}' y1='{y:.1f}' x2='{right_px:.1f}' y2='{y:.1f}' "
            f"stroke='{GUIDE_COLOR}' stroke-width='1' stroke-dasharray='4 4'/>"
            f"<text x='{SCALE_WIDTH_PX - 8:.1f}' y='{y + 4:.1f}' text-anchor='end' font-size='11' {FONT} "
            f"fill='{FLOOR_COLOR}'>{mark:.2f} m</text>"
        )
    return "\n".join(lines)


def _legend(entries: Sequence[LegendEntry], left_px: float, top_px: float) -> str:
    """右边的图例：每种颜色是什么，还有重心的记号。"""
    lines = []
    for row, (name, rgba) in enumerate(entries):
        y = top_px + row * LEGEND_ROW_PX
        lines.append(
            f"<rect x='{left_px:.1f}' y='{y:.1f}' width='14' height='14' fill='{_css_color(rgba)}' "
            f"fill-opacity='{rgba[3]:.2f}' stroke='{OUTLINE_COLOR}' stroke-width='0.8'/>"
            f"<text x='{left_px + 22:.1f}' y='{y + 12:.1f}' font-size='13' {FONT} "
            f"fill='{TEXT_COLOR}'>{name}</text>"
        )
    y = top_px + len(entries) * LEGEND_ROW_PX
    lines.append(
        f"<circle cx='{left_px + 7:.1f}' cy='{y + 7:.1f}' r='5' stroke='{CENTER_OF_MASS_COLOR}' stroke-width='2' "
        f"fill='none'/><text x='{left_px + 22:.1f}' y='{y + 12:.1f}' font-size='13' {FONT} "
        f"fill='{TEXT_COLOR}'>重心</text>"
    )
    return "\n".join(lines)
