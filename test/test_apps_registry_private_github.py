"""Registry sources in private GitHub repositories, read through the host's ``gh``.

An owner-designated ``https://github.com/<owner>/<repo>`` fetch that fails the way
a private repository fails is checked against the host's ``gh`` and, when ``gh``
can read the repository, run once more with ``gh`` as git's credential helper on
the network step alone. ``gh`` and git are faked here; no process starts.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from kiro_crew import github_runner
from kiro_crew.apps import registry
from kiro_crew.testing.ids import UNALLOCATABLE_PID

_URL = "https://github.com/acme/private-apps.git"
_GH = "/usr/bin/gh"
_PRIVATE_FAILURE = (
    b"remote: Repository not found.\n"
    b"fatal: repository 'https://github.com/acme/private-apps.git/' not found\n"
)
_PINNED = "a" * 40


class _Proc:
    def __init__(self, returncode: int, out: bytes = b"") -> None:
        self.returncode = returncode
        self._out = out
        self.pid = UNALLOCATABLE_PID

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._out, self._out


def _helper_of(env: dict[str, str]) -> list[str]:
    """The ``credential.helper`` values the command-scope git config carries."""
    count = int(env.get("GIT_CONFIG_COUNT", "0"))
    return [
        env[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(count)
        if env.get(f"GIT_CONFIG_KEY_{i}") == "credential.helper"
    ]


class _FakeGit:
    """Every git spawn the registry makes, answered without a process.

    Without a gh helper in its env, a network step fails like a private repository.
    With one, it succeeds; the local steps always succeed. ``landed`` is the commit
    a fresh checkout reports.
    """

    def __init__(self, *, landed: str = _PINNED) -> None:
        self.calls: list[dict[str, Any]] = []
        self.modes: list[str] = []
        self.landed = landed
        self.network_failure = _PRIVATE_FAILURE
        #: Files a checkout writes into its tree, by relative path.
        self.files: dict[str, str] = {}

    async def wrap(self, argv: list[str], **kwargs: Any) -> tuple[list[str], None]:
        self.modes.append(kwargs.get("mode", ""))
        return list(argv), None

    async def spawn(self, *argv: str, **kwargs: Any) -> _Proc:
        env = dict(kwargs.get("env") or {})
        cwd = kwargs.get("cwd")
        self.calls.append({"argv": list(argv), "env": env, "mode": self.modes[-1]})
        verb = next((a for a in argv[1:] if not a.startswith("-") and "=" not in a), "")
        if verb in {"clone", "fetch", "pull"}:
            if not _helper_of(env) or not any("auth git-credential" in h for h in _helper_of(env)):
                return _Proc(128, self.network_failure)
            return _Proc(0)
        if verb == "init":
            dest = Path(argv[-1])
            (dest / ".git").mkdir(parents=True, exist_ok=True)
        if verb == "checkout" and cwd:
            dest = Path(cwd)
            (dest / ".git" / "HEAD").write_text(self.landed + "\n", encoding="utf-8")
            for rel, text in self.files.items():
                (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                (dest / rel).write_text(text, encoding="utf-8")
        return _Proc(0)

    def network_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if {"clone", "fetch", "pull"} & set(c["argv"])]


@pytest.fixture
def fake_git(monkeypatch: pytest.MonkeyPatch) -> _FakeGit:
    git = _FakeGit()
    monkeypatch.setattr(registry, "wrap_argv_async", git.wrap)
    monkeypatch.setattr(registry, "cgroup_scope_argv", lambda argv: argv)
    monkeypatch.setattr(registry, "create_subprocess_limited", git.spawn)
    monkeypatch.setattr(registry, "is_clone_host_trusted", lambda url: True)
    monkeypatch.setattr(registry, "_sel_fn", None)
    monkeypatch.setattr(
        github_runner,
        "gh_env",
        lambda pin_host="": {"GH_CONFIG_DIR": "/cfg/gh", "GH_HOST": pin_host},
    )
    yield git
    # The index fetch records its cause in a module-level map; leave none behind.
    registry._FETCH_FAILURE_CAUSES.pop((_URL, "main"), None)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["clone", "pull", "index", "manifest"])
async def test_first_network_attempt_pins_the_classifier_locale(
    fake_git: _FakeGit,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setattr(registry, "_gh_access", AsyncMock(return_value=("", "gh_missing")))
    dest = tmp_path / "private-app"
    if operation == "pull":
        (dest / ".git").mkdir(parents=True)
        monkeypatch.setattr(registry, "_clone_origin_url", AsyncMock(return_value=_URL))
        monkeypatch.setattr(registry, "_read_clone_branch", lambda path: "main")
    if operation in {"clone", "pull"}:
        await registry._git_clone_or_pull(_URL, "main", dest, [])
    elif operation == "index":
        await registry._fetch_external_registry_index(_URL, "main")
    else:
        await registry._fetch_app_manifest(_URL, "main", owner_designated=True)
    first = fake_git.network_calls()[0]
    expected_verb = "pull" if operation == "pull" else "clone"
    assert expected_verb in first["argv"]
    assert first["env"]["LC_ALL"] == registry._GIT_CLONE_LOCALE


# ---------------------------------------------------------------------------
# Repository name validation: the only text that reaches a gh argv
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "repo"),
    [
        ("https://github.com/acme/private-apps.git", "acme/private-apps"),
        ("https://github.com/acme/private-apps", "acme/private-apps"),
        ("https://github.com/acme/private-apps/", "acme/private-apps"),
        ("https://github.com/a-b/x.y_z", "a-b/x.y_z"),
    ],
)
def test_a_plain_github_https_url_names_its_repository(url: str, repo: str) -> None:
    assert registry._github_https_repo(url) == repo


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/apps;rm -rf ~",
        "https://github.com/acme/$(id)",
        "https://github.com/ac`me`/apps",
        "https://github.com/acme/apps|sh",
        "https://github.com/acme/apps\nx",
        "https://github.com/-acme/apps",
        "https://github.com/acme/..",
        "https://github.com/acme/apps/tree/main",
        "https://user:pw@github.com/acme/apps",
        "https://github.com:8443/acme/apps",
        "https://github.com/acme/apps?x=1",
        "https://github.com/acme/apps#frag",
        "http://github.com/acme/apps",
        "git@github.com:acme/apps.git",
        "https://gitlab.com/acme/apps",
        "https://github.com.evil.example/acme/apps",
    ],
)
def test_any_other_url_is_refused_before_gh_runs(url: str) -> None:
    assert registry._github_https_repo(url) == ""


@pytest.mark.asyncio
async def test_gh_access_refuses_a_repository_name_with_shell_characters() -> None:
    with (
        patch.object(github_runner, "resolve_gh") as resolve,
        patch.object(github_runner, "run_gh") as run,
    ):
        _path, cause = await registry._gh_access("acme/apps;id")
    assert cause == "gh_no_access"
    resolve.assert_not_called()
    run.assert_not_called()


# ---------------------------------------------------------------------------
# The gh access check
# ---------------------------------------------------------------------------


def _completed(code: int) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout="", stderr="")


@pytest.mark.asyncio
async def test_gh_missing_is_reported_and_nothing_runs() -> None:
    with (
        patch.object(github_runner, "resolve_gh", side_effect=github_runner.SetupError("no gh")),
        patch.object(github_runner, "run_gh") as run,
    ):
        assert await registry._gh_access("acme/private-apps") == ("", "gh_missing")
    run.assert_not_called()


@pytest.mark.asyncio
async def test_gh_signed_out_is_reported_before_the_repository_read() -> None:
    with (
        patch.object(github_runner, "resolve_gh", return_value=_GH),
        patch.object(github_runner, "run_gh", return_value=_completed(1)) as run,
    ):
        assert await registry._gh_access("acme/private-apps") == ("", "gh_signed_out")
    assert run.call_count == 1
    argv = run.call_args.args[0]
    assert argv == [_GH, "auth", "status", "--hostname", "github.com"]


@pytest.mark.asyncio
async def test_a_repository_gh_cannot_read_is_no_access() -> None:
    with (
        patch.object(github_runner, "resolve_gh", return_value=_GH),
        patch.object(github_runner, "run_gh", side_effect=[_completed(0), _completed(1)]) as run,
    ):
        assert await registry._gh_access("acme/private-apps") == ("", "gh_no_access")
    argv = run.call_args.args[0]
    assert argv == [_GH, "api", "repos/acme/private-apps", "--silent"]
    assert run.call_args.kwargs["pin_host"] == "github.com"


@pytest.mark.asyncio
async def test_a_gh_timeout_fails_closed() -> None:
    with (
        patch.object(github_runner, "resolve_gh", return_value=_GH),
        patch.object(
            github_runner,
            "run_gh",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=1),  # flake-ok: a raised value
        ),
    ):
        assert await registry._gh_access("acme/private-apps") == ("", "timeout")


@pytest.mark.asyncio
async def test_gh_that_can_read_the_repository_answers_its_path() -> None:
    with (
        patch.object(github_runner, "resolve_gh", return_value=_GH),
        patch.object(github_runner, "run_gh", return_value=_completed(0)),
    ):
        assert await registry._gh_access("acme/private-apps") == (_GH, "")


# ---------------------------------------------------------------------------
# The credential env: gh does the sign-in, no token in Kiro Crew's hands
# ---------------------------------------------------------------------------


def test_the_credential_env_clears_other_helpers_and_names_gh_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github_runner, "gh_env", lambda pin_host="": {"GH_CONFIG_DIR": "/c"})
    env = registry._gh_credential_env({}, _GH)
    assert _helper_of(env) == ["", f"!{_GH} auth git-credential"]
    # Entries already in the env are kept and the new ones go after them.
    twice = registry._gh_credential_env(env, _GH)
    assert _helper_of(twice) == ["", f"!{_GH} auth git-credential"] * 2
    assert env["GH_CONFIG_DIR"] == "/c"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert not any("token" in key.lower() for key in env if key.startswith("GIT_"))


def test_the_credential_env_refuses_a_relative_gh_path() -> None:
    with pytest.raises(ValueError):
        registry._gh_credential_env({}, "gh")


# ---------------------------------------------------------------------------
# Install and update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_private_app_installs_through_gh_on_the_network_step_only(
    fake_git: _FakeGit, tmp_path: Path
) -> None:
    dest = tmp_path / "sources" / "private-app"
    log: list[str] = []
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=(_GH, ""))) as access:
        err = await registry._git_clone_or_pull(_URL, "main", dest, log)
    assert err is None
    access.assert_awaited_once_with("acme/private-apps")
    first, second = fake_git.network_calls()
    assert not _helper_of(first["env"])
    assert any("auth git-credential" in h for h in _helper_of(second["env"]))
    assert second["mode"] == "standard"
    # Init and checkout never carry the helper.
    for call in fake_git.calls:
        if call not in (first, second):
            assert not _helper_of(call["env"]), call["argv"]
    assert any("looks private" in line for line in log)


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["gh_missing", "gh_signed_out", "gh_no_access"])
async def test_a_private_app_gh_cannot_read_fails_with_its_cause(
    fake_git: _FakeGit, tmp_path: Path, cause: str
) -> None:
    dest = tmp_path / "sources" / "private-app"
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=("", cause))):
        err = await registry._git_clone_or_pull(_URL, "main", dest, [])
    assert err is not None and err["ok"] is False
    assert err["code"] == cause
    assert "acme/private-apps" in err["error"]
    assert "computer that runs Kiro Crew" in err["error"]
    assert "token" not in err["error"].lower()
    # No second git fetch ran.
    assert len(fake_git.network_calls()) == 1


@pytest.mark.asyncio
async def test_a_pinned_private_app_whose_commit_differs_is_refused(
    fake_git: _FakeGit, tmp_path: Path
) -> None:
    fake_git.landed = "b" * 40
    dest = tmp_path / "sources" / "private-app"
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=(_GH, ""))):
        err = await registry._git_clone_or_pull(_URL, "main", dest, [], commit=_PINNED)
    assert err is not None
    assert err["error"] == "pinned commit verification failed"


@pytest.mark.asyncio
async def test_a_pinned_private_app_whose_commit_matches_installs(
    fake_git: _FakeGit, tmp_path: Path
) -> None:
    dest = tmp_path / "sources" / "private-app"
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=(_GH, ""))):
        err = await registry._git_clone_or_pull(_URL, "main", dest, [], commit=_PINNED)
    assert err is None


@pytest.mark.asyncio
async def test_an_index_originated_install_never_asks_gh(
    fake_git: _FakeGit, tmp_path: Path
) -> None:
    dest = tmp_path / "sources" / "sibling"
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=(_GH, ""))) as access:
        err = await registry._git_clone_or_pull(_URL, "main", dest, [], index_originated=True)
    assert err is not None
    access.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_branch_that_does_not_exist_is_not_retried_through_gh(
    fake_git: _FakeGit, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def spawn(*argv: str, **kwargs: Any) -> _Proc:
        fake_git.calls.append({"argv": list(argv), "env": kwargs.get("env") or {}, "mode": ""})
        return _Proc(128, b"warning: Could not find remote branch nope to clone.\n")

    monkeypatch.setattr(registry, "create_subprocess_limited", spawn)
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=(_GH, ""))) as access:
        err = await registry._git_clone_or_pull(_URL, "nope", tmp_path / "x", [])
    assert err is not None
    access.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_gh_sign_in_never_combines_with_an_index_originated_fetch(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        await registry._git_clone_or_pull(
            _URL, "main", tmp_path / "x", [], index_originated=True, gh_path=_GH
        )


# ---------------------------------------------------------------------------
# The registry index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_private_index_is_read_through_gh(fake_git: _FakeGit) -> None:
    fake_git.files["app-registry.json"] = json.dumps([{"name": "private-app", "repo": _URL}])
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=(_GH, ""))):
        entries = await registry._fetch_external_registry_index(_URL, "main")
    assert entries == [{"name": "private-app", "repo": _URL}]
    assert registry._registry_fetch_failure(_URL, "main") == ""
    network = fake_git.network_calls()
    assert any("auth git-credential" in h for h in _helper_of(network[-1]["env"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["gh_missing", "gh_signed_out", "gh_no_access"])
async def test_a_private_index_gh_cannot_read_records_its_cause(
    fake_git: _FakeGit, cause: str
) -> None:
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=("", cause))):
        assert await registry._fetch_external_registry_index(_URL, "main") is None
    assert registry._registry_fetch_failure(_URL, "main") == cause
    assert len(fake_git.network_calls()) == 1


def test_a_gh_cause_status_names_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = type("Reg", (), {"repo": _URL, "branch": "main", "name": "acme"})()
    monkeypatch.setattr(registry, "_external_registry_cache_identity", lambda r: "acme")
    monkeypatch.setattr(
        registry, "_read_external_registry_failure_cause", lambda n: "gh_signed_out"
    )
    monkeypatch.setattr(registry, "_read_external_registry_cache", lambda *a, **k: None)
    status = registry._external_registry_fetch_status(reg)
    assert status == {
        "ok": False,
        "cause": "gh_signed_out",
        "cached": False,
        "host": "github.com",
        "repo": "acme/private-apps",
    }


# ---------------------------------------------------------------------------
# The store card's app.json
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_same_repo_private_manifest_is_read_through_gh(fake_git: _FakeGit) -> None:
    fake_git.files["apps/private-app/app.json"] = json.dumps({"name": "private-app"})
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=(_GH, ""))) as access:
        manifest = await registry._fetch_app_manifest(
            _URL, "main", "apps/private-app", git_url=_URL, owner_designated=True
        )
    assert manifest == {"name": "private-app"}
    access.assert_awaited_once_with("acme/private-apps")


@pytest.mark.asyncio
async def test_a_manifest_the_owner_did_not_designate_never_asks_gh(fake_git: _FakeGit) -> None:
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=(_GH, ""))) as access:
        manifest = await registry._fetch_app_manifest(
            _URL, "main", "apps/private-app", git_url=_URL, owner_designated=False
        )
    assert manifest is None
    access.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["index", "manifest"])
async def test_a_private_source_behind_a_credentialed_proxy_retries_through_gh(
    fake_git: _FakeGit, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    monkeypatch.setattr(registry, "_proxy_env_has_credentials", lambda url: True)
    fake_git.network_failure = b"fatal: Authentication failed\n"
    fake_git.files["app-registry.json"] = json.dumps([{"name": "private-app", "repo": _URL}])
    fake_git.files["app.json"] = json.dumps({"name": "private-app"})
    with patch.object(registry, "_gh_access", new=AsyncMock(return_value=(_GH, ""))) as access:
        if operation == "index":
            result = await registry._fetch_external_registry_index(_URL, "main")
            assert result == [{"name": "private-app", "repo": _URL}]
            assert registry._registry_fetch_failure(_URL, "main") == ""
        else:
            result = await registry._fetch_app_manifest(_URL, "main", owner_designated=True)
            assert result == {"name": "private-app"}
    access.assert_awaited_once_with("acme/private-apps")
    first, second = fake_git.network_calls()
    assert "fetch" in first["argv"] and "fetch" in second["argv"]
    assert not _helper_of(first["env"])
    assert any("auth git-credential" in h for h in _helper_of(second["env"]))
    for call in fake_git.calls:
        if call not in (first, second):
            assert not _helper_of(call["env"]), call["argv"]


def test_the_redacted_authentication_label_still_looks_private() -> None:
    label = registry._loggable_git_transport_output(
        "fatal: Authentication failed", credentialed=True
    )
    assert label == "git authentication failed (credentialed transport details redacted)"
    assert registry._private_github_shaped(label)
