import argparse
import filecmp
import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from termcolor import colored
from tqdm import tqdm

import robocasa

# path to the box_links.json shipped with robocasa
BOX_LINKS_PATH = os.path.join(
    robocasa.__path__[0], "models", "assets", "box_links", "box_links_assets.json"
)
with open(BOX_LINKS_PATH, "r") as f:
    BOX_LINKS = json.load(f)


def _get_direct_download_url(shared_url):
    """
    Convert a Box shared link into a direct-download URL.
    e.g. https://utexas.box.com/s/abc123  →
         https://utexas.box.com/shared/static/abc123.zip
    """
    shared_id = shared_url.rstrip("/").split("/")[-1]
    base = shared_url.split("/s/")[0]
    return f"{base}/shared/static/{shared_id}.zip"


DOWNLOAD_ASSET_REGISTRY = {
    ### textures ###
    "tex": dict(
        message="Downloading environment textures",
        url=_get_direct_download_url(BOX_LINKS["textures"]),
        folder=os.path.join(robocasa.__path__[0], "models/assets/textures"),
        check_folder_exists=False,
    ),
    "tex_generative": dict(
        message="Downloading AI-generated environment textures",
        url=_get_direct_download_url(BOX_LINKS["generative_textures"]),
        folder=os.path.join(robocasa.__path__[0], "models/assets/generative_textures"),
        check_folder_exists=False,
    ),
    "fixtures_lw": dict(
        message="Downloading lightwheel fixtures",
        url=_get_direct_download_url(BOX_LINKS["fixtures_lightwheel"]),
        folder=os.path.join(robocasa.__path__[0], "models/assets/fixtures"),
        check_folder_exists=False,
    ),
    ### objects ###
    "objs_objaverse": dict(
        message="Downloading objaverse objects",
        url=_get_direct_download_url(BOX_LINKS["objaverse"]),
        folder=os.path.join(robocasa.__path__[0], "models/assets/objects/objaverse"),
        check_folder_exists=False,
    ),
    "objs_aigen": dict(
        message="Downloading AI-generated objects",
        url=_get_direct_download_url(BOX_LINKS["aigen_objs"]),
        folder=os.path.join(robocasa.__path__[0], "models/assets/objects/aigen_objs"),
        check_folder_exists=False,
    ),
    "objs_lw": dict(
        message="Downloading lightwheel objects",
        url=_get_direct_download_url(BOX_LINKS["objects_lightwheel"]),
        folder=os.path.join(robocasa.__path__[0], "models/assets/objects/lightwheel"),
        check_folder_exists=False,
    ),
}


class DownloadProgressBar(tqdm):
    def update_to(self, b=1, bsize=1, tsize=None):
        if tsize is not None:
            self.total = tsize
        self.update(b * bsize - self.n)


def _needs_install(source, target, overwrite):
    if not target.exists() and not target.is_symlink():
        return True
    if target.is_symlink() or not target.is_file():
        raise FileExistsError(f"Asset destination is not a regular file: {target}")
    if overwrite:
        return True
    if source.stat().st_size == target.stat().st_size and filecmp.cmp(
        source, target, shallow=False
    ):
        return False
    raise FileExistsError(
        f"Asset differs from the installed file: {target}. "
        "Rerun the same robocasa-download-assets command with --overwrite "
        "to replace conflicting resource files."
    )


def _publish_file(complete, target, overwrite):
    """Publish a complete file without exposing a partial destination."""
    if overwrite:
        os.replace(complete, target)
    else:
        try:
            # Unlike replace(), link() cannot overwrite a concurrently created file.
            os.link(complete, target)
        except FileExistsError:
            if _needs_install(complete, target, overwrite=False):
                raise
        complete.unlink()


def _copy_file_atomically(source, target, overwrite):
    target.parent.mkdir(parents=True, exist_ok=True)
    out = tempfile.NamedTemporaryFile(
        mode="wb", prefix=".robocasa-copy-", dir=target.parent, delete=False
    )
    temporary = Path(out.name)
    try:
        with out, source.open("rb") as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        shutil.copymode(source, temporary)
        _publish_file(temporary, target, overwrite)
    finally:
        temporary.unlink(missing_ok=True)


def copy_missing_files(
    source, destination, *, overwrite=False, relative_paths=None, move=False
):
    """Install complete files; existing different content requires opt-in."""
    source, destination = Path(source), Path(destination)
    if relative_paths is None:
        relative_paths = [
            path.relative_to(source) for path in source.rglob("*") if path.is_file()
        ]
    pending = [
        path
        for path in relative_paths
        if _needs_install(source / path, destination / path, overwrite)
    ]
    for path in pending:
        target = destination / path
        if move:
            target.parent.mkdir(parents=True, exist_ok=True)
            _publish_file(source / path, target, overwrite)
        else:
            _copy_file_atomically(source / path, target, overwrite)


def download_is_complete(url, folder):
    """Only skip a download whose installed file inventory is still present."""
    folder = Path(folder)
    try:
        record = json.loads((folder / ".robocasa-download.json").read_text())
        if record.get("url") != url or not record.get("files"):
            return False
        for name, size in record["files"].items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                return False
            path = folder.parent / relative
            if not path.is_file() or path.stat().st_size != size:
                return False
        return True
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def url_is_alive(url):
    """
    Checks that a given URL is reachable.
    From https://gist.github.com/dehowell/884204.

    Args:
        url (str): url string

    Returns:
        is_alive (bool): True if url is reachable, False otherwise
    """
    request = urllib.request.Request(url)
    request.get_method = lambda: "HEAD"

    try:
        urllib.request.urlopen(request)
        return True
    except urllib.request.HTTPError:
        return False


def download_url(url, download_dir, fname=None, check_overwrite=True):
    """
    First checks that @url is reachable, then downloads the file
    at that url into the directory specified by @download_dir.
    Prints a progress bar during the download using tqdm.

    Modified from https://github.com/tqdm/tqdm#hooks-and-callbacks, and
    https://stackoverflow.com/a/53877507.

    Args:
        url (str): url string
        download_dir (str): path to directory where file should be downloaded
        check_overwrite (bool): if True, will sanity check the download fpath to make sure a file of that name
            doesn't already exist there
    """
    if fname is None:
        # infer filename from url link
        fname = url.split("/")[-1]
    file_to_write = os.path.join(download_dir, fname)

    # If we're checking overwrite and the path already exists,
    # we ask the user to verify that they want to overwrite the file
    if check_overwrite and os.path.exists(file_to_write):
        user_response = input(
            f"Warning: file {file_to_write} already exists. Overwrite? y/n "
        )
        assert user_response.lower() in {
            "yes",
            "y",
        }, f"Did not receive confirmation. Aborting download."

    print(colored(f"Downloading to {file_to_write}", "yellow"))

    with DownloadProgressBar(unit="B", unit_scale=True, miniters=1, desc=fname) as t:
        urllib.request.urlretrieve(url, filename=file_to_write, reporthook=t.update_to)


def download_and_extract_zip(
    url,
    folder,
    check_folder_exists=True,
    prompt_before_download=False,
    delete_old_folder=False,
    message="Downloading...",
    overwrite=False,
):
    assert url.endswith(".zip")

    download_dir = os.path.abspath(os.path.join(folder, os.pardir))
    Path(download_dir).mkdir(parents=True, exist_ok=True)

    if delete_old_folder and os.path.exists(folder):
        print(colored(f"Deleting existing folder: {folder}", "yellow"))
        shutil.rmtree(folder)

    download_path = os.path.join(
        download_dir, "{}.zip".format(os.path.basename(folder))
    )

    print(colored(message, "yellow"))

    # check if folder already exists
    if check_folder_exists and os.path.exists(folder):
        ans = input("{} already exists! \noverwrite? (y/n) ".format(folder))

        if ans == "y":
            print(colored("Proceeding.", "yellow"))
        else:
            print(colored("Skipping.\n", "yellow"))
            return

    if prompt_before_download:
        ans = input(
            "Assets to be downloaded may be a few Gb. Proceed? (y/n) ".format(folder)
        )

        if ans == "y":
            print(colored("Proceeding.", "yellow"))
        else:
            print(colored("Skipping.\n", "yellow"))
            return

    partial_path = download_path + ".part"
    last_error = None
    for i in range(3):
        try:
            download_url(
                url=url,
                download_dir=download_dir,
                fname=os.path.basename(partial_path),
                check_overwrite=False,
            )
            with ZipFile(partial_path) as archive:
                bad_member = archive.testzip()
                if bad_member is not None:
                    raise BadZipFile(f"CRC check failed: {bad_member}")
            break
        except Exception as exc:
            last_error = exc
            print("Error downloading after try #{}".format(i + 1))
    else:
        raise RuntimeError(
            f"Asset download failed after 3 attempts: {folder}"
        ) from last_error

    print(colored("Extracting...", "yellow"))
    with tempfile.TemporaryDirectory(
        prefix=".robocasa-extract-", dir=download_dir
    ) as stage:
        with ZipFile(partial_path) as archive:
            inventory = {}
            for member in archive.infolist():
                path = Path(member.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise BadZipFile(f"Invalid asset path: {member.filename}")
                if not member.is_dir():
                    inventory[str(path)] = member.file_size
            if not any(
                len(Path(name).parts) > 1 and Path(name).parts[0] == Path(folder).name
                for name in inventory
            ):
                raise BadZipFile(f"Archive has no payload for {Path(folder).name}")
            archive.extractall(stage)
        marker = Path(folder) / ".robocasa-download.json"
        marker.unlink(missing_ok=True)
        copy_missing_files(
            stage,
            download_dir,
            overwrite=overwrite,
            relative_paths=inventory,
            move=True,
        )
        out = tempfile.NamedTemporaryFile(mode="w", dir=folder, delete=False)
        temporary_marker = Path(out.name)
        try:
            with out:
                json.dump({"url": url, "files": inventory}, out, sort_keys=True)
            temporary_marker.replace(marker)
        finally:
            temporary_marker.unlink(missing_ok=True)
    os.remove(partial_path)

    print(colored("Done.\n", "yellow"))


def download_kitchen_assets(types, registry=None, *, overwrite=False):
    ans = input("The script will download ~10 Gb of data. Proceed? (y/n) ")
    if ans == "y":
        print("Proceeding...")
    else:
        print("Aborting.")
        return

    registry = DOWNLOAD_ASSET_REGISTRY if registry is None else registry
    for ds_name, config in registry.items():
        if types is None:
            pass
        elif "all" in types:
            # download everything
            pass
        else:
            if ds_name not in types:
                continue
        download_and_extract_zip(**config, overwrite=overwrite)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--overwrite", action="store_true", help="replace conflicting resource files"
    )
    parser.add_argument(
        "--type",
        type=str,
        nargs="+",
        choices=list(DOWNLOAD_ASSET_REGISTRY.keys()) + ["all"],
        help='asset registry types to download (specify "all" to download all types)',
    )

    args = parser.parse_args()
    types = args.type

    download_kitchen_assets(types, overwrite=args.overwrite)
