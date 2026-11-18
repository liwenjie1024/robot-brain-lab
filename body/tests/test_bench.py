"""测试台的测试：地面、步长、关节位置控制的软硬、关节的传感器，对每个身体（Nova 和基线）都一样。"""

import mujoco
import numpy as np
import pytest

from nova_body.bench import (
    CONTACT_SOLREF,
    DAMPING_TIME_S,
    FLOOR,
    FLOOR_PRIORITY,
    FULL_TORQUE_ERROR_RAD,
    POSITION_SUFFIX,
    STAND_KEY,
    TIMESTEP_S,
    TORQUE_SUFFIX,
    VELOCITY_SUFFIX,
    add_floor,
    add_joint_sensors,
    damping_for,
    stiffness_for,
    store_stand_pose,
    use_bench_settings,
)
from nova_body.body import StandPose
from nova_body.standing import read_sensor, standing_data

SETTLE_STEPS = 20


def small_arm() -> mujoco.MjSpec:
    """一根固定在世界上的小臂：两个关节，只有第一个有驱动器。"""
    spec = mujoco.MjSpec()
    spec.compiler.degree = False
    upper = spec.worldbody.add_body(name="upper", pos=[0.0, 0.0, 1.0])
    upper.add_joint(name="shoulder", type=mujoco.mjtJoint.mjJNT_HINGE, axis=[0.0, 1.0, 0.0])
    upper.add_geom(type=mujoco.mjtGeom.mjGEOM_CAPSULE, size=[0.03, 0.0, 0.0], fromto=[0, 0, 0, 0, 0, -0.3], mass=1.0)
    lower = upper.add_body(name="lower", pos=[0.0, 0.0, -0.3])
    lower.add_joint(name="elbow", type=mujoco.mjtJoint.mjJNT_HINGE, axis=[0.0, 1.0, 0.0])
    lower.add_geom(type=mujoco.mjtGeom.mjGEOM_CAPSULE, size=[0.02, 0.0, 0.0], fromto=[0, 0, 0, 0, 0, -0.3], mass=0.5)
    actuator = spec.add_actuator(name="shoulder", trntype=mujoco.mjtTrn.mjTRN_JOINT, target="shoulder")
    actuator.set_to_position(kp=stiffness_for(20.0), kv=damping_for(20.0))
    return spec


# 同一个仿真 ------------------------------------------------------------------------------------------


def test_every_body_runs_with_the_same_step_and_integrator(body):
    """每个身体都是每秒 1000 步，用把驱动器的阻尼算进去的积分方法。"""
    assert body.model.opt.timestep == TIMESTEP_S == 0.001
    assert body.model.opt.integrator == mujoco.mjtIntegrator.mjINT_IMPLICITFAST
    assert body.model.opt.gravity == pytest.approx([0.0, 0.0, -9.81])


def test_every_body_stands_on_the_same_floor(body):
    """地面是同一块平地：只让身体碰它，优先级比身体上任何一个形状都高。"""
    model = body.model
    floor = model.geom(FLOOR).id
    assert model.geom_type[floor] == mujoco.mjtGeom.mjGEOM_PLANE
    assert (model.geom_contype[floor], model.geom_conaffinity[floor]) == (0, 1)
    assert model.geom_solref[floor] == pytest.approx(CONTACT_SOLREF)
    others = [model.geom_priority[geom] for geom in range(model.ngeom) if geom != floor]
    assert model.geom_priority[floor] == FLOOR_PRIORITY > max(others)


def test_floor_decides_how_every_contact_with_it_behaves(body):
    """和地面的每个接触，摩擦和软硬都是地面的，不管这个身体的脚自己写的是什么。"""
    model = body.model
    data = standing_data(model)
    for _ in range(SETTLE_STEPS):
        mujoco.mj_step(model, data)
    floor = model.geom(FLOOR).id
    slide, spin, roll = model.geom_friction[floor]
    assert data.ncon > 0
    for index in range(data.ncon):
        contact = data.contact[index]
        assert floor in contact.geom
        # 接触里的摩擦是五个数：两个方向的滑动、转动、两个方向的滚动。
        assert contact.friction == pytest.approx([slide, slide, spin, roll, roll])
        assert contact.solref == pytest.approx(CONTACT_SOLREF)


def test_stand_pose_is_stored_under_the_same_name(body):
    """每个身体的站姿都存在模型里，名字都是 stand。"""
    key = body.model.key(STAND_KEY)
    assert tuple(key.qpos) == body.stand.qpos
    assert tuple(key.ctrl) == body.stand.ctrl


# 同一条关节控制的规则 --------------------------------------------------------------------------------


def test_stiffness_and_damping_rule():
    """峰值 100 N·m 的关节：偏 0.1 弧度出全力，所以刚度是 1000；阻尼 = 刚度 x 0.05 秒 = 50。"""
    assert (FULL_TORQUE_ERROR_RAD, DAMPING_TIME_S) == (0.1, 0.05)
    assert stiffness_for(100.0) == pytest.approx(1000.0)
    assert damping_for(100.0) == pytest.approx(50.0)
    assert stiffness_for(0.0) == 0.0
    assert stiffness_for(5.0) * FULL_TORQUE_ERROR_RAD == pytest.approx(5.0)


def test_every_drive_follows_the_rule(body):
    """每个驱动器都是位置控制，软硬按它的峰值定（偏 0.1 弧度出全力）；目标只能在它的范围里。
    带一个关节的驱动器，就是那个关节的。"""
    model = body.model
    assert model.nu == len(body.actuators)
    for index, actuator in enumerate(body.actuators):
        stiffness = actuator.peak_torque_nm / FULL_TORQUE_ERROR_RAD
        assert model.actuator(index).name == actuator.name
        if len(actuator.joints) == 1:
            assert model.joint(int(model.actuator_trnid[index, 0])).name == actuator.joints[0][0]
        assert model.actuator_gainprm[index, 0] == pytest.approx(stiffness), actuator.name
        assert model.actuator_biasprm[index, :3] == pytest.approx([0.0, -stiffness, -stiffness * DAMPING_TIME_S])
        assert model.actuator_ctrllimited[index], actuator.name
        assert model.actuator_ctrlrange[index] == pytest.approx([actuator.lower, actuator.upper]), actuator.name
    for joint in body.joints:
        assert model.joint(joint.name).range == pytest.approx([joint.lower_rad, joint.upper_rad]), joint.name


def test_no_joint_gets_more_than_its_peak_torque(body):
    """目标离得再远，关节上的力矩也不超过峰值：把每个关节的目标放到范围的一头，力矩正好是峰值。

    力矩的传感器读到的也是这个限过的数。（有的模型把上限写在关节上，驱动器自己的数没限过，会大几十倍。）
    """
    model = body.model
    data = standing_data(model)
    for index, actuator in enumerate(body.actuators):
        length = data.actuator_length[index]
        far_end = actuator.upper if actuator.upper - length > length - actuator.lower else actuator.lower
        assert abs(far_end - length) > FULL_TORQUE_ERROR_RAD, actuator.name
        data.ctrl[:] = body.stand.ctrl
        data.ctrl[index] = far_end
        mujoco.mj_forward(model, data)
        expected = np.sign(far_end - length) * actuator.peak_torque_nm
        if len(actuator.joints) == 1:
            name = actuator.joints[0][0]
            assert data.qfrc_actuator[model.joint(name).dofadr[0]] == pytest.approx(expected), name
            assert read_sensor(model, data, name + TORQUE_SUFFIX)[0] == pytest.approx(expected), name
        else:
            # 带几个关节的驱动器（并联的一对），上限写在驱动器上：它自己的力就是限过的。
            assert data.actuator_force[index] == pytest.approx(expected), actuator.name


# 同样的关节传感器 ------------------------------------------------------------------------------------


def test_every_driven_joint_has_position_velocity_and_torque_sensors(body):
    """每个有驱动器的关节都有位置、速度、力矩三个传感器，名字是同一个规则，各是一个数。"""
    model = body.model
    for joint in body.joints:
        for suffix in (POSITION_SUFFIX, VELOCITY_SUFFIX, TORQUE_SUFFIX):
            assert model.sensor(joint.name + suffix).dim[0] == 1, joint.name + suffix


def test_joint_without_a_drive_gets_no_torque_sensor():
    """没有驱动器的关节只有位置和速度的传感器。"""
    spec = small_arm()
    add_joint_sensors(spec, joints=["shoulder", "elbow"], driven=["shoulder"])
    model = spec.compile()
    names = [model.sensor(index).name for index in range(model.nsensor)]
    assert names == ["shoulder_pos", "shoulder_vel", "shoulder_torque", "elbow_pos", "elbow_vel"]
    assert model.sensor("shoulder_torque").type[0] == mujoco.mjtSensor.mjSENS_JOINTACTFRC
    assert model.sensor("elbow_vel").type[0] == mujoco.mjtSensor.mjSENS_JOINTVEL


# 小零件 ----------------------------------------------------------------------------------------------


def test_bench_settings_replace_whatever_the_model_file_says():
    """模型文件自己写的步长和积分方法，放上测试台以后都换成测试台的。"""
    spec = small_arm()
    spec.option.timestep = 0.005
    spec.option.integrator = mujoco.mjtIntegrator.mjINT_EULER
    use_bench_settings(spec)
    model = spec.compile()
    assert model.opt.timestep == TIMESTEP_S
    assert model.opt.integrator == mujoco.mjtIntegrator.mjINT_IMPLICITFAST


def test_floor_can_be_added_once():
    """地面的名字是 floor；再加一次会重名，当场报错。"""
    spec = small_arm()
    add_floor(spec)
    assert spec.compile().geom(FLOOR).id >= 0
    with pytest.raises(ValueError, match="repeated name 'floor'"):
        add_floor(spec)


def test_store_stand_pose_writes_a_keyframe():
    """把站姿存进模型：位置和目标原样存进去，名字是 stand。"""
    spec = small_arm()
    stand = StandPose(
        qpos=(0.3, -0.2),
        ctrl=(0.31,),
        holding_torque_nm=(4.0,),
        knee_deg=0.0,
        ankle_deg=0.0,
        hip_deg=0.0,
        pelvis_height_m=1.0,
        center_of_mass_height_m=0.8,
    )
    store_stand_pose(spec, stand)
    key = spec.compile().key(STAND_KEY)
    assert key.qpos == pytest.approx([0.3, -0.2])
    assert key.ctrl == pytest.approx([0.31])
