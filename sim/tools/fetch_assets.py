"""시험용 몸(Unitree G1)의 모델·메시·걷기 정책을 고정한 커밋에서 내려받고 SHA-256으로 확인한다.

큰 바이너리(메시 약 30MB, 정책)를 저장소에 넣지 않으려고 내려받는다. 내용이 바뀌지 않았는지는
assets.lock.json의 해시로 확인한다 (커밋을 바꿀 때만 --update-lock으로 다시 만든다).

    python tools/fetch_assets.py              # 없거나 다른 파일만 내려받고 모두 확인
    python tools/fetch_assets.py --update-lock

표준 라이브러리만 쓴다 (가상 환경을 만들기 전에도 돌릴 수 있게).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

UPSTREAM = "unitreerobotics/unitree_rl_gym"
# 2025-07-25 main. 바꾸면 --update-lock으로 해시를 다시 만들고 docs/assets.md를 고친다.
UPSTREAM_COMMIT = "276801e46c5d433564f24658bac64f254b7d2d4b"
RAW_BASE = f"https://raw.githubusercontent.com/{UPSTREAM}/{UPSTREAM_COMMIT}/"

ROBOT_XML = "resources/robots/g1_description/g1_12dof.xml"
MESH_DIR = "resources/robots/g1_description/meshes/"
# 받아 둘 곳의 이름 (upstream 경로 → 로컬 경로)
FIXED_FILES = {
    ROBOT_XML: "g1_12dof.xml",
    "deploy/pre_train/g1/motion.pt": "motion.pt",
    "deploy/deploy_mujoco/configs/g1.yaml": "g1.yaml",
    "LICENSE": "LICENSE",
}

SIM_DIR = Path(__file__).resolve().parent.parent
ASSET_DIR = SIM_DIR / "assets" / "unitree_g1"
LOCK_FILE = Path(__file__).resolve().parent / "assets.lock.json"
DOWNLOAD_TIMEOUT_SECONDS = 60


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(upstream_path: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(RAW_BASE + upstream_path, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        target.write_bytes(response.read())


def mesh_files(robot_xml: Path) -> dict[str, str]:
    """로봇 모델이 쓰는 메시 파일만 고른다 (저장소의 메시 64개 중 일부)."""
    root = ET.parse(robot_xml).getroot()
    files = sorted({mesh.attrib["file"] for mesh in root.iter("mesh")})
    return {MESH_DIR + name: "meshes/" + name for name in files}


def fetch(update_lock: bool) -> int:
    lock: dict[str, str] = {} if update_lock or not LOCK_FILE.exists() else json.loads(LOCK_FILE.read_text("utf-8"))
    robot_xml = ASSET_DIR / FIXED_FILES[ROBOT_XML]
    if not robot_xml.exists() or (lock and sha256_of(robot_xml) != lock.get(FIXED_FILES[ROBOT_XML])):
        download(ROBOT_XML, robot_xml)
    files = {**FIXED_FILES, **mesh_files(robot_xml)}

    mismatched = []
    for upstream_path, local_name in files.items():
        target = ASSET_DIR / local_name
        expected = lock.get(local_name)
        if not target.exists() or (expected and sha256_of(target) != expected):
            print(f"내려받기: {local_name}")
            download(upstream_path, target)
        actual = sha256_of(target)
        if update_lock:
            lock[local_name] = actual
        elif expected != actual:
            mismatched.append(local_name)

    if update_lock:
        LOCK_FILE.write_text(json.dumps(dict(sorted(lock.items())), indent=2) + "\n", "utf-8")
        print(f"해시 {len(lock)}개를 {LOCK_FILE.name}에 남겼습니다.")
        return 0
    if mismatched:
        print("해시가 맞지 않는 파일 (받은 내용이 고정한 것과 다릅니다):", *mismatched, sep="\n  ", file=sys.stderr)
        return 1
    print(f"시험용 몸 파일 {len(files)}개를 확인했습니다 ({ASSET_DIR}).")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update-lock", action="store_true", help="받은 파일로 해시 목록을 다시 만든다")
    sys.exit(fetch(parser.parse_args().update_lock))
