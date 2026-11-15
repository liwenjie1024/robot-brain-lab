"""测试共用的东西。"""

import mujoco
import pytest

from nova_body.baseline import load_g1
from nova_body.body import Body
from nova_body.model import NovaModel, build_nova


@pytest.fixture(scope="session")
def nova() -> NovaModel:
    """核心版的身体。生成一次，所有测试共用；测试不能改它里面的模型。"""
    return build_nova()


@pytest.fixture(scope="session")
def g1() -> Body:
    """基线的身体（Unitree G1），已经放上测试台。读一次，所有测试共用；测试不能改它里面的模型。"""
    return load_g1()


@pytest.fixture(scope="session", params=["nova", "g1"], ids=["Nova", "G1"])
def body(request: pytest.FixtureRequest) -> Body:
    """测试台上的每个身体。用到它的测试，Nova 和基线各跑一遍：这就是"同一套测试"。"""
    if request.param == "nova":
        return request.getfixturevalue("nova").body
    return request.getfixturevalue("g1")


@pytest.fixture
def zero_pose(nova: NovaModel) -> mujoco.MjData:
    """零位（站直、手臂垂着）时的仿真状态，位置已经算好。"""
    data = mujoco.MjData(nova.model)
    mujoco.mj_forward(nova.model, data)
    return data
