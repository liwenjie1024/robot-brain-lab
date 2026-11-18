"""从 mjlab 的训练环境写出策略的规约（contracts/policy）：测试台照它把策略接到身体上。

只认得规约里有的那几种观测。别的（观测的历史、剪裁、延迟、每一维不同的缩放）这一版还不支持：
导出的时候就拒绝（ExportError），不留到测试台上去猜。
"""

import datetime
import importlib.metadata
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import mujoco
from mjlab.entity import Entity
from mjlab.envs import ManagerBasedRlEnv
from mjlab.envs.mdp.actions import JointPositionAction
from mjlab.utils.spec import export_spec

MJLAB_SOURCE = "https://github.com/mujocolab/mjlab/tree/dcdf6ce519abfd2ea45e9503ae6fb650b75bb869"
CONTRACT_VERSION = 1
ENTITY = "robot"
ACTION_TERM = "joint_pos"
ACTOR_GROUP = "actor"
COMMAND_TERM = "twist"
COMMAND_CURRICULUM = "command_vel"
COMMAND_FIELDS = ("lin_vel_x", "lin_vel_y", "ang_vel_z")
BODY_XML = "scene.xml"

# mjlab 的观测项 → 规约里的项，加上 mjlab 算它的函数（名字一样、算法不一样的不认）。
OBSERVATION_TERMS: Mapping[str, tuple[str, str]] = {
    "base_lin_vel": ("base_lin_vel", "builtin_sensor"),
    "base_ang_vel": ("base_ang_vel", "builtin_sensor"),
    "projected_gravity": ("projected_gravity", "projected_gravity"),
    "joint_pos": ("joint_pos", "joint_pos_rel"),
    "joint_vel": ("joint_vel", "joint_vel_rel"),
    "actions": ("last_action", "last_action"),
    "command": ("command", "generated_commands"),
}
IMU_SENSOR_TYPES: Mapping[str, int] = {
    "base_lin_vel": mujoco.mjtSensor.mjSENS_VELOCIMETER,
    "base_ang_vel": mujoco.mjtSensor.mjSENS_GYRO,
}


class ExportError(RuntimeError):
    """训练环境里有规约表达不了的东西。"""


def build_contract(
    env: ManagerBasedRlEnv,
    *,
    name: str,
    body: str,
    task: str,
    iterations: int,
    common_step_counter: int,
    onnx: Mapping[str, str],
    body_model: Mapping[str, str],
    today: datetime.date | None = None,
) -> dict[str, Any]:
    """一份规约（还没写进文件）。body 是身体的名字；onnx、body_model 是已经写好的文件：相对路径、SHA-256，
    ONNX 还有输入输出的名字。"""
    joints = joints_section(env)
    observations, imu_site = observations_section(env, [joint["name"] for joint in joints])
    return {
        "contract_version": CONTRACT_VERSION,
        "name": name,
        "body": {"name": body, **body_model},
        "trained": {
            "tool": "mjlab",
            "version": importlib.metadata.version("mjlab"),
            "source": MJLAB_SOURCE,
            "task": task,
            "iterations": iterations,
            "date": (today or datetime.date.today()).isoformat(),
        },
        "onnx": dict(onnx),
        "rate_hz": 1.0 / env.step_dt,
        "imu_site": imu_site,
        "joints": joints,
        "observations": observations,
        "command": command_section(env, common_step_counter),
    }


def joints_section(env: ManagerBasedRlEnv) -> list[dict[str, Any]]:
    """动作的顺序就是关节的顺序：每个关节的默认姿势、动作的比例、驱动器的软硬和力矩的上限。"""
    action = env.action_manager.get_term(ACTION_TERM)
    if not isinstance(action, JointPositionAction):
        raise ExportError(f"动作 {ACTION_TERM} 不是关节位置的动作")
    if list(env.action_manager.active_terms) != [ACTION_TERM]:
        raise ExportError(f"动作只能有 {ACTION_TERM} 一项，现在是 {env.action_manager.active_terms}")
    robot = env.scene[ENTITY]
    defaults = robot.data.default_joint_pos[0].cpu().tolist()
    scales = _per_target(action.scale, action.action_dim)
    model = env.sim.mj_model
    joints = []
    for index, (joint_id, joint_name) in enumerate(zip(action.target_ids.tolist(), action.target_names, strict=True)):
        actuator = _position_actuator(model, f"{ENTITY}/{joint_name}")
        joints.append(
            {
                "name": joint_name,
                "default_position_rad": float(defaults[joint_id]),
                "action_scale_rad": scales[index],
                "stiffness_nm_per_rad": float(model.actuator_gainprm[actuator, 0]),
                "damping_nms_per_rad": float(-model.actuator_biasprm[actuator, 2]),
                "torque_limit_nm": float(model.actuator_forcerange[actuator, 1]),
            }
        )
    return joints


def _per_target(scale: Any, count: int) -> list[float]:
    if isinstance(scale, int | float):
        return [float(scale)] * count
    values = scale[0].cpu().tolist()
    if len(values) != count:
        raise ExportError(f"动作的比例有 {len(values)} 个，动作有 {count} 个")
    return [float(value) for value in values]


def _position_actuator(model: mujoco.MjModel, joint: str) -> int:
    """只带着这一个关节的位置驱动器（力矩 = 刚度 x (目标 - 角度) - 阻尼 x 转速，有上限）。"""
    joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
    found = [
        actuator
        for actuator in range(model.nu)
        if model.actuator_trntype[actuator] == mujoco.mjtTrn.mjTRN_JOINT
        and model.actuator_trnid[actuator, 0] == joint_id
    ]
    if len(found) != 1:
        raise ExportError(f"关节 {joint} 要正好一个驱动器，现在有 {len(found)} 个")
    actuator = found[0]
    stiffness = model.actuator_gainprm[actuator, 0]
    is_position = (
        model.actuator_gaintype[actuator] == mujoco.mjtGain.mjGAIN_FIXED
        and model.actuator_biastype[actuator] == mujoco.mjtBias.mjBIAS_AFFINE
        and math.isclose(model.actuator_biasprm[actuator, 1], -stiffness)
        and model.actuator_gear[actuator, 0] == 1.0
    )
    if not is_position:
        raise ExportError(f"关节 {joint} 的驱动器不是位置控制的")
    if not model.actuator_forcelimited[actuator]:
        raise ExportError(f"关节 {joint} 的驱动器没有力矩的上限")
    low, high = model.actuator_forcerange[actuator]
    if not math.isclose(low, -high):
        raise ExportError(f"关节 {joint} 的力矩上限两边不一样：[{low:g}, {high:g}]")
    return actuator


def observations_section(env: ManagerBasedRlEnv, joint_names: Sequence[str]) -> tuple[list[dict[str, Any]], str]:
    """策略看的观测（actor 那一组），按顺序；还有量身体速度的 IMU 在哪个点。"""
    manager = env.observation_manager
    names = manager.active_terms[ACTOR_GROUP]
    sizes = manager.group_obs_term_dim[ACTOR_GROUP]
    robot = env.scene[ENTITY]
    if list(robot.joint_names) != list(joint_names):
        raise ExportError("观测里关节的顺序和动作的不一样")
    observations, imu_sites = [], set()
    for term_name, size in zip(names, sizes, strict=True):
        cfg = manager.get_term_cfg(ACTOR_GROUP, term_name)
        term = _contract_term(term_name, cfg)
        if term_name in IMU_SENSOR_TYPES:
            imu_sites.add(_imu_site(env.sim.mj_model, cfg.params["sensor_name"], IMU_SENSOR_TYPES[term_name]))
        observations.append({"term": term, "size": math.prod(size), "scale": _scalar_scale(term_name, cfg.scale)})
    if len(imu_sites) != 1:
        raise ExportError(f"速度和角速度要是同一个 IMU 量的，现在是：{sorted(imu_sites)}")
    return observations, imu_sites.pop()


def _contract_term(term_name: str, cfg: Any) -> str:
    if term_name not in OBSERVATION_TERMS:
        raise ExportError(f"规约里没有观测 {term_name}")
    term, function = OBSERVATION_TERMS[term_name]
    if cfg.func.__name__ != function:
        raise ExportError(f"观测 {term_name} 是 {cfg.func.__name__} 算的，规约里的是 {function}")
    unsupported = {
        "历史": cfg.history_length > 0,
        "剪裁": cfg.clip is not None,
        "延迟": cfg.delay_max_lag > 0,
    }
    for label, present in unsupported.items():
        if present:
            raise ExportError(f"观测 {term_name} 有{label}，这一版的规约还不支持")
    if term_name == "actions" and cfg.params.get("action_name") is not None:
        raise ExportError("last_action 要是整个动作")
    if term_name == "command" and cfg.params.get("command_name") != COMMAND_TERM:
        raise ExportError(f"命令要是 {COMMAND_TERM}")
    return term


def _scalar_scale(term_name: str, scale: Any) -> float:
    if scale is None:
        return 1.0
    if isinstance(scale, int | float):
        return float(scale)
    raise ExportError(f"观测 {term_name} 每一维的缩放不一样，这一版的规约还不支持")


def _imu_site(model: mujoco.MjModel, sensor_name: str, sensor_type: int) -> str:
    sensor = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SENSOR, sensor_name)
    if sensor < 0 or model.sensor_type[sensor] != sensor_type:
        raise ExportError(f"传感器 {sensor_name} 不是想的那一种")
    if model.sensor_objtype[sensor] != mujoco.mjtObj.mjOBJ_SITE:
        raise ExportError(f"传感器 {sensor_name} 不是装在一个点（site）上的")
    site = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_SITE, int(model.sensor_objid[sensor]))
    return site.removeprefix(f"{ENTITY}/")


def command_section(env: ManagerBasedRlEnv, common_step_counter: int) -> dict[str, Any]:
    """命令的范围：练到这一轮时课程（curriculum）放宽到了哪一步。"""
    ranges = env.command_manager.get_term(COMMAND_TERM).cfg.ranges
    current = {field: tuple(getattr(ranges, field)) for field in COMMAND_FIELDS}
    curriculum = env.cfg.curriculum.get(COMMAND_CURRICULUM) if env.cfg.curriculum else None
    if curriculum is not None:
        for stage in curriculum.params["velocity_stages"]:
            if common_step_counter >= stage["step"]:
                current.update({field: tuple(stage[field]) for field in COMMAND_FIELDS if stage.get(field) is not None})
    return {
        "fields": list(COMMAND_FIELDS),
        "ranges": {field: [float(low), float(high)] for field, (low, high) in current.items()},
    }


def export_body(env: ManagerBasedRlEnv, directory: Path) -> Path:
    """练的时候用的身体（mjlab 改过驱动器、碰撞以后的样子），写成 MJCF 和网格。directory 要是新的、空的。

    按训练的设置另建一份身体再写：已经接进训练场景的那一份，MuJoCo 3.17 里再复制会崩（段错误）。
    开始时随机改的（脚的摩擦、重心……）不在里面：写的是没改过的身体。
    """
    if directory.exists() and any(directory.iterdir()):
        raise ExportError(f"{directory} 已经有东西了，不往里面写")
    source = Entity(env.cfg.scene.entities[ENTITY]).spec
    spec = source.copy()
    model_dir = Path(source.modelfiledir)
    for mesh in source.meshes:
        path = model_dir / mesh.compiler.meshdir / mesh.file
        if mesh.file and mesh.file not in spec.assets and path.is_file():
            spec.assets[mesh.file] = path.read_bytes()
    export_spec(spec, directory)
    return directory / BODY_XML
