#!/usr/bin/env python3
"""Build script to generate version file with git SHA."""

import subprocess
from pathlib import Path


def get_git_sha():
    """Get current git SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return "unknown"


def generate_version_file():
    """Generate _version.py with current git SHA."""
    version = "0.1.0"
    git_sha = get_git_sha()

    version_file = Path("src/gstat/_version.py")
    version_file.write_text(
        f'# Auto-generated during build\n__version__ = "{version}"\n__git_sha__ = "{git_sha}"\n'
    )
    print(f"Generated {version_file} with version={version}, git={git_sha}")


if __name__ == "__main__":
    generate_version_file()
