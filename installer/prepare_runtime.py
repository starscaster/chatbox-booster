#!/usr/bin/env python3
"""
Build script: prepares the runtime directory for the installer.

Downloads Python 3.12 embeddable package, injects pip, and installs
dependencies into runtime/python/.

Usage:
    python installer/prepare_runtime.py           # base: core deps only
    python installer/prepare_runtime.py --full   # full: core + all plugin deps
"""
import os
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = APP_ROOT / "runtime"
PYTHON_DIR = RUNTIME_DIR / "python"
WHEELS_DIR = RUNTIME_DIR / "wheels"

PYTHON_VERSION = "3.12.10"
PYTHON_ARCH = "amd64"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-{PYTHON_ARCH}.zip"
GET_PIP_URL = "https://bootstrap.pypa.org/get-pip.py"

# Full plugin dependencies (installed with --full flag)
PLUGIN_DEPS = [
    "ddgs", "requests", "tiktoken",      # search
    "curl_cffi", "lxml",                  # web_fetch
    "pypdf",                              # academic
    "patchright",                         # browser_engine (optional heavy)
]


def download(url, dest):
    print(f"Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"  -> {dest}")


def step_download_python():
    if PYTHON_DIR.exists():
        print(f"Python dir already exists: {PYTHON_DIR}, skipping download")
        return
    PYTHON_DIR.mkdir(parents=True)
    zip_path = RUNTIME_DIR / "python-embed.zip"
    download(PYTHON_URL, zip_path)
    print("Extracting Python...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(PYTHON_DIR)
    zip_path.unlink()

    pth_files = list(PYTHON_DIR.glob("python*._pth"))
    for pth in pth_files:
        content = pth.read_text()
        content = content.replace("#import site", "import site")
        # Add app root to path so app package is importable (one level up from runtime/)
        content += "\n..\\..\n"
        pth.write_text(content)
        print(f"  Patched {pth.name}")


def _bootstrap_pip():
    """Install pip into embedded Python. Tries get-pip.py, falls back to wheel extraction."""
    python_exe = PYTHON_DIR / "python.exe"
    site_packages = PYTHON_DIR / "Lib" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)

    # Method 1: get-pip.py
    get_pip_path = RUNTIME_DIR / "get-pip.py"
    try:
        if not get_pip_path.exists():
            download(GET_PIP_URL, get_pip_path)
        result = subprocess.run(
            [str(python_exe), str(get_pip_path), "--no-warn-script-location"],
            capture_output=True, text=True, cwd=str(PYTHON_DIR), timeout=60,
        )
        if result.returncode == 0:
            print("  pip installed via get-pip.py")
            return
        print(f"  get-pip.py failed, trying wheel fallback...")
    except Exception as e:
        print(f"  get-pip.py download/run failed ({e}), trying wheel fallback...")

    # Method 2: extract pip + setuptools wheels directly
    WHEELS_DIR.mkdir(parents=True, exist_ok=True)
    for pkg in ["pip", "setuptools"]:
        subprocess.run(
            [sys.executable, "-m", "pip", "download", pkg, "--no-deps", "-d", str(WHEELS_DIR)],
            capture_output=True, text=True, timeout=60,
        )
    import glob
    for pattern, target in [("pip-*.whl", "pip"), ("setuptools-*.whl", "setuptools")]:
        matches = glob.glob(str(WHEELS_DIR / pattern))
        if matches:
            with zipfile.ZipFile(matches[0]) as zf:
                zf.extractall(site_packages)
            print(f"  {target} extracted from wheel")
    # Verify
    result = subprocess.run(
        [str(python_exe), "-m", "pip", "--version"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("  Failed to bootstrap pip!", file=sys.stderr)
        sys.exit(1)
    print(f"  pip bootstrapped via wheel fallback")


def step_install_deps(full: bool):
    python_exe = PYTHON_DIR / "python.exe"
    core_req = APP_ROOT / "requirements-core.txt"
    print(f"Installing core dependencies from {core_req}...")
    result = subprocess.run(
        [str(python_exe), "-m", "pip", "install", "-r", str(core_req), "-q",
         "--no-warn-script-location"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Core dep install failed:\n{result.stderr}")
        sys.exit(1)
    print("  Core dependencies installed")

    if full:
        print(f"Installing plugin dependencies: {PLUGIN_DEPS}")
        result = subprocess.run(
            [str(python_exe), "-m", "pip", "install"] + PLUGIN_DEPS + ["-q",
             "--no-warn-script-location"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"Plugin dep install failed:\n{result.stderr}")
            sys.exit(1)
        print("  Plugin dependencies installed")
    else:
        print("  Skipping plugin dependencies (use --full to include them)")


def step_verify(full: bool):
    python_exe = PYTHON_DIR / "python.exe"
    print("Verifying runtime...")
    imports = ["fastmcp", "aiohttp"]
    if full:
        imports += ["ddgs", "pypdf", "tiktoken"]
    code = f"import {', '.join(imports)}; print('OK')"
    result = subprocess.run(
        [str(python_exe), "-c", code],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Verification failed:\n{result.stderr}")
        sys.exit(1)
    print(f"  {result.stdout.strip()}")


def main():
    full = "--full" in sys.argv
    mode = "full" if full else "base"
    print(f"App root: {APP_ROOT}")
    print(f"Runtime dir: {RUNTIME_DIR}")
    print(f"Build mode: {mode}")

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    step_download_python()
    _bootstrap_pip()
    step_install_deps(full=full)
    step_verify(full=full)

    print(f"\nRuntime preparation complete ({mode})!")
    print(f"Python executable: {PYTHON_DIR / 'python.exe'}")
    print(f"Next: run ISCC with installer/build-{mode}.iss")


if __name__ == "__main__":
    main()
