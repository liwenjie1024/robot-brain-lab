"""状态估计（2.1 步的第二部分，C++ 的带接触 InEKF）接到测试台的身体上。

每 1 毫秒：
- 骨盆上的 IMU 的读数（带噪声、零偏、2 毫秒的延迟，`sensing.SensorModel`）把状态往前推；
- 从关节的角度（驱动器上的编码器，经过脊髓层的换算）算脚底的点在 IMU 坐标里在哪（腿的运动学）；
- 脚上的力判断着没着地：Nova 用踝的六轴力；G1 脚上没有力传感器，测试台用仿真里脚和地面的接触力代替；
- 着地的脚拿来纠正。
开始的那一刻用仿真里的真状态（真机上是开机时站着不动校准的）。绝对的位置和偏航看不出来，会慢慢漂。
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import mujoco
import nova_rt
import numpy as np

from nova_body.bench import FLOOR
from nova_body.body import Body, Imu, ImuGrade
from nova_body.policy_runner import BodySense, root_body
from nova_body.sensing import ACCELEROMETER, GYRO, SensorModel, SensorSet
from nova_body.spine import spine_joints

# 滤波器里的 IMU 噪声比数据手册的大：读数晚 2 毫秒到、一步一步地积分、身体在晃，都算进去。
# 下面这几个数是 G1 走路时试出来的（2.1 步）：3 倍、0.002、5 mm 时走路的速度只差约 0.03 m/s。
NOISE_INFLATION = 3.0
# 零偏慢慢变（数据手册里没有，是假设）。
GYRO_BIAS_WALK = 1e-5  # rad/s²/√Hz
ACCEL_BIAS_WALK = 1e-4  # m/s³/√Hz
# 脚踩着的那一点也会动一点（脚跟抬起、脚掌转的时候）。给大了脚就管不住速度：0.1 时站着也差 0.1 m/s。
CONTACT_NOISE = 0.002  # m/s/√Hz
KINEMATICS_NOISE_M = 0.005
# 一开始的不确定：状态从真状态开始，只有零偏不知道（在数据手册的范围里均匀地取，标准差是范围 / √3）。
INITIAL_VELOCITY_M_S = 0.01
INITIAL_POSITION_M = 0.001
# 着地的判断：脚上的力大过体重的这么多算着地，小过这么多算抬起来（中间照上一次的，免得一会儿有一会儿没有）。
CONTACT_ON_SHARE = 0.10
CONTACT_OFF_SHARE = 0.05
SPATIAL_SIZE = 6


@dataclass(frozen=True)
class EstimatorSetup:
    """一个身体做状态估计要用的：IMU 在哪（点、两个传感器的名字、哪一种）、脚底的点、脚（算接触力用）。"""

    imu_site: str
    accelerometer: str
    gyro: str
    grade: ImuGrade
    feet: tuple[str, ...]
    foot_bodies: tuple[str, ...]


# 练的时候的身体（规约里的 body.name）：状态估计用哪个 IMU、哪两只脚。
POLICY_BODY_SETUPS: dict[str, EstimatorSetup] = {
    "unitree_g1": EstimatorSetup(
        imu_site="imu_in_pelvis",
        accelerometer="imu_lin_acc",
        gyro="imu_ang_vel",
        grade=ImuGrade.STANDARD,
        feet=("left_foot", "right_foot"),
        foot_bodies=("left_ankle_roll_link", "right_ankle_roll_link"),
    ),
}


def setup_for_policy_body(body_name: str) -> EstimatorSetup:
    if body_name not in POLICY_BODY_SETUPS:
        raise ValueError(f"测试台不知道身体 {body_name} 的 IMU 和脚在哪（POLICY_BODY_SETUPS 里没有）")
    return POLICY_BODY_SETUPS[body_name]


def setup_for_body(body: Body, model: mujoco.MjModel) -> EstimatorSetup:
    """测试台上的身体：用骨盆上最准的 IMU、两只脚底正中间的点。"""
    root = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body.anatomy.root)
    on_root = [imu for imu in body.imus if model.site_bodyid[int(model.sensor(imu.accelerometer).objid[0])] == root]
    if not on_root:
        raise ValueError(f"{body.name} 的骨盆上没有 IMU")
    imu = max(on_root, key=lambda item: item.grade == ImuGrade.PRECISE)
    legs = list(body.anatomy.legs.values())
    return EstimatorSetup(
        imu_site=mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SITE, int(model.sensor(imu.accelerometer).objid[0])),
        accelerometer=imu.accelerometer,
        gyro=imu.gyro,
        grade=imu.grade,
        feet=tuple(leg.sole for leg in legs),
        foot_bodies=tuple(leg.foot for leg in legs),
    )


def make_estimator(grade: ImuGrade, gravity: Sequence[float], contact_count: int) -> nova_rt.Estimator:
    gyro, accelerometer = GYRO[grade], ACCELEROMETER[grade]
    return nova_rt.Estimator(
        contact_count=contact_count,
        gyro_noise=gyro.density * NOISE_INFLATION,
        accel_noise=accelerometer.density * NOISE_INFLATION,
        gyro_bias_walk=GYRO_BIAS_WALK,
        accel_bias_walk=ACCEL_BIAS_WALK,
        contact_noise=CONTACT_NOISE,
        kinematics_noise_m=KINEMATICS_NOISE_M,
        gravity=np.asarray(gravity, dtype=float),
        initial_velocity_m_s=INITIAL_VELOCITY_M_S,
        initial_position_m=INITIAL_POSITION_M,
        initial_gyro_bias_rad_s=gyro.bias / math.sqrt(3.0),
        initial_accel_bias_m_s2=accelerometer.bias / math.sqrt(3.0),
    )


class LegKinematics:
    """从关节的角度算脚底的点在 IMU 坐标里在哪。用一份自己的仿真状态：骨盆放在原点不动，只算运动学。"""

    def __init__(self, model: mujoco.MjModel, joints: Sequence[int], imu_site: str, feet: Sequence[str]) -> None:
        self._model = model
        self._data = mujoco.MjData(model)
        self._addresses = np.array([model.jnt_qposadr[joint] for joint in joints], dtype=int)
        self._imu = _site(model, imu_site)
        self._feet = np.array([_site(model, foot) for foot in feet], dtype=int)

    def feet_in_imu(self, joint_positions: np.ndarray) -> np.ndarray:
        """每只脚底的点在 IMU 坐标里的位置（N x 3）。joint_positions 按 joints 的顺序。"""
        self._data.qpos[self._addresses] = joint_positions
        mujoco.mj_kinematics(self._model, self._data)
        rotation = self._data.site_xmat[self._imu].reshape(3, 3)
        return (self._data.site_xpos[self._feet] - self._data.site_xpos[self._imu]) @ rotation


class ContactDetector:
    """看脚上的力判断着没着地：大过 on 才算着地，小过 off 才算抬起来，中间照上一次的。"""

    def __init__(self, count: int, on_n: float, off_n: float) -> None:
        if not 0.0 <= off_n < on_n:
            raise ValueError(f"着地的门槛要比抬起来的高：着地 {on_n:g} N，抬起 {off_n:g} N")
        self._on, self._off = on_n, off_n
        self._state = np.zeros(count, dtype=bool)

    @property
    def state(self) -> np.ndarray:
        return self._state.copy()

    def reset(self) -> None:
        self._state[:] = False

    def update(self, forces: np.ndarray) -> np.ndarray:
        forces = np.asarray(forces, dtype=float)
        if forces.shape != self._state.shape:
            raise ValueError(f"脚上的力要给 {self._state.size} 个，收到的是 {forces.shape}")
        self._state = np.where(forces > self._on, True, np.where(forces < self._off, False, self._state))
        return self._state.copy()


class GroundContact:
    """仿真里每只脚和地面之间的法向接触力（牛顿）。G1 脚上没有力传感器，测试台拿它代替。"""

    def __init__(self, model: mujoco.MjModel, foot_bodies: Sequence[str], floor_geom: str) -> None:
        self._model = model
        self._floor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, floor_geom)
        if self._floor < 0:
            raise ValueError(f"模型里没有地面 {floor_geom}")
        feet = [mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, name) for name in foot_bodies]
        if min(feet) < 0:
            raise ValueError(f"模型里没有这些脚：{', '.join(foot_bodies)}")
        # 每个身体属于哪只脚（脚和它下面的段，比如脚趾）；不属于脚的是 -1。
        self._foot_of_body = np.full(model.nbody, -1, dtype=int)
        for body in range(model.nbody):
            ancestor = body
            while ancestor > 0 and ancestor not in feet:
                ancestor = int(model.body_parentid[ancestor])
            if ancestor in feet:
                self._foot_of_body[body] = feet.index(ancestor)
        self._count = len(feet)

    def forces(self, data: mujoco.MjData) -> np.ndarray:
        forces = np.zeros(self._count)
        wrench = np.zeros(SPATIAL_SIZE)
        for index in range(data.ncon):
            contact = data.contact[index]
            if self._floor not in (contact.geom1, contact.geom2):
                continue
            other = contact.geom2 if contact.geom1 == self._floor else contact.geom1
            foot = self._foot_of_body[self._model.geom_bodyid[other]]
            if foot >= 0:
                mujoco.mj_contactForce(self._model, data, index, wrench)
                forces[foot] += wrench[0]
        return forces


class StateEstimator:
    """测试台上的状态估计：C++ 的估计器 + 腿的运动学 + 着地的判断。"""

    def __init__(self, model: mujoco.MjModel, setup: EstimatorSetup, joints: Sequence[int], weight_n: float) -> None:
        self._model = model
        self._estimator = make_estimator(setup.grade, model.opt.gravity, len(setup.feet))
        self._kinematics = LegKinematics(model, joints, setup.imu_site, setup.feet)
        self._detector = ContactDetector(len(setup.feet), CONTACT_ON_SHARE * weight_n, CONTACT_OFF_SHARE * weight_n)
        self._imu = _site(model, setup.imu_site)
        gravity = np.asarray(model.opt.gravity, dtype=float)
        self._gravity_direction = gravity / np.linalg.norm(gravity)

    def reset(self, data: mujoco.MjData) -> None:
        """从仿真里这一刻的真状态开始（IMU 那一点的转动、速度、位置）。"""
        mujoco.mj_forward(self._model, data)
        rotation, velocity, position = imu_truth(self._model, data, self._imu)
        self._estimator.reset(rotation, velocity, position)
        self._detector.reset()

    def step(
        self, gyro: np.ndarray, accel: np.ndarray, joint_positions: np.ndarray, foot_forces: np.ndarray, dt: float
    ) -> None:
        """往前推 dt 秒，再用着地的脚纠正。"""
        self._estimator.propagate(np.asarray(gyro, dtype=float), np.asarray(accel, dtype=float), dt)
        contacts = self._detector.update(foot_forces)
        self._estimator.correct([bool(contact) for contact in contacts], self._kinematics.feet_in_imu(joint_positions))

    @property
    def rotation(self) -> np.ndarray:
        """IMU 的朝向（世界坐标里）。"""
        return np.array(self._estimator.rotation)

    @property
    def velocity(self) -> np.ndarray:
        """IMU 那一点的速度（世界坐标里）。"""
        return np.array(self._estimator.velocity)

    @property
    def position(self) -> np.ndarray:
        return np.array(self._estimator.position)

    @property
    def velocity_in_imu(self) -> np.ndarray:
        """IMU 那一点的速度，在 IMU 自己的坐标里（像速度计量的）。"""
        return self.rotation.T @ self.velocity

    @property
    def gravity_in_imu(self) -> np.ndarray:
        """重力的方向（单位向量），在 IMU 的坐标里。"""
        return self.rotation.T @ self._gravity_direction

    @property
    def contacts(self) -> np.ndarray:
        return self._detector.state

    @property
    def gyro_bias(self) -> np.ndarray:
        return np.array(self._estimator.gyro_bias)


class BodyFeel:
    """身体自己感觉到的：骨盆上的 IMU 的读数（带噪声、零偏、延迟）和状态估计，给策略看（`BodySense`）。

    建的时候从仿真里这一刻的真状态开始。每一步先 `step`（用到上一步为止的读数估一次），
    仿真走完再 `sample`（读这一步的）。
    脚上的力用仿真里脚和地面的接触力（不是所有身体脚上都有力传感器）。
    """

    def __init__(
        self, model: mujoco.MjModel, setup: EstimatorSetup, spine: nova_rt.Spine, data: mujoco.MjData, seed: int = 0
    ) -> None:
        self._model = model
        self._spine = spine
        imu = Imu("骨盆", setup.accelerometer, setup.gyro, setup.grade)
        self._sensors = SensorModel(model, SensorSet(imus=(imu,)), seed)
        weight = mujoco.mj_getTotalmass(model) * float(np.linalg.norm(model.opt.gravity))
        self._estimator = StateEstimator(model, setup, spine_joints(model), weight)
        self._ground = GroundContact(model, setup.foot_bodies, FLOOR)
        self._imu = _site(model, setup.imu_site)
        if model.site_bodyid[self._imu] != root_body(model):
            raise ValueError(f"IMU 的点 {setup.imu_site} 要在骨盆上（策略的重力方向在骨盆的坐标里）")
        self._root_from_imu = np.zeros(9)
        mujoco.mju_quat2Mat(self._root_from_imu, model.site_quat[self._imu])
        self._root_from_imu = self._root_from_imu.reshape(3, 3)
        self._estimator.reset(data)
        self._sensors.sample(data)

    @property
    def estimator(self) -> StateEstimator:
        return self._estimator

    @property
    def true_gyro_bias(self) -> np.ndarray:
        """IMU 这一回真的角速度零偏（测试台知道，状态估计不知道）。"""
        return self._sensors.bias[3:6]

    def step(self, data: mujoco.MjData, dt: float) -> BodySense:
        accel, gyro = self._sensors.latest().imus[0]
        joints = self._spine.joints_from_actuators(data.actuator_length.copy())
        self._estimator.step(gyro, accel, joints, self._ground.forces(data), dt)
        return BodySense(
            base_lin_vel=self._estimator.velocity_in_imu,
            base_ang_vel=gyro,
            projected_gravity=self._root_from_imu @ self._estimator.gravity_in_imu,
        )

    def sample(self, data: mujoco.MjData) -> None:
        self._sensors.sample(data)

    def errors(self, data: mujoco.MjData) -> tuple[float, float]:
        """估出来的和仿真里真的差多少：速度（m/s）、身体的歪斜（度，只看横滚、俯仰）。"""
        mujoco.mj_forward(self._model, data)
        rotation, velocity, _ = imu_truth(self._model, data, self._imu)
        speed_error = float(np.linalg.norm(self._estimator.velocity - velocity))
        return speed_error, tilt_error_deg(self._estimator.rotation, rotation)


def imu_truth(model: mujoco.MjModel, data: mujoco.MjData, imu_site: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """仿真里 IMU 那一点真的转动、速度（世界坐标）、位置。要先算过 mj_forward。"""
    velocity = np.zeros(SPATIAL_SIZE)
    mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_SITE, imu_site, velocity, 0)
    rotation = data.site_xmat[imu_site].reshape(3, 3).copy()
    return rotation, velocity[3:].copy(), data.site_xpos[imu_site].copy()


def tilt_error_deg(estimated: np.ndarray, actual: np.ndarray) -> float:
    """两个朝向的重力方向差多少度（只看横滚、俯仰；偏航本来就看不出来）。"""
    up_estimated = estimated.T @ np.array([0.0, 0.0, 1.0])
    up_actual = actual.T @ np.array([0.0, 0.0, 1.0])
    return math.degrees(math.acos(max(-1.0, min(1.0, float(up_estimated @ up_actual)))))


def _site(model: mujoco.MjModel, name: str) -> int:
    site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, name)
    if site < 0:
        raise ValueError(f"模型里没有点 {name}")
    return site
