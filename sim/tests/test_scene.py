"""화면용 모델 설명: 화면이 기체를 몰라도 시험장을 그릴 수 있는지."""

from __future__ import annotations

import pytest

from robot_sim.drones import MAX_DRONES
from robot_sim.limits import DEFAULT_LIMITS
from robot_sim.scenarios import SCENARIOS
from robot_sim.scene import describe, mesh_binary, moving_bodies

RATES = {"physicsHz": 500.0, "controlHz": 50.0, "stateHz": 50.0}


@pytest.fixture
def scene(simulation):
    return describe(simulation.model, simulation.units, DEFAULT_LIMITS, RATES)


def test_describes_floor_mecha_and_drones(scene, simulation):
    """바닥 하나와 기체·드론의 모양을 알린다 (기본 도형이라 메시는 없다)"""
    shapes = [geom["shape"] for geom in scene["geoms"]]
    bodies = {geom["body"] for geom in scene["geoms"]}

    assert shapes.count("plane") == 1
    assert scene["meshes"] == []
    assert simulation.root_body in bodies
    assert all(unit["body"] in bodies for unit in scene["units"])


def test_lists_every_unit_including_parked_drones(scene):
    """장면에서 쓰지 않는 드론도 모델에 있어 모두 알린다 (상태 메시지는 쓰는 드론만 보낸다)"""
    kinds = [unit["kind"] for unit in scene["units"]]

    assert kinds.count("mecha") == 1
    assert kinds.count("drone") == MAX_DRONES


def test_moving_bodies_cover_mecha_arms_and_drones(simulation):
    """움직이는 몸체: 기체 몸통, 양쪽 어깨·팔, 드론"""
    assert len(moving_bodies(simulation.model)) == 1 + 4 + MAX_DRONES


def test_publishes_robot_size_scenarios_limits_and_rates(scene):
    assert scene["robot"]["height"] == 16.0
    assert [scenario["name"] for scenario in scene["scenarios"]] == list(SCENARIOS)
    assert scene["limits"]["up"] == {"min": -15.0, "max": 20.0}
    assert scene["rates"]["controlHz"] == 50.0


def test_scenarios_tell_how_many_drones_and_how_many_shoot_back(scene):
    """시험 점수는 드론이 있는 장면에서만 낸다: 장면마다 드론 수와 반격하는 드론 수를 알린다"""
    counts = {scenario["name"]: (scenario["drones"], scenario["armedDrones"]) for scenario in scene["scenarios"]}
    assert counts == {"empty": (0, 0), "targets": (3, 0), "moving": (3, 0), "skirmish": (3, 3)}


@pytest.mark.parametrize("mesh", [-1, 0], ids=["음수", "메시 없음"])
def test_unknown_mesh_raises(simulation, mesh):
    with pytest.raises(KeyError):
        mesh_binary(simulation.model, mesh)
