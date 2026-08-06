"""
This script sets up a private macros file.
The private macros file (macros_private.py) is not tracked by git,
allowing user-specific settings that are not tracked by git.
The target path must be set via the ROBOCASA_MACROS_PATH env var.
"""

import os
import shutil

import robocasa

if __name__ == "__main__":
    # source macros.py from package
    base_path = robocasa.__path__[0]
    macros_path = os.path.join(base_path, "macros.py")

    # target: ROBOCASA_MACROS_PATH (required)
    macros_private_path = os.environ.get("ROBOCASA_MACROS_PATH")
    if not macros_private_path:
        raise RuntimeError(
            "ROBOCASA_MACROS_PATH must be set. "
            "Example: export ROBOCASA_MACROS_PATH=~/.robocasa/macros_private.py"
        )
    os.makedirs(os.path.dirname(macros_private_path), exist_ok=True)

    print("Setting up private macros file...")
    print("Target: {}".format(macros_private_path))

    if not os.path.exists(macros_path):
        print("{} does not exist! Aborting...".format(macros_path))
        exit(1)

    if os.path.exists(macros_private_path):
        ans = input(
            "{} already exists! \noverwrite? (y/n)\n".format(macros_private_path)
        )

        if ans == "y":
            print("REMOVING")
        else:
            exit()

    shutil.copyfile(macros_path, macros_private_path)
    print("copied {}\nto {}".format(macros_path, macros_private_path))
