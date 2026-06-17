"""Real browser coverage for the top-level Agents page shell."""

from __future__ import annotations

import socket
import threading
import time
from contextlib import ExitStack, closing
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
import uvicorn
from playwright.sync_api import sync_playwright


pytestmark = [pytest.mark.integration, pytest.mark.slow]


class FakeAgentsTaskQueue:
    def list_tasks(self, page=1, page_size=200, status=None):
        tasks = [
            SimpleNamespace(status="running"),
            SimpleNamespace(status="pending"),
            SimpleNamespace(status="failed"),
        ]
        return tasks, len(tasks)


class FakeTokenTracker:
    def get_stats(self, since=None):
        return SimpleNamespace(
            total_requests=6,
            total_prompt_tokens=1200,
            total_completion_tokens=300,
            total_tokens=1500,
            total_cost_usd=1.2345,
        )

    def get_attribution_breakdown(self, since=None):
        return {
            "by_workspace": [
                {
                    "key": "/tmp/agents",
                    "count": 6,
                    "prompt_tokens": 1200,
                    "completion_tokens": 300,
                    "total_tokens": 1500,
                    "total_cost_usd": 1.2345,
                }
            ],
            "by_agent": [
                {
                    "key": "agent-worker-2",
                    "count": 4,
                    "prompt_tokens": 900,
                    "completion_tokens": 250,
                    "total_tokens": 1150,
                    "total_cost_usd": 0.9345,
                },
                {
                    "key": "agent-planner",
                    "count": 2,
                    "prompt_tokens": 300,
                    "completion_tokens": 50,
                    "total_tokens": 350,
                    "total_cost_usd": 0.3000,
                },
            ],
            "by_runtime": [
                {
                    "key": "swarm",
                    "count": 6,
                    "prompt_tokens": 1200,
                    "completion_tokens": 300,
                    "total_tokens": 1500,
                    "total_cost_usd": 1.2345,
                }
            ],
        }


def _build_agent_registry():
    from src.server.services.agent_registry import AgentRegistry, AgentState

    registry = AgentRegistry()
    worker = registry.register(
        name="Worker 2",
        provider="claude",
        workspace="/tmp/agents",
        capabilities=["planning", "review"],
        model="claude-3-sonnet",
        alias="claude",
        agent_id="agent-worker-2",
        metadata={
            "exec_user": "ubuntu",
            "memory_summary": "Shared session context available",
            "memory_entries": ["brief", "notes"],
        },
    )
    registry.update_status(worker.id, AgentState.RUNNING)

    planner = registry.register(
        name="Planner",
        provider="codex",
        workspace="/tmp/agents",
        capabilities=["memory", "analysis"],
        model="gpt-4o",
        alias="codex",
        agent_id="agent-planner",
        metadata={
            "exec_user": "ubuntu",
            "memory_summary": "Read-only memory",
            "memory_entries": ["timeline"],
        },
    )
    registry.update_status(planner.id, AgentState.ERROR)
    return registry


@pytest.fixture(scope="module")
def live_server():
    from src.server import app as server_app

    registry = _build_agent_registry()

    with ExitStack() as stack:
        stack.enter_context(patch.dict("src.server.routers.nexus_agents._AGENT_BINDINGS", {}, clear=True))
        stack.enter_context(patch("src.server.services.agent_registry.get_registry", return_value=registry))
        stack.enter_context(patch("src.core.cost.tracker.get_token_tracker", return_value=FakeTokenTracker()))
        stack.enter_context(patch("src.server.routers.nexus_models.get_task_queue", return_value=FakeAgentsTaskQueue()))

        app = server_app.create_app_with_overrides(
            use_env=False,
            startup_policy_overrides={
                "start_task_executor": False,
                "start_task_scheduler": False,
                "start_channel_service": False,
                "start_terminal_manager": False,
                "start_evolution_service": False,
            },
        )

        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.bind(("127.0.0.1", 0))
            host, port = sock.getsockname()

        config = uvicorn.Config(app, host=host, port=port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        base_url = f"http://{host}:{port}"
        deadline = time.time() + 20
        last_error = None
        while time.time() < deadline:
            try:
                response = requests.get(f"{base_url}/", timeout=1)
                if response.status_code < 500:
                    yield base_url
                    break
            except Exception as exc:  # pragma: no cover - startup polling only
                last_error = exc
                time.sleep(0.2)
        else:  # pragma: no cover - hard failure path
            raise RuntimeError(f"Timed out waiting for live server: {last_error}")

        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        yield browser
        browser.close()


@pytest.fixture()
def page(browser):
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    yield page
    page.close()


def test_agents_page_default_state_renders_overview_and_list(live_server, page):
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto(f"{live_server}/?page=agents", wait_until="commit", timeout=20_000)
    page.wait_for_timeout(2500)

    assert page.locator('.page-nav-btn[data-page="agents"]').evaluate("el => el.classList.contains('active')")
    assert page.locator("#agentsView").evaluate("el => el.classList.contains('active')")
    assert page.locator("#agentsPageShell").evaluate("el => el.dataset.agentsMode") == "overview"
    assert page.locator("#agentsSearchInput").count() == 1
    assert page.locator("#agentsStatusFilter").count() == 1
    assert page.locator("#agentsList .agents-list-item").count() >= 2  # 2 seeded agents (team seed removed)
    assert page.locator("#agentsOverviewPanel").is_visible()
    assert page.locator("#agentsOverviewPanel").text_content().find("Agents Overview") >= 0
    assert not page_errors


