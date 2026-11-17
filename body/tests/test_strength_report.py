import math

import pytest

from nova_body.strength_report import _dof_label, _kind, _mm, _percent, _table


def test_table_has_a_header_a_rule_and_one_line_per_row():
    """表格：一行表头、一行分隔、每行一行。"""
    assert _table(["a", "b"], [["1", "2"], ["3", "4"]]) == ["| a | b |", "|---|---|", "| 1 | 2 |", "| 3 | 4 |"]


@pytest.mark.parametrize(
    ("label", "kind"),
    [("左 膝", "膝"), ("右 踝 前后", "踝 前后"), ("腰 转", "腰 转")],
    ids=["左", "右", "中间的"],
)
def test_kind_drops_the_side(label, kind):
    """去掉"左 ""右 "，剩下关节的种类：两个身体一样，好对着比。"""
    assert _kind(label) == kind


@pytest.mark.parametrize(
    ("value", "text"),
    [(0.0123, "12 mm"), (-0.0217, "-22 mm"), (math.nan, "-")],
    ids=["正的", "负的（跑出脚底）", "没有（只有点撑着）"],
)
def test_millimetres(value, text):
    """米换成毫米，没有数的写"-"。"""
    assert _mm(value) == text


def test_percent():
    """比例写成百分数。"""
    assert _percent(0.666) == "67%"


@pytest.mark.parametrize(
    ("group", "index", "name"),
    [("ankle", 0, "踝 前后"), ("ankle", 1, "踝 侧"), ("knee", 0, "膝"), ("no_such_group", 0, "-")],
    ids=["踝的第一个", "踝的第二个", "膝", "没有这一组"],
)
def test_dof_label_comes_from_the_skeleton(group, index, name):
    """一组关节里第几个自由度叫什么，按骨架里的名字。"""
    assert _dof_label(group, index) == name
