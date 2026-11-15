"""画图的测试：画出来的是一份合格的 SVG，每一块都画了，两次画的一样；几个身体并排画时是同一个比例。"""

import math
from xml.etree import ElementTree

import mujoco
import numpy as np
import pytest

from nova_body.drawing import (
    MARGIN_PX,
    PIXELS_PER_METER,
    VIEWS,
    _convex_hull,
    _hull_of_many,
    _outline,
    _stadium,
    draw_body,
    draw_lineup,
)
from nova_body.model import PART_STYLES, PartKind, part_legend

SVG = "{http://www.w3.org/2000/svg}"
G1_VISIBLE_MESHES = 35
# 估字的宽度用的：从这个编码往后是汉字和全角的标点；别的字符按 0.62 个字宽；字在基线下面还有 0.25 个字高。
FIRST_WIDE_CHARACTER = 0x2E80
NARROW_WIDTH_EM = 0.62
DESCENT_EM = 0.25


def polygons_of(picture: str) -> list[np.ndarray]:
    """图里每个多边形的点（像素）。"""
    root = ElementTree.fromstring(picture)
    return [
        np.array([[float(value) for value in pair.split(",")] for pair in polygon.attrib["points"].split()])
        for polygon in root.findall(SVG + "polygon")
    ]


def texts_of(picture: str) -> list[str]:
    return [element.text for element in ElementTree.fromstring(picture).iter(SVG + "text")]


def text_boxes(picture: str) -> list[tuple[str, float, float, float, float]]:
    """图上每一行字占的地方：字、左、上、右、下（像素）。

    这里没有字体，量不了真的宽度，所以按最宽的估：汉字和全角的标点一个字宽，别的（字母、数字、空格）0.62 个字宽。
    """
    boxes = []
    for element in ElementTree.fromstring(picture).iter(SVG + "text"):
        size = float(element.attrib["font-size"])
        width = size * sum(
            1.0 if ord(character) >= FIRST_WIDE_CHARACTER else NARROW_WIDTH_EM for character in element.text
        )
        x, baseline = float(element.attrib["x"]), float(element.attrib["y"])
        anchor = element.attrib.get("text-anchor", "start")
        left = {"start": x, "middle": x - width / 2, "end": x - width}[anchor]
        boxes.append((element.text, left, baseline - size, left + width, baseline + DESCENT_EM * size))
    return boxes


def floor_lines_of(picture: str) -> list[float]:
    """每个视图里地面那条线的高度（像素）。"""
    root = ElementTree.fromstring(picture)
    return [float(line.attrib["y1"]) for line in root.findall(SVG + "line") if line.attrib["stroke-width"] == "2"]


@pytest.fixture(scope="module")
def picture(nova) -> str:
    """Nova 站姿的图，只画一次。"""
    return draw_body(nova.body, legend=part_legend())


@pytest.fixture(scope="module")
def lineup(nova, g1) -> str:
    """Nova 和基线并排的图，只画一次。"""
    return draw_lineup([nova.body, g1])


# 一个身体 --------------------------------------------------------------------------------------------


def test_picture_is_well_formed_svg(picture):
    """画出来的是能解析的 SVG，有宽和高。"""
    root = ElementTree.fromstring(picture)
    assert root.tag == SVG + "svg"
    assert float(root.attrib["width"]) > 0
    assert float(root.attrib["height"]) > 0


def test_every_part_is_drawn_in_both_views(picture, nova):
    """每一块（除了地面）在正面和侧面各画一次。"""
    assert len(polygons_of(picture)) == len(VIEWS) * (nova.model.ngeom - 1)


def test_every_shape_is_inside_the_picture(picture):
    """每个多边形的点都在图的范围里，没有画到外面去，也没有坏掉的数。"""
    root = ElementTree.fromstring(picture)
    width, height = float(root.attrib["width"]), float(root.attrib["height"])
    for points in polygons_of(picture):
        assert np.isfinite(points).all()
        assert (points[:, 0] >= 0).all() and (points[:, 0] <= width).all()
        assert (points[:, 1] >= 0).all() and (points[:, 1] <= height).all()


def test_picture_has_titles_and_legend(picture):
    """图上有两个视图的名字、每种颜色的说明、重心的记号、身高。"""
    texts = texts_of(picture)
    for view in VIEWS:
        assert view.title in texts
    for style in PART_STYLES.values():
        assert style.name in texts
    assert "重心" in texts
    assert "1.70 m" in texts


def test_colors_are_the_ones_in_the_model(picture):
    """每一块的颜色就是模型里写的：电池是橙色的，外壳是半透明的。"""
    red, green, blue, _ = PART_STYLES[PartKind.BATTERY].rgba
    battery = f"fill='rgb({red * 255:.0f},{green * 255:.0f},{blue * 255:.0f})' fill-opacity='1.00'"
    assert picture.count(battery) == len(VIEWS) + 1  # 两个视图各一块电池，图例里一个
    assert f"fill-opacity='{PART_STYLES[PartKind.SHELL].rgba[3]:.2f}'" in picture


def test_shells_are_drawn_under_the_parts_inside_them(picture, nova):
    """外壳先画，里面的东西后画，所以里面的东西不会被外壳盖住。"""
    root = ElementTree.fromstring(picture)
    opacities = [polygon.attrib["fill-opacity"] for polygon in root.findall(SVG + "polygon")]
    per_view = len(opacities) // len(VIEWS)
    shells = sum(1 for kind in nova.part_kinds.values() if kind is PartKind.SHELL)
    for view in range(len(VIEWS)):
        one_view = opacities[view * per_view : (view + 1) * per_view]
        assert set(one_view[:shells]) == {"0.35"}
        assert set(one_view[shells:]) == {"1.00"}


def test_drawing_twice_gives_the_same_picture(picture, nova):
    """同一个姿势画两次，一个字都不差。"""
    assert draw_body(nova.body, legend=part_legend()) == picture


def test_another_pose_gives_another_picture(picture, nova):
    """换一个姿势（零位：站直），画出来的不一样。"""
    assert draw_body(nova.body, nova.model.qpos0, part_legend()) != picture


def test_center_of_mass_mark_has_a_white_edge(picture):
    """重心的记号先画一圈白边，再画红的：落在红色的东西上面也看得清。每个视图各一个。"""
    groups = ElementTree.fromstring(picture).findall(SVG + "g")
    assert [group.attrib["stroke"] for group in groups] == ["#ffffff", "#d12d2d"] * len(VIEWS)
    for white, red in zip(groups[::2], groups[1::2], strict=True):
        assert float(white.attrib["stroke-width"]) > float(red.attrib["stroke-width"])
        assert [child.attrib for child in white] == [child.attrib for child in red]
        assert [child.tag for child in red] == [SVG + "circle", SVG + "line", SVG + "line"]


@pytest.mark.parametrize("which", ["picture", "lineup"], ids=["一个身体的图", "并排的图"])
def test_every_line_of_text_fits_and_none_overlap(which, request):
    """图上的每一行字都在图的范围里，互相不重叠，也不压在身体上（字的宽度按最宽的估）。"""
    drawn = request.getfixturevalue(which)
    root = ElementTree.fromstring(drawn)
    width, height = float(root.attrib["width"]), float(root.attrib["height"])
    boxes = text_boxes(drawn)
    assert len(boxes) >= 8
    for text, left, top, right, bottom in boxes:
        assert left >= 0 and right <= width, text
        assert top >= 0 and bottom <= height, text
    for index, (text, left, top, right, bottom) in enumerate(boxes):
        for other, other_left, other_top, other_right, other_bottom in boxes[index + 1 :]:
            apart = right <= other_left or other_right <= left or bottom <= other_top or other_bottom <= top
            assert apart, (text, other)
    body_top = min(points[:, 1].min() for points in polygons_of(drawn))
    titles = [box for box in boxes if box[0] in {view.title for view in VIEWS} or "身高" in box[0]]
    assert titles
    assert max(bottom for _, _, _, _, bottom in titles) < body_top


def test_legend_is_only_drawn_when_given(nova, picture):
    """不给图例时只有重心的记号，没有各种颜色的说明；身体画的还是一样。"""
    plain = draw_body(nova.body)
    assert "重心" in texts_of(plain)
    assert PART_STYLES[PartKind.BATTERY].name not in texts_of(plain)
    assert len(polygons_of(plain)) == len(polygons_of(picture))


def test_standing_straight_reaches_the_height_line(body):
    """每个身体站直（零位）时，画出来的头顶正好在身高那条线上，脚底在地面的线上（差不到 2 像素）。"""
    straight = draw_body(body, body.model.qpos0)
    floor = floor_lines_of(straight)[0]
    polygons = polygons_of(straight)
    top = min(points[:, 1].min() for points in polygons)
    bottom = max(points[:, 1].max() for points in polygons)
    assert floor - top == pytest.approx(body.height_m * PIXELS_PER_METER, abs=2.0)
    assert bottom == pytest.approx(floor, abs=2.0)
    assert f"{body.height_m:.2f} m" in texts_of(straight)


# 现成的模型：画网格 ----------------------------------------------------------------------------------


def test_baseline_is_drawn_from_its_visible_meshes(g1):
    """基线画的是它看得见的 35 个网格，正面和侧面各一次；碰撞用的形状和地面不画。"""
    drawn = draw_body(g1)
    assert len(polygons_of(drawn)) == len(VIEWS) * G1_VISIBLE_MESHES
    assert "fill='rgb(178,178,178)' fill-opacity='1.00'" in drawn
    assert "fill='rgb(51,51,51)' fill-opacity='1.00'" in drawn


def test_mesh_outlines_are_small_polygons(g1):
    """一个网格有上万个点，画出来只是它的凸包：每个多边形最多 180 个点。"""
    polygons = polygons_of(draw_body(g1))
    assert max(len(points) for points in polygons) <= 180
    assert min(len(points) for points in polygons) >= 3


def test_hull_of_many_points_keeps_the_corners():
    """很多个点里，最外面的四个角都留着，里面的点都去掉。"""
    random = np.random.default_rng(0)
    inside = random.uniform(-0.9, 0.9, size=(5000, 2))
    corners = np.array([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
    hull = _hull_of_many(np.vstack([inside, corners]))
    assert sorted(map(tuple, hull)) == sorted(map(tuple, corners))


def test_hull_of_many_points_on_a_circle_stays_round():
    """一圈 2000 个点：凸包的面积和圆差不到千分之一。"""
    angles = np.linspace(0.0, 2 * math.pi, 2000, endpoint=False)
    hull = _hull_of_many(np.column_stack([np.cos(angles), np.sin(angles)]))
    x, y = hull[:, 0], hull[:, 1]
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    assert area == pytest.approx(math.pi, rel=1e-3)


# 几个身体并排 ----------------------------------------------------------------------------------------


def test_lineup_shows_every_body_with_its_facts(lineup):
    """并排的图上每个身体都有名字、身高、质量、自由度；左边的刻度上有每个身体的身高。"""
    texts = texts_of(lineup)
    assert "Nova（核心版）" in texts
    assert "Unitree G1" in texts
    assert "身高 1.70 m · 质量 78.2 kg · 75 个自由度" in texts
    assert "身高 1.32 m · 质量 33.3 kg · 29 个自由度" in texts
    assert {"1.32 m", "1.70 m", "0.00 m", "1.50 m"} <= set(texts)
    assert texts.count(VIEWS[0].title) == 2


def test_lineup_draws_every_body_in_both_views(lineup, nova):
    """并排的图里，每个身体的每一块都画了：Nova 的每一块和基线的 35 个网格，各两个视图。"""
    assert len(polygons_of(lineup)) == len(VIEWS) * (nova.model.ngeom - 1 + G1_VISIBLE_MESHES)


def test_lineup_puts_every_body_on_the_same_floor(lineup):
    """几个身体站在同一条地面的线上，从左到右一个挨一个，都在图的范围里。"""
    root = ElementTree.fromstring(lineup)
    width, height = float(root.attrib["width"]), float(root.attrib["height"])
    floors = floor_lines_of(lineup)
    assert len(floors) == 2 * len(VIEWS)
    assert len(set(floors)) == 1
    assert floors[0] == height - MARGIN_PX
    for points in polygons_of(lineup):
        assert (points[:, 0] >= 0).all() and (points[:, 0] <= width).all()
        assert (points[:, 1] >= 0).all() and (points[:, 1] <= floors[0] + 1.0).all()


def test_lineup_uses_the_same_scale_for_every_body(lineup, nova, g1):
    """并排的图里每个身体的大小，和单独画它的时候一样（同一个比例），所以高的就是画得高。"""
    polygons = polygons_of(lineup)
    nova_count = len(VIEWS) * (nova.model.ngeom - 1)

    def height_px(shapes: list[np.ndarray]) -> float:
        return max(points[:, 1].max() for points in shapes) - min(points[:, 1].min() for points in shapes)

    nova_px, g1_px = height_px(polygons[:nova_count]), height_px(polygons[nova_count:])
    assert nova_px == pytest.approx(height_px(polygons_of(draw_body(nova.body))), abs=0.2)
    assert g1_px == pytest.approx(height_px(polygons_of(draw_body(g1))), abs=0.2)
    assert nova_px / g1_px == pytest.approx(nova.body.height_m / g1.height_m, rel=0.02)
    # 基线画在 Nova 的右边。
    nova_right = max(points[:, 0].max() for points in polygons[:nova_count])
    g1_left = min(points[:, 0].min() for points in polygons[nova_count:])
    assert g1_left > nova_right


def test_lineup_is_repeatable_and_needs_a_body(lineup, nova, g1):
    """画两次一个字都不差；一个身体也能画；一个都没有就报错。"""
    assert draw_lineup([nova.body, g1]) == lineup
    alone = draw_lineup([g1])
    assert len(polygons_of(alone)) == len(VIEWS) * G1_VISIBLE_MESHES
    with pytest.raises(ValueError, match="至少要有一个身体才能画"):
        draw_lineup([])


# 每种形状 --------------------------------------------------------------------------------------------


def test_capsule_seen_end_on_is_a_circle():
    """胶囊正对着看的人时，画出来是一个圆。"""
    outline = _stadium(np.array([1.0, 2.0]), np.array([1.0, 2.0]), 0.5)
    assert np.linalg.norm(outline - [1.0, 2.0], axis=1) == pytest.approx(0.5)


def test_capsule_seen_from_the_side_is_a_stadium():
    """胶囊从侧面看：长度是线段的长加两个半径，宽度是两个半径。"""
    outline = _stadium(np.array([0.0, 0.0]), np.array([2.0, 0.0]), 0.5)
    assert outline[:, 0].min() == pytest.approx(-0.5)
    assert outline[:, 0].max() == pytest.approx(2.5)
    assert outline[:, 1].min() == pytest.approx(-0.5)
    assert outline[:, 1].max() == pytest.approx(0.5)


def test_convex_hull_drops_inner_and_repeated_points():
    """凸包只留最外面的点：里面的点、重复的点都去掉。"""
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    hull = _convex_hull(np.array([*square, (0.5, 0.5), (1.0, 1.0), (0.5, 0.0)]))
    assert sorted(map(tuple, hull)) == sorted(square)


def test_convex_hull_of_too_few_points_is_the_points():
    """不到 3 个点时没有凸包，原样返回。"""
    assert len(_convex_hull(np.array([(0.0, 0.0), (1.0, 1.0), (0.0, 0.0)]))) == 2


@pytest.mark.parametrize(
    ("geom_type", "size", "width", "height"),
    [
        (mujoco.mjtGeom.mjGEOM_SPHERE, (0.5, 0.0, 0.0), 1.0, 1.0),
        (mujoco.mjtGeom.mjGEOM_BOX, (0.1, 0.2, 0.3), 0.4, 0.6),
        (mujoco.mjtGeom.mjGEOM_ELLIPSOID, (0.1, 0.2, 0.3), 0.4, 0.6),
        (mujoco.mjtGeom.mjGEOM_CAPSULE, (0.1, 0.3, 0.0), 0.2, 0.8),
    ],
    ids=["球", "盒子", "椭球", "胶囊"],
)
def test_outline_has_the_size_of_the_shape(geom_type, size, width, height):
    """从正面看（y 向右、z 向上），每种形状的轮廓有它该有的宽和高。"""
    axes = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    outline = _outline(geom_type, np.array(size), np.zeros(3), np.eye(3), axes)
    assert np.ptp(outline[:, 0]) == pytest.approx(width, abs=0.01)
    assert np.ptp(outline[:, 1]) == pytest.approx(height, abs=0.01)


def test_rotated_box_outline():
    """盒子绕前后的轴转 90°，宽和高就换过来。"""
    axes = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    quarter = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    outline = _outline(mujoco.mjtGeom.mjGEOM_BOX, np.array([0.1, 0.2, 0.3]), np.zeros(3), quarter, axes)
    assert np.ptp(outline[:, 0]) == pytest.approx(0.6)
    assert np.ptp(outline[:, 1]) == pytest.approx(0.4)


def test_unknown_shape_is_rejected():
    """还不会画的形状（比如圆柱）要报错，不能悄悄漏掉。"""
    with pytest.raises(ValueError, match="还不会画这种形状"):
        _outline(mujoco.mjtGeom.mjGEOM_CYLINDER, np.ones(3), np.zeros(3), np.eye(3), np.eye(3)[:2])


def test_stadium_points_go_around_once():
    """胶囊的轮廓是绕一圈的：围出来的面积 = 长方形 + 一个圆（多边形比圆略小）。"""
    outline = _stadium(np.array([0.0, 0.0]), np.array([2.0, 0.0]), 0.5)
    x, y = outline[:, 0], outline[:, 1]
    area = 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
    assert area == pytest.approx(2.0 * 1.0 + math.pi * 0.25, rel=0.02)
