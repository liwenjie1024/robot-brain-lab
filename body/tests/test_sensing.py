"""身体的传感器的测试：噪声和数据手册对得上；高精度的 IMU 噪声小得多；零偏每一回取一次、在范围里；
IMU 晚 2 步、六轴力晚 1 步；同样的随机数种子，读数一样。"""

import math
from dataclasses import replace

import mujoco
import numpy as np
import pytest

from nova_body.body import ImuGrade, TouchSensor
from nova_body.sensing import (
    ACCELEROMETER,
    FORCE_STD_N,
    GYRO,
    IMU_DELAY_STEPS,
    MOMENT_STD_NM,
    TOUCH_STD_N,
    SensorModel,
    per_reading_std,
)
from nova_body.standing import standing_data

SAMPLES = 4000


def readings(nova, seed: int = 0, samples: int = SAMPLES):
    """站着不动的时候读很多次：理想的读数不变，变的只有噪声。"""
    data = standing_data(nova.model)
    sensors = SensorModel(nova.model, nova.body, seed=seed)
    collected = []
    for _ in range(samples):
        sensors.sample(data)
        collected.append(sensors.latest())
    return data, sensors, collected


def truth(model, data, name: str) -> np.ndarray:
    sensor = model.sensor(name)
    return data.sensordata[sensor.adr[0] : sensor.adr[0] + 3].copy()


def test_white_noise_follows_the_datasheet_density():
    """每次读的标准差 = 噪声密度 x √带宽：每毫秒读一次，带宽 500 Hz。"""
    assert per_reading_std(1.0, 0.001) == pytest.approx(math.sqrt(500.0))
    assert per_reading_std(GYRO[ImuGrade.STANDARD].density, 0.001) == pytest.approx(
        0.014 * math.pi / 180 * math.sqrt(500.0)
    )


def test_nova_has_a_precise_pelvis_imu_and_wide_range_ankle_sensors(nova):
    """Nova：骨盆的 IMU 是高精度的，头的是一般的；踝的六轴力量程大，噪声按两倍。"""
    grades = {imu.label: imu.grade for imu in nova.body.imus}
    assert grades == {"骨盆": ImuGrade.PRECISE, "头": ImuGrade.STANDARD}
    scales = {sensor.label: sensor.noise_scale for sensor in nova.body.force_sensors}
    assert scales == {"左踝": 2.0, "右踝": 2.0, "左腕": 1.0, "右腕": 1.0}


def test_noise_and_bias_match_the_specs(nova):
    """站着不动读很多次：每个读数抖动的标准差和规格对得上；平均值比真的偏了一点（零偏），在零偏的范围里。"""
    data, _, collected = readings(nova)
    model, body = nova.model, nova.body
    for index, imu in enumerate(body.imus):
        for name, spec, part in ((imu.accelerometer, ACCELEROMETER[imu.grade], 0), (imu.gyro, GYRO[imu.grade], 1)):
            values = np.array([reading.imus[index][part] for reading in collected])
            assert values.std(axis=0) == pytest.approx([per_reading_std(spec.density, 0.001)] * 3, rel=0.1), name
            offset = values.mean(axis=0) - truth(model, data, name)
            assert np.all(np.abs(offset) <= spec.bias + 4 * values.std(axis=0) / math.sqrt(SAMPLES)), name
    for index, sensor in enumerate(body.force_sensors):
        forces = np.array([reading.forces[index][0] for reading in collected])
        moments = np.array([reading.forces[index][1] for reading in collected])
        assert forces.std(axis=0) == pytest.approx([FORCE_STD_N * sensor.noise_scale] * 3, rel=0.1)
        assert moments.std(axis=0) == pytest.approx([MOMENT_STD_NM * sensor.noise_scale] * 3, rel=0.1)
        assert forces.mean(axis=0) == pytest.approx(truth(model, data, sensor.force), abs=0.05)
    touches = np.array([reading.touches[0] for reading in collected])
    assert touches.std(axis=0) == pytest.approx([TOUCH_STD_N] * 3, rel=0.1)


def test_precise_imu_is_much_quieter(nova):
    """高精度的 IMU，角速度的噪声比一般的小二十倍、加速度的小三倍多。"""
    gyro = GYRO[ImuGrade.STANDARD].density / GYRO[ImuGrade.PRECISE].density
    acceleration = ACCELEROMETER[ImuGrade.STANDARD].density / ACCELEROMETER[ImuGrade.PRECISE].density
    assert gyro > 15
    assert acceleration > 3


def test_imu_readings_arrive_two_steps_late_and_forces_one(nova):
    """IMU 读到的是 2 步以前的，六轴力是 1 步以前的：理想的读数突然变了，晚这么多步才看得到。"""
    model = nova.model
    data = standing_data(model)
    sensors = SensorModel(model, nova.body, seed=1)
    for _ in range(5):
        sensors.sample(data)
    gyro = model.sensor(nova.body.imus[0].gyro)
    force = model.sensor(nova.body.force_sensors[0].force)
    data.sensordata[gyro.adr[0]] += 100.0
    data.sensordata[force.adr[0]] += 1000.0
    seen_gyro, seen_force = [], []
    for _ in range(4):
        sensors.sample(data)
        latest = sensors.latest()
        seen_gyro.append(latest.imus[0][1][0] > 50.0)
        seen_force.append(latest.forces[0][0][0] > 500.0)
    assert seen_gyro == [False] * IMU_DELAY_STEPS + [True] * (4 - IMU_DELAY_STEPS)
    assert seen_force == [False, True, True, True]


def test_same_seed_same_readings_and_reset_draws_new_biases(nova):
    """同样的种子，读数一模一样；重新开始，IMU 换一个零偏。"""
    _, _, first = readings(nova, seed=7, samples=3)
    _, sensors, second = readings(nova, seed=7, samples=3)
    for one, two in zip(first, second, strict=True):
        assert np.array_equal(one.imus[0][0], two.imus[0][0])
    before = sensors._bias.copy()
    sensors.reset()
    assert not np.array_equal(before, sensors._bias)


def test_nothing_to_read_before_the_first_sample(nova):
    """还没读过就要读数：报错。"""
    sensors = SensorModel(nova.model, nova.body)
    with pytest.raises(ValueError, match="还没有读过"):
        sensors.latest()


def test_only_three_number_sensors_can_be_modeled(nova):
    """传感器的读数不是三个数（比如关节的角度）：不认，报错。"""
    joint_sensor = next(
        mujoco.mj_id2name(nova.model, mujoco.mjtObj.mjOBJ_SENSOR, index)
        for index in range(nova.model.nsensor)
        if nova.model.sensor_dim[index] == 1
    )
    odd = replace(nova.body, touch_sensors=(TouchSensor("关节", joint_sensor),))
    with pytest.raises(ValueError, match="不是三个数的传感器"):
        SensorModel(nova.model, odd)
