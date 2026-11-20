# 外面来的东西

这里放不是我们自己做的东西：现成的模型文件。基线的身体 Unitree G1，基线的策略 SONIC 和它部署要用的东西。

- **清单**（`<名字>.json`）提交进仓库：从哪来、哪个版本（写死的提交号）、什么许可证、每个文件多大、SHA-256 是多少。
- **文件本身**（`<名字>/` 目录）不提交，按清单下载：

  ```bash
  docker compose run --rm body python -m nova_body.third_party
  ```

  已经有的只核对一遍，不连网；没有的、和清单不一样的才下载。`scripts/check.ps1` 的第一步就是它。
- 每次用之前都核对每个文件的 SHA-256，所以用到的一定是清单上的那一版。
  **不要手改下载下来的文件**：改了一个字就不能用了。删掉那个文件，再运行上面的命令，就会重新下载。

## 现在有什么

| 名字 | 是什么 | 从哪来 | 许可证 |
|---|---|---|---|
| `unitree_g1` | Unitree G1（29 个自由度，没有灵巧手）的 MuJoCo 模型：`g1.xml`、35 个网格、许可证的原文，一共 19.7 MB。基线的身体 | [MuJoCo Menagerie](https://github.com/google-deepmind/mujoco_menagerie) 的 `unitree_g1`，提交 `cda5236f9838`（2026-10-20） | BSD-3-Clause，可以商用 |
| `gear_sonic` | NVIDIA 的 SONIC 默认的那一版：运动规划器、编码器、解码器（ONNX）、观测的设置、训练时的设置、许可证，一共 865 MB。基线的策略之一 | [Hugging Face](https://huggingface.co/nvidia/GEAR-SONIC)，版本 `6733128a3d8a`（2026-08-26） | 权重是 NVIDIA 开放模型许可（能商用，要署名），代码 Apache-2.0 |
| `gr00t_wbc` | SONIC 部署要用的：G1 的 MuJoCo 模型 `g1_29dof.xml` 和 36 个网格、部署的 C++ 源码、G1 的关节顺序和软硬、许可证，一共 19.0 MB（只取这 61 个文件） | [GR00T-WholeBodyControl](https://github.com/NVlabs/GR00T-WholeBodyControl)，提交 `1e1ec4f5f27e`（2026-11-03） | Apache-2.0，可以商用 |

## 加一样新的东西，或者换一个版本

1. 先查许可证，登记进 [AI 模型](../docs/AI模型.md) 第 10 节。
2. 写一份清单 `<名字>.json`，照 `unitree_g1.json` 的样子。`base_url` 要写死在一个提交号上；发布超过两周的版本才用。
3. 每个文件的大小和 SHA-256 要自己算、自己核对。G1 这一份是下载以后，把每个文件的 git 指纹和 GitHub 目录清单里写的对过的；SONIC 的两份是下载时就和 Hugging Face、GitHub 给的指纹（git 的 SHA-1、Git LFS 的 SHA-256）对过的。
   GitHub 上用 Git LFS 存的文件（网格）不在 raw 的地址上：标上 `"lfs": true`，从 `lfs_base_url`（`media.githubusercontent.com`，也写死在提交号上）下。路径里可以有空格，下载时会转义。
4. 运行上面的命令，再运行 `scripts/check.ps1`。
