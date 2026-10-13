"""Offline verifier checks with real isolated venvs and a local fixture wheel.

Only the PyPI download is substituted. These checks are not a published-release
verification; smoke.yml separately verifies a real known-good PyPI package.
"""
import importlib.util
from pathlib import Path
import subprocess
import zipfile
import pytest

SPEC = importlib.util.spec_from_file_location("release_verifier", Path(__file__).resolve().parents[1] / "verify.py")
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


@pytest.fixture
def local_package(tmp_path, monkeypatch):
    wheel = tmp_path / "release_probe-1.0.0-py3-none-any.whl"
    files = {
        "release_probe/__init__.py": '__version__ = "1.0.0"\n',
        "release_probe/schema/check.json": '{}',
        "release_probe-1.0.0.dist-info/METADATA": 'Metadata-Version: 2.1\nName: release-probe\nVersion: 1.0.0\n',
        "release_probe-1.0.0.dist-info/WHEEL": 'Wheel-Version: 1.0\nGenerator: local-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
    }
    files["release_probe-1.0.0.dist-info/RECORD"] = ''.join(f'{name},,\n' for name in files) + 'release_probe-1.0.0.dist-info/RECORD,,\n'
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    actual_run = subprocess.run
    roots = []
    def download_from_fixture(command, *args, **kwargs):
        roots.append(Path(kwargs["cwd"]))
        if "-m" in command or "-c" in command:
            assert "PYTHONPATH" not in kwargs["env"]
            assert "PYTHONHOME" not in kwargs["env"]
        if "--index-url" in command:
            assert command[command.index("--index-url") + 1] == "https://pypi.org/simple"
            command = command[:command.index("--index-url")] + ["--no-index", str(wheel)]
        return actual_run(command, *args, **kwargs)
    monkeypatch.setattr(verify.subprocess, "run", download_from_fixture)
    return roots


def test_installs_version_files_and_cleans_unique_environment(local_package):
    verify.verify_install("release-probe", "1.0.0", "release_probe/schema/*.json", "")
    assert local_package and all(not root.exists() for root in local_package)


def test_missing_schema_fails_and_cleans_environment(local_package):
    with pytest.raises(RuntimeError, match="missing files"):
        verify.verify_install("release-probe", "1.0.0", "release_probe/missing/*.json", "")
    assert all(not root.exists() for root in local_package)


def test_wrong_installed_version_is_rejected(local_package):
    with pytest.raises(subprocess.CalledProcessError):
        verify.verify_install("release-probe", "9.9.9", "", "")
    assert all(not root.exists() for root in local_package)


def test_unsafe_input_is_rejected_before_network(monkeypatch):
    monkeypatch.setenv("VERIFY_PACKAGE", "release-probe;echo bad")
    monkeypatch.setenv("VERIFY_VERSION", "1.0.0")
    with pytest.raises(ValueError, match="package name"):
        verify.main()


@pytest.mark.parametrize("pattern", ["../outside.py", "/tmp/outside.py", "C:/outside.py", "\\\\host/share/outside.py"])
def test_file_glob_cannot_escape_install_directory(tmp_path, pattern):
    with pytest.raises(ValueError, match="relative globs"):
        verify.check_expected_files(tmp_path, pattern)


def test_directories_cannot_impersonate_package_files(tmp_path):
    (tmp_path / "schema.json").mkdir()
    with pytest.raises(RuntimeError, match="missing files"):
        verify.check_expected_files(tmp_path, "schema.json")


def test_environment_overrides_are_removed(local_package, monkeypatch, tmp_path):
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path))
    verify.verify_install("release-probe", "1.0.0", "release_probe/__init__.py", "")
