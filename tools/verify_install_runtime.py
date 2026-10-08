#!/usr/bin/env python3
"""Execute the install's runtime steps, instead of reading them.

Runs, as the current user and inside a temp directory, what the install plan
generates for the interpreter and the venv:

- the uv download, checked against its pinned SHA-256 (and refused with a wrong one);
- ``uv python install`` of a version's recommended interpreter;
- the venv, pip/wheel/setuptools and requirements steps for each Odoo clone given,
  with the interpreter the matrix picks for this host, then ``odoo-bin --version``
  (which imports ``pkg_resources`` on Odoo <= 16, so it proves the setuptools pin);
- for an Odoo <= 16 clone, the negative control: an unpinned setuptools breaks it.

It never writes to the clones (``PYTHONDONTWRITEBYTECODE``), /usr/local or /opt.
Needs network access and the Odoo build dependencies (libpq-dev, libldap2-dev, …).

    python3 tools/verify_install_runtime.py --clone 14=/path/odoo-14.0 --clone 16=/path/odoo-16.0
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from instance_manager import planners, support, system  # noqa: E402
from instance_manager.models import InstanceConfig  # noqa: E402

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'}  {name}" + (f" — {detail[-800:]}" if detail and not ok else ""), flush=True)
    if not ok:
        FAILURES.append(name)


def _sudo_stub(bindir: Path) -> None:
    """`sudo -u <user> [-H] cmd…` runs cmd as us."""
    bindir.mkdir(parents=True, exist_ok=True)
    (bindir / "sudo").write_text(
        "#!/usr/bin/env bash\n"
        'while [ $# -gt 0 ]; do case "$1" in -u) shift 2 ;; -H) shift ;; *) break ;; esac; done\n'
        'exec "$@"\n',
        encoding="utf-8",
    )
    (bindir / "sudo").chmod(0o755)


def _run(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env)


def _uv(root: Path, env: dict[str, str]) -> Path | None:
    arch = system.detect_arch()
    commands = planners.plan_ensure_uv(arch)
    if not commands:
        print(f"skip  no pinned uv for {arch}")
        return None
    script = commands[-1].command.replace("command -v uv >/dev/null 2>&1 && exit 0; ", "")
    dest = root / "bin"
    dest.mkdir()
    good = script.replace("/usr/local/bin/", f"{dest}/")
    result = _run(good, env)
    version = subprocess.run([str(dest / "uv"), "--version"], capture_output=True, text=True)
    check("uv installs from the pinned, checksum-verified asset",
          result.returncode == 0 and support.UV_VERSION in version.stdout, result.stderr)
    bad_dest = root / "bad"
    bad_dest.mkdir()
    sha = support.UV_ASSETS[arch][1]
    bad = script.replace(sha, "0" * 64).replace("/usr/local/bin/", f"{bad_dest}/")
    result = _run(bad, env)
    check("a wrong checksum refuses the install", result.returncode != 0 and not any(bad_dest.iterdir()))
    return dest


def _venv(root: Path, major: int, clone: Path, env: dict[str, str]) -> None:
    version = support.ODOO_SUPPORT[major]
    host = system.detect_host_python()
    python, source = support.choose_python(version, host)
    print(f"info  Odoo {major}: host python3 {host}, matrix picks {python} ({source})", flush=True)
    base = root / f"opt{major}"
    with mock.patch.object(InstanceConfig, "base_instances_dir", str(base)):
        config = InstanceConfig(instance="shop", version=str(major), repo_branch=f"{major}.0",
                                python=python, python_source=source)
        home = Path(config.odoo_home)
        home.mkdir(parents=True)
        (home / "odoo").symlink_to(clone)
        if source == support.UV:
            [command] = planners.plan_uv_python(python)
            result = _run(command.command, env)
            check(f"Odoo {major}: uv installs Python {python}", result.returncode == 0, result.stderr)
        for command in planners._venv_commands(config):
            result = _run(command.command, env)
            check(f"Odoo {major}: {command.description}", result.returncode == 0, result.stdout + result.stderr)
            if result.returncode != 0:
                return
        venv_python = home / "venv" / "bin" / "python"
        got = subprocess.run([str(venv_python), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                             capture_output=True, text=True, env=env).stdout.strip()
        check(f"Odoo {major}: the venv runs Python {python}", got == python, got)
        started = subprocess.run([str(venv_python), str(clone / "odoo-bin"), "--version"],
                                 capture_output=True, text=True, env=env)
        check(f"Odoo {major}: odoo-bin starts", started.returncode == 0 and "Odoo" in started.stdout,
              started.stdout + started.stderr)
        if major <= support.PKG_RESOURCES_LAST_MAJOR:
            pip = home / "venv" / "bin" / "pip"
            subprocess.run([str(pip), "install", "-q", "--upgrade", "setuptools"], capture_output=True, env=env)
            found = subprocess.run([str(venv_python), "-c", "import importlib.metadata as m; print(m.version('setuptools'))"],
                                   capture_output=True, text=True, env=env).stdout.strip()
            if int(found.split(".")[0] or 0) < 81:
                # pip resolves the newest setuptools the interpreter supports: on
                # 3.8 that is 75.x, which still ships pkg_resources.
                print(f"info  Odoo {major}: unpinned setuptools on Python {python} is {found}, "
                      "which keeps pkg_resources; no negative control here", flush=True)
                return
            broken = subprocess.run([str(venv_python), str(clone / "odoo-bin"), "--version"],
                                    capture_output=True, text=True, env=env)
            check(f"Odoo {major}: without the pin (setuptools {found}) it does not start (negative control)",
                  broken.returncode != 0 and "pkg_resources" in broken.stderr, broken.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--clone", action="append", default=[], metavar="MAJOR=PATH",
                        help="an Odoo checkout to build a venv for (repeatable)")
    args = parser.parse_args()
    clones: dict[int, Path] = {}
    for item in args.clone:
        major, _, path = item.partition("=")
        clones[int(major)] = Path(path).resolve()

    with tempfile.TemporaryDirectory(prefix="oim-verify-runtime-") as tmp:
        root = Path(tmp)
        stubs = root / "stubs"
        _sudo_stub(stubs)
        uv_python = root / "uv-python"
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", UV_CACHE_DIR=str(root / "uv-cache"),
                   PIP_CACHE_DIR=str(root / "pip-cache"))
        uv_bin = _uv(root, env)
        if uv_bin is None:
            return 1
        env["PATH"] = f"{stubs}:{uv_bin}:{env['PATH']}"
        with mock.patch.object(support, "UV_PYTHON_DIR", str(uv_python)):
            for major, clone in sorted(clones.items()):
                _venv(root, major, clone, env)
    print(f"\n{len(FAILURES)} failure(s)" if FAILURES else "\nall checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
