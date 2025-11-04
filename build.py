#!/usr/bin/env python3
"""Build script to generate version file from git tags and SHA."""

import subprocess
from pathlib import Path


def run_git_command(args):
    """Run a git command and return output."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return None


def get_git_sha():
    """Get current git SHA."""
    sha = run_git_command(["rev-parse", "--short", "HEAD"])
    return sha if sha else "unknown"


def is_working_tree_dirty():
    """Check if working tree has uncommitted changes."""
    result = run_git_command(["status", "--porcelain"])
    return bool(result)


def get_version_from_git():
    """Get version from git tags.

    Returns version in format:
    - "X.Y.Z" if on a tag
    - "X.Y.Z+sha" if commits after tag
    - "X.Y.Z+sha.dirty" if uncommitted changes
    - "0.0.0+sha" if no tags exist
    """
    # Get the most recent tag
    tag = run_git_command(["describe", "--tags", "--abbrev=0"])

    if not tag:
        # No tags exist yet, use 0.0.0
        version = "0.0.0"
        sha = get_git_sha()
        return f"{version}+{sha}"

    # Strip 'v' prefix if present (v0.1.0 -> 0.1.0)
    version = tag[1:] if tag.startswith("v") else tag

    # Check if we're exactly on the tag
    current_sha = run_git_command(["rev-parse", "HEAD"])
    tag_sha = run_git_command(["rev-parse", f"{tag}^{{}}"])

    sha = get_git_sha()

    if current_sha != tag_sha:
        # Commits after tag
        version = f"{version}+{sha}"

    if is_working_tree_dirty():
        # Uncommitted changes
        version = f"{version}.dirty" if "+" in version else f"{version}+{sha}.dirty"

    return version


def update_pyproject_version(version: str) -> None:
    """Update version in pyproject.toml."""
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        return

    content = pyproject_path.read_text()
    lines = content.splitlines()

    # Find and replace version line
    for i, line in enumerate(lines):
        if line.startswith("version = "):
            # Extract base version (without +sha suffix) for pyproject.toml
            base_version = version.split("+")[0].split(".dirty")[0]
            lines[i] = f'version = "{base_version}"'
            break

    pyproject_path.write_text("\n".join(lines) + "\n")


def generate_version_file():
    """Generate _version.py with version from git and current SHA."""
    version = get_version_from_git()
    git_sha = get_git_sha()

    # Update pyproject.toml with base version
    update_pyproject_version(version)

    version_file = Path("src/gstat/_version.py")
    version_file.write_text(
        f'# Auto-generated during build\n__version__ = "{version}"\n__git_sha__ = "{git_sha}"\n'
    )
    print(f"Generated {version_file} with version={version}, git={git_sha}")


if __name__ == "__main__":
    generate_version_file()
