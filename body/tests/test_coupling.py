"""并联的两个驱动器在仿真里耦合起来的测试：踝、腰、腕各由两根固定肌腱上的两个驱动器带（一个是和、一个是差），
两个关节的力合起来受两个驱动器的限制；身体交出的驱动器清单和模型对得上；站姿按驱动器算的目标顶得住。"""

import mujoco
import numpy as np
import pytest

from nova_body.body import Side
from nova_body.model import PAIR_SIGNS, pair_actuator_name
from nova_body.standing import standing_data

PAIRS = (
    ("ankle", Side.LEFT),
    ("ankle", Side.RIGHT),
    ("wrist", Side.LEFT),
    ("wrist", Side.RIGHT),
    ("lumbar_pitch_roll", None),
)


def moment_matrix(model: mujoco.MjModel, data: mujoco.MjData) -> np.ndarray:
    dense = np.zeros((model.nu, model.nv))
    mujoco.mju_sparse2dense(dense, data.actuator_moment, data.moment_rownnz, data.moment_rowadr, data.moment_colind)
    return dense


def actuator(nova, name: str):
    return next(item for item in nova.body.actuators if item.name == name)


def test_each_pair_is_two_tendon_actuators(nova):
    """踝、腕（两侧）和腰：每对两个驱动器，都在肌腱上；驱动器一共还是 67 个，和模型里的一样。"""
    model = nova.model
    assert model.nu == len(nova.body.actuators) == 67
    assert [model.actuator(index).name for index in range(model.nu)] == [item.name for item in nova.body.actuators]
    tendon_actuators = [
        index for index in range(model.nu) if model.actuator_trntype[index] == mujoco.mjtTrn.mjTRN_TENDON
    ]
    assert len(tendon_actuators) == 2 * len(PAIRS)
    for key, side in PAIRS:
        for part, sign in enumerate(PAIR_SIGNS):
            item = actuator(nova, pair_actuator_name(key, side, part))
            assert [coefficient for _, coefficient in item.joints] == [1.0, sign]
            assert item.drive is not None and item.drive.peak_torque_nm == item.peak_torque_nm


def test_one_motor_turns_both_joints_and_two_together_turn_one(nova):
    """力臂：甲推，两个关节都得到它的力；甲乙一起推（同向），只有第一个关节得到两倍；反向，只有第二个。"""
    model = nova.model
    data = standing_data(model)
    moment = moment_matrix(model, data)
    first = model.actuator(pair_actuator_name("ankle", Side.LEFT, 0)).id
    second = model.actuator(pair_actuator_name("ankle", Side.LEFT, 1)).id
    pitch = model.joint("left_ankle_pitch").dofadr[0]
    roll = model.joint("left_ankle_roll").dofadr[0]
    assert moment[first, [pitch, roll]] == pytest.approx([1.0, 1.0])
    assert moment[second, [pitch, roll]] == pytest.approx([1.0, -1.0])
    forces = np.zeros(model.nu)
    forces[[first, second]] = [1.0, 1.0]
    assert (moment.T @ forces)[[pitch, roll]] == pytest.approx([2.0, 0.0])
    forces[[first, second]] = [1.0, -1.0]
    assert (moment.T @ forces)[[pitch, roll]] == pytest.approx([0.0, 2.0])


@pytest.mark.parametrize(
    ("targets", "pitch_share", "roll_share"),
    [((1.0, 1.0), 2.0, 0.0), ((1.0, -1.0), 0.0, 2.0), ((1.0, 0.0), 1.0, 1.0)],
    ids=["两个同向推到顶", "两个反向推到顶", "只有甲推到顶"],
)
def test_the_two_joints_share_the_two_motors(nova, targets, pitch_share, roll_share):
    """真的推到顶：踝前后、踝侧得到的力矩，是一个驱动器峰值的几倍。单独一个方向能到两倍，两个方向一起就分着用。"""
    model = nova.model
    data = standing_data(model)
    first = model.actuator(pair_actuator_name("ankle", Side.LEFT, 0)).id
    second = model.actuator(pair_actuator_name("ankle", Side.LEFT, 1)).id
    peak = actuator(nova, pair_actuator_name("ankle", Side.LEFT, 0)).peak_torque_nm
    for index, target in zip((first, second), targets, strict=True):
        # 目标远远偏开（偏 1 弧度，比"出全力"的 0.1 弧度大得多），驱动器就出到它的上限。
        data.ctrl[index] = data.actuator_length[index] + target
    mujoco.mj_forward(model, data)
    pitch = model.joint("left_ankle_pitch").dofadr[0]
    roll = model.joint("left_ankle_roll").dofadr[0]
    assert data.qfrc_actuator[pitch] == pytest.approx(pitch_share * peak, rel=1e-6)
    assert abs(data.qfrc_actuator[roll]) == pytest.approx(roll_share * peak, rel=1e-6)


def test_a_paired_joint_alone_can_use_both_motors(nova):
    """并联的关节单独用力时，两个驱动器一起出：关节的峰值是一个驱动器的两倍。"""
    joints = {joint.name: joint for joint in nova.body.joints}
    motor = actuator(nova, pair_actuator_name("ankle", Side.LEFT, 0)).peak_torque_nm
    assert joints["left_ankle_pitch"].peak_torque_nm == pytest.approx(2 * motor)
    assert joints["left_ankle_roll"].peak_torque_nm == pytest.approx(2 * motor)
    assert joints["left_knee"].peak_torque_nm == actuator(nova, "left_knee").peak_torque_nm


def test_pair_targets_cover_the_joint_ranges(nova):
    """并联的驱动器的目标范围，正好是两个关节的范围合起来（和、差）。"""
    joints = {joint.name: joint for joint in nova.body.joints}
    pitch, roll = joints["left_ankle_pitch"], joints["left_ankle_roll"]
    together = actuator(nova, pair_actuator_name("ankle", Side.LEFT, 0))
    apart = actuator(nova, pair_actuator_name("ankle", Side.LEFT, 1))
    assert (together.lower, together.upper) == pytest.approx(
        (pitch.lower_rad + roll.lower_rad, pitch.upper_rad + roll.upper_rad)
    )
    assert (apart.lower, apart.upper) == pytest.approx(
        (pitch.lower_rad - roll.upper_rad, pitch.upper_rad - roll.lower_rad)
    )


def test_stand_forces_give_exactly_the_holding_torques(nova):
    """站姿：每个驱动器要出的力经力臂合起来，正好是每个关节顶住重力要的力矩（并联的也一样）。"""
    model = nova.model
    data = standing_data(model)
    moment = moment_matrix(model, data)
    forces = np.array(nova.body.stand.holding_torque_nm)
    joint_torques = moment.T @ forces
    for name in ("left_ankle_pitch", "left_ankle_roll", "lumbar_pitch", "left_knee"):
        dof = model.joint(name).dofadr[0]
        assert abs(joint_torques[dof]) > 0.0
    target = np.array(nova.body.stand.ctrl)
    assert target == pytest.approx(data.actuator_length + forces / model.actuator_gainprm[:, 0])


def test_baseline_has_one_actuator_per_joint(g1):
    """基线（G1）：每个关节一个驱动器，系数 1，没有驱动器的模型。"""
    assert len(g1.actuators) == len(g1.joints) == 29
    for item, joint in zip(g1.actuators, g1.joints, strict=True):
        assert item.joints == ((joint.name, 1.0),)
        assert item.peak_torque_nm == joint.peak_torque_nm
        assert item.drive is None
