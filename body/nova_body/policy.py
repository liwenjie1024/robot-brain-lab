"""练出来的策略（小脑层）：照规约（contracts/policy）读进来，并且核对。

规约、策略的文件（ONNX）、练的时候用的身体模型，有一样对不上就不跑（PolicyError，说清楚哪里不对），不猜。
"""

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import jsonschema
import numpy as np
import onnxruntime

CONTRACTS_DIR = Path(os.environ.get("NOVA_CONTRACTS_DIR", "/contracts"))
POLICY_SCHEMA_PATH = CONTRACTS_DIR / "policy" / "policy.schema.json"
CONTRACT_VERSION = 1
VECTOR_SIZE = 3
# 测试台上一次只跑一个策略：一个线程，结果每次一样。
ONNX_THREADS = 1
# ONNX 一次算一行：输入、输出的形状是 [行, 列] 两维。
ROW_SHAPE_RANK = 2


class PolicyError(ValueError):
    """策略和规约、文件、身体对不上。"""


class ObservationTerm(StrEnum):
    """观测的每一项是什么（意思写在规约里）。"""

    BASE_LIN_VEL = "base_lin_vel"
    BASE_ANG_VEL = "base_ang_vel"
    PROJECTED_GRAVITY = "projected_gravity"
    JOINT_POS = "joint_pos"
    JOINT_VEL = "joint_vel"
    LAST_ACTION = "last_action"
    COMMAND = "command"


VECTOR_TERMS = frozenset(
    {ObservationTerm.BASE_LIN_VEL, ObservationTerm.BASE_ANG_VEL, ObservationTerm.PROJECTED_GRAVITY}
)
JOINT_TERMS = frozenset({ObservationTerm.JOINT_POS, ObservationTerm.JOINT_VEL, ObservationTerm.LAST_ACTION})


@dataclass(frozen=True)
class PolicyJoint:
    """策略管的一个关节。目标 = 默认的姿势 + 动作 x action_scale_rad。"""

    name: str
    default_position_rad: float
    action_scale_rad: float
    stiffness_nm_per_rad: float
    damping_nms_per_rad: float
    torque_limit_nm: float


@dataclass(frozen=True)
class Observation:
    """观测里的一项：是什么、多长、先乘多少。"""

    term: ObservationTerm
    size: int
    scale: float


@dataclass(frozen=True)
class CommandSpec:
    """给策略的命令：有哪几项（顺序），每一项练过的范围。"""

    fields: tuple[str, ...]
    ranges: Mapping[str, tuple[float, float]]

    def vector(self, command: Mapping[str, float]) -> np.ndarray:
        """按 fields 的顺序排好的命令。少了一项、多了一项、超出练过的范围，都拒绝（不剪）。"""
        unknown = sorted(set(command) - set(self.fields))
        if unknown:
            raise PolicyError(f"策略不认得这几项命令：{'、'.join(unknown)}")
        missing = [name for name in self.fields if name not in command]
        if missing:
            raise PolicyError(f"命令少了：{'、'.join(missing)}")
        for name in self.fields:
            low, high = self.ranges[name]
            if not low <= command[name] <= high:
                raise PolicyError(f"命令 {name} = {command[name]:g} 超出了练过的范围 [{low:g}, {high:g}]")
        return np.array([command[name] for name in self.fields], dtype=float)


@dataclass(frozen=True, eq=False)
class Policy:
    """一个核对过的策略。act 给一行观测，回一行动作。"""

    name: str
    contract_path: Path
    body_name: str
    body_model_path: Path
    trained: Mapping[str, Any]
    rate_hz: float
    imu_site: str
    joints: tuple[PolicyJoint, ...]
    observations: tuple[Observation, ...]
    command: CommandSpec
    input_name: str
    output_name: str
    session: onnxruntime.InferenceSession = field(repr=False)

    @property
    def observation_size(self) -> int:
        return sum(observation.size for observation in self.observations)

    @property
    def action_size(self) -> int:
        return len(self.joints)

    def act(self, observation: np.ndarray) -> np.ndarray:
        if observation.shape != (self.observation_size,):
            raise PolicyError(f"观测的长度是 {observation.shape}，策略要 {self.observation_size}")
        feed = {self.input_name: observation.astype(np.float32)[np.newaxis, :]}
        (action,) = self.session.run([self.output_name], feed)
        return np.asarray(action, dtype=float).reshape(self.action_size)


def load_policy(contract_path: Path, schema_path: Path = POLICY_SCHEMA_PATH) -> Policy:
    """读一份策略的规约，核对它和 ONNX、身体模型对得上，再把 ONNX 准备好。"""
    contract = read_contract(contract_path, schema_path)
    directory = contract_path.parent
    onnx_path = directory / contract["onnx"]["file"]
    body_model_path = directory / contract["body"]["model"]
    check_file(onnx_path, contract["onnx"]["sha256"], "策略（ONNX）")
    check_file(body_model_path, contract["body"]["sha256"], "身体的模型")

    joints = tuple(PolicyJoint(**joint) for joint in contract["joints"])
    observations = tuple(
        Observation(ObservationTerm(item["term"]), item["size"], item["scale"]) for item in contract["observations"]
    )
    command = CommandSpec(
        fields=tuple(contract["command"]["fields"]),
        ranges={name: (low, high) for name, (low, high) in contract["command"]["ranges"].items()},
    )
    check_consistency(joints, observations, command)
    session = open_session(onnx_path)
    observation_size = sum(observation.size for observation in observations)
    check_session(session, contract["onnx"]["input"], contract["onnx"]["output"], observation_size, len(joints))
    return Policy(
        name=contract["name"],
        contract_path=contract_path,
        body_name=contract["body"]["name"],
        body_model_path=body_model_path,
        trained=contract["trained"],
        rate_hz=float(contract["rate_hz"]),
        imu_site=contract["imu_site"],
        joints=joints,
        observations=observations,
        command=command,
        input_name=contract["onnx"]["input"],
        output_name=contract["onnx"]["output"],
        session=session,
    )


def read_contract(contract_path: Path, schema_path: Path = POLICY_SCHEMA_PATH) -> dict[str, Any]:
    """读规约，照 JSON Schema 检查。不合格就说出每一处。"""
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"读不了策略的规约 {contract_path}：{error}") from error
    check_contract(contract, schema_path)
    return contract


def check_contract(contract: Any, schema_path: Path = POLICY_SCHEMA_PATH) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    problems = sorted(validator.iter_errors(contract), key=lambda error: list(error.absolute_path))
    if problems:
        lines = [
            f"{'/'.join(str(part) for part in error.absolute_path) or '（整份）'}：{error.message}"
            for error in problems
        ]
        raise PolicyError("策略的规约不合格：\n" + "\n".join(lines))
    if contract["contract_version"] != CONTRACT_VERSION:
        raise PolicyError(f"规约的版本是 {contract['contract_version']}，测试台认的是 {CONTRACT_VERSION}")


def check_file(path: Path, sha256: str, label: str) -> None:
    if not path.is_file():
        raise PolicyError(f"{label}的文件不在：{path}")
    actual = file_sha256(path)
    if actual != sha256:
        raise PolicyError(
            f"{label}的文件和规约里写的不一样（SHA-256 是 {actual[:12]}…，规约里是 {sha256[:12]}…）：{path}"
        )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_consistency(
    joints: tuple[PolicyJoint, ...], observations: tuple[Observation, ...], command: CommandSpec
) -> None:
    """规约自己内部对得上：每一项观测的长度、关节不重名、命令的范围一项不少。"""
    names = [joint.name for joint in joints]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise PolicyError(f"关节重名：{'、'.join(repeated)}")
    terms = [observation.term for observation in observations]
    repeated_terms = sorted({term.value for term in terms if terms.count(term) > 1})
    if repeated_terms:
        raise PolicyError(f"观测里有重复的项：{'、'.join(repeated_terms)}")
    for observation in observations:
        expected = expected_size(observation.term, len(joints), len(command.fields))
        if observation.size != expected:
            raise PolicyError(f"观测 {observation.term.value} 的长度是 {observation.size}，应该是 {expected}")
    if set(command.ranges) != set(command.fields):
        raise PolicyError(
            f"命令的范围（{'、'.join(sorted(command.ranges))}）和命令（{'、'.join(command.fields)}）对不上"
        )
    for name, (low, high) in command.ranges.items():
        if low > high:
            raise PolicyError(f"命令 {name} 的范围反了：[{low:g}, {high:g}]")


def expected_size(term: ObservationTerm, joint_count: int, command_count: int) -> int:
    if term in VECTOR_TERMS:
        return VECTOR_SIZE
    if term in JOINT_TERMS:
        return joint_count
    return command_count


def open_session(onnx_path: Path) -> onnxruntime.InferenceSession:
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = ONNX_THREADS
    options.inter_op_num_threads = ONNX_THREADS
    try:
        return onnxruntime.InferenceSession(str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"])
    except Exception as error:  # onnxruntime 读坏文件时抛的错误种类很多
        raise PolicyError(f"ONNX 打不开：{onnx_path}：{error}") from error


def check_session(
    session: onnxruntime.InferenceSession, input_name: str, output_name: str, observation_size: int, action_size: int
) -> None:
    """ONNX 的输入、输出要和规约一样：名字对，长度对（一次一行）。"""
    inputs = {item.name: item.shape for item in session.get_inputs()}
    outputs = {item.name: item.shape for item in session.get_outputs()}
    if input_name not in inputs:
        raise PolicyError(f"ONNX 没有叫 {input_name} 的输入（有：{'、'.join(inputs)}）")
    if output_name not in outputs:
        raise PolicyError(f"ONNX 没有叫 {output_name} 的输出（有：{'、'.join(outputs)}）")
    if not _fits_one_row(inputs[input_name], observation_size):
        raise PolicyError(f"ONNX 的输入是 {inputs[input_name]}，规约里的观测一行是 {observation_size}")
    if not _fits_one_row(outputs[output_name], action_size):
        raise PolicyError(f"ONNX 的输出是 {outputs[output_name]}，规约里的关节有 {action_size} 个")


def _fits_one_row(shape: list[Any], size: int) -> bool:
    """[1, size]，或者第一维不定（名字或 None）。"""
    if len(shape) != ROW_SHAPE_RANK:
        return False
    rows, columns = shape
    return columns == size and (rows == 1 or not isinstance(rows, int))
