"""画图的测试：画出来的是一份合格的 SVG，每一块都画了，两次画的一样。"""

import math
from xml.etree import ElementTree

import mujoco
import numpy as np
import pytest

from nova_body.drawing import VIEWS, _convex_hull, _outline, _stadium, draw_body
from nova_body.model import PART_STYLES

SVG = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module")
def picture(nova) -> str:
    """站姿的图，只画一次。"""
    return draw_body(nova)


def test_picture_is_well_formed_svg(picture):
    """画出来的是能解析的 SVG，有宽和高。"""
    root = ElementTree.fromstring(picture)
    assert root.tag == SVG + "svg"
    assert float(root.attrib["width"]) > 0
    assert float(root.attrib["height"]) > 0


def test_every_part_is_drawn_in_both_views(picture, nova):
    """每一块（除了地面）在正面和侧面各画一次。"""
    root = ElementTree.fromstring(picture)
    polygons = root.findall(SVG + "polygon")
    assert len(polygons) == len(VIEWS) * (nova.model.ngeom - 1)


def test_every_shape_is_inside_the_picture(picture):
    """每个多边形的点都在图的范围里，没有画到外面去，也没有坏掉的数。"""
    root = ElementTree.fromstring(picture)
    width, height = float(root.attrib["width"]), float(root.attrib["height"])
    for polygon in root.findall(SVG + "polygon"):
        for pair in polygon.attrib["points"].split():
            x, y = (float(value) for value in pair.split(","))
            assert 0 <= x <= width
            assert 0 <= y <= height


def test_picture_has_titles_and_legend(picture):
    """图上有两个视图的名字、每种颜色的说明、重心的记号。"""
    texts = [element.text for element in ElementTree.fromstring(picture).iter(SVG + "text")]
    for view in VIEWS:
        assert view.title in texts
    for style in PART_STYLES.values():
        assert style.name in texts
    assert "重心" in texts
    assert "1.70 m" in texts


def test_drawing_twice_gives_the_same_picture(picture, nova):
    """同一个姿势画两次，一个字都不差。"""
    assert draw_body(nova) == picture


def test_another_pose_gives_another_picture(picture, nova):
    """换一个姿势（零位：站直），画出来的不一样。"""
    assert draw_body(nova, nova.model.qpos0) != picture


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
