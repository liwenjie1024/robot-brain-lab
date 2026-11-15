"""测试台：每个身体都放进同一个仿真里，用同一条规则顶着关节。

地面、步长、积分的方法、关节位置控制的软硬、关节的传感器，对每个身体都一样，只写在这一处。
这样 Nova 和基线的结果差在哪里，只能是因为身体不一样。
"""

from collections.abc import Iterable

import mujoco

from nova_body.body import StandPose

TIMESTEP_S = 0.001
FLOOR = "floor"
STAND_KEY = "stand"

# 接触的软硬：时间常数越小越硬，不能小于 2 个仿真步长。
CONTACT_SOLREF = (0.005, 1.0)
# 和地面的接触（摩擦、软硬）由地面说了算：地面的优先级比任何身体的形状都高。
# 现成的模型会给自己的脚设优先级（G1 是 1）；不这样做，同一块地面对不同的身体就不一样了。
FLOOR_PRIORITY = 10
FLOOR_RGBA = (0.90, 0.90, 0.88, 1.0)

# 关节的位置控制：偏了这么多弧度，驱动器就出全力；阻尼 = 刚度 x 这个时间。
FULL_TORQUE_ERROR_RAD = 0.1
DAMPING_TIME_S = 0.05

POSITION_SUFFIX = "_pos"
VELOCITY_SUFFIX = "_vel"
TORQUE_SUFFIX = "_torque"


def use_bench_settings(spec: mujoco.MjSpec) -> None:
    """用测试台的步长和积分的方法。"""
    spec.option.timestep = TIMESTEP_S
    # 驱动器的阻尼很大，要用把它算进去的积分方法才稳。
    spec.option.integrator = mujoco.mjtIntegrator.mjINT_IMPLICITFAST


def add_floor(spec: mujoco.MjSpec) -> None:
    """加上测试台的地面：一块平地。以后换成考场。"""
    spec.worldbody.add_geom(
        name=FLOOR,
        type=mujoco.mjtGeom.mjGEOM_PLANE,
        size=[0.0, 0.0, 1.0],
        contype=0,
        conaffinity=1,
        priority=FLOOR_PRIORITY,
        solref=list(CONTACT_SOLREF),
        rgba=list(FLOOR_RGBA),
    )


def stiffness_for(peak_torque_nm: float) -> float:
    """位置控制的刚度（N·m/rad）：按这个关节的峰值力矩定。"""
    return peak_torque_nm / FULL_TORQUE_ERROR_RAD


def damping_for(peak_torque_nm: float) -> float:
    """位置控制的阻尼（N·m·s/rad）。"""
    return stiffness_for(peak_torque_nm) * DAMPING_TIME_S


def add_joint_sensors(spec: mujoco.MjSpec, joints: Iterable[str], driven: Iterable[str]) -> None:
    """每个关节加位置和速度的传感器；有驱动器的再加一个"驱动器给这个关节的力矩"。

    力矩量的是关节实际得到的（已经按峰值限过的）。有的模型把力矩的上限写在关节上，不写在驱动器上；
    那样的模型里，驱动器自己的那个数在出到顶的时候是没限过的，会大出很多倍。
    """
    driven = set(driven)
    for joint in joints:
        _add_sensor(spec, joint + POSITION_SUFFIX, mujoco.mjtSensor.mjSENS_JOINTPOS, joint)
        _add_sensor(spec, joint + VELOCITY_SUFFIX, mujoco.mjtSensor.mjSENS_JOINTVEL, joint)
        if joint in driven:
            _add_sensor(spec, joint + TORQUE_SUFFIX, mujoco.mjtSensor.mjSENS_JOINTACTFRC, joint)


def store_stand_pose(spec: mujoco.MjSpec, stand: StandPose) -> None:
    """把站姿存进模型，名字是 stand。"""
    spec.add_key(name=STAND_KEY, qpos=list(stand.qpos), ctrl=list(stand.ctrl))


def _add_sensor(spec: mujoco.MjSpec, name: str, sensor_type, joint: str) -> None:
    spec.add_sensor(name=name, type=sensor_type, objtype=mujoco.mjtObj.mjOBJ_JOINT, objname=joint)
