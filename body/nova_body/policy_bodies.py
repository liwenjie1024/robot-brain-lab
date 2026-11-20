"""练的时候的身体（规约里的 body.name），测试台要认得的几样：推哪里（胸），状态估计用哪个 IMU、哪两只脚。

测试台不认识的身体（比如测试用的小身体）推骨盆、不做状态估计。
"""

from dataclasses import dataclass

from nova_body.body import ImuGrade
from nova_body.estimation import EstimatorSetup


@dataclass(frozen=True)
class PolicyBodyInfo:
    """trunk 是推的地方（胸，和 P1 一样）；None 就推骨盆。estimator 是状态估计的设置；None 就做不了状态估计。"""

    trunk: str | None = None
    estimator: EstimatorSetup | None = None


# 练 G1 的那个（mjlab 的）和 SONIC 部署代码里的 G1（测试台在骨盆上加了同样的 IMU 和脚底的点）用同一套。
_G1 = PolicyBodyInfo(
    trunk="torso_link",
    estimator=EstimatorSetup(
        imu_site="imu_in_pelvis",
        accelerometer="imu_lin_acc",
        gyro="imu_ang_vel",
        grade=ImuGrade.STANDARD,
        feet=("left_foot", "right_foot"),
        foot_bodies=("left_ankle_roll_link", "right_ankle_roll_link"),
    ),
)
POLICY_BODIES: dict[str, PolicyBodyInfo] = {"unitree_g1": _G1, "unitree_g1_sonic": _G1}


def info_for(body_name: str) -> PolicyBodyInfo:
    return POLICY_BODIES.get(body_name, PolicyBodyInfo())
