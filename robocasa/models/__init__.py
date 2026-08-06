import os

# external assets via ROBOCASA_ASSETS_PATH, fallback to bundled
assets_root = os.environ.get("ROBOCASA_ASSETS_PATH") or os.path.join(os.path.dirname(__file__), "assets")
