"""Small offline fixtures for the public asset installer (no simulator)."""

import importlib.util
import json
import shutil
import sys
import types
from pathlib import Path
from zipfile import ZipFile

import pytest


@pytest.fixture
def installer(monkeypatch, tmp_path):
    package = Path(__file__).resolve().parents[1] / "robocasa"
    stub = types.ModuleType("robocasa")
    stub.__path__ = [str(package)]
    monkeypatch.setitem(sys.modules, "robocasa", stub)
    scripts = types.ModuleType("robocasa.scripts")
    scripts.__path__ = [str(package / "scripts")]
    monkeypatch.setitem(sys.modules, "robocasa.scripts", scripts)
    modules = []
    for name in ("download_kitchen_assets", "download_assets_cli"):
        fullname = "robocasa.scripts." + name
        spec = importlib.util.spec_from_file_location(
            fullname, package / "scripts" / (name + ".py")
        )
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, fullname, module)
        spec.loader.exec_module(module)
        modules.append(module)
    downloader, cli = modules
    bundled = tmp_path / "package" / "robocasa" / "models" / "assets"
    for relative in ("arenas/empty.xml", "fixtures/cabinets/panel.xml"):
        path = bundled / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("<mujoco/>")
    entries = [
        Path("robocasa/models/assets") / path.relative_to(bundled)
        for path in bundled.rglob("*.xml")
    ]
    monkeypatch.setattr(cli, "PACKAGE_ASSETS", str(bundled))
    monkeypatch.setattr(cli, "distribution_files", lambda name: entries)
    registry = {
        "fixtures_lw": {
            "url": "https://example.org/fixtures.zip",
            "folder": str(bundled / "fixtures"),
            "check_folder_exists": False,
        }
    }
    monkeypatch.setattr(cli, "DOWNLOAD_ASSET_REGISTRY", registry)
    return downloader, cli, bundled


def test_external_root_gets_static_files_and_downloads_even_with_skeleton(
    installer, tmp_path, monkeypatch
):
    downloader, cli, bundled = installer
    archive = tmp_path / "official.zip"
    with ZipFile(archive, "w") as output:
        output.writestr("fixtures/object/model.xml", "<mujoco/>")
        output.writestr("fixtures/cabinets/panel.xml", "<mujoco/>")
        output.writestr("README.md", "Official asset attribution\n")
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        shutil.copyfile(archive, Path(kwargs["download_dir"]) / kwargs["fname"])

    monkeypatch.setattr(downloader, "download_url", download)
    target = tmp_path / "external"
    args = ["--assets-path", str(target), "--skip-existing", "--no-macros", "-y"]
    assert cli.main(args) == 0
    assert (target / "arenas/empty.xml").is_file()
    assert (target / "fixtures/cabinets/panel.xml").is_file()
    assert (target / "fixtures/object/model.xml").is_file()
    assert (target / "README.md").read_text() == "Official asset attribution\n"
    assert cli.main(args) == 0
    assert len(calls) == 1
    (target / "fixtures/object/model.xml").unlink()
    assert cli.main(args) == 0
    assert len(calls) == 2
    assert cli.DOWNLOAD_ASSET_REGISTRY["fixtures_lw"]["folder"] == str(
        bundled / "fixtures"
    )
    assert not list(target.glob("*.part"))
    assert not list(target.glob(".robocasa-extract-*"))


@pytest.mark.parametrize("failure", ["network", "truncated"])
def test_failed_download_never_reports_complete(
    installer, tmp_path, monkeypatch, failure
):
    downloader, cli, _ = installer
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        if failure == "network":
            raise OSError("connection lost")
        (Path(kwargs["download_dir"]) / kwargs["fname"]).write_bytes(
            b"PK\x03\x04partial"
        )

    monkeypatch.setattr(downloader, "download_url", download)
    target = tmp_path / "external"
    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        cli.main(["--assets-path", str(target), "--no-macros", "-y"])
    assert len(calls) == 3
    assert not downloader.download_is_complete(
        "https://example.org/fixtures.zip", target / "fixtures"
    )
    assert not (target / "fixtures/.robocasa-download.json").exists()


def test_existing_static_content_is_not_replaced(installer, tmp_path):
    _, cli, _ = installer
    target = tmp_path / "external"
    path = target / "arenas/empty.xml"
    path.parent.mkdir(parents=True)
    path.write_text("user scene")
    with pytest.raises(FileExistsError, match="differs"):
        cli._copy_bundled_assets(target)
    assert path.read_text() == "user scene"


def test_download_merge_rejects_conflicts_before_copying(installer, tmp_path):
    downloader, _, _ = installer
    stage, target = tmp_path / "stage", tmp_path / "target"
    stage.mkdir()
    target.mkdir()
    (stage / "new.xml").write_text("new")
    (stage / "old.xml").write_text("different")
    (target / "old.xml").write_text("user")
    with pytest.raises(FileExistsError):
        downloader.copy_missing_files(stage, target)
    assert not (target / "new.xml").exists()
    assert (target / "old.xml").read_text() == "user"


def test_invalid_or_stale_marker_does_not_skip(installer, tmp_path):
    downloader, _, _ = installer
    folder = tmp_path / "fixtures"
    folder.mkdir()
    marker = folder / ".robocasa-download.json"
    for content in (
        "broken",
        "null",
        "[]",
        json.dumps({"url": "old", "files": {"a": 1}}),
    ):
        marker.write_text(content)
        assert not downloader.download_is_complete(
            "https://example.org/fixtures.zip", folder
        )


def test_editable_install_uses_setuptools_package_inventory(
    installer, monkeypatch, tmp_path
):
    _, cli, bundled = installer
    sources = bundled.parents[2] / "rlinf_robocasa365.egg-info/SOURCES.txt"
    sources.parent.mkdir()
    sources.write_text("robocasa/models/assets/arenas/empty.xml\n")
    monkeypatch.setattr(
        cli, "distribution_files", lambda name: [Path("__editable__.pth")]
    )
    cli._copy_bundled_assets(tmp_path / "external")
    assert (tmp_path / "external/arenas/empty.xml").is_file()
