from __future__ import annotations

import pytest

from robot_sim.commands import Fly
from robot_sim.flight import HOLD, FlightCommand
from robot_sim.simulation import Simulation


@pytest.fixture
def simulation() -> Simulation:
    return Simulation("targets")


def run_for(simulation: Simulation, seconds: float, flight: FlightCommand | None = None) -> None:
    if flight is not None:
        simulation.apply(Fly(flight))
    for _ in range(round(seconds / simulation.control_dt)):
        simulation.step_control_tick()


def take_off(simulation: Simulation, climb_seconds: float = 3.0) -> None:
    """초속 6m로 올라가 멈춰 떠 있는다 (시험 대부분의 출발점)"""
    run_for(simulation, climb_seconds, FlightCommand(0.0, 0.0, 6.0, 0.0))
    run_for(simulation, 1.0, HOLD)


def ticks_until(simulation: Simulation, condition, max_seconds: float) -> float:
    """조건이 맞을 때까지 진행하고 걸린 시간을 돌려준다 (못 맞추면 max_seconds 뒤 실패)."""
    start = simulation.sim_time
    while simulation.sim_time - start < max_seconds:
        simulation.step_control_tick()
        if condition():
            return simulation.sim_time - start
    raise AssertionError(f"{max_seconds}초 안에 조건이 맞지 않았습니다")
