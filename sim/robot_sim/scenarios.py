"""시험 장면: 처음으로 되돌릴 때 고른다. 장면마다 쓰는 드론과 그 움직임·무장이 다르다."""

from __future__ import annotations

from dataclasses import dataclass

from .drones import MAX_DRONES, DronePlan


@dataclass(frozen=True)
class Scenario:
    name: str
    label: str
    description: str
    drones: tuple[DronePlan, ...] = ()

    def __post_init__(self) -> None:
        if len(self.drones) > MAX_DRONES:
            raise ValueError(f"{self.name}: 드론은 {MAX_DRONES}대까지입니다")


SCENARIOS = {
    scenario.name: scenario
    for scenario in (
        Scenario("empty", "빈 시험장", "드론 없이 날기·자세만 시험합니다."),
        Scenario(
            "targets",
            "표적 사격",
            "멈춰 떠 있는 드론 3대를 맞힙니다. 드론은 반격하지 않습니다.",
            (
                DronePlan(home=(150.0, 0.0, 25.0)),
                DronePlan(home=(220.0, 80.0, 40.0)),
                DronePlan(home=(260.0, -120.0, 30.0)),
            ),
        ),
        Scenario(
            "moving",
            "움직이는 표적",
            "원을 그리며 나는 드론 3대를 맞힙니다. 드론은 반격하지 않습니다.",
            (
                DronePlan(home=(200.0, 0.0, 30.0), orbit_radius=60.0, orbit_speed=15.0),
                DronePlan(home=(250.0, 100.0, 45.0), orbit_radius=80.0, orbit_speed=20.0, orbit_phase=2.0),
                DronePlan(home=(250.0, -100.0, 35.0), orbit_radius=100.0, orbit_speed=25.0, orbit_phase=4.0),
            ),
        ),
        Scenario(
            "skirmish",
            "반격하는 드론",
            "원을 그리며 나는 드론 3대가 조준 경고 1.2초 뒤에 쏩니다. 피하거나 방패로 막으며 맞힙니다.",
            (
                DronePlan(home=(180.0, 0.0, 30.0), orbit_radius=60.0, orbit_speed=12.0, armed=True),
                DronePlan(home=(220.0, 120.0, 40.0), orbit_radius=70.0, orbit_speed=15.0, orbit_phase=2.0, armed=True),
                DronePlan(home=(220.0, -120.0, 35.0), orbit_radius=80.0, orbit_speed=18.0, orbit_phase=4.0, armed=True),
            ),
        ),
    )
}
DEFAULT_SCENARIO = "targets"
