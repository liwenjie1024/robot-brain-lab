"""我们自己的训练任务：在 mjlab 自带的任务上改，名字以 Nova- 开头。训练、导出以前先 import 这个模块，任务才登记上。

Nova-Velocity-Stairs-Unitree-G1（2.2 步）：mjlab 的"G1 在不平的地上按指令走"（看得到脚下的高度），地形换成楼梯多的：
上的、下的都有，台阶从 5 cm 到 20 cm（练的时候由易到难），踏面 22 cm 和 30 cm。考试的楼梯是一级 20 cm、踏面 22 cm
（套内楼梯里最难的），mjlab 自带的楼梯只到 10 cm。别的（奖励、命令、随机改的、PPO 的设置）照 mjlab 的不改。

地形都用方块搭（不用高度场）：G1 碰撞的形状只有球和胶囊，它们和方块之间 MuJoCo Warp 有现成的算法，
用不到凸形状的迭代。所以凸形状的迭代用 mjlab 平地的 50 次，不用它不平地的 500 次（那是给高度场的）：
500 次时这块 8 GB 的显卡放不下（4096 个仿真，光一块缓冲就要 2.9 GB）。
"""

from mjlab.envs import ManagerBasedRlEnvCfg
from mjlab.tasks.registry import register_mjlab_task
from mjlab.tasks.velocity.config.g1.env_cfgs import unitree_g1_rough_env_cfg
from mjlab.tasks.velocity.config.g1.rl_cfg import unitree_g1_ppo_runner_cfg
from mjlab.tasks.velocity.rl import VelocityOnPolicyRunner
from mjlab.terrains.config import box_random_grid, flat, pyramid_stairs, pyramid_stairs_inv
from mjlab.terrains.terrain_generator import SubTerrainCfg

STAIRS_TASK = "Nova-Velocity-Stairs-Unitree-G1"
STEP_HEIGHT_RANGE_M = (0.05, 0.20)
NARROW_TREAD_M = 0.22
WIDE_TREAD_M = 0.30
# 楼梯中间的平台和四边留的平地（一块地 8 m × 8 m：留 0.5 m、平台 2 m，窄的楼梯一边 11 级）。
PLATFORM_M = 2.0
STAIRS_BORDER_M = 0.5
# 高低不平的地面：40 cm 一格，最难时每格高低 ±8 cm（mjlab 默认到 ±30 cm，是给四条腿的）。
ROUGH_CELL_M = 0.4
ROUGH_HEIGHT_RANGE_M = (0.0, 0.08)
CONVEX_ITERATIONS = 50


def stairs_sub_terrains() -> dict[str, SubTerrainCfg]:
    """几种地形和每种分到的机器人的比例：一大半是楼梯（窄的多），还有平地、高低不平的地面。"""

    def stairs(build, proportion: float, tread_m: float) -> SubTerrainCfg:
        return build(
            proportion=proportion,
            step_height_range=STEP_HEIGHT_RANGE_M,
            step_width=tread_m,
            platform_width=PLATFORM_M,
            border_width=STAIRS_BORDER_M,
        )

    return {
        "flat": flat(proportion=0.1),
        "stairs_up_narrow": stairs(pyramid_stairs, 0.25, NARROW_TREAD_M),
        "stairs_down_narrow": stairs(pyramid_stairs_inv, 0.25, NARROW_TREAD_M),
        "stairs_up_wide": stairs(pyramid_stairs, 0.1, WIDE_TREAD_M),
        "stairs_down_wide": stairs(pyramid_stairs_inv, 0.1, WIDE_TREAD_M),
        "rough": box_random_grid(
            proportion=0.2,
            grid_width=ROUGH_CELL_M,
            grid_height_range=ROUGH_HEIGHT_RANGE_M,
            merge_similar_heights=True,
        ),
    }


def g1_stairs_env_cfg(play: bool = False) -> ManagerBasedRlEnvCfg:
    """mjlab 的 G1 不平地的任务，地形换成 stairs_sub_terrains、凸形状的迭代换成 50 次。
    别的照 mjlab 的，play 时的也一样。"""
    cfg = unitree_g1_rough_env_cfg(play=play)
    terrain = cfg.scene.terrain
    if terrain is None or terrain.terrain_generator is None:
        raise RuntimeError("mjlab 的 G1 不平地的任务里没有地形生成器（mjlab 改了？）")
    terrain.terrain_generator.sub_terrains = stairs_sub_terrains()
    cfg.sim.mujoco.ccd_iterations = CONVEX_ITERATIONS
    return cfg


register_mjlab_task(
    task_id=STAIRS_TASK,
    env_cfg=g1_stairs_env_cfg(),
    play_env_cfg=g1_stairs_env_cfg(play=True),
    rl_cfg=unitree_g1_ppo_runner_cfg(),
    runner_cls=VelocityOnPolicyRunner,
)
