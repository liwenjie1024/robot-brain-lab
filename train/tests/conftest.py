"""训练这边的测试共用的东西：一个 G1 按指令走的训练环境（显卡上，1 个世界）。"""

import pytest
from mjlab.envs import ManagerBasedRlEnv
from mjlab.tasks.registry import load_env_cfg

TASK = "Mjlab-Velocity-Flat-Unitree-G1"


@pytest.fixture(scope="session")
def g1_env():
    """mjlab 自带的"G1 按指令走"，练的时候的设置，只开 1 个世界。所有测试共用，测试不能改它。"""
    import mjlab.tasks  # noqa: F401, PLC0415 - 登记 mjlab 的任务

    cfg = load_env_cfg(TASK)
    cfg.scene.num_envs = 1
    env = ManagerBasedRlEnv(cfg=cfg, device="cuda:0")
    yield env
    env.close()
