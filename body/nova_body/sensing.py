"""身体自己的传感器读到的（1.6 步）：仿真里的读数是理想的，这里加上真的传感器会有的噪声、零偏和延迟。

数来自真实的产品（公开的数据手册或厂家的页面）：
- 一般的 IMU：Bosch BMI088。角速度噪声 0.014 °/s/√Hz，零偏 ±1 °/s；加速度噪声 175 µg/√Hz，零偏 ±20 mg。
- 高精度的 IMU（骨盆）：Epson M-G370。角速度噪声 2.5 (°/h)/√Hz、零偏稳定性 0.8 °/h（开机时在静止中校准，
  剩下的零偏按 ±0.1 °/s 估，这个是假设）；加速度噪声 50 µg/√Hz（M-G370PDG），开机零偏 2 mg。
- 六轴力：按 ATI Mini45（580 N / 20 N·m 那一档）的分辨率当噪声：力 0.25 N、力矩 0.005 N·m。量程大的（踝要扛住体重）
  按 noise_scale 放大。开机时没踩着地面，去掉了零点，所以没有零偏。
- 接触力（皮肤）：每一处 0.05 N 的噪声（假设）。

噪声是白噪声：每次读的标准差 = 噪声密度 x √带宽，带宽是读的频率的一半（每毫秒读一次，就是 500 Hz）。
零偏每一回（重新开始）随机取一次，在上面的范围里均匀地取。
延迟：IMU 2 毫秒（芯片里的滤波），六轴力 1 毫秒，接触力 2 毫秒。
"""

import math
from collections import deque
from dataclasses import dataclass
from typing import Protocol

import mujoco
import numpy as np

from nova_body.body import ForceSensor, Imu, ImuGrade, TouchSensor
from nova_body.mass_closure import GRAVITY_M_S2

DEG = math.pi / 180.0
MICRO_G = 1e-6 * GRAVITY_M_S2
MILLI_G = 1e-3 * GRAVITY_M_S2
SECONDS_PER_HOUR = 3600.0
AXES = 3


@dataclass(frozen=True)
class NoiseSpec:
    """一种读数的噪声：噪声密度（每 √Hz）和零偏的范围（±）。"""

    density: float
    bias: float


GYRO: dict[ImuGrade, NoiseSpec] = {
    ImuGrade.STANDARD: NoiseSpec(density=0.014 * DEG, bias=1.0 * DEG),
    ImuGrade.PRECISE: NoiseSpec(density=2.5 / SECONDS_PER_HOUR * DEG, bias=0.1 * DEG),
}
ACCELEROMETER: dict[ImuGrade, NoiseSpec] = {
    ImuGrade.STANDARD: NoiseSpec(density=175.0 * MICRO_G, bias=20.0 * MILLI_G),
    ImuGrade.PRECISE: NoiseSpec(density=50.0 * MICRO_G, bias=2.0 * MILLI_G),
}
# 六轴力和接触力给的是每次读的标准差（不是密度）；没有零偏。
FORCE_STD_N = 0.25
MOMENT_STD_NM = 0.005
TOUCH_STD_N = 0.05
IMU_DELAY_STEPS = 2
FORCE_DELAY_STEPS = 1
TOUCH_DELAY_STEPS = 2


def per_reading_std(density: float, timestep_s: float) -> float:
    """白噪声：每次读的标准差 = 噪声密度 x √带宽（带宽是读的频率的一半）。"""
    return density * math.sqrt(0.5 / timestep_s)


class SensorList(Protocol):
    """传感器模型要的：身体带着的 IMU、六轴力、接触力（`Body` 就是一个；只有一个 IMU 的模型可以用 `SensorSet`）。"""

    imus: tuple[Imu, ...]
    force_sensors: tuple[ForceSensor, ...]
    touch_sensors: tuple[TouchSensor, ...]


@dataclass(frozen=True)
class SensorSet:
    """一组传感器（不是 `Body` 的模型用，比如练的时候的 G1）。"""

    imus: tuple[Imu, ...]
    force_sensors: tuple[ForceSensor, ...] = ()
    touch_sensors: tuple[TouchSensor, ...] = ()


@dataclass(frozen=True)
class Readings:
    """身体的传感器这一刻拿得到的（顺序和 body.imus、body.force_sensors、body.touch_sensors 一样）。

    imus 是每个 IMU 的（加速度 m/s²、角速度 rad/s），forces 是每个六轴力的（力 N、力矩 N·m），
    touches 是每一处的接触力（N）。
    """

    imus: tuple[tuple[np.ndarray, np.ndarray], ...]
    forces: tuple[tuple[np.ndarray, np.ndarray], ...]
    touches: tuple[np.ndarray, ...]


class SensorModel:
    """一个身体的传感器：每一步读一次理想的读数，加上噪声和零偏，晚几步交出来。

    全部的读数排成一行一起算（一步只取一次随机数），所以很快。seed 定了随机数：同样的 seed 每次一样。
    """

    def __init__(self, model: mujoco.MjModel, body: SensorList, seed: int = 0) -> None:
        timestep = float(model.opt.timestep)
        self._rng = np.random.default_rng(seed)
        # 每个传感器：名字、每次读的噪声的标准差、零偏的范围。
        parts: list[tuple[str, float, float]] = []
        for imu in body.imus:
            accelerometer, gyro = ACCELEROMETER[imu.grade], GYRO[imu.grade]
            parts.append((imu.accelerometer, per_reading_std(accelerometer.density, timestep), accelerometer.bias))
            parts.append((imu.gyro, per_reading_std(gyro.density, timestep), gyro.bias))
        for sensor in body.force_sensors:
            parts.append((sensor.force, FORCE_STD_N * sensor.noise_scale, 0.0))
            parts.append((sensor.moment, MOMENT_STD_NM * sensor.noise_scale, 0.0))
        parts += [(sensor.sensor, TOUCH_STD_N, 0.0) for sensor in body.touch_sensors]
        self._index = np.concatenate([_addresses(model, name) for name, _, _ in parts])
        self._std = np.concatenate([np.full(AXES, std) for _, std, _ in parts])
        self._bias_range = np.concatenate([np.full(AXES, bias) for _, _, bias in parts])
        self._imu_count = len(body.imus)
        self._force_count = len(body.force_sensors)
        self._touch_count = len(body.touch_sensors)
        self._bias = np.zeros(len(self._index))
        self._history: deque[np.ndarray] = deque(maxlen=max(IMU_DELAY_STEPS, FORCE_DELAY_STEPS, TOUCH_DELAY_STEPS) + 1)
        self.reset()

    @property
    def bias(self) -> np.ndarray:
        """这一回每个读数的零偏（排成一行，和读数一样的顺序；测试和诊断用）。"""
        return self._bias.copy()

    @property
    def ready(self) -> bool:
        """读过没有（读过才有读数可拿）。"""
        return bool(self._history)

    def reset(self) -> None:
        """重新开始：IMU 重新取一个零偏（别的没有零偏），以前读到的都不要了。"""
        self._bias = self._rng.uniform(-1.0, 1.0, len(self._index)) * self._bias_range
        self._history.clear()

    def sample(self, data: mujoco.MjData) -> None:
        """这一步读一次（理想的读数加上噪声和零偏），存起来。"""
        noise = self._std * self._rng.standard_normal(len(self._index))
        self._history.append(data.sensordata[self._index] + self._bias + noise)

    def latest(self) -> Readings:
        """身体现在拿得到的读数：IMU 是 2 步以前的，六轴力 1 步以前的，接触力 2 步以前的（还没读够就用最早的）。"""
        if not self._history:
            raise ValueError("还没有读过：先 sample")
        imu_rows = self._delayed(IMU_DELAY_STEPS)
        force_rows = self._delayed(FORCE_DELAY_STEPS)
        touch_rows = self._delayed(TOUCH_DELAY_STEPS)
        imu_end = 2 * AXES * self._imu_count
        force_end = imu_end + 2 * AXES * self._force_count
        imus = tuple(
            (imu_rows[start : start + AXES].copy(), imu_rows[start + AXES : start + 2 * AXES].copy())
            for start in range(0, imu_end, 2 * AXES)
        )
        forces = tuple(
            (force_rows[start : start + AXES].copy(), force_rows[start + AXES : start + 2 * AXES].copy())
            for start in range(imu_end, force_end, 2 * AXES)
        )
        touches = tuple(
            touch_rows[start : start + AXES].copy()
            for start in range(force_end, force_end + AXES * self._touch_count, AXES)
        )
        return Readings(imus, forces, touches)

    def _delayed(self, steps: int) -> np.ndarray:
        return self._history[max(0, len(self._history) - 1 - steps)]


def _addresses(model: mujoco.MjModel, name: str) -> np.ndarray:
    """一个传感器的读数在 sensordata 里的位置（三个数）。"""
    sensor = model.sensor(name)
    if int(sensor.dim[0]) != AXES:
        raise ValueError(f"{name} 不是三个数的传感器")
    start = int(sensor.adr[0])
    return np.arange(start, start + AXES)
