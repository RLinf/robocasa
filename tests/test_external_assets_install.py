"""Small offline fixtures for the public asset installer (no simulator)."""

import errno
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

    def package_files(name):
        assert name == "rpent-robocasa365"
        return entries

    monkeypatch.setattr(cli, "distribution_files", package_files)
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
    path.write_text("userscene")  # Same size as the bundled XML, different content.
    with pytest.raises(FileExistsError, match="differs"):
        cli._copy_bundled_assets(target)
    assert path.read_text() == "userscene"


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
    sources = bundled.parents[2] / "rpent_robocasa365.egg-info/SOURCES.txt"
    sources.parent.mkdir()
    sources.write_text("robocasa/models/assets/arenas/empty.xml\n")
    monkeypatch.setattr(
        cli, "distribution_files", lambda name: [Path("__editable__.pth")]
    )
    cli._copy_bundled_assets(tmp_path / "external")
    assert (tmp_path / "external/arenas/empty.xml").is_file()


@pytest.mark.parametrize("entry", ["bundled", "downloaded"])
@pytest.mark.parametrize("failure", ["interrupt", "disk_full"])
def test_atomic_copy_failure_preserves_destination_and_allows_retry(
    installer, tmp_path, monkeypatch, entry, failure
):
    downloader, cli, bundled = installer

    def install(target):
        if entry == "bundled":
            cli._copy_bundled_assets(target, overwrite=True)
        else:
            downloader.copy_missing_files(bundled, target, overwrite=True)

    def fail_copy(src, dst):
        dst.write(src.read(2))
        if failure == "interrupt":
            raise KeyboardInterrupt
        raise OSError(errno.ENOSPC, "disk full")

    for existed in (False, True):
        target = tmp_path / str(existed)
        asset = target / "arenas/empty.xml"
        if existed:
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b"original complete file")
        with monkeypatch.context() as patch:
            patch.setattr(downloader.shutil, "copyfileobj", fail_copy)
            with pytest.raises((KeyboardInterrupt, OSError)):
                install(target)
        if existed:
            assert asset.read_bytes() == b"original complete file"
        else:
            assert not asset.exists()
        assert not list(target.rglob(".robocasa-copy-*"))
        install(target)
        assert asset.read_bytes() == (bundled / "arenas/empty.xml").read_bytes()
        assert asset.stat().st_mode & 0o444 == 0o444


def test_atomic_publish_does_not_clobber_a_concurrently_created_file(
    installer, tmp_path, monkeypatch
):
    downloader, cli, _ = installer
    original_link = downloader.os.link

    def race(source, target):
        target.write_bytes(b"another writer")
        return original_link(source, target)

    monkeypatch.setattr(downloader.os, "link", race)
    target = tmp_path / "external"
    with pytest.raises(FileExistsError, match="--overwrite"):
        cli._copy_bundled_assets(target)
    assert (target / "arenas/empty.xml").read_bytes() == b"another writer"
    assert not list(target.rglob(".robocasa-copy-*"))


@pytest.fixture
def installed_assets(installer, tmp_path, monkeypatch):
    downloader, cli, bundled = installer
    archive = tmp_path / "official.zip"
    with ZipFile(archive, "w") as output:
        output.writestr("fixtures/object/model.xml", "<mujoco/>")
        output.writestr("README.md", "Official attribution\n")
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        shutil.copyfile(archive, Path(kwargs["download_dir"]) / kwargs["fname"])

    monkeypatch.setattr(downloader, "download_url", download)
    target = tmp_path / "external"
    args = ["--assets-path", str(target), "--skip-existing", "--no-macros", "-y"]
    assert cli.main(args) == 0
    return downloader, cli, bundled, target, args, calls


def test_overwrite_repairs_bundled_and_downloaded_files_despite_skip_existing(
    installed_assets,
):
    _, cli, bundled, target, args, calls = installed_assets
    static = target / "arenas/empty.xml"
    dynamic = target / "fixtures/object/model.xml"
    static.write_bytes(b"broken")
    dynamic.write_bytes(b"123456789")  # Same size as the completed payload.
    unrelated = target / "user.txt"
    unrelated.write_text("keep me")
    with pytest.raises(FileExistsError, match="--overwrite"):
        cli.main(args)
    assert cli.main([*args, "--overwrite"]) == 0
    assert len(calls) == 2
    assert static.read_bytes() == (bundled / "arenas/empty.xml").read_bytes()
    assert dynamic.read_text() == "<mujoco/>"
    assert unrelated.read_text() == "keep me"


def test_overwrite_failure_invalidates_completion_marker(installed_assets, monkeypatch):
    downloader, cli, _, target, args, _ = installed_assets
    original_publish = downloader._publish_file

    def fail_payload(source, destination, overwrite):
        if destination.name == "model.xml":
            raise OSError(errno.ENOSPC, "disk full")
        return original_publish(source, destination, overwrite)

    with monkeypatch.context() as patch:
        patch.setattr(downloader, "_publish_file", fail_payload)
        with pytest.raises(OSError, match="disk full"):
            cli.main([*args, "--overwrite"])
    assert not (target / "fixtures/.robocasa-download.json").exists()
    assert (target / "fixtures/object/model.xml").read_text() == "<mujoco/>"
    assert cli.main(args) == 0
    assert downloader.download_is_complete(
        "https://example.org/fixtures.zip", target / "fixtures"
    )


@pytest.mark.parametrize("overwrite", [False, True])
def test_download_publishes_staged_inodes_without_copying_or_tree_scans(
    installed_assets, tmp_path, monkeypatch, overwrite
):
    downloader, _, _, _, _, _ = installed_assets
    target = tmp_path / "fresh" / "fixtures"
    if overwrite:
        asset = target / "object/model.xml"
        asset.parent.mkdir(parents=True)
        asset.write_text("old")

    def unexpected(*args, **kwargs):
        pytest.fail("download publication must use the ZIP inventory and move files")

    original_publish = downloader._publish_file
    published = []

    def publish(source, destination, replace):
        inode = source.stat().st_ino
        original_publish(source, destination, replace)
        assert destination.stat().st_ino == inode
        assert not source.exists()
        published.append(destination)

    monkeypatch.setattr(downloader, "_copy_file_atomically", unexpected)
    monkeypatch.setattr(Path, "rglob", unexpected)
    monkeypatch.setattr(downloader, "_publish_file", publish)
    downloader.download_and_extract_zip(
        "https://example.org/fixtures.zip",
        target,
        check_folder_exists=False,
        overwrite=overwrite,
    )
    assert len(published) == 2
    assert downloader.download_is_complete("https://example.org/fixtures.zip", target)
    assert (target.parent / "README.md").read_text() == "Official attribution\n"


def test_completed_collection_skips_download_and_payload_comparison(
    installed_assets, monkeypatch
):
    downloader, cli, bundled, _, args, calls = installed_assets
    original_compare = downloader.filecmp.cmp

    def compare(source, target, **kwargs):
        assert Path(source).is_relative_to(bundled)
        return original_compare(source, target, **kwargs)

    def unexpected(*args, **kwargs):
        pytest.fail("verified collections must not be downloaded again")

    monkeypatch.setattr(downloader.filecmp, "cmp", compare)
    monkeypatch.setattr(downloader, "download_url", unexpected)
    assert cli.main(args) == 0
    assert len(calls) == 1


def test_size_mismatch_does_not_read_both_files(installer, tmp_path, monkeypatch):
    downloader, cli, _ = installer
    target = tmp_path / "external"
    asset = target / "arenas/empty.xml"
    asset.parent.mkdir(parents=True)
    asset.write_text("different size")

    def unexpected(*args, **kwargs):
        pytest.fail("size mismatch must not perform a deep comparison")

    monkeypatch.setattr(downloader.filecmp, "cmp", unexpected)
    with pytest.raises(FileExistsError, match="--overwrite"):
        cli._copy_bundled_assets(target)


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_overwrite_rejects_non_regular_destinations(installer, tmp_path, kind):
    _, cli, _ = installer
    target = tmp_path / "external"
    asset = target / "arenas/empty.xml"
    asset.parent.mkdir(parents=True)
    unrelated = tmp_path / "user.txt"
    unrelated.write_text("keep me")
    if kind == "directory":
        asset.mkdir()
    else:
        asset.symlink_to(unrelated)
    with pytest.raises(FileExistsError, match="not a regular file"):
        cli._copy_bundled_assets(target, overwrite=True)
    assert unrelated.read_text() == "keep me"
    assert asset.is_dir() if kind == "directory" else asset.is_symlink()
