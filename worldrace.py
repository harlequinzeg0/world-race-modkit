# /// script
# requires-python = ">=3.11"
# dependencies = ["PySide6-Essentials"]
# ///
"""World Race Mod Manager entry point. With no arguments it opens the window."""
import sys


def main():
    if len(sys.argv) > 1:
        from wrmod.cli import main as cli_main

        return cli_main(sys.argv[1:])
    from wrmod.gui.app import run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
