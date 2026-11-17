"""Optional channel SDKs the desktop app installs on first use.

The desktop app's backend is a code-signed bundle: nothing may be written inside
it, and every app update replaces it whole. So an optional SDK is not shipped in
the bundle and not pip-installed into it. The owner presses Install in Settings,
and the gateway installs the SDK's pinned wheels into the data home::

    <data home>/extras/<extra>/<python tag>/

Outside the bundle, so the signature is untouched and the files survive updates.
The directory joins the END of ``sys.path``, so a bundled module always wins over
a same-named one here.

Integrity: ``pip --require-hashes`` checks every wheel against the lock shipped in
the package (``sdk_extras_locks/<extra>.txt``), with ``--no-deps`` so nothing but
the locked files is fetched. The ``extras`` leaf is READONLY inside every agent
sandbox and fenced from the agent's file tools (``sandbox_leaves``,
``security.paths_lists``), so the agent cannot change code the gateway later
imports. The installer runs in the gateway, outside the sandbox.

The python tag carries the interpreter version and the machine, because a wheel
with native code (``pycryptodome``) only loads in the interpreter it was built for.
A new app with a different Python finds no install for its tag and offers Install
again, rather than importing a library built for another interpreter.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import platform
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from kiro_crew import platform_compat
from kiro_crew.config.paths import config_dir
from kiro_crew.subprocess_utf8 import UTF8_TEXT

logger = logging.getLogger(__name__)

#: The crew-home leaf. Spelled identically in ``sandbox_leaves``,
#: ``sandbox_precreate`` and ``security.paths_lists``; ``test_sdk_extras`` pins them.
EXTRAS_LEAF = "extras"

#: The hashed locks, beside this module.
LOCKS_DIR = Path(__file__).with_name("sdk_extras_locks")

#: Written last, so a directory without it is an install that did not finish.
MARKER_FILE = "kirocrew-extra.json"

#: The extras this installer may lay down. Each has a lock in ``LOCKS_DIR``.
INSTALLABLE: frozenset[str] = frozenset({"feishu"})

#: A cold download of the locked wheels over a slow link.
_PIP_TIMEOUT_SECS = 10 * 60.0

#: The tail of pip's output an error carries; the reason is at the end.
ERROR_DETAIL_CAP = 2000


#: One install at a time in this process. The Settings button and the start-up
#: install for an already enabled channel can both run; the second waits and then
#: finds the finished install instead of writing the same ``.partial`` directory.
_INSTALL_LOCK = threading.Lock()


class InstallError(RuntimeError):
    """An install that did not finish; the message is shown in Settings."""


def python_tag() -> str:
    """``cp312-darwin-arm64``: the interpreter and machine a native wheel needs."""
    return (
        f"cp{sys.version_info[0]}{sys.version_info[1]}-{sys.platform}-"
        f"{platform.machine().lower() or 'unknown'}"
    )


def extra_dir(extra: str, home: Path | None = None) -> Path:
    return Path(home or config_dir()) / EXTRAS_LEAF / extra / python_tag()


def lock_file(extra: str) -> Path:
    return LOCKS_DIR / f"{extra}.txt"


def is_installed(extra: str, home: Path | None = None) -> bool:
    return (extra_dir(extra, home) / MARKER_FILE).is_file()


def install_supported(extra: str) -> bool:
    """True on the desktop bundle, for an extra this installer knows, with pip present.

    Elsewhere the user owns their environment and gets a ``pip install`` command
    instead (``extras.pip_install_channel_available``).
    """
    return (
        extra in INSTALLABLE
        and platform_compat.is_bundled_interpreter()
        and lock_file(extra).is_file()
        and importlib.util.find_spec("pip") is not None
    )


def activate(home: Path | None = None) -> None:
    """Append every finished install for this interpreter to ``sys.path``. Idempotent.

    Called before anything probes or imports an optional SDK. Only reads the disk.
    """
    added = False
    for extra in sorted(INSTALLABLE):
        target = extra_dir(extra, home)
        if not (target / MARKER_FILE).is_file():
            continue
        entry = str(target)
        if entry not in sys.path:
            sys.path.append(entry)
            added = True
    if added:
        importlib.invalidate_caches()


def install_extra(extra: str, home: Path | None = None) -> Path:
    """Install *extra*'s locked wheels for this interpreter; blocking. Returns the directory.

    Built in a sibling ``.partial`` directory and renamed into place, so a failed
    or interrupted install never leaves a half-filled directory that ``activate``
    would load. A finished install is returned untouched: the running gateway may
    already have imported it (on Windows its native files are then locked), so it
    is never deleted or rebuilt. Every failure, a disk or permission error
    included, is an ``InstallError`` and leaves no ``.partial`` behind.
    """
    if extra not in INSTALLABLE:
        raise InstallError(f"no installer for '{extra}'")
    lock = lock_file(extra)
    if not lock.is_file():
        raise InstallError(f"lock file missing: {lock}")
    target = extra_dir(extra, home)
    with _INSTALL_LOCK:
        return _install_locked(extra, lock, target, home)


def _install_locked(extra: str, lock: Path, target: Path, home: Path | None) -> Path:
    if (target / MARKER_FILE).is_file():
        activate(home)
        return target
    partial = target.with_name(f".{target.name}.partial")
    try:
        _lay_down(extra, lock, target, partial)
    except OSError as exc:
        raise InstallError(f"could not write the install: {exc}") from exc
    finally:
        # After a successful rename there is nothing here; otherwise this is the
        # half-built tree, never the finished ``target``.
        shutil.rmtree(partial, ignore_errors=True)
    logger.info("installed the %s SDK into %s", extra, target)
    activate(home)
    return target


def _lay_down(extra: str, lock: Path, target: Path, partial: Path) -> None:
    """Run pip into *partial*, mark it finished, and rename it to *target*."""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir()
    argv = [
        sys.executable,
        "-I",
        "-m",
        "pip",
        "install",
        "--target",
        str(partial),
        "--no-deps",
        "--require-hashes",
        "--only-binary",
        ":all:",
        "--no-input",
        "--disable-pip-version-check",
        "-r",
        str(lock),
    ]
    # Lazy: the browser harness installer pulls in ~35 ms of modules, and this
    # module loads at gateway start while pip runs only on an install.
    from kiro_crew.browser_harness.install import _child_env

    try:
        result = subprocess.run(
            argv,
            cwd=str(partial),
            env=_child_env(),
            capture_output=True,
            timeout=_PIP_TIMEOUT_SECS,
            check=False,
            **UTF8_TEXT,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstallError(f"timed out after {_PIP_TIMEOUT_SECS:.0f}s") from exc
    except OSError as exc:
        raise InstallError(str(exc)) from exc
    if result.returncode != 0:
        output = ((result.stderr or "") + (result.stdout or "")).strip()
        raise InstallError(output[-ERROR_DETAIL_CAP:] or f"pip exited {result.returncode}")
    (partial / MARKER_FILE).write_text(
        json.dumps({"extra": extra, "python": python_tag()}) + "\n", encoding="utf-8"
    )
    # Only an unfinished leftover can be here (a finished one returned above), and
    # ``activate`` never loads one, so removing it touches nothing the gateway runs.
    shutil.rmtree(target, ignore_errors=True)
    if target.exists():
        raise InstallError(f"could not remove an unfinished install at {target}")
    partial.rename(target)
