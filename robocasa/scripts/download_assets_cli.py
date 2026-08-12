"""``robocasa-download-assets`` — one-step asset and macro setup.

Writes ``macros_private.py``, then downloads the kitchen assets. Both can
target a directory outside ``site-packages`` so they survive reinstalls and
can be shared between virtualenvs.
"""

import argparse
import builtins
import os
import shutil
import sys

import robocasa
from robocasa.scripts.download_kitchen_assets import (
    DOWNLOAD_ASSET_REGISTRY,
    download_kitchen_assets,
)

PACKAGE_ASSETS = os.path.join(robocasa.__path__[0], "models", "assets")


def _resolve_assets_path(explicit):
    return os.path.abspath(
        explicit or os.environ.get("ROBOCASA_ASSETS_PATH") or PACKAGE_ASSETS
    )


def _resolve_macros_path(explicit, assets_path):
    path = explicit or os.environ.get("ROBOCASA_MACROS_PATH")
    if path:
        return os.path.abspath(path)
    return os.path.join(os.path.dirname(assets_path), "macros_private.py")


def _retarget_registry(assets_path):
    """Point the download registry at ``assets_path``.

    The registry hardcodes the in-package asset directory, so without this
    everything lands in site-packages and has to be moved by hand.
    """
    for entry in DOWNLOAD_ASSET_REGISTRY.values():
        folder = os.path.abspath(entry["folder"])
        if folder.startswith(PACKAGE_ASSETS):
            entry["folder"] = os.path.join(
                assets_path, os.path.relpath(folder, PACKAGE_ASSETS)
            )


def _write_macros(macros_path, force):
    source = os.path.join(robocasa.__path__[0], "macros.py")
    if not os.path.exists(source):
        print("macros.py missing from the installed package; skipping", file=sys.stderr)
        return False
    if os.path.exists(macros_path) and not force:
        print(f"macros: {macros_path} already exists (use --force-macros to replace)")
        return True
    os.makedirs(os.path.dirname(macros_path) or ".", exist_ok=True)
    shutil.copyfile(source, macros_path)
    print(f"macros: wrote {macros_path}")
    return True


def main(argv=None):
    """Entry point for the ``robocasa-download-assets`` console script."""
    parser = argparse.ArgumentParser(
        prog="robocasa-download-assets",
        description="Set up macros_private.py and download the RoboCasa kitchen assets.",
    )
    parser.add_argument(
        "--assets-path",
        default=None,
        help="where to place assets (default: $ROBOCASA_ASSETS_PATH, else inside the package)",
    )
    parser.add_argument(
        "--macros-path",
        default=None,
        help="where to write macros_private.py (default: $ROBOCASA_MACROS_PATH, "
        "else next to the assets directory)",
    )
    parser.add_argument(
        "--type",
        nargs="+",
        default=["all"],
        choices=list(DOWNLOAD_ASSET_REGISTRY) + ["all"],
        help="asset types to download (default: all)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="leave already-downloaded asset folders alone",
    )
    parser.add_argument(
        "--no-macros", action="store_true", help="do not write macros_private.py"
    )
    parser.add_argument(
        "--force-macros", action="store_true", help="overwrite an existing macros file"
    )
    parser.add_argument(
        "--no-assets", action="store_true", help="only do the macro setup"
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="answer the download prompts for ~10 GB"
    )
    args = parser.parse_args(argv)

    assets_path = _resolve_assets_path(args.assets_path)
    macros_path = _resolve_macros_path(args.macros_path, assets_path)

    if not args.no_macros:
        _write_macros(macros_path, args.force_macros)

    if not args.no_assets:
        if assets_path != PACKAGE_ASSETS:
            os.makedirs(assets_path, exist_ok=True)
            _retarget_registry(assets_path)
        if args.skip_existing:
            for name, entry in list(DOWNLOAD_ASSET_REGISTRY.items()):
                if os.path.isdir(entry["folder"]) and os.listdir(entry["folder"]):
                    print(f"skipping {name}: {entry['folder']} already populated")
                    DOWNLOAD_ASSET_REGISTRY.pop(name)
        types = args.type
        if "all" in types:
            types = list(DOWNLOAD_ASSET_REGISTRY)
        if not types:
            print("nothing left to download")
        else:
            original_input = builtins.input
            if args.yes:
                # download_kitchen_assets prompts several times; -y is what
                # makes this usable from a script or Dockerfile.
                builtins.input = lambda *a, **k: "y"
            try:
                download_kitchen_assets(types)
            finally:
                builtins.input = original_input
        print(f"assets: {assets_path}")

    exports = []
    if not args.no_macros:
        exports.append(f"export ROBOCASA_MACROS_PATH={macros_path}")
    if assets_path != PACKAGE_ASSETS:
        exports.append(f"export ROBOCASA_ASSETS_PATH={assets_path}")
    if exports:
        print("\nAdd these to the shell that launches RoboCasa:")
        for line in exports:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
