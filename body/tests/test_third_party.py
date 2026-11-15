"""外面来的文件的测试：清单每一项都检查；文件缺了、被改了、多了都看得出来；下载到的不对就不保存。

这里不连网：下载用一个假的函数代替。最后几条看仓库里真的那份清单，和已经下载下来的文件。
"""

import hashlib
import json
import urllib.error
from pathlib import Path

import pytest

from nova_body import third_party
from nova_body.third_party import (
    FETCH_COMMAND,
    THIRD_PARTY_DIR,
    AssetError,
    ManifestError,
    download_file,
    fetch,
    find_manifests,
    load_manifest,
    main,
    problems,
    require,
)

COMMIT = "0123456789abcdef0123456789abcdef01234567"
BASE_URL = f"https://example.org/models/{COMMIT}/toy/"
CONTENTS = {"model.xml": b"<mujoco/>", "assets/part.STL": b"solid part" * 40, "LICENSE": b"BSD"}


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def manifest_data(**changes) -> dict:
    """一份写对了的清单；changes 里的项会替换掉对应的那一项。"""
    data = {
        "name": "toy",
        "description": "测试用的小模型",
        "source": "https://example.org/models",
        "commit": COMMIT,
        "commit_date": "2026-01-01",
        "license": "BSD-3-Clause",
        "base_url": BASE_URL,
        "files": [
            {"path": path, "bytes": len(content), "sha256": sha256(content)} for path, content in CONTENTS.items()
        ],
    }
    return data | changes


def write_manifest(directory: Path, data: dict | None = None, name: str = "toy") -> Path:
    path = directory / f"{name}.json"
    path.write_text(json.dumps(manifest_data() if data is None else data, ensure_ascii=False), encoding="utf-8")
    return path


class FakeServer:
    """假的下载：按网址给内容，记下被要过哪些。"""

    def __init__(self, contents: dict[str, bytes] | None = None) -> None:
        self.contents = {BASE_URL + path: content for path, content in (contents or CONTENTS).items()}
        self.requests: list[tuple[str, int]] = []

    def __call__(self, url: str, size_bytes: int) -> bytes:
        self.requests.append((url, size_bytes))
        return self.contents[url]


@pytest.fixture
def toy(tmp_path):
    """一份清单，文件已经全部下载好。"""
    manifest = load_manifest(write_manifest(tmp_path))
    fetch(manifest, tmp_path, FakeServer())
    return manifest


# 清单 ------------------------------------------------------------------------------------------------


def test_loads_a_good_manifest(tmp_path):
    """写对了的清单读得出来：从哪来、哪个版本、什么许可证、每个文件多大。"""
    manifest = load_manifest(write_manifest(tmp_path))
    assert (manifest.name, manifest.license, manifest.commit) == ("toy", "BSD-3-Clause", COMMIT)
    assert [file.path for file in manifest.files] == list(CONTENTS)
    assert manifest.files[0].size_bytes == len(CONTENTS["model.xml"])
    assert manifest.total_bytes == sum(len(content) for content in CONTENTS.values())


def one_file(**changes) -> list[dict]:
    return [{"path": "model.xml", "bytes": 9, "sha256": sha256(b"<mujoco/>")} | changes]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"license": ""}, "license 要是一段文字"),
        ({"source": 5}, "source 要是一段文字"),
        ({"name": "Toy"}, "name 要和文件名一样"),
        ({"name": "other"}, "name 要和文件名一样"),
        ({"commit": "main"}, "commit 要是 40 位的提交号"),
        ({"base_url": BASE_URL.replace("https", "http")}, "base_url 要是 https 的"),
        ({"base_url": BASE_URL.rstrip("/")}, "base_url 要是 https 的"),
        ({"base_url": "https://example.org/models/main/toy/"}, "写死在 commit 这个版本上"),
        ({"files": []}, "files 要是一张不空的表"),
        ({"files": {"model.xml": 9}}, "files 要是一张不空的表"),
        ({"files": ["model.xml"]}, "files 里每一项要是一个对象"),
        ({"files": one_file(path="../model.xml")}, "文件的路径不对"),
        ({"files": one_file(path="/etc/model.xml")}, "文件的路径不对"),
        ({"files": one_file(path="assets\\model.xml")}, "文件的路径不对"),
        ({"files": one_file(path="C:/model.xml")}, "文件的路径不对"),
        ({"files": one_file(path="assets//model.xml")}, "文件的路径不对"),
        ({"files": one_file(path=".hidden")}, "文件的路径不对"),
        ({"files": one_file(path=7)}, "文件的路径不对"),
        ({"files": one_file(bytes=0)}, "bytes 要是正的整数"),
        ({"files": one_file(bytes=-9)}, "bytes 要是正的整数"),
        ({"files": one_file(bytes=9.0)}, "bytes 要是正的整数"),
        ({"files": one_file(bytes=True)}, "bytes 要是正的整数"),
        ({"files": one_file(sha256="abc")}, "sha256 要是 64 位小写的十六进制"),
        ({"files": one_file(sha256=sha256(b"x").upper())}, "sha256 要是 64 位小写的十六进制"),
        ({"files": one_file() + one_file()}, "files 里有重复的路径"),
    ],
    ids=[
        "许可证是空的",
        "来源不是文字",
        "名字有大写",
        "名字和文件名不一样",
        "版本不是提交号",
        "不是 https",
        "网址不以斜杠结尾",
        "网址没有写死版本",
        "没有文件",
        "文件不是一张表",
        "文件那一项不是对象",
        "路径往上走",
        "路径从根开始",
        "路径有反斜杠",
        "路径有盘符",
        "路径有空的一段",
        "路径以点开头",
        "路径不是文字",
        "大小是 0",
        "大小是负的",
        "大小是小数",
        "大小是真假值",
        "指纹太短",
        "指纹是大写",
        "路径重复",
    ],
)
def test_rejects_a_bad_manifest(tmp_path, changes, message):
    """清单里任何一项写得不对都拒绝，说清楚是哪里。"""
    path = write_manifest(tmp_path, manifest_data(**changes))
    with pytest.raises(ManifestError, match=message):
        load_manifest(path)


@pytest.mark.parametrize("field", ["name", "commit", "base_url", "files", "license"])
def test_rejects_a_manifest_with_a_missing_field(tmp_path, field):
    """清单里少了一项：拒绝。"""
    data = manifest_data()
    del data[field]
    with pytest.raises(ManifestError):
        load_manifest(write_manifest(tmp_path, data))


@pytest.mark.parametrize(
    ("text", "message"),
    [("{ not json", "读不出来"), ("[1, 2]", "最外面应该是一个对象"), ('"toy"', "最外面应该是一个对象")],
    ids=["不是 JSON", "是一张表", "是一段文字"],
)
def test_rejects_a_file_that_is_not_a_manifest(tmp_path, text, message):
    """不是 JSON，或者最外面不是对象：拒绝。"""
    path = tmp_path / "toy.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ManifestError, match=message):
        load_manifest(path)


def test_rejects_a_manifest_that_does_not_exist(tmp_path):
    """清单文件不在：拒绝。"""
    with pytest.raises(ManifestError, match="读不出来"):
        load_manifest(tmp_path / "toy.json")


def test_finds_manifests_in_name_order(tmp_path):
    """目录里的清单按名字排；别的文件和下载下来的目录不算。"""
    write_manifest(tmp_path, manifest_data(name="zebra"), "zebra")
    write_manifest(tmp_path, manifest_data(name="ant"), "ant")
    (tmp_path / "README.md").write_text("说明", encoding="utf-8")
    (tmp_path / "ant").mkdir()
    assert [manifest.name for manifest in find_manifests(tmp_path)] == ["ant", "zebra"]
    assert find_manifests(tmp_path / "ant") == []


# 下载 ------------------------------------------------------------------------------------------------


def test_fetch_downloads_every_file_to_its_place(tmp_path):
    """第一次：每个文件都下载，放在"清单名/路径"下面，内容和清单一样。"""
    manifest = load_manifest(write_manifest(tmp_path))
    server = FakeServer()
    assert fetch(manifest, tmp_path, server) == list(CONTENTS)
    for path, content in CONTENTS.items():
        assert (tmp_path / "toy" / path).read_bytes() == content
    assert server.requests == [(BASE_URL + path, len(content)) for path, content in CONTENTS.items()]
    assert problems(manifest, tmp_path) == []


def test_fetch_again_downloads_nothing(tmp_path, toy):
    """文件都在、都对：再运行一次什么也不下载。"""
    server = FakeServer()
    assert fetch(toy, tmp_path, server) == []
    assert server.requests == []


def test_fetch_replaces_a_changed_file_and_a_missing_file(tmp_path, toy):
    """一个文件被改了、一个被删了：只重新下载这两个。"""
    (tmp_path / "toy" / "model.xml").write_bytes(b"<changed/>")
    (tmp_path / "toy" / "assets" / "part.STL").unlink()
    server = FakeServer()
    assert fetch(toy, tmp_path, server) == ["model.xml", "assets/part.STL"]
    assert (tmp_path / "toy" / "model.xml").read_bytes() == CONTENTS["model.xml"]
    assert problems(toy, tmp_path) == []


@pytest.mark.parametrize(
    "served",
    [b"<mujoc0/>", b"<mujoco/>" + b" ", b"<mujoco", b""],
    ids=["内容不一样、大小一样", "多了一个字节", "少了两个字节", "空的"],
)
def test_fetch_refuses_content_that_differs_from_the_manifest(tmp_path, served):
    """下载到的内容和清单不一样：报错，不保存，也不留下半个文件。"""
    manifest = load_manifest(write_manifest(tmp_path))
    with pytest.raises(AssetError, match=r"下载到的 model\.xml 和清单不一样，没有保存"):
        fetch(manifest, tmp_path, FakeServer(CONTENTS | {"model.xml": served}))
    assert not (tmp_path / "toy" / "model.xml").exists()
    assert list(tmp_path.rglob("*.part")) == []


def test_fetch_clears_half_written_files_from_an_interrupted_run(tmp_path, toy):
    """上一次下载到一半断了，留下 .part 文件：这一次先清掉。"""
    leftover = tmp_path / "toy" / "assets" / "part.STL.part"
    leftover.write_bytes(b"half")
    assert fetch(toy, tmp_path, FakeServer()) == []
    assert not leftover.exists()


def test_fetch_does_not_delete_unknown_files_but_reports_them(tmp_path, toy):
    """目录里多了清单里没有的文件：不替人删掉，但是报错。"""
    stranger = tmp_path / "toy" / "assets" / "extra.py"
    stranger.write_text("print('hi')", encoding="utf-8")
    with pytest.raises(AssetError, match=r"多了 assets/extra\.py（清单里没有）"):
        fetch(toy, tmp_path, FakeServer())
    assert stranger.exists()


def test_fetch_passes_download_failures_on(tmp_path):
    """下载不下来：原样报出去，已经下载好的留着。"""
    manifest = load_manifest(write_manifest(tmp_path))

    def flaky(url: str, size_bytes: int) -> bytes:
        if url.endswith("LICENSE"):
            raise AssetError("下载不下来：断网了")
        return CONTENTS[url.removeprefix(BASE_URL)]

    with pytest.raises(AssetError, match="断网了"):
        fetch(manifest, tmp_path, flaky)
    assert (tmp_path / "toy" / "model.xml").read_bytes() == CONTENTS["model.xml"]
    assert problems(manifest, tmp_path) == ["缺 LICENSE"]


# 核对 ------------------------------------------------------------------------------------------------


def test_problems_lists_everything_that_differs(tmp_path, toy):
    """缺了、大小不对、内容被改了（大小一样）、多了：每一样都列出来。"""
    assert problems(toy, tmp_path) == []
    root = tmp_path / "toy"
    (root / "LICENSE").unlink()
    (root / "model.xml").write_bytes(b"<mujoco/> ")
    (root / "assets" / "part.STL").write_bytes(b"solid PART" * 40)
    (root / "notes.txt").write_text("x", encoding="utf-8")
    assert problems(toy, tmp_path) == [
        "model.xml 的大小不对",
        "assets/part.STL 的内容和清单不一样",
        "缺 LICENSE",
        "多了 notes.txt（清单里没有）",
    ]


def test_problems_when_nothing_was_downloaded(tmp_path):
    """还没下载过：每个文件都缺。"""
    manifest = load_manifest(write_manifest(tmp_path))
    assert problems(manifest, tmp_path) == [f"缺 {path}" for path in CONTENTS]


def test_require_returns_the_folder_when_everything_matches(tmp_path, toy):
    """文件都对：给出它们所在的目录。"""
    assert require(toy, tmp_path) == tmp_path / "toy"


def test_require_tells_how_to_download(tmp_path):
    """文件不在：报错里写着要运行哪条命令；对不上的地方最多列三处。"""
    manifest = load_manifest(write_manifest(tmp_path))
    with pytest.raises(AssetError) as error:
        require(manifest, tmp_path)
    message = str(error.value)
    assert FETCH_COMMAND in message
    assert "缺 model.xml；缺 assets/part.STL；缺 LICENSE" in message
    assert "……" not in message
    files = manifest_data()["files"] + [{"path": "more.bin", "bytes": 1, "sha256": sha256(b"m")}]
    longer = load_manifest(write_manifest(tmp_path, manifest_data(files=files)))
    with pytest.raises(AssetError, match="缺 LICENSE……"):
        require(longer, tmp_path)


# 真的去下载的那个函数（这里不连网）--------------------------------------------------------------------


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.asked_for = None

    def __enter__(self):
        return self

    def __exit__(self, *exception) -> None:
        return None

    def read(self, amount: int) -> bytes:
        self.asked_for = amount
        return self.content[:amount]


def test_download_reads_at_most_one_byte_more_than_expected(monkeypatch):
    """下载时最多读"应该的大小 + 1"个字节：对方给得再多也不收，多出来的那一个字节会让核对不通过。"""
    response = FakeResponse(b"x" * 1000)
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"], seen["agent"], seen["timeout"] = request.full_url, request.get_header("User-agent"), timeout
        return response

    monkeypatch.setattr(third_party.urllib.request, "urlopen", fake_urlopen)
    assert download_file("https://example.org/file", 10) == b"x" * 11
    assert response.asked_for == 11
    assert seen == {"url": "https://example.org/file", "agent": "nova-body-third-party", "timeout": 120.0}


@pytest.mark.parametrize(
    "failure",
    [urllib.error.URLError("no route"), TimeoutError("timed out"), ConnectionResetError("reset")],
    ids=["连不上", "超时", "连接断了"],
)
def test_download_failure_becomes_a_clear_error(monkeypatch, failure):
    """网络出了问题：换成一句说得清楚的错（哪个网址、怎么办）。"""

    def broken_urlopen(request, timeout):
        raise failure

    monkeypatch.setattr(third_party.urllib.request, "urlopen", broken_urlopen)
    with pytest.raises(AssetError, match=r"下载不下来：https://example\.org/file.*检查一下网络"):
        download_file("https://example.org/file", 10)


# 命令行 ----------------------------------------------------------------------------------------------


def test_command_fetches_and_reports(tmp_path, monkeypatch, capsys):
    """命令行：第一次说新下载了几个，第二次说都在。"""
    write_manifest(tmp_path)
    monkeypatch.setattr(third_party, "download_file", FakeServer())
    assert main(["--dir", str(tmp_path)]) == 0
    assert "toy（3 个文件，0.0 MB，BSD-3-Clause）：新下载了 3 个" in capsys.readouterr().out
    assert main(["--dir", str(tmp_path)]) == 0
    assert "都在，核对过了" in capsys.readouterr().out


def test_command_fails_clearly(tmp_path, monkeypatch, capsys):
    """命令行：没有清单、清单写错、下载不下来，都返回 1，并且说为什么。"""
    assert main(["--dir", str(tmp_path)]) == 1
    assert "里没有清单" in capsys.readouterr().err
    write_manifest(tmp_path, manifest_data(commit="main"))
    assert main(["--dir", str(tmp_path)]) == 1
    assert "没成功：toy.json：commit 要是 40 位的提交号" in capsys.readouterr().err

    def offline(url: str, size_bytes: int) -> bytes:
        raise AssetError("下载不下来：没有网")

    write_manifest(tmp_path)
    monkeypatch.setattr(third_party, "download_file", offline)
    assert main(["--dir", str(tmp_path)]) == 1
    assert "没成功：下载不下来：没有网" in capsys.readouterr().err


# 仓库里真的那份 --------------------------------------------------------------------------------------


def test_every_real_manifest_is_valid_and_pinned():
    """仓库里的清单都写对了，都写死在一个提交号上，都登记了许可证。"""
    manifests = find_manifests(THIRD_PARTY_DIR)
    assert [manifest.name for manifest in manifests] == ["unitree_g1"]
    for manifest in manifests:
        assert manifest.commit in manifest.base_url
        assert manifest.license == "BSD-3-Clause"
        assert "LICENSE" in {file.path for file in manifest.files}


def test_downloaded_files_match_the_real_manifests():
    """下载下来的文件和清单一模一样（没有下载的话，先运行 python -m nova_body.third_party）。"""
    for manifest in find_manifests(THIRD_PARTY_DIR):
        assert problems(manifest, THIRD_PARTY_DIR) == [], f"先运行：{FETCH_COMMAND}"
