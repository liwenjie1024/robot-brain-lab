"""把练好的策略交给测试台：ONNX、练的时候用的身体模型、规约（contract.json），放进一个新的目录。

用法：docker compose run --rm train python -m nova_train.export_policy Mjlab-Velocity-Flat-Unitree-G1 \
        /results/train/g1_velocity/<那一次训练> --name g1-velocity-flat --body unitree_g1
默认用那一次训练里最后的存档（model_<轮数>.pt），写到 /results/policies/<名字>。
导出以后在同一批观测上比一比 ONNX 和 PyTorch 的动作，差得多就不交（策略在导出时变了样）。
"""

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path

import numpy as np
import onnx
import torch
from mjlab.envs import ManagerBasedRlEnv
from mjlab.rl import MjlabOnPolicyRunner, RslRlVecEnvWrapper
from mjlab.tasks.registry import load_env_cfg, load_rl_cfg, load_runner_cls
from nova_body.policy import file_sha256, load_policy

from nova_train.contract import ExportError, build_contract, export_body

POLICIES_DIR = Path("/results/policies")
CONTRACT_NAME = "contract.json"
ONNX_NAME = "policy.onnx"
BODY_DIR = "body"
CHECKPOINT_PATTERN = re.compile(r"^model_(\d+)\.pt$")
DEVICE = "cuda:0"
# 比一比 ONNX 和 PyTorch：跑这么多步，每一步的动作差在这以内（float32 的误差）。
COMPARE_STEPS = 50
ACTION_TOLERANCE = 1e-4


def latest_checkpoint(run_dir: Path) -> tuple[Path, int]:
    found = [
        (int(match.group(1)), path) for path in run_dir.iterdir() if (match := CHECKPOINT_PATTERN.match(path.name))
    ]
    if not found:
        raise ExportError(f"{run_dir} 里没有存档（model_<轮数>.pt）")
    iteration, path = max(found)
    return path, iteration


def export(task: str, run_dir: Path, *, name: str, body: str, out_dir: Path, checkpoint: Path | None = None) -> Path:
    target = out_dir / name
    if target.exists():
        raise ExportError(f"{target} 已经有了：换个名字，或者先把它删掉")
    checkpoint_path, iteration = (checkpoint, _iteration_of(checkpoint)) if checkpoint else latest_checkpoint(run_dir)

    env_cfg = load_env_cfg(task, play=True)
    env_cfg.scene.num_envs = 1
    env = ManagerBasedRlEnv(cfg=env_cfg, device=DEVICE)
    agent_cfg = load_rl_cfg(task)
    agent_cfg.logger = "tensorboard"
    agent_cfg.upload_model = False
    wrapped = RslRlVecEnvWrapper(env, clip_actions=agent_cfg.clip_actions)
    runner_cls = load_runner_cls(task) or MjlabOnPolicyRunner
    runner = runner_cls(wrapped, asdict(agent_cfg), log_dir=None, device=DEVICE)
    infos = runner.load(str(checkpoint_path), map_location=DEVICE)
    common_step_counter = int((infos or {}).get("env_state", {}).get("common_step_counter", 0))

    target.mkdir(parents=True)
    runner.export_policy_to_onnx(str(target), ONNX_NAME)
    onnx_path = target / ONNX_NAME
    input_name, output_name = _onnx_io(onnx_path)
    compare_onnx_with_torch(runner, wrapped, onnx_path, input_name)
    body_xml = export_body(env, target / BODY_DIR)
    contract = build_contract(
        env,
        name=name,
        body=body,
        task=task,
        iterations=iteration,
        common_step_counter=common_step_counter,
        onnx={"file": ONNX_NAME, "sha256": file_sha256(onnx_path), "input": input_name, "output": output_name},
        body_model={"model": str(body_xml.relative_to(target)), "sha256": file_sha256(body_xml)},
    )
    contract_path = target / CONTRACT_NAME
    contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    load_policy(contract_path)
    env.close()
    return contract_path


def _iteration_of(checkpoint: Path) -> int:
    match = CHECKPOINT_PATTERN.match(checkpoint.name)
    if match is None:
        raise ExportError(f"存档的名字要是 model_<轮数>.pt：{checkpoint}")
    return int(match.group(1))


def _onnx_io(onnx_path: Path) -> tuple[str, str]:
    graph = onnx.load(str(onnx_path)).graph
    if len(graph.input) != 1 or len(graph.output) != 1:
        raise ExportError(f"ONNX 要正好一个输入、一个输出：{onnx_path}")
    return graph.input[0].name, graph.output[0].name


def compare_onnx_with_torch(
    runner: MjlabOnPolicyRunner, env: RslRlVecEnvWrapper, onnx_path: Path, input_name: str
) -> None:
    """让 PyTorch 的策略在环境里走几步，每一步也让 ONNX 算一遍同一行观测，动作要一样。"""
    import onnxruntime  # noqa: PLC0415 - 只在比较的时候用

    session = onnxruntime.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    policy = runner.get_inference_policy(device=DEVICE)
    observations = env.get_observations()
    worst = 0.0
    with torch.inference_mode():
        for _ in range(COMPARE_STEPS):
            actions = policy(observations)
            actor = observations["actor"].cpu().numpy().astype(np.float32)
            (onnx_actions,) = session.run(None, {input_name: actor})
            worst = max(worst, float(np.abs(onnx_actions - actions.cpu().numpy()).max()))
            observations, _, _, _ = env.step(actions)
    if worst > ACTION_TOLERANCE:
        raise ExportError(f"ONNX 和 PyTorch 算的动作差了 {worst:.2e}（要在 {ACTION_TOLERANCE:g} 以内）")
    print(f"ONNX 和 PyTorch 算的动作一样（{COMPARE_STEPS} 步里最多差 {worst:.1e}）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task", help="mjlab 的任务，比如 Mjlab-Velocity-Flat-Unitree-G1")
    parser.add_argument("run_dir", type=Path, help="那一次训练的目录（里面有 model_<轮数>.pt）")
    parser.add_argument("--name", required=True, help="策略的名字（小写字母、数字、-）")
    parser.add_argument("--body", required=True, help="身体的名字，比如 unitree_g1")
    parser.add_argument("--out", type=Path, default=POLICIES_DIR, help="放到哪个目录下")
    parser.add_argument("--checkpoint", type=Path, help="用哪个存档（默认最后一个）")
    arguments = parser.parse_args()
    contract = export(
        arguments.task,
        arguments.run_dir,
        name=arguments.name,
        body=arguments.body,
        out_dir=arguments.out,
        checkpoint=arguments.checkpoint,
    )
    print(f"交给测试台了：{contract}")


if __name__ == "__main__":
    main()
