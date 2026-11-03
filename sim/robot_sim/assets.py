"""내려받은 시험용 몸 파일의 위치 (sim/tools/fetch_assets.py)."""

from __future__ import annotations

from pathlib import Path

ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "unitree_g1"
ROBOT_XML = ASSET_DIR / "g1_12dof.xml"
POLICY_FILE = ASSET_DIR / "motion.pt"
POLICY_CONFIG = ASSET_DIR / "g1.yaml"
REQUIRED_FILES = (ROBOT_XML, POLICY_FILE, POLICY_CONFIG)


class AssetsMissingError(RuntimeError):
    pass


def require_assets() -> None:
    missing = [path.name for path in REQUIRED_FILES if not path.exists()]
    if missing:
        raise AssetsMissingError(
            f"시험용 몸 파일이 없습니다: {', '.join(missing)}. "
            "저장소 맨 위에서 python sim/tools/fetch_assets.py 를 먼저 실행하세요."
        )
