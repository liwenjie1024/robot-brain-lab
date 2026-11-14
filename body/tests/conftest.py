"""测试共用的东西。"""

import mujoco
import pytest

from nova_body.model import NovaModel, build_nova


@pytest.fixture(scope="session")
def nova() -> NovaModel:
    """核心版的身体。生成一次，所有测试共用；测试不能改它里面的模型。"""
    return build_nova()


@pytest.fixture
def zero_pose(nova: NovaModel) -> mujoco.MjData:
    """零位（站直、手臂垂着）时的仿真状态，位置已经算好。"""
    data = mujoco.MjData(nova.model)
    mujoco.mj_forward(nova.model, data)
    return data
