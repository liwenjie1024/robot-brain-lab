"""驱动器有多重：从真实产品的数，估计"出这么大的峰值力矩要多重"。

做法：拿公开的低减速比关节电机（电机 + 减速器 + 驱动板一体）的峰值力矩和重量，
拟合一条幂律 质量 = 系数 × 力矩^指数。大的电机每公斤能出的力矩更大，所以指数小于 1。

数都是厂商或经销商公布的峰值，没有独立测过。所以给两条线：
- 今天最好的：全部样本，包括最好的那个（Unitree M107）。
- 保守的：去掉最好的那个。
"""

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ActuatorSample:
    """一个真实的驱动器。"""

    name: str
    peak_torque_nm: float
    mass_kg: float
    source: str


CUBEMARS_SPEC_TABLE = "https://www.cubemars.com/images/file/20230703/1688352405877552.pdf"
ROBSTRIDE_GUIDE = (
    "https://openelab.com/blogs/learn/complete-guide-to-robstride-qdd-motors-model-comparison-and-selection"
)

# 按峰值力矩从大到小排。第一个是每公斤力矩最大的（厂商的数）。
QDD_SAMPLES: tuple[ActuatorSample, ...] = (
    ActuatorSample("Unitree M107", 360.0, 1.9, "https://unitree.com/h1"),
    ActuatorSample(
        "RobStride 04",
        120.0,
        1.42,
        "https://openelab.io/a/s/products/robstride04-qdd-120n-m-integrated-joint-motor-module",
    ),
    ActuatorSample("CubeMars AK10-9 V2.0", 48.0, 0.96, CUBEMARS_SPEC_TABLE),
    ActuatorSample("RobStride 06", 36.0, 0.621, ROBSTRIDE_GUIDE),
    ActuatorSample("CubeMars AK70-10", 24.8, 0.521, CUBEMARS_SPEC_TABLE),
    ActuatorSample("Unitree GO-M8010-6", 23.7, 0.53, "https://unitree.com/go1/motor"),
    ActuatorSample("CubeMars AK80-9", 18.0, 0.485, CUBEMARS_SPEC_TABLE),
    ActuatorSample("RobStride 02", 17.0, 0.405, ROBSTRIDE_GUIDE),
)

BEST_SAMPLE_NAME = "Unitree M107"
MIN_SAMPLES_FOR_FIT = 2


@dataclass(frozen=True)
class ActuatorMassModel:
    """幂律：质量 = coefficient × 力矩^exponent。"""

    name: str
    coefficient: float
    exponent: float
    min_torque_nm: float
    max_torque_nm: float

    def mass_kg(self, peak_torque_nm: float) -> float:
        """出这么大的峰值力矩，驱动器大约多重。"""
        if peak_torque_nm <= 0:
            raise ValueError(f"峰值力矩必须大于 0，收到的是 {peak_torque_nm}")
        return self.coefficient * peak_torque_nm**self.exponent

    def is_beyond_data(self, peak_torque_nm: float) -> bool:
        """这个力矩是不是超出了样本的范围（超出了就是外推，没那么可信）。"""
        return not self.min_torque_nm <= peak_torque_nm <= self.max_torque_nm


def fit_power_law(name: str, samples: tuple[ActuatorSample, ...]) -> ActuatorMassModel:
    """在对数坐标里用最小二乘拟合幂律。"""
    if len(samples) < MIN_SAMPLES_FOR_FIT:
        raise ValueError(f"拟合至少要 {MIN_SAMPLES_FOR_FIT} 个样本，收到 {len(samples)} 个")
    torques = np.array([sample.peak_torque_nm for sample in samples])
    masses = np.array([sample.mass_kg for sample in samples])
    if np.any(torques <= 0) or np.any(masses <= 0):
        raise ValueError("样本的力矩和质量都必须大于 0")
    exponent, log_coefficient = np.polyfit(np.log(torques), np.log(masses), deg=1)
    return ActuatorMassModel(
        name=name,
        coefficient=math.exp(float(log_coefficient)),
        exponent=float(exponent),
        min_torque_nm=float(torques.min()),
        max_torque_nm=float(torques.max()),
    )


def best_today_model() -> ActuatorMassModel:
    """今天最好的：全部样本。"""
    return fit_power_law("今天最好的驱动", QDD_SAMPLES)


def conservative_model() -> ActuatorMassModel:
    """保守的：去掉每公斤力矩最大的那个样本。"""
    samples = tuple(sample for sample in QDD_SAMPLES if sample.name != BEST_SAMPLE_NAME)
    return fit_power_law("保守的驱动", samples)
