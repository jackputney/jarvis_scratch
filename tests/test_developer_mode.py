"""developer_mode gating — self-modifying GitHub/ops tools must be hideable
for non-dev installs, both from the model's tool list and from direct dispatch."""

from __future__ import annotations

import pytest

from tools.registry import DEMO_TOOLS, DEV_ONLY_TOOLS, dispatch_tool, get_tool_definitions


def test_developer_mode_on_includes_dev_tools():
    names = {t["name"] for t in get_tool_definitions(developer_mode=True)}
    assert DEV_ONLY_TOOLS <= names


def test_demo_mode_exposes_only_demo_tools():
    names = {t["name"] for t in get_tool_definitions(developer_mode=True, demo_mode=True)}
    assert names == set(DEMO_TOOLS)


def test_demo_tools_all_exist_in_registry():
    all_names = {t["name"] for t in get_tool_definitions(developer_mode=True)}
    assert DEMO_TOOLS <= all_names


def test_developer_mode_off_excludes_dev_tools():
    names = {t["name"] for t in get_tool_definitions(developer_mode=False)}
    assert names.isdisjoint(DEV_ONLY_TOOLS)


@pytest.mark.parametrize("tool_name", sorted(DEV_ONLY_TOOLS))
def test_dispatch_blocks_dev_tools_when_off(tool_name, monkeypatch):
    from tools import registry

    called = {"hit": False}

    def _spy(*args, **kwargs):
        called["hit"] = True
        return "should not run"

    monkeypatch.setitem(registry.TOOL_DISPATCH, tool_name, _spy)

    result = dispatch_tool(tool_name, {}, developer_mode=False)

    assert "unavailable" in result.lower()
    assert called["hit"] is False


def test_dispatch_allows_dev_tools_when_on(monkeypatch):
    from tools import registry

    monkeypatch.setitem(registry.TOOL_DISPATCH, "create_own_issue", lambda **kw: "ok")

    result = dispatch_tool("create_own_issue", {}, developer_mode=True)

    assert result == "ok"


def test_dashboard_tools_list_excludes_dev_tools_when_off(temp_env, monkeypatch):
    import config as config_module
    from dashboard.app import create_app

    monkeypatch.setattr(config_module.Config, "developer_mode", False)
    config_module.Config.invalidate_cache()

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    tools = client.get("/api/tools").get_json()["tools"]
    names = {t["name"] for t in tools}
    assert names.isdisjoint(DEV_ONLY_TOOLS)


def test_dashboard_tools_run_403_for_dev_tool_when_off(temp_env, monkeypatch):
    import config as config_module
    from dashboard.app import create_app

    monkeypatch.setattr(config_module.Config, "developer_mode", False)
    config_module.Config.invalidate_cache()

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    r = client.post("/api/tools/run", json={"name": "create_own_pr", "inputs": {}})
    assert r.status_code == 403
