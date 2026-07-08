"""Real browser smoke tests for Nexus UI flows.

These tests start an isolated FastAPI app and exercise the browser against an
actual HTTP server, replacing Python-mirror pseudo-E2E checks for key paths.
"""

from __future__ import annotations

import socket
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path

import pytest
import requests
import uvicorn
from playwright.sync_api import sync_playwright


pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture()
def live_server(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_DB_PATH", str(tmp_path / "nexus-e2e.db"))

    from src.server import app as server_app

    app = server_app.create_app_with_overrides(
        use_env=False,
        settings_overrides={"log_dir": str(tmp_path / "logs")},
        startup_policy_overrides={
            "start_task_executor": False,
            "start_task_scheduler": False,
            "start_terminal_manager": False,
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
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture()
def page(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 960})
    page = context.new_page()
    yield page
    context.close()


def _create_task(base_url: str, description: str) -> dict:
    workspace = Path("/tmp/browser-smoke")
    workspace.mkdir(parents=True, exist_ok=True)
    response = requests.post(
        f"{base_url}/api/nexus/tasks",
        params={"exec_user": "ubuntu"},
        json={
            "description": description,
            "provider": "claude",
            "workspace": str(workspace),
            "agent": "ubuntu",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _create_session(base_url: str, title: str) -> dict:
    response = requests.post(
        f"{base_url}/api/nexus/sessions",
        json={
            "username": "ubuntu",
            "provider": "claude",
            "title": title,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def test_browser_boots_without_reference_errors(live_server, page):
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto(f"{live_server}/", wait_until="commit", timeout=20_000)
    page.wait_for_timeout(1500)

    assert page.locator("#app").evaluate("el => getComputedStyle(el).display !== 'none'")
    assert page.locator("#chatView").evaluate("el => el.classList.contains('active')")
    assert page.locator(".new-session-view").count() == 1 or page.locator(".session-item.active").count() >= 1
    assert not page_errors


def test_chat_auto_selects_first_runtime_session(live_server, page):
    session = _create_session(live_server, f"chat auto select {uuid.uuid4().hex[:8]}")

    page.goto(f"{live_server}/", wait_until="commit", timeout=20_000)
    page.wait_for_timeout(2000)

    assert page.locator(f'.session-item[data-session-id="{session["id"]}"]').count() == 1
    assert page.locator(f'.session-item[data-session-id="{session["id"]}"]').evaluate(
        "el => el.classList.contains('active')"
    )
    assert "Select a chat" not in page.locator('[id^="chatDetail-"]').first.inner_text()


def test_task_deep_link_opens_requested_detail_and_tab(live_server, page):
    task = _create_task(live_server, f"browser deep link {uuid.uuid4().hex[:8]}")
    task_id = task["id"]

    page.goto(
        f"{live_server}/?page=task&task={task_id}&taskTab=timeline",
        wait_until="commit",
        timeout=20_000,
    )
    page.wait_for_timeout(2500)

    assert page.locator('.page-nav-btn[data-page="task"]').evaluate(
        "el => el.classList.contains('active')"
    )
    assert page.locator("#taskDetail-global").evaluate(
        "el => !el.classList.contains('hidden')"
    )
    assert page.locator("#taskDetail-global").evaluate("el => el.dataset.taskId") == task_id
    assert page.locator("#taskDetail-global .task-detail-tab.active").text_content() == "Timeline"


def test_task_surfaces_are_visible_and_settings_hides_legacy_entries(live_server, page):
    page.goto(f"{live_server}/?page=task", wait_until="commit", timeout=20_000)
    page.wait_for_selector("#taskSurfaceSwitcher-global", timeout=10_000)
    page.wait_for_timeout(1000)

    assert page.locator("#taskPageContainer").is_visible()
    assert page.locator('#taskSurfaceSwitcher-global [data-surface="board"]').is_visible()
    assert page.locator('#taskSurfaceSwitcher-global [data-surface="schedules"]').is_visible()
    assert page.locator('#taskSurfaceSwitcher-global [data-surface="workflows"]').count() == 0
    assert page.locator('#kanbanBoard-global .kanban-column[data-status="cancelled"]').count() == 1

    page.goto(f"{live_server}/?page=settings", wait_until="commit", timeout=20_000)
    page.wait_for_timeout(2000)

    assert page.locator('.settings-tab[data-settings-tab="workflows"]').count() == 0
    assert page.locator('.settings-tab[data-settings-tab="scheduling"]').count() == 0


def test_settings_single_page_sections_and_legacy_dashboard_route_work(live_server, page):
    page.goto(f"{live_server}/?page=dashboard", wait_until="commit", timeout=20_000)
    page.wait_for_timeout(2000)

    assert page.locator('.page-nav-btn[data-page="settings"]').evaluate(
        "el => el.classList.contains('active')"
    )

    page.goto(f"{live_server}/?page=settings", wait_until="commit", timeout=20_000)
    page.wait_for_timeout(2000)

    assert page.locator('.page-nav-btn[data-page="settings"]').evaluate(
        "el => el.classList.contains('active')"
    )
    assert page.locator('[data-settings-nav=\"provider\"]').count() == 1
    assert page.locator('[data-settings-nav=\"skills\"]').count() == 1
    assert page.locator('[data-settings-nav=\"runtime\"]').count() == 1
    assert page.locator('[data-settings-section=\"basic\"]').count() == 1
    assert page.locator('[data-settings-section=\"skills\"]').count() == 1
    assert page.locator('[data-settings-section=\"safety\"]').count() == 1


def test_settings_section_navigation_supports_provider_and_browser_back(live_server, page):
    page.goto(f"{live_server}/?page=settings", wait_until="commit", timeout=20_000)
    page.wait_for_timeout(2000)

    assert "settingsSection=" not in page.url
    assert page.locator('[data-settings-nav="provider"]').get_attribute("aria-current") == "true"

    page.click('[data-settings-nav="skills"]')
    page.wait_for_timeout(1000)
    assert "settingsSection=skills" in page.url
    assert page.locator('[data-settings-nav="skills"]').get_attribute("aria-current") == "true"

    page.click('[data-settings-nav="runtime"]')
    page.wait_for_timeout(1000)
    assert "settingsSection=runtime" in page.url
    assert page.locator('[data-settings-nav="runtime"]').get_attribute("aria-current") == "true"

    page.go_back(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    assert "settingsSection=skills" in page.url
    assert page.locator('[data-settings-nav="skills"]').get_attribute("aria-current") == "true"

    page.go_back(wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    assert "settingsSection=" not in page.url
    assert page.locator('[data-settings-nav="provider"]').get_attribute("aria-current") == "true"


def test_global_search_task_result_navigates_to_task_deep_link(live_server, page):
    description = f"browser search target {uuid.uuid4().hex[:8]}"
    task = _create_task(live_server, description)
    task_id = task["id"]

    page.goto(f"{live_server}/", wait_until="commit", timeout=20_000)
    page.wait_for_timeout(1500)

    page.click("#globalSearchBtn")
    page.fill("#globalSearchInput", description)
    page.click("#globalSearchSubmitBtn")
    page.wait_for_timeout(1500)
    page.locator("#globalSearchResults .search-result-item").first.click()
    page.wait_for_timeout(2000)

    assert f"task={task_id}" in page.url
    assert page.locator('.page-nav-btn[data-page="task"]').evaluate(
        "el => el.classList.contains('active')"
    )
    assert page.locator("#taskDetail-global").evaluate("el => el.dataset.taskId") == task_id
