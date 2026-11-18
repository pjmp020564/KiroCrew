"""A cron an app's manifest declares may run with ``approval_mode: "auto"``.

Only a manifest cron, and only one that names an agent: ``AppManifest.validate``
refuses ``"auto"`` without one, and the bridge gives such an entry no auto even
from an ``app-crons.json`` an older build wrote. An auto job's calls still pass
the deny rules first. The owner's own jobs are unchanged.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

import kiro_crew.apps.execution as execution_mod
from kiro_crew import llm_helpers, name_grant
from kiro_crew.apps.bridges import _register_crons, register_app_crons_with_service
from kiro_crew.apps.bridges_crons import _manifest_approval_mode
from kiro_crew.apps.manifest import AppManifest
from kiro_crew.cron import CronService
from kiro_crew.hooks import HookManager
from kiro_crew.llm_helpers_parts.tool_approval import ToolApprovalPolicy
from kiro_crew.providers.base import EVENT_PERMISSION_REQUEST, LLMEvent

APP = "auto-app"


def _manifest(cron: dict) -> AppManifest:
    return AppManifest.from_dict(
        {
            "name": APP,
            "version": "1.0.0",
            "displayName": "Auto App",
            "description": "x",
            "author": "t",
            "permissions": {"cron": True},
            "crons": [cron],
        }
    )


def _cron(**extra) -> dict:
    return {"name": "poll", "every": 600, "message": "poll", "agent": "auto-app-agent", **extra}


@pytest.mark.parametrize(
    ("cron", "error"),
    [
        (_cron(approval_mode="auto"), None),
        (_cron(), None),
        (_cron(approval_mode="auto", agent=""), "needs an 'agent'"),
        (_cron(approval_mode="auto", agent="kirocrew"), "needs an 'agent'"),
        (_cron(approval_mode="always"), 'must be "auto" or absent'),
        (_cron(approval_mode=True), "wrong JSON type"),
    ],
)
def test_the_manifest_takes_auto_only_with_an_agent(cron, error) -> None:
    errors = [e for e in _manifest(cron).validate() if "cron entry" in e]
    if error is None:
        assert errors == []
    else:
        assert any(error in e for e in errors), errors


def test_auto_round_trips_through_the_manifest_and_stays_off_when_unset() -> None:
    assert _manifest(_cron(approval_mode="auto")).crons[0].to_dict()["approval_mode"] == "auto"
    assert "approval_mode" not in _manifest(_cron()).crons[0].to_dict()


@pytest.mark.parametrize(
    ("cron_def", "mode"),
    [
        ({"agent": "auto-app-agent", "approval_mode": "auto"}, "auto"),
        ({"agent": "auto-app-agent"}, ""),
        # An older build's app-crons.json was never validated against the rule.
        ({"agent": "", "approval_mode": "auto"}, ""),
        ({"agent": "kirocrew", "approval_mode": "auto"}, ""),
    ],
)
def test_the_bridge_gives_auto_only_to_a_named_agent(cron_def, mode) -> None:
    assert _manifest_approval_mode(cron_def) == mode


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "kirocrew-home"
    (root / "apps" / APP).mkdir(parents=True)
    monkeypatch.setenv("KIROCREW_HOME", str(root))
    monkeypatch.setattr("kiro_crew.apps.bridges._registration_denied", lambda *a, **k: False)
    monkeypatch.setattr(execution_mod, "third_party_execution_allowed", lambda: True)
    return root


def _register(home, cron: dict, seed=None) -> dict:
    async def _go() -> dict:
        svc = CronService(base_dir=home / "crons")
        await svc.start()
        try:
            if seed is not None:
                await seed(svc)
            _register_crons(APP, _manifest(cron))
            await register_app_crons_with_service(APP, svc)
            return {j.name: j for j in await svc.list_jobs_async(include_disabled=True)}
        finally:
            await svc.stop()

    return asyncio.run(_go())


def test_a_manifest_cron_with_an_agent_runs_auto(home) -> None:
    jobs = _register(home, _cron(approval_mode="auto"))
    assert jobs[f"{APP}/poll"].approval_mode == "auto"


def test_a_manifest_cron_that_asks_for_nothing_keeps_asking(home) -> None:
    jobs = _register(home, _cron())
    assert jobs[f"{APP}/poll"].approval_mode == ""


def test_adding_auto_to_a_registered_entry_reaches_the_job(home) -> None:
    _register(home, _cron())
    jobs = _register(home, _cron(approval_mode="auto"))
    assert jobs[f"{APP}/poll"].approval_mode == "auto"


def test_the_owners_own_job_is_untouched(home) -> None:
    async def _seed(svc: CronService) -> None:
        await svc.add_job_async("mine", "my own job", every_secs=600)

    jobs = _register(home, _cron(approval_mode="auto"), seed=_seed)
    assert (jobs["mine"].approval_mode, jobs["mine"].created_by) == ("", "")


class _Provider:
    def __init__(self) -> None:
        self.approved: list[str] = []
        self.rejected: list[str] = []

    async def approve_tool(self, request_id: str) -> None:
        self.approved.append(request_id)

    async def reject_tool(self, request_id: str) -> None:
        self.rejected.append(request_id)

    async def steer(self, *_args: object, **_kwargs: object) -> None:
        return None


@pytest.mark.asyncio
async def test_a_deny_rule_still_refuses_a_call_under_auto() -> None:
    """The auto policy a manifest job runs with approves only after the deny checks."""

    async def _clean(_event: object) -> None:
        return None

    provider = _Provider()
    event = LLMEvent(
        kind=EVENT_PERMISSION_REQUEST,
        title="Running: rm -rf /",
        request_id="r1",
        tool_input=json.dumps({"command": "rm -rf /"}),
        is_shell=True,
    )
    with (
        patch("kiro_crew.sel.sel", lambda: MagicMock()),
        patch.object(name_grant, "refusal_for_event", _clean),
    ):
        approved = await llm_helpers._resolve_permission(
            provider,
            event,
            ToolApprovalPolicy.AUTO_APPROVE,
            HookManager(),
            session_key="cron:a1b2c3d4",
            agent="auto-app-agent",
            app=APP,
        )

    assert approved is False
    assert (provider.approved, provider.rejected) == ([], ["r1"])
