# read the contents of your README file
from os import path

from setuptools import find_packages, setup

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, "README.md"), encoding="utf-8") as f:
    lines = f.readlines()

# remove images from README
lines = [x for x in lines if ".png" not in x]
long_description = "".join(lines)

setup(
    name="rpent-robocasa365",
    packages=[package for package in find_packages() if package.startswith("robocasa")],
    # Runtime requirements only — everything here is reachable from
    # ``import robocasa`` or from creating/stepping a kitchen environment.
    # Version floors, not pins: exact pins in this list are what forced
    # downstream projects (RPent) to restate torch/numpy/protobuf constraints
    # and to install this package straight from git. Anything used solely by
    # ``robocasa/scripts`` or ``robocasa/demos`` belongs in extras_require.
    install_requires=[
        "robosuite>=1.5.2",
        # <3.10 mirrors robosuite master: 3.10 changed the mj_fullM signature
        # and breaks controllers/parts/controller.py.
        "mujoco>=3.3,<3.10",
        # Floor only. robosuite 1.5.2 depends on mink==0.0.5, which caps
        # numpy below 2, while robosuite master has dropped mink entirely —
        # so the workable numpy major depends on which robosuite the resolver
        # picks. Pinning a single numpy here is what forced consumers onto a
        # git checkout of robosuite; let the resolver decide instead.
        # No robocasa module uses an API that is exclusive to either major.
        "numpy>=1.24",
        "scipy>=1.15",
        "gymnasium",
        "h5py",
        "imageio",
        "lxml",
        "opencv-python",
        "Pillow",
        "pyyaml",
        "termcolor",
        "tqdm",
    ],
    extras_require={
        # LeRobot dataset conversion/playback:
        # robocasa/utils/lerobot_utils.py, scripts/dataset_scripts/*.
        # Not imported by the environment runtime. Kept out of the base
        # install because lerobot pins torch, which would make this package
        # dictate the torch version of every environment it lands in.
        "datasets": ["lerobot>=0.4"],
        # scripts/bench_speed.py only. tianshou 0.4.x drags an old tensorboard
        # that caps protobuf below 3.20 — a constraint no RoboCasa user should
        # inherit just by installing the simulator.
        "bench": ["tianshou>=0.4.10"],
        # wrappers/enclosing_wall_render_wrapper.py; needs a display, so it is
        # not installed on headless render nodes by default.
        "teleop": ["pynput"],
    },
    eager_resources=["*"],
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "robocasa-download-assets=robocasa.scripts.download_assets_cli:main",
        ],
    },
    python_requires=">=3.10",
    description=(
        "RoboCasa365: A Large-Scale Simulation Framework for Training and "
        "Benchmarking Generalist Robots — RPent redistribution"
    ),
    author="Soroush Nasiriany, Sepehr Nasiriany, Abhiram Maddukuri, Yuke Zhu",
    url="https://github.com/RLinf/robocasa",
    author_email="abhicm@utexas.edu",
    version="1.0.1",
    long_description=long_description,
    long_description_content_type="text/markdown",
)
