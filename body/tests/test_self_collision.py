"""身体各段之间碰撞的测试：站姿里哪两段都没碰；大腿抬起来、腰往前弯，大腿就碰到胸；父子两段（大腿和小腿）不算；
腕那里本来就挨着的几段不算（不排除的话，站姿里它们就插在一起）。"""

import mujoco
import numpy as np
import pytest

from nova_body.body import Side
from nova_body.model import THUMB_BASE
from nova_body.standing import standing_data
from nova_body.strength import self_contacts


def pose(nova, **angles: float) -> np.ndarray:
    """站姿上把几个关节转到给的角度（弧度）。"""
    qpos = np.array(nova.body.stand.qpos)
    for name, value in angles.items():
        qpos[nova.model.joint(name).qposadr[0]] = value
    return qpos


def limit(nova, name: str, end: int) -> float:
    return float(nova.model.joint(name).range[end])


def test_no_two_parts_touch_while_standing(nova):
    """站姿里身体的哪两段都没碰在一起（只有脚踩着地面）。"""
    assert self_contacts(nova.body, [np.array(nova.body.stand.qpos)]) == {}


def test_a_raised_thigh_hits_the_bent_trunk(nova):
    """大腿抬到头、腰往前弯到头：大腿插进胸里，记下来，插得很深。"""
    raised = pose(nova, left_hip_pitch=limit(nova, "left_hip_pitch", 1), lumbar_pitch=limit(nova, "lumbar_pitch", 1))
    contacts = self_contacts(nova.body, [raised])
    assert contacts[("chest", "left_thigh")] > 0.05


def test_parent_and_child_never_collide(nova):
    """膝弯到头，小腿贴着大腿折回来：父子两段不算碰撞。"""
    folded = pose(nova, left_knee=limit(nova, "left_knee", 1))
    contacts = self_contacts(nova.body, [folded])
    assert ("left_shank", "left_thigh") not in contacts


@pytest.mark.parametrize("side", list(Side), ids=["左", "右"])
def test_wrist_neighbours_overlap_but_are_excluded(nova, side):
    """腕：前臂和手掌的尺骨那一半、拇指的掌骨，站姿里就插着几毫米（中间只隔着腕那一段），排除了，不算碰撞。"""
    model = nova.model
    data = standing_data(model)
    excluded = {
        (
            model.body(model.exclude_signature[index] >> 16).name,
            model.body(model.exclude_signature[index] & 0xFFFF).name,
        )
        for index in range(model.nexclude)
    }
    forearm = f"{side.value}_forearm"
    for neighbour in (f"{side.value}_hand_ulnar", f"{side.value}_{THUMB_BASE}"):
        assert (forearm, neighbour) in excluded or (neighbour, forearm) in excluded
        shells = [
            geom
            for geom in range(model.ngeom)
            if model.body(model.geom_bodyid[geom]).name in {forearm, neighbour} and model.geom_conaffinity[geom]
        ]
        first = [geom for geom in shells if model.body(model.geom_bodyid[geom]).name == forearm]
        second = [geom for geom in shells if model.body(model.geom_bodyid[geom]).name == neighbour]
        closest = min(mujoco.mj_geomDistance(model, data, one, two, 0.05, None) for one in first for two in second)
        assert closest < 0.0
    contacts = self_contacts(nova.body, [np.array(nova.body.stand.qpos)])
    assert not any(forearm in pair for pair in contacts)
