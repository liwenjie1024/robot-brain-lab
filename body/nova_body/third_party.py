"""外面来的东西：现成的模型文件（基线的身体 Unitree G1、基线的策略 SONIC）。按清单下载，每个文件都核对。

清单（third_party/<名字>.json）是提交进仓库的：从哪来、哪个版本、什么许可证、每个文件多大、SHA-256 是多少。
GitHub 上用 Git LFS 存的文件（网格、权重）不在 raw 的地址上，标上 "lfs": true，从 lfs_base_url 下。
文件本身不提交，下载到 third_party/<名字>/ 里。用之前每次都核对，所以用到的一定是清单上的那一版。

用法：python -m nova_body.third_party [--dir 目录]
已经有的文件核对一遍；没有的、不对的重新下载。
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

THIRD_PARTY_DIR = Path("/third_party")
MANIFEST_SUFFIX = ".json"
PARTIAL_SUFFIX = ".part"
FETCH_COMMAND = "docker compose run --rm body python -m nova_body.third_party"
USER_AGENT = "nova-body-third-party"
DOWNLOAD_TIMEOUT_S = 120.0
BYTES_PER_MB = 1.0e6
# 报错的时候最多列出几处对不上的地方。
MAX_SHOWN_PROBLEMS = 3

_NAME = re.compile(r"[a-z0-9_]+")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
# 文件的路径只能往清单自己的目录里面写：不能有 ..、不能从根开始、不能有反斜杠。中间可以有空格（许可证的文件名有）。
_PATH_PART = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_ .-]*[A-Za-z0-9_.-])?")
_TEXT_FIELDS = ("name", "description", "source", "commit", "commit_date", "license", "base_url")

Download = Callable[[str, int], bytes]


class ManifestError(ValueError):
    """清单写得不对。"""


class AssetError(RuntimeError):
    """外面来的文件不在、被改过，或者下载不下来。"""


@dataclass(frozen=True)
class AssetFile:
    """清单里的一个文件：相对的路径（用 / 分开）、大小、SHA-256；lfs 是从 lfs_base_url 下。"""

    path: str
    size_bytes: int
    sha256: str
    lfs: bool = False


@dataclass(frozen=True)
class Manifest:
    """一份清单：一样外面来的东西是从哪来的、哪个版本、什么许可证、有哪些文件。"""

    name: str
    description: str
    source: str
    commit: str
    commit_date: str
    license: str
    base_url: str
    files: tuple[AssetFile, ...]
    lfs_base_url: str | None = None

    def url_of(self, file: AssetFile) -> str:
        base = self.lfs_base_url if file.lfs else self.base_url
        return base + urllib.parse.quote(file.path)

    @property
    def total_bytes(self) -> int:
        """全部文件一共多大。"""
        return sum(file.size_bytes for file in self.files)


def load_manifest(path: Path) -> Manifest:
    """读一份清单，每一项都检查。写得不对就报错，说清楚是哪里。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"{path.name}：读不出来（{error}）") from error
    if not isinstance(raw, dict):
        raise ManifestError(f"{path.name}：最外面应该是一个对象")
    for field in _TEXT_FIELDS:
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise ManifestError(f"{path.name}：{field} 要是一段文字")
    if not _NAME.fullmatch(raw["name"]) or raw["name"] != path.stem:
        raise ManifestError(f"{path.name}：name 要和文件名一样，只用小写字母、数字和下划线")
    if not _COMMIT.fullmatch(raw["commit"]):
        raise ManifestError(f"{path.name}：commit 要是 40 位的提交号")
    for field in ("base_url", "lfs_base_url"):
        url = raw.get(field)
        if field == "lfs_base_url" and url is None:
            continue
        if (
            not isinstance(url, str)
            or not url.startswith("https://")
            or not url.endswith("/")
            or raw["commit"] not in url
        ):
            raise ManifestError(f"{path.name}：{field} 要是 https 的、以 / 结尾，而且写死在 commit 这个版本上")
    entries = raw.get("files")
    if not isinstance(entries, list) or not entries:
        raise ManifestError(f"{path.name}：files 要是一张不空的表")
    files = tuple(_asset_file(path.name, entry) for entry in entries)
    if len({file.path for file in files}) != len(files):
        raise ManifestError(f"{path.name}：files 里有重复的路径")
    if any(file.lfs for file in files) and raw.get("lfs_base_url") is None:
        raise ManifestError(f"{path.name}：有 lfs 的文件就要写 lfs_base_url")
    return Manifest(**{field: raw[field] for field in _TEXT_FIELDS}, files=files, lfs_base_url=raw.get("lfs_base_url"))


def find_manifests(directory: Path) -> list[Manifest]:
    """这个目录里全部的清单，按名字排。"""
    return [load_manifest(path) for path in sorted(directory.glob(f"*{MANIFEST_SUFFIX}"))]


def problems(manifest: Manifest, directory: Path) -> list[str]:
    """下载下来的文件和清单对不对得上。返回对不上的地方；全对就是空的。"""
    root = directory / manifest.name
    found = []
    for file in manifest.files:
        target = root / file.path
        if not target.is_file():
            found.append(f"缺 {file.path}")
        elif target.stat().st_size != file.size_bytes:
            found.append(f"{file.path} 的大小不对")
        elif _sha256(target.read_bytes()) != file.sha256:
            found.append(f"{file.path} 的内容和清单不一样")
    listed = {file.path for file in manifest.files}
    if root.is_dir():
        extra = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.relative_to(root).as_posix() not in listed
        )
        found += [f"多了 {path}（清单里没有）" for path in extra]
    return found


def require(manifest: Manifest, directory: Path = THIRD_PARTY_DIR) -> Path:
    """确认文件都在、都对，返回它们所在的目录。不对就报错，告诉人怎么下载。"""
    found = problems(manifest, directory)
    if found:
        shown = "；".join(found[:MAX_SHOWN_PROBLEMS]) + ("……" if len(found) > MAX_SHOWN_PROBLEMS else "")
        raise AssetError(f"{manifest.name} 的文件和清单对不上（{shown}）。先运行：{FETCH_COMMAND}")
    return directory / manifest.name


def fetch(manifest: Manifest, directory: Path, download: Download | None = None) -> list[str]:
    """把清单里还没有的、不对的文件下载下来。返回这次下载了哪些。

    每个文件先核对大小和 SHA-256，对了才放到位置上，所以不会留下半个文件或者别的内容。
    """
    download = download or download_file
    root = directory / manifest.name
    if root.is_dir():
        for leftover in root.rglob(f"*{PARTIAL_SUFFIX}"):
            leftover.unlink()
    fetched = []
    for file in manifest.files:
        target = root / file.path
        if (
            target.is_file()
            and target.stat().st_size == file.size_bytes
            and _sha256(target.read_bytes()) == file.sha256
        ):
            continue
        content = download(manifest.url_of(file), file.size_bytes)
        if len(content) != file.size_bytes or _sha256(content) != file.sha256:
            raise AssetError(f"{manifest.name}：下载到的 {file.path} 和清单不一样，没有保存")
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + PARTIAL_SUFFIX)
        partial.write_bytes(content)
        partial.replace(target)
        fetched.append(file.path)
    require(manifest, directory)
    return fetched


def download_file(url: str, size_bytes: int) -> bytes:
    """下载一个文件。最多读 size_bytes + 1 个字节：对方给得再多也不收。"""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
            return response.read(size_bytes + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise AssetError(f"下载不下来：{url}（{error}）。检查一下网络，再运行一次") from error


def main(argv: list[str] | None = None) -> int:
    """命令行入口：把每份清单里的文件准备好，说一说结果。"""
    parser = argparse.ArgumentParser(description="按清单下载、核对外面来的模型文件。")
    parser.add_argument("--dir", type=Path, default=THIRD_PARTY_DIR, help="清单在哪个目录")
    arguments = parser.parse_args(argv)
    try:
        manifests = find_manifests(arguments.dir)
        if not manifests:
            raise AssetError(f"{arguments.dir} 里没有清单")
        for manifest in manifests:
            fetched = fetch(manifest, arguments.dir)
            size = f"{len(manifest.files)} 个文件，{manifest.total_bytes / BYTES_PER_MB:.1f} MB"
            outcome = f"新下载了 {len(fetched)} 个" if fetched else "都在，核对过了"
            print(f"{manifest.name}（{size}，{manifest.license}）：{outcome}")
    except (ManifestError, AssetError) as error:
        print(f"没成功：{error}", file=sys.stderr)
        return 1
    return 0


def _asset_file(manifest_name: str, entry: object) -> AssetFile:
    if not isinstance(entry, dict):
        raise ManifestError(f"{manifest_name}：files 里每一项要是一个对象")
    path, size, sha256, lfs = entry.get("path"), entry.get("bytes"), entry.get("sha256"), entry.get("lfs", False)
    if not isinstance(path, str) or not all(_PATH_PART.fullmatch(part) for part in path.split("/")):
        raise ManifestError(f"{manifest_name}：文件的路径不对：{path!r}")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ManifestError(f"{manifest_name}：{path} 的 bytes 要是正的整数")
    if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
        raise ManifestError(f"{manifest_name}：{path} 的 sha256 要是 64 位小写的十六进制")
    if not isinstance(lfs, bool):
        raise ManifestError(f"{manifest_name}：{path} 的 lfs 要是 true 或 false")
    return AssetFile(path, size, sha256, lfs)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


if __name__ == "__main__":
    sys.exit(main())
