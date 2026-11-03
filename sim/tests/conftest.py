from __future__ import annotations

import pytest

from robot_sim.assets import POLICY_CONFIG, POLICY_FILE, ROBOT_XML, require_assets
from robot_sim.locomotion import Velocity, WalkingController
from robot_sim.simulation import Simulation, build_arena


@pytest.fixture(scope="session")
def arena_model():
    require_assets()
    return build_arena(ROBOT_XML)


@pytest.fixture
def simulation(arena_model) -> Simulation:
    # 정책은 안에 기억(LSTM)을 들고 있어 시험마다 새로 읽는다 (가벼워 몇 ms면 된다).
    return Simulation(arena_model, WalkingController.from_files(POLICY_CONFIG, POLICY_FILE))


def run_for(simulation: Simulation, seconds: float, command: Velocity | None = None) -> bool:
    """정한 시간만큼 진행하고 그동안 한 번이라도 넘어졌는지 돌려준다."""
    if command is not None:
        simulation.set_command(command)
    ticks = round(seconds / simulation.controller.config.control_dt)
    fell = False
    for _ in range(ticks):
        simulation.step_control_tick()
        fell = fell or simulation.status().fallen
    return fell
