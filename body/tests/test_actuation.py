"""仿真里驱动器的那一层的测试（真的跑物理）：命令晚 1 毫秒到；转得快了推不动；一直出大力，绕组热了就降额、关节就顶不住；
重新开始就凉了；没有驱动器模型的身体只有延迟。"""

import copy

import mujoco
import numpy as np
import pytest

from nova_body.actuation import COMMAND_DELAY_STEPS, HEAT_EVERY_STEPS, DriveLayer, ImpedanceCommand, step
from nova_body.actuator_mass import best_today_model
from nova_body.drives import COOLANT_C, DERATE_FROM_C, Cooling, DriveArrays, Temperatures, size_drive
from nova_body.standing import drive_layer, standing_data

TIMESTEP_S = 0.001


def one_joint(inertia_kg_m2: float = 0.05):
    """一个关节、一个位置驱动器的小模型（没有重力、没有摩擦），目标不限范围。"""
    spec = mujoco.MjSpec()
    spec.compiler.degree = False
    spec.option.timestep = TIMESTEP_S
    spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    spec.option.gravity = [0.0, 0.0, 0.0]
    link = spec.worldbody.add_body(name="link")
    link.add_joint(name="joint", type=mujoco.mjtJoint.mjJNT_HINGE, axis=[0, 0, 1])
    link.add_geom(type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.05], mass=1.0)
    link.mass = 1.0
    link.inertia = [inertia_kg_m2] * 3
    link.explicitinertial = True
    actuator = spec.add_actuator(name="motor", trntype=mujoco.mjtTrn.mjTRN_JOINT, target="joint")
    actuator.set_to_position(kp=1000.0, kv=1.0)
    actuator.forcelimited = mujoco.mjtLimited.mjLIMITED_TRUE
    actuator.forcerange = [-100.0, 100.0]
    return spec.compile()


def drive(peak: float = 100.0, knee: float = 8.0):
    return size_drive(peak, 0.0, knee, Cooling.LIQUID, best_today_model())


def run(model, data, layer, seconds: float, applied_nm: float = 0.0) -> None:
    for _ in range(round(seconds / TIMESTEP_S)):
        data.qfrc_applied[0] = applied_nm
        step(model, data, layer)


def test_a_command_arrives_one_step_later():
    """发的命令晚 1 步（1 毫秒）才到驱动器；只发一次也会到。"""
    model = one_joint()
    data = mujoco.MjData(model)
    layer = DriveLayer(model, [drive()])
    layer.command([0.5])
    for _ in range(COMMAND_DELAY_STEPS):
        layer.before_step(data)
        assert data.ctrl[0] == 0.0
        mujoco.mj_step(model, data)
        layer.after_step(data, TIMESTEP_S)
    layer.before_step(data)
    assert data.ctrl[0] == 0.5


def test_later_commands_replace_earlier_ones_in_order():
    """连着发几次：按发的顺序一步一步到，最后停在最后那一次。"""
    model = one_joint()
    data = mujoco.MjData(model)
    layer = DriveLayer(model, [drive()])
    seen = []
    for target in (0.1, 0.2, 0.3):
        layer.command([target])
        step(model, data, layer)
        seen.append(float(data.ctrl[0]))
    run(model, data, layer, 0.005)
    assert seen == [0.0, 0.1, 0.2]
    assert data.ctrl[0] == 0.3


def test_spinning_fast_runs_out_of_push():
    """目标在很远的地方：关节越转越快，到了"峰值出到的转速"以后推的力变小，最快到空载转速就推不动了。"""
    model = one_joint()
    data = mujoco.MjData(model)
    spec = drive(peak=10.0, knee=5.0)
    layer = DriveLayer(model, [spec])
    data.ctrl[0] = 1000.0
    run(model, data, layer, 3.0)
    speed = float(data.qvel[0])
    assert spec.knee_speed_rad_s < speed <= spec.no_load_speed_rad_s * 1.001
    assert data.actuator_force[0] <= spec.speed_limit_nm(speed) + 1e-6
    assert data.actuator_force[0] < 0.5 * spec.peak_torque_nm


def test_braking_is_not_limited_by_the_speed():
    """转得很快时往反方向刹：不受电压限，还能出峰值（受温度限）。"""
    model = one_joint()
    data = mujoco.MjData(model)
    spec = drive(peak=10.0, knee=5.0)
    layer = DriveLayer(model, [spec])
    data.qvel[0] = spec.no_load_speed_rad_s * 1.5
    data.ctrl[0] = -1000.0
    step(model, data, layer)
    assert data.actuator_force[0] == pytest.approx(-spec.peak_torque_nm)


def test_holding_more_than_the_continuous_torque_heats_up_and_gives_way():
    """一直顶着比"能一直出的"大的力：一开始顶得住；绕组过了 100 °C 就降额，降到顶不住，关节就被推开了。"""
    model = one_joint()
    data = mujoco.MjData(model)
    spec = drive(peak=100.0)
    layer = DriveLayer(model, [spec])
    load = -1.6 * spec.continuous_torque_nm
    run(model, data, layer, 2.0, applied_nm=load)
    assert abs(data.qpos[0]) < 0.1
    assert layer.winding_c[0] > COOLANT_C
    seconds = 2.0
    while layer.winding_c[0] < DERATE_FROM_C + 15 and seconds < 300:
        run(model, data, layer, 1.0, applied_nm=load)
        seconds += 1.0
    assert seconds < 300
    run(model, data, layer, 5.0, applied_nm=load)
    assert model.actuator_forcerange[0, 1] < abs(load)
    assert data.qpos[0] < -1.0


def test_a_light_hold_never_derates():
    """一直顶着比"能一直出的"小的力：怎么都不会热到降额，一直顶得住。"""
    model = one_joint()
    data = mujoco.MjData(model)
    spec = drive(peak=100.0)
    layer = DriveLayer(model, [spec])
    run(model, data, layer, 60.0, applied_nm=-0.5 * spec.continuous_torque_nm)
    assert layer.winding_c[0] < DERATE_FROM_C
    assert abs(data.qpos[0]) < 0.1


def test_layer_heat_matches_the_drive_heat():
    """这一层每 10 步算一次热，和驱动器自己一下子算的差不多（力不变的时候一样）。"""
    model = one_joint()
    data = mujoco.MjData(model)
    spec = drive(peak=100.0)
    layer = DriveLayer(model, [spec])
    run(model, data, layer, 5.0, applied_nm=-50.0)
    torque = abs(float(data.actuator_force[0]))
    alone = spec.heat(Temperatures(COOLANT_C, COOLANT_C), torque, 5.0)
    assert layer.winding_c[0] == pytest.approx(alone.winding_c, abs=0.5)
    assert 0.1 * spec.thermal.winding_time_constant_s > HEAT_EVERY_STEPS * TIMESTEP_S


def test_reset_cools_down_and_restores_the_limits():
    """重新开始：驱动器都是冷的，力的上下限回到原来的，路上的命令不要了。"""
    model = one_joint()
    data = mujoco.MjData(model)
    layer = DriveLayer(model, [drive(peak=100.0)])
    run(model, data, layer, 5.0, applied_nm=-80.0)
    layer.command([1.0])
    layer.reset()
    assert layer.winding_c[0] == COOLANT_C
    assert model.actuator_forcerange[0] == pytest.approx([-100.0, 100.0])
    data.ctrl[0] = 0.0
    run(model, data, layer, 0.005)
    assert data.ctrl[0] == 0.0


def test_arrays_follow_the_same_rules_as_one_drive():
    """一次算全部的（数组），和一个驱动器自己算的一样：不同的转速、温度都对得上。"""
    spec = drive(peak=50.0, knee=5.0)
    arrays = DriveArrays.of([spec])
    for speed in (-20.0, -6.0, -1.0, 0.0, 1.0, 5.0, 6.0, 6.6, 20.0):
        for winding in (COOLANT_C, 99.0, 110.0, 120.0, 125.0, 140.0):
            lower, upper = arrays.torque_limits_nm(np.array([speed]), np.array([winding]))
            expected = spec.torque_limits_nm(speed, Temperatures(winding, winding))
            assert (lower[0], upper[0]) == pytest.approx(expected), (speed, winding)


def test_refuses_mismatched_counts():
    """驱动器的样子和模型里的驱动器个数对不上、命令的个数对不上：报错。"""
    model = one_joint()
    with pytest.raises(ValueError, match="模型里有 1 个驱动器"):
        DriveLayer(model, [drive(), drive()])
    layer = DriveLayer(model, [drive()])
    with pytest.raises(ValueError, match="命令要给 1 个驱动器"):
        layer.command([0.1, 0.2])


def test_baseline_only_has_the_delay(g1):
    """基线没有驱动器的模型：力的上下限不改，也不发热；命令照样晚 1 毫秒到。"""
    own = copy.copy(g1.model)
    data = standing_data(own)
    layer = drive_layer(g1, own)
    before = own.actuator_forcerange.copy()
    run(own, data, layer, 0.05)
    assert len(layer.modeled) == 0
    assert own.actuator_forcerange == pytest.approx(before)


def test_nova_drives_have_their_full_strength_while_standing(nova):
    """Nova 站着：不转、不热，每个有模型的驱动器力的上下限就是它的峰值。"""
    own = copy.copy(nova.model)
    data = standing_data(own)
    layer = drive_layer(nova.body, own)
    run(own, data, layer, 0.05)
    peaks = np.array([item.peak_torque_nm for item in nova.body.actuators])[layer.modeled]
    assert own.actuator_forcerange[layer.modeled, 1] == pytest.approx(peaks, rel=1e-3)
    assert own.actuator_forcerange[layer.modeled, 0] == pytest.approx(-peaks, rel=1e-3)
    assert len(layer.modeled) == 31


def impedance(position: float, stiffness: float, damping: float, force: float) -> ImpedanceCommand:
    return ImpedanceCommand(np.array([position]), np.array([stiffness]), np.array([damping]), np.array([force]))


def test_a_full_command_arrives_one_step_later_all_together():
    """完整的命令（目标、刚度、阻尼、前馈力）四样一起晚 1 步到；到了以后驱动器照它出力（没到力的上限 100）。"""
    model = one_joint()
    data = mujoco.MjData(model)
    layer = DriveLayer(model, [None])
    layer.command_impedance(impedance(0.1, 200.0, 1.0, 3.0))
    layer.before_step(data)
    assert data.ctrl[0] == 0.0
    assert model.actuator_gainprm[0, 0] == 1000.0
    mujoco.mj_step(model, data)
    layer.after_step(data, TIMESTEP_S)
    layer.before_step(data)
    mujoco.mj_forward(model, data)
    expected = 200.0 * (0.1 - data.qpos[0]) - 1.0 * data.qvel[0] + 3.0
    assert data.actuator_force[0] == pytest.approx(expected, rel=1e-12)


def test_reset_puts_the_file_gains_back():
    """重新开始：驱动器的软硬、偏置回到模型文件里的。"""
    model = one_joint()
    data = mujoco.MjData(model)
    layer = DriveLayer(model, [None])
    layer.command_impedance(impedance(0.5, 200.0, 1.0, 3.0))
    for _ in range(2):
        layer.before_step(data)
        layer.after_step(data, TIMESTEP_S)
    assert model.actuator_gainprm[0, 0] == 200.0
    layer.reset()
    assert model.actuator_gainprm[0, 0] == 1000.0
    assert model.actuator_biasprm[0, 0] == 0.0
    assert model.actuator_biasprm[0, 2] == -1.0


def test_a_full_command_of_the_wrong_length_is_refused():
    """完整的命令长度不对就拒绝。"""
    layer = DriveLayer(one_joint(), [None])
    with pytest.raises(ValueError, match="要给 1 个驱动器"):
        layer.command_impedance(ImpedanceCommand(np.zeros(2), np.zeros(2), np.zeros(2), np.zeros(2)))


def test_a_full_command_needs_position_controlled_actuators():
    """只出力的驱动器（motor）接不了目标、刚度、阻尼、前馈力的命令。"""
    spec = mujoco.MjSpec()
    link = spec.worldbody.add_body(name="link")
    link.add_joint(name="joint", type=mujoco.mjtJoint.mjJNT_HINGE)
    link.add_geom(type=mujoco.mjtGeom.mjGEOM_SPHERE, size=[0.05, 0, 0], mass=1.0)
    spec.add_actuator(name="motor", trntype=mujoco.mjtTrn.mjTRN_JOINT, target="joint")
    layer = DriveLayer(spec.compile(), [None])
    with pytest.raises(ValueError, match="不是位置控制的"):
        layer.command_impedance(impedance(0.0, 1.0, 0.0, 0.0))
