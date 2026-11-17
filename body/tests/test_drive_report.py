"""驱动器的报告里几个小帮手的测试：驱动器的名字、每个驱动板的电流、不液冷的那句话。
（整份报告要做一遍全部的动作，太慢；提交前的检查会生成一遍，和存着的比。）"""

from dataclasses import replace

import pytest

from nova_body.actuator_mass import best_today_model
from nova_body.design import JOINT_GROUPS
from nova_body.drive_report import BUS_VOLTAGES_V, _arms_enclosed_sentence, _currents, _drive_label, _table
from nova_body.drives import Cooling, size_drive
from nova_body.heat import STRESS_HOLDS, HeldMotor, HoldHeat, Motor


def group(key: str):
    return next(group for group in JOINT_GROUPS if group.key == key)


@pytest.mark.parametrize(
    ("key", "position", "label"),
    [
        ("knee", 0, "膝"),
        ("ankle", 1, "踝 前后、侧（并联乙）"),
        ("neck_upper", 1, "上颈 转、点头（第 2 个）"),
    ],
    ids=["一个驱动器", "并联的第二个", "一组里有两个"],
)
def test_drive_labels(key, position, label):
    """驱动器的名字：一组只有一个就叫组名；并联的叫甲、乙；别的按第几个。"""
    assert _drive_label(group(key), position) == label


def test_higher_voltage_and_two_boards_mean_less_current():
    """电压翻倍，电流减半；双绕组两个驱动板，每个出一半。"""
    drive = size_drive(360.0, 0.0, 12.4, Cooling.LIQUID, best_today_model())
    one = _currents(drive, 1)
    two = _currents(drive, 2)
    assert BUS_VOLTAGES_V[0] * 2 == BUS_VOLTAGES_V[2]
    assert one[2] == pytest.approx(one[0] / 2)
    assert two == pytest.approx(tuple(current / 2 for current in one))


def test_enclosed_arms_sentence_lists_the_waits_or_says_none():
    """不液冷的对照：列出左侧会降额的、多久；都不会就说不会。"""
    drive = size_drive(146.0, 0.0, None, Cooling.ENCLOSED, best_today_model())
    shoulder = Motor("left_shoulder_pitch", "左 肩 前后", "shoulder_pitch", ((0, 1.0),), drive)
    right = replace(shoulder, name="right_shoulder_pitch", label="右 肩 前后")
    late = HoldHeat(
        STRESS_HOLDS[0],
        (HeldMotor(shoulder, 45.0, 130.0, 192.0, 30.0), HeldMotor(right, 45.0, 130.0, 190.0, 30.0)),
    )
    assert _arms_enclosed_sentence(late) == f"不液冷的话，{STRESS_HOLDS[0].name}，肩 前后 3.2 分钟就开始降额。"
    never = HoldHeat(STRESS_HOLDS[0], (HeldMotor(shoulder, 45.0, 60.0, None, 5.0),))
    assert _arms_enclosed_sentence(never) == "不液冷也不会降额。"


def test_table_has_a_header_a_rule_and_one_line_per_row():
    """表格：一行表头、一行分隔、每行一行。"""
    assert _table(["a", "b"], [["1", "2"]]) == ["| a | b |", "|---|---|", "| 1 | 2 |"]
