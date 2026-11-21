"""训练这边小工具的测试：显卡能用、显卡和 CPU 算的一样；训练、播放时只关掉"解的次数用完了"的提醒；
测试用的小策略提交进仓库的和现在做出来的一模一样。"""

from pathlib import Path

import mujoco_warp as mjw
from mjlab.sim.sim import SimulationCfg
from mjlab.tasks.registry import list_tasks

from nova_train.fixtures import PLAIN, SCAN, fixture_files
from nova_train.gpu import check
from nova_train.play import main as play_main
from nova_train.tasks import STAIRS_TASK
from nova_train.train import EXPECTED_OVERFLOWS, apply_wp_opt_quietly

COMMITTED_FIXTURES = Path("/body/tests/fixtures")


def test_the_gpu_is_usable_and_agrees_with_the_cpu():
    """显卡上的 MuJoCo Warp 和 CPU 的 MuJoCo 算一个方块落地，高度一样。"""
    report = check()
    assert report.same_physics
    assert report.mujoco_version == "3.17.0"


def test_training_silences_only_the_expected_overflows():
    """训练时关掉"解的次数用完了"（迭代、线搜索）的提醒，接触、约束放不下的提醒留着。"""
    option = SimpleOption(int(mjw.OverflowType.ALL))
    apply_wp_opt_quietly(SimulationCfg(), option)
    assert option.warn_overflow & EXPECTED_OVERFLOWS == 0
    for kept in (mjw.OverflowType.NEFC, mjw.OverflowType.BROADPHASE, mjw.OverflowType.NARROWPHASE):
        assert option.warn_overflow & int(kept)


def test_the_player_knows_our_tasks():
    """播放器（nova_train.play）认得我们自己的任务（Nova-…），也认得 mjlab 自带的。"""
    assert callable(play_main)
    assert {STAIRS_TASK, "Mjlab-Velocity-Flat-Unitree-G1"} <= set(list_tasks())


class SimpleOption:
    """只有 apply_wp_opt 用到的几项的 Warp 选项。"""

    def __init__(self, warn_overflow: int):
        self.warn_overflow = warn_overflow
        self.contact_sensor_maxmatch = 0
        self.broadphase = None
        self.broadphase_filter = None
        self.graph_conditional = None


def test_the_committed_fixture_policies_are_what_the_generator_makes():
    """body/tests/fixtures 里提交的两个小策略（policy、policy_scan）的三个文件，和现在做出来的一个字节都不差。"""
    for kind in (PLAIN, SCAN):
        for name, content in fixture_files(kind).items():
            assert (COMMITTED_FIXTURES / kind / name).read_bytes() == content, f"{kind}/{name}"
