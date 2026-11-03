"""비행 제어(System 0): 명령한 속도로 날고, 똑바로 서 있고, 착지하면 추진기를 끄는지 물리를 돌려 확인한다."""

from __future__ import annotations

import math

import numpy as np
import pytest

from robot_sim.commands import Push
from robot_sim.flight import HOLD, FlightCommand
from tests.conftest import run_for, take_off


def tilt_degrees(simulation) -> float:
    up = simulation.data.xmat[simulation.root_body].reshape(3, 3)[:, 2]
    return math.degrees(math.acos(min(1.0, float(up[2]))))


def test_starts_landed_with_thrusters_off(simulation):
    """처음에는 땅에 서 있고 추진기를 쓰지 않는다"""
    run_for(simulation, 1.0)

    status = simulation.mecha_status()
    assert status["mode"] == "landed"
    assert status["altitude"] == pytest.approx(0.0, abs=0.05)
    assert not simulation.data.ctrl[:6].any()


def test_climbs_at_commanded_rate_and_holds_altitude(simulation):
    """위로 8m/s면 그 빠르기로 오르고, 멈추면 그 높이에 떠 있다"""
    run_for(simulation, 4.0, FlightCommand(0.0, 0.0, 8.0, 0.0))
    climbing = simulation.mecha_status()
    run_for(simulation, 2.0, HOLD)
    altitude = simulation.mecha_status()["altitude"]
    run_for(simulation, 5.0)

    assert climbing["mode"] == "flying"
    assert climbing["velocity"]["up"] == pytest.approx(8.0, abs=0.2)
    assert simulation.mecha_status()["altitude"] == pytest.approx(altitude, abs=0.3)
    assert tilt_degrees(simulation) < 1.0


def test_flies_forward_then_stops(simulation):
    """앞으로 20m/s로 날다가 멈추면 다시 떠 있는다 (기체는 내내 똑바로)"""
    take_off(simulation)

    run_for(simulation, 4.0, FlightCommand(20.0, 0.0, 0.0, 0.0))
    flying = simulation.mecha_status()
    tilt_while_flying = tilt_degrees(simulation)
    run_for(simulation, 4.0, HOLD)

    assert flying["velocity"]["forward"] == pytest.approx(20.0, abs=0.5)
    assert tilt_while_flying < 2.0
    assert abs(simulation.mecha_status()["velocity"]["forward"]) < 0.3
    assert simulation.mecha_status()["position"][0] > 50


def test_turns_at_commanded_rate(simulation):
    """왼쪽으로 0.8rad/s면 그 빠르기로 기수를 돌린다"""
    take_off(simulation)

    run_for(simulation, 2.0, FlightCommand(0.0, 0.0, 0.0, 0.8))

    status = simulation.mecha_status()
    assert status["velocity"]["turn"] == pytest.approx(0.8, abs=0.05)
    assert status["heading"] > 1.2


@pytest.mark.parametrize(
    ("flight", "axis", "sign"),
    [(FlightCommand(-10.0, 0.0, 0.0, 0.0), 0, -1), (FlightCommand(0.0, 15.0, 0.0, 0.0), 1, 1)],
    ids=["뒤로", "왼쪽 옆으로"],
)
def test_flies_backward_and_sideways(simulation, flight, axis, sign):
    take_off(simulation)

    run_for(simulation, 3.0, flight)

    assert sign * simulation.mecha_status()["position"][axis] > 15


def test_fastest_allowed_speed_keeps_attitude(simulation):
    """경계값: 허용한 가장 빠른 앞 속도(40m/s)로도 기체가 2도 넘게 기울지 않는다"""
    take_off(simulation)

    run_for(simulation, 5.0, FlightCommand(40.0, 0.0, 0.0, 0.0))

    assert simulation.mecha_status()["velocity"]["forward"] > 38
    assert tilt_degrees(simulation) < 2.0


def test_descends_and_lands_with_thrusters_off(simulation):
    """내려가다 땅에 닿아 느려지면 착지로 바뀌고 추진기를 끈다"""
    take_off(simulation)

    run_for(simulation, 6.0, FlightCommand(0.0, 0.0, -8.0, 0.0))
    run_for(simulation, 2.0, HOLD)

    status = simulation.mecha_status()
    assert status["mode"] == "landed"
    assert status["altitude"] == pytest.approx(0.0, abs=0.1)
    assert not simulation.data.ctrl[:6].any()


def test_recovers_attitude_after_hit(simulation):
    """옆에서 크게 맞아도(100만 N, 0.2초) 다시 똑바로 서서 떠 있다"""
    take_off(simulation)
    altitude = simulation.mecha_status()["altitude"]

    simulation.apply(Push((0.0, 1_000_000.0, 0.0), 0.2))
    run_for(simulation, 0.4)
    shaken = tilt_degrees(simulation)
    run_for(simulation, 4.0)

    assert simulation.mecha_status()["pushing"] is False
    assert tilt_degrees(simulation) < 1.0
    assert simulation.mecha_status()["altitude"] == pytest.approx(altitude, abs=3.0)
    assert shaken < 30


def test_reset_returns_to_start(simulation):
    """처음으로 되돌리면 시작 자리에 서고, 같은 명령이면 같은 결과가 나온다"""
    take_off(simulation)
    first = np.array(simulation.mecha_status()["position"])

    simulation.reset()
    assert simulation.mecha_status()["mode"] == "landed"
    take_off(simulation)

    assert np.array(simulation.mecha_status()["position"]) == pytest.approx(first, abs=1e-6)
