"""무장과 전투: 겨누기(팔 제어), 사격과 맞히기, 소총 한도, 드론의 경고와 반격, 방패."""

from __future__ import annotations

import pytest

from robot_sim.commands import AimUnit, CommandRejectedError, Fire, Fly, Guard, LowerAim, Reset
from robot_sim.flight import FlightCommand
from robot_sim.weapons import DRONE_LOCK_S, RIFLE_MAX_ENERGY, RIFLE_SHOT_ENERGY
from tests.conftest import run_for, take_off, ticks_until

AIMED_DEGREES = 0.5


def aim_error(simulation) -> float:
    return simulation.mecha_status()["weapon"]["aimError"]


def unit(simulation, unit_id):
    return next(status for status in simulation.units_status() if status["id"] == unit_id)


def fire_until_destroyed(simulation, target: str, max_shots: int = 8) -> list[dict]:
    events = []
    for _ in range(max_shots):
        ticks_until(
            simulation,
            lambda: (
                aim_error(simulation) < AIMED_DEGREES and simulation.rifle.not_ready_reason(simulation.sim_time) is None
            ),
            3.0,
        )
        simulation.apply(Fire())
        events.extend(simulation.drain_events())
        if not unit(simulation, target)["alive"]:
            return events
    raise AssertionError(f"{max_shots}번 쏘아도 {target}을 파괴하지 못했습니다")


def test_aim_settles_on_target(simulation):
    """표적을 겨누면 팔이 1.5초 안에 0.5도 안쪽으로 맞춘다"""
    take_off(simulation)

    simulation.apply(AimUnit("drone-1"))
    settled = ticks_until(simulation, lambda: aim_error(simulation) < AIMED_DEGREES, 1.5)

    assert settled < 1.5
    assert simulation.mecha_status()["weapon"]["aimTarget"] == "drone-1"


def test_aimed_shots_destroy_drone_which_then_falls(simulation):
    """조준이 맞을 때 쏘면 맞히고, 체력이 다하면 파괴 사건이 오고 드론이 떨어진다"""
    take_off(simulation)
    simulation.apply(AimUnit("drone-1"))

    events = fire_until_destroyed(simulation, "drone-1")
    run_for(simulation, 6.0)

    hits = [event for event in events if event["type"] == "shot" and event.get("hit")]
    assert hits
    assert all(event["hit"]["unit"] == "drone-1" for event in hits)
    assert {key: events[-1][key] for key in ("type", "unit")} == {"type": "destroyed", "unit": "drone-1"}
    assert unit(simulation, "drone-1")["position"][2] < 5


def test_shot_goes_where_barrel_points_not_where_commanded(simulation):
    """실패: 표적이 등 뒤라 팔이 닿지 않으면 겨눠도 크게 빗나간다 (사격은 실제 총열 방향)"""
    take_off(simulation)
    run_for(simulation, 4.0, FlightCommand(0.0, 0.0, 0.0, 0.8))
    run_for(simulation, 1.0, FlightCommand(0.0, 0.0, 0.0, 0.0))

    simulation.apply(AimUnit("drone-1"))
    run_for(simulation, 2.0)
    simulation.apply(Fire())
    shot = simulation.drain_events()[0]

    assert aim_error(simulation) > 30
    assert "hit" not in shot


def test_rifle_cooldown_rejects_rapid_fire(simulation):
    """식는 중에 다시 쏘면 거절하고 남은 시간을 알린다"""
    simulation.apply(Fire())

    with pytest.raises(CommandRejectedError) as rejected:
        simulation.apply(Fire())

    assert "식는 중" in rejected.value.reason


def test_energy_runs_out_after_five_shots(simulation):
    """경계값: 에너지 100으로 다섯 번 쏘면 바닥나 여섯 번째는 거절한다"""
    shots = int(RIFLE_MAX_ENERGY // RIFLE_SHOT_ENERGY)
    for _ in range(shots):
        simulation.apply(Fire())
        run_for(simulation, 0.5)
    simulation.rifle.energy = min(simulation.rifle.energy, RIFLE_SHOT_ENERGY - 1)

    with pytest.raises(CommandRejectedError) as rejected:
        simulation.apply(Fire())

    assert "에너지가 모자랍니다" in rejected.value.reason


def test_unknown_or_inactive_target_is_rejected(simulation):
    """실패: 없는 유닛이나 이 장면에서 쓰지 않는 드론은 겨눌 수 없다"""
    for target in ("drone-9", "drone-4", "mecha"):
        with pytest.raises(CommandRejectedError, match="그런 표적이 없습니다"):
            simulation.apply(AimUnit(target))


def test_lower_aim_returns_to_ready(simulation):
    simulation.apply(AimUnit("drone-1"))
    simulation.apply(LowerAim())

    assert "aimError" not in simulation.mecha_status()["weapon"]


def test_armed_drone_warns_before_firing(simulation):
    """반격하는 드론은 쏘기 전에 조준 경고(남은 시간)를 내고, 경고가 끝나야 쏜다"""
    simulation.apply(Reset("skirmish"))
    take_off(simulation)

    simulation.drain_events()
    ticks_until(simulation, lambda: bool(simulation.threats()), 6.0)
    threat = simulation.threats()[0]
    warned_at = simulation.sim_time
    simulation.drain_events()
    fired_at = None
    while fired_at is None and simulation.sim_time - warned_at < DRONE_LOCK_S + 0.2:
        simulation.step_control_tick()
        if any(e["type"] == "shot" and e["shooter"] == threat["from"] for e in simulation.drain_events()):
            fired_at = simulation.sim_time

    assert threat["secondsToFire"] > DRONE_LOCK_S - 0.1
    assert fired_at is not None
    assert fired_at - warned_at >= DRONE_LOCK_S - 0.05


def test_unguarded_mecha_takes_damage(simulation):
    simulation.apply(Reset("skirmish"))
    take_off(simulation)

    run_for(simulation, 8.0)

    assert simulation.mecha_status()["hp"] < simulation.units.mecha.max_hp


def test_shield_blocks_shots_from_guarded_drone(simulation):
    """막을 드론 쪽으로 방패를 들면 그 드론의 사격은 피해 없이 막힌다"""
    simulation.apply(Reset("skirmish"))
    take_off(simulation)
    simulation.apply(Guard(True, "drone-1"))

    shots = []
    for _ in range(round(10.0 / simulation.control_dt)):
        simulation.step_control_tick()
        shots.extend(e for e in simulation.drain_events() if e["type"] == "shot" and e["shooter"] == "drone-1")

    assert len(shots) >= 2
    assert all(shot["hit"]["blocked"] for shot in shots[1:])


def test_destroyed_mecha_falls_and_refuses_commands(simulation):
    """실패: 기체가 파괴되면 추진기가 꺼져 떨어지고, 움직이기·쏘기 명령을 거절한다"""
    take_off(simulation)
    simulation.units.damage(simulation.units.mecha, simulation.units.mecha.max_hp)

    run_for(simulation, 4.0)

    assert simulation.mecha_status()["mode"] == "destroyed"
    assert simulation.mecha_status()["altitude"] < 1.0
    for command in (Fly(FlightCommand(10.0, 0.0, 0.0, 0.0)), Fire()):
        with pytest.raises(CommandRejectedError, match="파괴"):
            simulation.apply(command)
