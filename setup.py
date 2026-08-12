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
    name="rlinf-robocasa365",
    packages=[package for package in find_packages() if package.startswith("robocasa")],
    # Runtime requirements only, as version floors. Anything used solely by
    # robocasa/scripts or robocasa/demos belongs in extras_require.
    entry_points={
        "console_scripts": [
            "robocasa-download-assets = robocasa.scripts.download_assets_cli:main",
        ],
    },
    install_requires=[
        # Necessary but not sufficient: RoboCasa365 needs robosuite master,
        # which reports the same version but carries APIs the release lacks.
        "robosuite>=1.5.2",
        "mujoco>=3.3,<3.10",  # 3.10 changed mj_fullM; breaks robosuite controllers
        # Floor only: no robocasa module uses a numpy-major-specific API, so
        # let robosuite's own constraints decide the major.
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
        # Dataset conversion/playback only; lerobot pins torch.
        "datasets": ["lerobot>=0.4"],
        # scripts/bench_speed.py only; tianshou 0.4.x caps protobuf.
        "bench": ["tianshou>=0.4.10"],
        # enclosing_wall_render_wrapper.py only; needs a display.
        "teleop": ["pynput"],
    },
    eager_resources=["*"],
    include_package_data=True,
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
