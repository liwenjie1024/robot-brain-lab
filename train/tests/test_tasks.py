"""我们自己的训练任务的测试（不开仿真，只看设置）：楼梯的任务登记上了；地形换成了我们的（楼梯到 20 cm、踏面 22 cm
和 30 cm、都是方块）；凸形状的迭代是 50 次；策略看得到脚下的高度；别的照 mjlab 的 G1 不平地的任务。"""

import pytest
from mjlab.tasks.registry import list_tasks, load_env_cfg
from mjlab.tasks.velocity.config.g1.env_cfgs import unitree_g1_rough_env_cfg

from nova_train.tasks import (
    CONVEX_ITERATIONS,
    NARROW_TREAD_M,
    STAIRS_TASK,
    STEP_HEIGHT_RANGE_M,
    WIDE_TREAD_M,
    g1_stairs_env_cfg,
)

BOX_TERRAINS = {
    "BoxFlatTerrainCfg",
    "BoxPyramidStairsTerrainCfg",
    "BoxInvertedPyramidStairsTerrainCfg",
    "BoxRandomGridTerrainCfg",
}


def test_the_stairs_task_is_registered():
    assert STAIRS_TASK in list_tasks()


def test_the_stairs_task_climbs_our_stairs_on_box_terrain():
    """地形一大半是楼梯（上的、下的，窄的、宽的），台阶 5~20 cm；都是方块（不用高度场），由易到难。"""
    generator = load_env_cfg(STAIRS_TASK).scene.terrain.terrain_generator
    assert generator.curriculum
    terrains = generator.sub_terrains
    stairs = [terrain for terrain in terrains.values() if hasattr(terrain, "step_width")]
    assert {terrain.step_width for terrain in stairs} == {NARROW_TREAD_M, WIDE_TREAD_M}
    assert all(tuple(terrain.step_height_range) == STEP_HEIGHT_RANGE_M for terrain in stairs)
    assert sum(terrain.proportion for terrain in stairs) > 0.5
    assert {type(terrain).__name__ for terrain in terrains.values()} <= BOX_TERRAINS
    assert sum(terrain.proportion for terrain in terrains.values()) == pytest.approx(1.0)


def test_the_stairs_task_sees_the_ground_and_keeps_mjlabs_other_settings():
    """策略看得到脚下的高度；凸形状的迭代 50 次；奖励、命令、观测和 mjlab 的 G1 不平地的任务一样。"""
    ours, mjlab = g1_stairs_env_cfg(), unitree_g1_rough_env_cfg()
    assert "height_scan" in ours.observations["actor"].terms
    assert ours.sim.mujoco.ccd_iterations == CONVEX_ITERATIONS
    assert ours.rewards.keys() == mjlab.rewards.keys()
    assert ours.commands["twist"].ranges == mjlab.commands["twist"].ranges
    assert list(ours.observations["actor"].terms) == list(mjlab.observations["actor"].terms)


def test_playing_uses_the_same_terrain_without_the_curriculum():
    """看练出来的样子（play）时也是我们的地形，不用由易到难。"""
    generator = g1_stairs_env_cfg(play=True).scene.terrain.terrain_generator
    assert not generator.curriculum
    assert generator.sub_terrains.keys() == g1_stairs_env_cfg().scene.terrain.terrain_generator.sub_terrains.keys()
