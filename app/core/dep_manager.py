"""
Dependency manager for the embedded Python environment.

Replaces the old _dep_checker with a more robust approach:
- Uses the current Python's pip to install missing packages.
- Supports both required and optional dependencies.
- Designed to work with embedded Python (no venv needed).
"""
import importlib
import subprocess
import sys
from typing import Dict, List, Tuple


def check_installed(package_map: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Check which packages are already installed.

    Returns (missing_required, all_present_pip_names).
    """
    missing = []
    present = []
    for import_name, pip_name in package_map.items():
        try:
            importlib.import_module(import_name)
            present.append(pip_name)
        except ImportError:
            missing.append(pip_name)
    return missing, present


def install_packages(packages: List[str], quiet: bool = True) -> bool:
    """Install packages via pip. Returns True if all succeeded."""
    if not packages:
        return True
    cmd = [sys.executable, "-m", "pip", "install"] + packages
    if quiet:
        cmd.append("-q")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            msg = result.stderr.strip() or result.stdout.strip()
            print(f"[dep_manager] Failed to install {packages}: {msg[:500]}",
                  file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"[dep_manager] Error installing {packages}: {e}", file=sys.stderr)
        return False


def ensure_deps(package_map: Dict[str, str]) -> bool:
    """Ensure all given dependencies are available; auto-install missing ones."""
    missing, _ = check_installed(package_map)
    if not missing:
        return True
    print(f"[dep_manager] Installing: {', '.join(missing)} ...", flush=True)
    return install_packages(missing)


def is_installed(import_name: str) -> bool:
    """Check if a single package is importable."""
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False
