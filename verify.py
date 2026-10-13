"""Public-PyPI release verification. Only trusted workflow owners supply smoke code."""
from __future__ import annotations
import glob
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv


def wait_for_release(package: str, version: str, timeout: int, poll: int) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            url = f"https://pypi.org/pypi/{package}/json?x={time.time()}"
            with urllib.request.urlopen(url, timeout=15) as response:
                files = (json.load(response).get("releases") or {}).get(version) or []
            if any(not item.get("yanked", False) for item in files):
                print(f"PyPI index shows {package}=={version} ({len(files)} files)", flush=True)
                return
        except (OSError, ValueError) as exc:
            print(f"poll will retry: {type(exc).__name__}", flush=True)
        time.sleep(min(poll, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"{package}=={version} did not appear on public PyPI within {timeout}s")


def verify_install(package: str, version: str, expected_files: str, commands: str) -> None:
    with tempfile.TemporaryDirectory(prefix="pypi-verify-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        scripts = environment / ("Scripts" if os.name == "nt" else "bin")
        python = scripts / ("python.exe" if os.name == "nt" else "python")
        # Ignore user/global pip configuration and index overrides from the host.
        pip_env = dict(os.environ)
        pip_env["PIP_CONFIG_FILE"] = os.devnull
        pip_env.pop("PYTHONPATH", None)
        pip_env.pop("PYTHONHOME", None)
        subprocess.run([str(python), "-m", "pip", "--isolated", "install", "--quiet",
                        "--no-cache-dir", "--index-url", "https://pypi.org/simple",
                        f"{package}=={version}"], check=True, cwd=root, env=pip_env)
        script = ("import importlib.metadata as m,sys; "
                  "actual=m.version(sys.argv[1]); "
                  "assert actual==sys.argv[2],(actual,sys.argv[2]); print('installed version:',actual)")
        subprocess.run([str(python), "-c", script, package, version], check=True,
                       cwd=root, env=pip_env)
        result = subprocess.run([str(python), "-c",
                                 "import json,sysconfig; print(json.dumps(sysconfig.get_path('purelib')))"],
                                check=True, capture_output=True, text=True, cwd=root, env=pip_env)
        site_packages = Path(json.loads(result.stdout))
        check_expected_files(site_packages, expected_files)
        env = dict(os.environ)
        env["PATH"] = str(scripts) + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(environment)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        for command in commands.splitlines():
            if command.strip():
                print(f">> {command}", flush=True)
                subprocess.run([os.environ.get("VERIFY_BASH", "bash"),
                                "-e", "-o", "pipefail", "-c", command],
                               check=True, cwd=root, env=env)
        print("Exact version, expected files and smoke commands verified", flush=True)


def check_expected_files(site_packages: Path, expected_files: str) -> None:
    root = site_packages.resolve()
    missing = []
    for line in expected_files.splitlines():
        pattern = line.strip().replace("\\", "/")
        if not pattern:
            continue
        if pattern.startswith("/") or PureWindowsPath(pattern).drive or ".." in pattern.split("/"):
            raise ValueError("expected-files must be relative globs inside site-packages")
        matches = [Path(value) for value in glob.glob(str(root / pattern))]
        for match in matches:
            if not match.resolve().is_relative_to(root):
                raise ValueError("expected file resolves outside site-packages")
        if not any(match.is_file() for match in matches):
            missing.append(pattern)
    if missing:
        raise RuntimeError(f"missing files in installed package: {missing}")


def main() -> int:
    package = os.environ.get("VERIFY_PACKAGE", "")
    version = os.environ.get("VERIFY_VERSION", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", package):
        raise ValueError("invalid PyPI package name")
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+!-]*", version):
        raise ValueError("invalid package version")
    timeout, poll = int(os.environ.get("VERIFY_TIMEOUT", "300")), int(os.environ.get("VERIFY_POLL", "10"))
    if timeout <= 0 or poll <= 0:
        raise ValueError("timeout and poll interval must be positive")
    wait_for_release(package, version, timeout, poll)
    verify_install(package, version, os.environ.get("VERIFY_FILES", ""),
                   os.environ.get("VERIFY_COMMANDS", ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Verification failed: {exc}", file=sys.stderr)
        sys.exit(1)
