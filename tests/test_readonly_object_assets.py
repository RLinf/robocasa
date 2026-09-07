"""Both MJCFObject loaders must preserve assets without writing beside them."""

import hashlib
import importlib
import os
import sys
import types
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import pytest
from PIL import Image

from robocasa.models.objects import objects
from robosuite.models.base import MujocoXML


@pytest.fixture(params=["kitchen", "model_zoo"])
def object_class(request, monkeypatch):
    if request.param == "kitchen":
        return objects, objects.MJCFObject
    # The optional package is used only to locate model-zoo-prefixed paths;
    # this test uses a standalone fixture, without those paths.
    stub = types.ModuleType("robosuite_model_zoo")
    stub.__file__ = __file__
    monkeypatch.setitem(sys.modules, "robosuite_model_zoo", stub)
    module = importlib.import_module("robocasa.utils.model_zoo.mjcf_obj")
    return module, module.MJCFObject


@pytest.fixture
def asset_xml(tmp_path):
    asset = tmp_path / "assets"
    asset.mkdir()
    (asset / "tetra.obj").write_text(
        "v 0 0 0\nv 0.1 0 0\nv 0 0.1 0\nv 0 0 0.1\n"
        "f 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n"
    )
    Image.new("RGB", (4, 4), "red").save(asset / "texture.png")
    path = asset / "model.xml"
    path.write_text(
        """<mujoco model="test">
      <asset>
        <mesh name="mesh" file="tetra.obj" scale="1 1 1"/>
        <texture name="texture" type="2d" file="texture.png"/>
        <material name="material" texture="texture"/>
      </asset>
      <worldbody><body><body name="object">
        <geom name="collision" type="mesh" mesh="mesh" material="material" group="0"/>
      </body>
        <site name="bottom_site" size="0.005" pos="0 0 0"/>
        <site name="top_site" size="0.005" pos="0 0 0.1"/>
        <site name="horizontal_radius_site" size="0.005" pos="0.1 0.1 0"/>
      </body></worldbody>
    </mujoco>"""
    )
    return path


def _inventory(root):
    return {
        str(path.relative_to(root)): (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def _compile_object(obj):
    import mujoco

    root = ET.Element("mujoco")
    root.append(deepcopy(obj.asset))
    world = ET.SubElement(root, "worldbody")
    world.append(deepcopy(obj.get_obj()))
    return mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))


def test_readonly_loader_matches_original_geometry_and_dynamics(
    object_class, asset_xml, monkeypatch, tmp_path
):
    import mujoco

    module, cls = object_class

    @contextmanager
    def original_location(xml_str):
        path = asset_xml.parent / "original-temp.xml"
        path.write_text(xml_str)
        try:
            yield str(path)
        finally:
            path.unlink()

    with monkeypatch.context() as baseline:
        baseline.setattr(module, "temporary_mjcf_xml", original_location)
        baseline.setattr(
            objects.MujocoXMLObjectRobocasa,
            "resolve_asset_dependency",
            MujocoXML.resolve_asset_dependency,
        )
        before = cls("test", str(asset_xml), scale=[0.8, 1.1, 1.2])
    original = before.get_xml()
    original_model = _compile_object(before)
    inventory = _inventory(asset_xml.parent)
    paths = list(asset_xml.parent.iterdir())
    for path in paths:
        path.chmod(0o444)
    asset_xml.parent.chmod(0o555)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(objects.tempfile, "tempdir", str(temporary))
    try:
        after = cls("test", str(asset_xml), scale=[0.8, 1.1, 1.2])
        assert after.get_xml() == original
        assert after.folder == str(asset_xml.parent)
        assert not Path(after.file).exists()
        assert list(temporary.iterdir()) == []
        assert _inventory(asset_xml.parent) == inventory
        updated_model = _compile_object(after)
        for name in (
            "geom_size",
            "geom_pos",
            "geom_friction",
            "body_mass",
            "mesh_vert",
            "site_pos",
        ):
            np.testing.assert_array_equal(
                getattr(original_model, name), getattr(updated_model, name)
            )
        left, right = mujoco.MjData(original_model), mujoco.MjData(updated_model)
        for _ in range(8):
            mujoco.mj_step(original_model, left)
            mujoco.mj_step(updated_model, right)
        np.testing.assert_array_equal(left.qpos, right.qpos)
        np.testing.assert_array_equal(left.qvel, right.qvel)
    finally:
        asset_xml.parent.chmod(0o755)
        for path in paths:
            path.chmod(0o644)


def test_constructor_exception_cleans_temporary_xml(
    object_class, asset_xml, monkeypatch, tmp_path
):
    _, cls = object_class
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setattr(objects.tempfile, "tempdir", str(temporary))

    def fail(*args, **kwargs):
        raise RuntimeError("parse failure")

    monkeypatch.setattr(objects.MujocoXMLObjectRobocasa, "__init__", fail)
    before = _inventory(asset_xml.parent)
    with pytest.raises(RuntimeError, match="parse failure"):
        cls("test", str(asset_xml))
    assert list(temporary.iterdir()) == []
    assert _inventory(asset_xml.parent) == before


def test_temporary_xml_works_without_explicit_tmpdir(monkeypatch):
    monkeypatch.delenv("TMPDIR", raising=False)
    with objects.temporary_mjcf_xml("<mujoco/>") as path:
        assert ET.parse(path).getroot().tag == "mujoco"
        assert os.stat(path).st_mode & 0o777 == 0o600
    assert not Path(path).exists()
