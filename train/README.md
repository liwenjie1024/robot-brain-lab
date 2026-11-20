# 训练（nova-train 容器）

在显卡上做强化学习：mjlab（MuJoCo Warp 上的训练框架）、PyTorch、PPO（rsl-rl）。
练出来的策略交给身体的测试台去考，**只认测试台的分数**，训练里的分数不算。

- 版本都写死在 `uv.lock` 里（每个文件都有 SHA-256），只用发布超过两周的版本；MuJoCo 和身体用同一个（3.17.0）。
  mjlab 用 2026-11-01 的那一版（1.6.0，还在用 MuJoCo 3.x 的最后一版）。用到的东西和许可证见 [技术栈](../docs/技术栈.md)、
  [AI 模型](../docs/AI模型.md) 第 10 节。
- 训练的记录、存档、练出来的策略都写进 `results/`（不提交）。
- 在 Git Bash 里运行下面的命令，前面要加 `MSYS_NO_PATHCONV=1`，不然它会把 `/results/...` 这样的路径改成 Windows 的路径。
  在 PowerShell 里不用加。

## 常用的命令

```powershell
docker compose build train                                    # 做镜像（第一次要下载约 4 GB）
docker compose run --rm train                                 # 看显卡能不能用（显卡和 CPU 算的一样不一样）
docker compose run --rm train pytest                          # 训练这边的测试（要显卡）

# 练 G1 按指令走（mjlab 自带的任务）：4096 个仿真一起跑，2000 轮约 50 分钟
docker compose run --rm train python -m nova_train.train Mjlab-Velocity-Flat-Unitree-G1 `
    --env.scene.num-envs 4096 --agent.max-iterations 2000 --agent.logger tensorboard `
    --agent.upload-model False --log-root /results/train --agent.run-name g1-flat

# 练 G1 上下楼梯（我们自己的任务，2.2 步）：要练 6~7 个小时，容器自己在后台跑，会话结束了也接着练
docker compose run -d --name nova-train-g1-stairs train python -m nova_train.train Nova-Velocity-Stairs-Unitree-G1 `
    --env.scene.num-envs 4096 --agent.max-iterations 6000 --agent.logger tensorboard `
    --agent.upload-model False --log-root /results/train --agent.run-name g1-stairs
docker logs -f nova-train-g1-stairs                          # 看练到哪了；练完 docker rm nova-train-g1-stairs

# 交给测试台：ONNX、练的时候的身体模型、规约（contract.json）写进 /results/policies/<名字>
docker compose run --rm train python -m nova_train.export_policy Mjlab-Velocity-Flat-Unitree-G1 `
    /results/train/g1_velocity/<那一次训练> --name g1-velocity-flat --body unitree_g1

# 在测试台上（CPU 的 MuJoCo）考：照命令表走一遍，结果写在规约旁边的 walk.json
docker compose run --rm body python -m nova_body.policy_walk /results/policies/g1-velocity-flat/contract.json

docker compose run --rm train python -m nova_train.nova_warp  # Nova 的模型在显卡上的仿真：多快、多少显存
docker compose run --rm train-lock                            # 改了 pyproject.toml 以后重新锁版本
# 重新做身体那边测试用的小策略（改了 nova_train/fixtures.py 以后），做完一起提交
docker compose run --rm -v ./body/tests/fixtures:/fixtures train python -m nova_train.fixtures /fixtures
```

## 里面有什么

| 文件 | 做什么 |
|---|---|
| `nova_train/gpu.py` | 看显卡能不能用：PyTorch、Warp、MuJoCo Warp 都认得它，显卡和 CPU 算一个方块落地一样 |
| `nova_train/train.py` | 就是 mjlab 的 train，只关掉"解的次数用完了"的提醒（MuJoCo Warp 3.17 每一步都打印，拖慢显卡） |
| `nova_train/contract.py` | 从训练环境写策略的规约（`contracts/policy`）。规约表达不了的（历史、剪裁、延迟……）导出时就拒绝 |
| `nova_train/export_policy.py` | 从存档导出 ONNX、身体模型、规约；导出以后比一比 ONNX 和 PyTorch 的动作，一样才交 |
| `nova_train/nova_warp.py` | Nova 的模型在 MuJoCo Warp 里：站不站得住、每秒多少步、占多少显存 |
| `nova_train/fixtures.py` | 做身体那边测试用的小策略（`body/tests/fixtures/policy`，还有看脚下高度的 `policy_scan`） |
| `nova_train/tasks.py` | 我们自己的训练任务（名字以 Nova- 开头）：G1 练上下楼梯（台阶到 20 cm，都是方块的地形） |
