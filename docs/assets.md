# 받아 쓰는 외부 파일

저장소에 넣지 않고 `sim/tools/fetch_assets.py`가 고정한 커밋에서 내려받아 SHA-256으로 확인한다
(`sim/tools/assets.lock.json`, 받은 곳 `sim/assets/unitree_g1/`).

| 파일 | 받은 곳 | 쓰는 곳 |
|---|---|---|
| `g1_12dof.xml` | `resources/robots/g1_description/g1_12dof.xml` | 몸 모델 (다리 12관절, 윗몸 고정) |
| `meshes/*.STL` (27개) | `resources/robots/g1_description/meshes/` | 모델이 쓰는 메시만 (저장소의 64개 중) |
| `motion.pt` | `deploy/pre_train/g1/motion.pt` | 걷기 정책 (TorchScript, LSTM) |
| `g1.yaml` | `deploy/deploy_mujoco/configs/g1.yaml` | 정책의 관측 배율·PD 값·기본 자세 |
| `LICENSE` | `LICENSE` | BSD-3-Clause 사용 조건 |

- 저장소: https://github.com/unitreerobotics/unitree_rl_gym
- 커밋: `276801e46c5d433564f24658bac64f254b7d2d4b` (2025-07-25)
- 사용 조건: BSD-3-Clause. 다시 배포할 때는 저작권 표시와 조건 문구를 함께 둔다 (지금은 배포하지 않고 내려받아 쓴다).

커밋을 바꾸려면 `fetch_assets.py`의 `UPSTREAM_COMMIT`을 고치고 `python sim/tools/fetch_assets.py --update-lock`을 실행한 뒤,
몸의 시험(`docker compose run --rm sim pytest`)으로 걷기·밀기 결과가 그대로인지 확인한다.
