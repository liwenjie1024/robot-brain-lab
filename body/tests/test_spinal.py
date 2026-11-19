"""脊髓层合起来（反射 → 硬限制和换算）的测试（真的跑物理）：刹车的阻尼按驱动器的电机常数算；手臂的皮肤只管手臂的关节；
被碰到的手臂变软；驱动器热了先降力；推倒时在着地以前就发现、全身变软；0 类停止断力、身体软下去；2 类停止照旧站着。"""

import copy
import math

import mujoco
import nova_rt
import numpy as np
import pytest

from nova_body import actuation
from nova_body.bench import STAND_KEY
from nova_body.body import Region
from nova_body.estimation import BodyFeel, setup_for_body
from nova_body.sensing import Readings
from nova_body.spinal import (
    SkinMap,
    SpinalLayer,
    actuator_temperatures,
    brake_damping,
    reflexes_for,
    tilt_rad,
)
from nova_body.spine import spine_for, stand_command
from nova_body.standing import drive_layer, tilt_deg

TOUCH_N = 20.0


class Standing:
    """Nova 照站姿站着：脊髓层（反射 + 硬限制）每 1 毫秒一步，状态估计给歪斜。"""

    def __init__(self, nova):
        self.body = nova.body
        self.model = copy.copy(self.body.model)
        self.data = mujoco.MjData(self.model)
        mujoco.mj_resetDataKeyframe(
            self.model, self.data, mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_KEY, STAND_KEY)
        )
        mujoco.mj_forward(self.model, self.data)
        drives = [actuator.drive for actuator in self.body.actuators]
        self.drives = drive_layer(self.body, self.model)
        self.spine = spine_for(self.model, drives)
        self.spinal = SpinalLayer(self.spine, reflexes_for(self.model, self.spine, drives))
        self.feel = BodyFeel(self.model, setup_for_body(self.body, self.model), self.spine, self.data)
        self.command = stand_command(self.body, self.model, self.spine)
        self.root = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, self.body.anatomy.root)
        self.timestep = float(self.model.opt.timestep)
        self.no_contacts = [False] * self.spine.joint_count

    def step(self, *, stop: int = nova_rt.STOP_NONE, contacts=None, push_n: float = 0.0):
        self.data.xfrc_applied[self.root, 0] = push_n
        self.feel.step(self.data, self.timestep)
        result = self.spinal.step(
            self.data,
            self.command,
            tilt=tilt_rad(self.feel.estimator.rotation),
            temperatures=actuator_temperatures(self.drives, self.model.nu),
            contacts=contacts or self.no_contacts,
            stop=stop,
            dt=self.timestep,
        )
        self.drives.command_impedance(result.impedance)
        actuation.step(self.model, self.data, self.drives)
        self.feel.sample(self.data)
        return result

    @property
    def pelvis_height(self) -> float:
        return float(self.data.xpos[self.root][2])


def touches_with(body, label: str, force_n: float) -> Readings:
    touches = tuple(np.zeros(3) for _ in body.touch_sensors)
    index = [sensor.label for sensor in body.touch_sensors].index(label)
    touches = tuple(np.array([0.0, 0.0, force_n]) if i == index else t for i, t in enumerate(touches))
    return Readings(imus=(), forces=(), touches=touches)


def actuator_of(body, joint: str) -> int:
    return next(index for index, actuator in enumerate(body.actuators) if actuator.joints == ((joint, 1.0),))


def test_brake_damping_is_the_motor_constant_squared(nova):
    """断电、绕组短接时的阻尼 = Km²：膝的就是它的驱动器的；并联的踝前后是两个驱动器的加起来。"""
    body = nova.body
    drives = [actuator.drive for actuator in body.actuators]
    damping = brake_damping(body.model, drives)
    names = [joint.name for joint in body.joints]
    knee = body.actuators[actuator_of(body, "left_knee")].drive
    assert damping[names.index("left_knee")] == pytest.approx(knee.km_nm_per_sqrt_w**2)
    pair = [actuator.drive for actuator in body.actuators if ("left_ankle_pitch", 1.0) in actuator.joints]
    assert damping[names.index("left_ankle_pitch")] == pytest.approx(sum(drive.km_nm_per_sqrt_w**2 for drive in pair))
    assert brake_damping(body.model, None) == [0.0] * len(names)


def test_arm_skin_covers_only_arm_joints(nova):
    """手臂的皮肤只管手臂的关节；左前臂被碰到：左肩、左肘算被碰到，右手臂、腿、腰都不算。"""
    body = nova.body
    spine = spine_for(body.model)
    skin = SkinMap(body, body.model, spine)
    names = spine.joint_names
    arm = {joint.name for joint in body.joints if joint.region == Region.ARM}
    assert {names[joint] for joint in skin.covered_joints} <= arm
    contacts = skin.contacts(touches_with(body, "左 前臂", TOUCH_N))
    touched = {names[joint] for joint, contact in enumerate(contacts) if contact}
    assert {"left_shoulder_pitch", "left_elbow"} <= touched
    assert all(name.startswith("left_") for name in touched)


def test_a_light_brush_is_not_a_collision(nova):
    """皮肤上 2 N（没过 5 N）不算被碰到；脚踩地的力本来就有，也不算。"""
    body = nova.body
    spine = spine_for(body.model)
    skin = SkinMap(body, body.model, spine)
    assert not any(skin.contacts(touches_with(body, "左 前臂", 2.0)))
    assert not any(skin.contacts(touches_with(body, "左 脚", 400.0)))


def test_a_touched_arm_goes_soft(nova):
    """左前臂被碰到：带着左肘的驱动器的刚度变成 20%，标"碰撞"；右肘照旧。"""
    standing = Standing(nova)
    body = standing.body
    skin = SkinMap(body, standing.model, standing.spine)
    calm = standing.step()
    touched = standing.step(contacts=skin.contacts(touches_with(body, "左 前臂", TOUCH_N)))
    left, right = actuator_of(body, "left_elbow"), actuator_of(body, "right_elbow")
    assert touched.impedance.stiffness[left] == pytest.approx(0.2 * calm.impedance.stiffness[left])
    assert touched.impedance.stiffness[right] == pytest.approx(calm.impedance.stiffness[right])
    names = standing.spine.joint_names
    assert touched.reflexes[names.index("left_elbow")] & nova_rt.REFLEX_COLLISION


def test_a_hot_knee_drive_is_derated(nova):
    """左膝的驱动器绕组到了 100 °C：它能出的力先降到 75%（驱动器自己 100 °C 才开始降），标"保护"。"""
    standing = Standing(nova)
    knee = actuator_of(standing.body, "left_knee")
    modeled = list(standing.drives.modeled)
    standing.drives.winding_c[modeled.index(knee)] = 100.0
    result = standing.step()
    names = standing.spine.joint_names
    assert result.reflexes[names.index("left_knee")] & nova_rt.REFLEX_PROTECT
    assert not result.reflexes[names.index("right_knee")] & nova_rt.REFLEX_PROTECT


def test_a_fall_is_caught_before_the_ground(nova):
    """被推得救不回来（体重的 40%，0.3 秒）：真的歪到 50° 以前就发现在倒，之后全身的刚度降到 30%。"""
    standing = Standing(nova)
    weight = mujoco.mj_getTotalmass(standing.model) * 9.81
    calm = standing.step()
    caught_at_deg = None
    for step in range(3000):
        push = 0.40 * weight if 200 <= step < 500 else 0.0
        result = standing.step(push_n=push)
        if result.mode == nova_rt.MODE_FALLING:
            caught_at_deg = tilt_deg(standing.data, standing.root)
            break
    assert caught_at_deg is not None
    assert caught_at_deg < 50.0
    after = standing.step()
    assert after.mode == nova_rt.MODE_FALLING
    assert np.all(after.impedance.stiffness <= 0.3 * calm.impedance.stiffness + 1e-9)


def test_category_zero_cuts_power_and_the_body_sinks(nova):
    """0 类停止：驱动器不出力、不顶着（刚度 0，只剩刹车的阻尼）；身体软下去，骨盆 1 秒里降了 5 cm 以上。"""
    standing = Standing(nova)
    for _ in range(100):
        standing.step()
    start = standing.pelvis_height
    result = standing.step(stop=nova_rt.STOP_CATEGORY_0)
    assert result.mode == nova_rt.MODE_POWER_OFF
    assert np.all(result.impedance.stiffness == 0.0)
    assert np.all(result.impedance.damping >= 0.0)
    for _ in range(1000):
        standing.step()
    assert standing.pelvis_height < start - 0.05


def test_category_two_keeps_standing(nova):
    """2 类停止：标出"在停止"（交给小脑层停下来站住），命令照旧，身体照样站着（骨盆 1 秒里动不到 1 cm）。"""
    standing = Standing(nova)
    start = standing.pelvis_height
    result = standing.step(stop=nova_rt.STOP_CATEGORY_2)
    assert result.mode == nova_rt.MODE_STOPPING
    for _ in range(1000):
        result = standing.step()
    assert result.mode == nova_rt.MODE_STOPPING
    assert abs(standing.pelvis_height - start) < 0.01
    assert math.isfinite(standing.pelvis_height)
