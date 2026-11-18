"""Nova 自己的传感器（基线的身体没有这些）：踝和腕的六轴力、全身的接触、指尖的力。站着时读到的对得上。"""

import math

import mujoco
import numpy as np
import pytest

from nova_body.bench import FLOOR
from nova_body.body import Side
from nova_body.mass_closure import GRAVITY_M_S2
from nova_body.model import (
    CONTACT_SUFFIX,
    FORCE_SUFFIX,
    MOMENT_SUFFIX,
    ankle_ft_site,
    tip_force_sensor,
    wrist_ft_site,
)
from nova_body.skeleton import LINKS, sides_of
from nova_body.standing import FootLoad, foot_load, pressure_center_from_ankle, read_sensor, standing_data

X, Y, Z = 0, 1, 2
SETTLE_STEPS = 3000
CONTACT_FORCE_SIZE = 6


@pytest.fixture(scope="module")
def settled(nova) -> mujoco.MjData:
    """Nova 站了 3 秒、已经静下来的状态。"""
    data = standing_data(nova.model)
    for _ in range(SETTLE_STEPS):
        mujoco.mj_step(nova.model, data)
    return data


def test_ankle_sensors_carry_the_body_above_the_feet(nova, settled):
    """踝部的力传感器：两只脚各压着一半的"体重减去脚"。"""
    model = nova.model
    foot_kg = float(model.body_subtreemass[model.body("left_foot").id])
    expected = (nova.budget.total_kg - 2 * foot_kg) * GRAVITY_M_S2 / 2
    for side in Side:
        force = read_sensor(model, settled, ankle_ft_site(side) + FORCE_SUFFIX)
        assert -force[Z] == pytest.approx(expected, rel=1e-3)


def test_pressure_center_from_ankle_sensor_matches_the_contacts(nova, settled):
    """用踝部力传感器算出来的压力中心，和直接从脚底的接触点算的：扣掉脚自己的重量，差不到 0.05 mm；
    不扣，差半毫米多（脚的重量也压在地上，却不经过传感器）。"""
    model = nova.model
    floor = model.geom(FLOOR).id
    for side in Side:
        sole = model.geom(f"{side.value}_foot.sole").id
        total, weighted = 0.0, np.zeros(3)
        force = np.zeros(CONTACT_FORCE_SIZE)
        for index in range(settled.ncon):
            contact = settled.contact[index]
            if {int(contact.geom[0]), int(contact.geom[1])} == {floor, sole}:
                mujoco.mj_contactForce(model, settled, index, force)
                total += force[0]
                weighted += force[0] * contact.pos
        truth = weighted / total - settled.site_xpos[model.site(ankle_ft_site(side)).id]
        reading = (
            read_sensor(model, settled, ankle_ft_site(side) + FORCE_SUFFIX),
            read_sensor(model, settled, ankle_ft_site(side) + MOMENT_SUFFIX),
        )
        load = foot_load(model, settled, ankle_ft_site(side), f"{side.value}_foot")
        forward, left = pressure_center_from_ankle(*reading, nova.dimensions.ankle_height, load)
        assert forward == pytest.approx(truth[X], abs=0.00005)
        assert left == pytest.approx(truth[Y], abs=0.00005)
        plain, _ = pressure_center_from_ankle(*reading, nova.dimensions.ankle_height)
        assert 0.0003 < abs(plain - truth[X]) < 0.002


def test_a_foot_with_nothing_above_presses_under_its_own_center():
    """上面什么也没压（传感器读 0），只有脚自己站在地上：压力中心就在脚的重心正下面；
    脚往上加速时（加速度计读得比 9.81 大）地面托得更多，压力中心还在那里。"""
    for upward in (9.81, 15.0):
        foot = FootLoad(
            mass_kg=0.9, center_m=np.array([0.04, 0.01, -0.03]), acceleration_m_s2=np.array([0.0, 0.0, upward])
        )
        forward, left = pressure_center_from_ankle(np.zeros(3), np.zeros(3), 0.066, foot)
        assert (forward, left) == pytest.approx((0.04, 0.01))


def test_pressure_center_needs_a_loaded_foot():
    """脚没有踩在地上（没有往下压的力）时，没有压力中心：报错。"""
    with pytest.raises(ValueError, match="没有踩在地上"):
        pressure_center_from_ankle(np.array([0.0, 0.0, 5.0]), np.zeros(3), 0.066)
    with pytest.raises(ValueError, match="没有踩在地上"):
        pressure_center_from_ankle(np.zeros(3), np.zeros(3), 0.066)


def test_pressure_center_formula():
    """压 100 N、力矩 5 N·m：压力中心在踝前面 5 cm；有水平力时按踝的高度修正。"""
    forward, left = pressure_center_from_ankle(np.array([0.0, 0.0, -100.0]), np.array([0.0, 5.0, 0.0]), 0.066)
    assert (forward, left) == pytest.approx((0.05, 0.0))
    forward, left = pressure_center_from_ankle(np.array([10.0, -10.0, -100.0]), np.array([2.0, 5.0, 0.0]), 0.1)
    assert (forward, left) == pytest.approx((0.06, -0.03))


def test_wrist_sensors_carry_the_hands(nova, settled):
    """手垂着时，腕部的力传感器量到的就是手的重量。"""
    model = nova.model
    hand_kg = float(model.body_subtreemass[model.body("left_hand").id])
    for side in Side:
        force = read_sensor(model, settled, wrist_ft_site(side) + FORCE_SUFFIX)
        assert np.linalg.norm(force) == pytest.approx(hand_kg * GRAVITY_M_S2, rel=1e-3)


def test_only_the_feet_feel_contact(nova, settled):
    """全身的接触力：两只脚各被地面往上托着一半体重，别的地方和指尖都是 0。"""
    model = nova.model
    half_weight = nova.budget.total_kg * GRAVITY_M_S2 / 2
    for part in LINKS:
        for side in sides_of(part):
            name = part.key if side is None else f"{side.value}_{part.key}"
            force = read_sensor(model, settled, name + CONTACT_SUFFIX)
            if part.key == "foot":
                assert force[Z] == pytest.approx(half_weight, rel=1e-3), name
            else:
                assert force == pytest.approx(np.zeros(3)), name
    for side in Side:
        assert read_sensor(model, settled, tip_force_sensor(side, "index")) == pytest.approx(np.zeros(3))


def test_fingertip_sensor_feels_a_touch(nova):
    """把腿收起来、身体放低，让两只手的中指指尖先碰到地面：指尖的力传感器量到往上的力；别的地方都没碰到地面
    （腿收得这么高，大腿顶着胸：身体各段之间也碰撞，胸的接触传感器量到的是大腿，不是地面）。"""
    model = nova.model
    data = mujoco.MjData(model)
    tucked = {"hip_pitch": 130.0, "knee": 150.0, "ankle_pitch": 20.0}
    for side in Side:
        for key, degrees in tucked.items():
            data.qpos[model.joint(f"{side.value}_{key}").qposadr[0]] = math.radians(degrees)
    mujoco.mj_forward(model, data)
    tip_height = data.site_xpos[model.site("left_middle_tip").id][Z]
    # 指尖压进地面 2 mm。
    data.qpos[Z] -= tip_height + 0.002
    mujoco.mj_forward(model, data)
    for side in Side:
        touch = read_sensor(model, data, tip_force_sensor(side, "middle"))
        assert touch[Z] > 0, side
        assert read_sensor(model, data, f"{side.value}_hand" + CONTACT_SUFFIX) == pytest.approx(touch)
        assert read_sensor(model, data, tip_force_sensor(side, "thumb")) == pytest.approx(np.zeros(3))
        assert read_sensor(model, data, f"{side.value}_foot" + CONTACT_SUFFIX) == pytest.approx(np.zeros(3))
    floor = model.geom(FLOOR).id
    on_floor = {
        model.body(model.geom_bodyid[int(contact.geom[1] if contact.geom[0] == floor else contact.geom[0])]).name
        for contact in data.contact[: data.ncon]
        if floor in (int(contact.geom[0]), int(contact.geom[1]))
    }
    assert on_floor == {f"{side.value}_middle_distal" for side in Side}
