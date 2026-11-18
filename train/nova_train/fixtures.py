"""做测试用的小策略：一个两条腿的小身体、一个 ONNX、一份规约。身体的测试（body/tests）用它们。

ONNX 的输出就是从观测里挑出来的两个数（重力方向的 x、命令的转弯），这样测试能核对观测的每一项放在哪。
身体的容器里没有做 ONNX 的库，所以在这里做好、提交进仓库；训练这边的测试核对提交的和现在做出来的一样。
用法：docker compose run --rm -v ./body/tests/fixtures:/fixtures train python -m nova_train.fixtures /fixtures/policy
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

CONTRACT_NAME = "contract.json"
ONNX_NAME = "policy.onnx"
BODY_NAME = "body.xml"
OPSET = 18
IR_VERSION = 9

BODY_XML = """<mujoco model="fixture">
  <option timestep="0.005"/>
  <worldbody>
    <body name="pelvis" pos="0 0 0.4">
      <freejoint name="root"/>
      <geom name="pelvis" type="box" size="0.1 0.1 0.05" mass="2"/>
      <site name="imu" pos="0.05 0 0"/>
      <body name="leg_a" pos="0 0.06 -0.05">
        <joint name="joint_a" axis="0 1 0" range="-1 1"/>
        <geom name="leg_a" type="capsule" fromto="0 0 0 0 0 -0.3" size="0.02" mass="0.5"/>
      </body>
      <body name="leg_b" pos="0 -0.06 -0.05">
        <joint name="joint_b" axis="0 1 0" range="-1 1"/>
        <geom name="leg_b" type="capsule" fromto="0 0 0 0 0 -0.3" size="0.02" mass="0.5"/>
      </body>
    </body>
  </worldbody>
  <actuator>
    <position name="joint_a" joint="joint_a" kp="10"/>
    <position name="joint_b" joint="joint_b" kp="10"/>
  </actuator>
</mujoco>
"""

JOINTS = [
    {
        "name": "joint_a",
        "default_position_rad": 0.1,
        "action_scale_rad": 0.5,
        "stiffness_nm_per_rad": 20.0,
        "damping_nms_per_rad": 1.0,
        "torque_limit_nm": 5.0,
    },
    {
        "name": "joint_b",
        "default_position_rad": -0.2,
        "action_scale_rad": 0.25,
        "stiffness_nm_per_rad": 30.0,
        "damping_nms_per_rad": 2.0,
        "torque_limit_nm": 8.0,
    },
]
OBSERVATIONS = [
    {"term": "base_lin_vel", "size": 3, "scale": 1.0},
    {"term": "base_ang_vel", "size": 3, "scale": 1.0},
    {"term": "projected_gravity", "size": 3, "scale": 1.0},
    {"term": "joint_pos", "size": 2, "scale": 1.0},
    {"term": "joint_vel", "size": 2, "scale": 1.0},
    {"term": "last_action", "size": 2, "scale": 1.0},
    {"term": "command", "size": 3, "scale": 1.0},
]
OBSERVATION_SIZE = sum(item["size"] for item in OBSERVATIONS)
# 动作 0 = 重力方向的 x（观测的第 6 个），动作 1 = 命令的转弯（最后一个）。
GRAVITY_X_INDEX = 6
TURN_COMMAND_INDEX = OBSERVATION_SIZE - 1


def selection_onnx() -> bytes:
    weight = np.zeros((OBSERVATION_SIZE, len(JOINTS)), dtype=np.float32)
    weight[GRAVITY_X_INDEX, 0] = 1.0
    weight[TURN_COMMAND_INDEX, 1] = 1.0
    graph = helper.make_graph(
        [helper.make_node("MatMul", ["obs", "weight"], ["actions"])],
        "fixture_policy",
        [helper.make_tensor_value_info("obs", TensorProto.FLOAT, [1, OBSERVATION_SIZE])],
        [helper.make_tensor_value_info("actions", TensorProto.FLOAT, [1, len(JOINTS)])],
        initializer=[numpy_helper.from_array(weight, name="weight")],
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", OPSET)], producer_name="nova_train.fixtures"
    )
    model.ir_version = IR_VERSION
    onnx.checker.check_model(model)
    return model.SerializeToString()


def contract(onnx_bytes: bytes, body_bytes: bytes) -> dict:
    return {
        "contract_version": 1,
        "name": "fixture",
        "body": {"name": "fixture", "model": BODY_NAME, "sha256": hashlib.sha256(body_bytes).hexdigest()},
        "trained": {
            "tool": "nova_train.fixtures",
            "version": "1",
            "source": "train/nova_train/fixtures.py",
            "task": "测试用：从观测里挑出两个数",
            "iterations": 0,
            "date": "2026-11-18",
        },
        "onnx": {
            "file": ONNX_NAME,
            "sha256": hashlib.sha256(onnx_bytes).hexdigest(),
            "input": "obs",
            "output": "actions",
        },
        "rate_hz": 50.0,
        "imu_site": "imu",
        "joints": JOINTS,
        "observations": OBSERVATIONS,
        "command": {
            "fields": ["lin_vel_x", "lin_vel_y", "ang_vel_z"],
            "ranges": {"lin_vel_x": [-1.0, 1.0], "lin_vel_y": [-1.0, 1.0], "ang_vel_z": [-0.5, 0.5]},
        },
    }


def fixture_files() -> dict[str, bytes]:
    """文件名 → 内容。每次做出来都一样。"""
    onnx_bytes = selection_onnx()
    body_bytes = BODY_XML.encode("utf-8")
    contract_bytes = (json.dumps(contract(onnx_bytes, body_bytes), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return {ONNX_NAME: onnx_bytes, BODY_NAME: body_bytes, CONTRACT_NAME: contract_bytes}


def write_fixtures(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in fixture_files().items():
        (directory / name).write_bytes(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("directory", type=Path)
    write_fixtures(parser.parse_args().directory)


if __name__ == "__main__":
    main()
