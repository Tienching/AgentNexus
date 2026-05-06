"""Real browser/API regression tests for the task board.

These replace the old pseudo-E2E mirror checks with actual HTTP + browser
coverage against a live FastAPI server.
"""

from __future__ import annotations

import socket
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import uvicorn
from playwright.sync_api import sync_playwright


pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(scope="module")
def live_server():
    from src.server import app as server_app

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


def _create_task(
    base_url: str,
    description: str,
    *,
    exec_user: str = "ubuntu",
    session_id: str | None = None,
) -> dict:
    workspace = Path("/tmp/kanban-e2e")
    workspace.mkdir(parents=True, exist_ok=True)
    payload = {
        "description": description,
        "provider": "claude",
        "workspace": str(workspace),
        "agent": "ubuntu",
    }
    if session_id:
        payload["session_id"] = session_id

    response = requests.post(
        f"{base_url}/api/nexus/tasks",
        params={"exec_user": exec_user},
        json=payload,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _set_task_status(base_url: str, task_id: str, status: str, *, exec_user: str = "ubuntu") -> dict:
    response = requests.patch(
        f"{base_url}/api/nexus/tasks/{task_id}/status",
        params={"exec_user": exec_user},
        json={"status": status},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _create_schedule(base_url: str, name: str) -> dict:
    workspace = Path("/tmp/kanban-e2e")
    workspace.mkdir(parents=True, exist_ok=True)
    response = requests.post(
        f"{base_url}/api/nexus/schedules",
        json={
            "name": name,
            "run_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "description": f"{name} description",
            "provider": "claude",
            "workspace": str(workspace),
            "exec_user": "ubuntu",
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def _wait_for_task_page(page, *, require_board: bool = True) -> None:
    page.wait_for_selector("#taskPageContainer", timeout=10_000)
    page.wait_for_selector("#taskSurfaceSwitcher-global", timeout=10_000)
    if require_board:
        page.wait_for_selector("#taskSearch-global", timeout=10_000)
    page.wait_for_timeout(1000)


def test_task_board_shows_empty_state_when_filters_match_no_tasks(live_server, page):
    missing_search = f"no-such-task-{uuid.uuid4().hex[:10]}"

    page.goto(f"{live_server}/?page=task", wait_until="commit", timeout=20_000)
    _wait_for_task_page(page)

    page.fill("#taskSearch-global", missing_search)
    page.wait_for_timeout(2500)

    assert page.locator("#taskBoardEmptyState-global").is_visible()
    assert page.locator("#kanbanBoard-global").evaluate("el => el.hidden") is True
    assert page.locator("#summaryStrip-global").evaluate("el => el.hidden") is True


def test_task_board_renders_real_api_task_and_detail(live_server, page):
    task_description = f"kanban e2e {uuid.uuid4().hex[:8]}"
    target_session_id = f"target-session-{uuid.uuid4().hex[:8]}"
    task = _create_task(live_server, task_description, session_id=target_session_id)

    assert task["session_id"] == target_session_id

    page.goto(f"{live_server}/?page=task", wait_until="commit", timeout=20_000)
    _wait_for_task_page(page)

    assert page.locator("#taskPageContainer").is_visible()
    assert page.locator("#kanbanBoard-global").is_visible()
    card = page.locator(f'#kanbanBoard-global .task-card[data-task-id="{task["id"]}"]')
    assert card.count() == 1
    assert task_description in card.text_content()

    card.click()
    page.wait_for_timeout(1000)

    assert page.locator("#taskDetail-global").evaluate("el => !el.classList.contains('hidden')")
    assert page.locator("#taskDetail-global").evaluate("el => el.dataset.taskId") == task["id"]



def test_task_board_navigation_survives_refresh_and_api_updates(live_server, page):
    description = f"kanban refresh {uuid.uuid4().hex[:8]}"
    task = _create_task(live_server, description)
    refreshed_session_id = f"target-session-{uuid.uuid4().hex[:8]}"

    page.goto(f"{live_server}/?page=task", wait_until="commit", timeout=20_000)
    _wait_for_task_page(page)

    card = page.locator(f'#kanbanBoard-global .task-card[data-task-id="{task["id"]}"]')
    assert card.count() == 1

    # Mutate the task through the API and confirm the browser picks up the new data
    requests.patch(
        f"{live_server}/api/nexus/tasks/{task['id']}",
        params={"exec_user": "ubuntu"},
        json={"description": f"{description} updated", "session_id": refreshed_session_id},
        timeout=10,
    ).raise_for_status()

    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    refreshed_card = page.locator(f'#kanbanBoard-global .task-card[data-task-id="{task["id"]}"]')
    assert refreshed_card.count() >= 1
    assert refreshed_card.filter(has_text="updated").count() >= 1


def test_task_summary_strip_reports_total_active_running_reviewing_failed_cancelled_and_scheduled(live_server, page):
    exec_user = f"summary-{uuid.uuid4().hex[:8]}"
    _create_task(live_server, f"summary pending {uuid.uuid4().hex[:8]}", exec_user=exec_user)
    running = _create_task(live_server, f"summary running {uuid.uuid4().hex[:8]}", exec_user=exec_user)
    reviewing = _create_task(live_server, f"summary reviewing {uuid.uuid4().hex[:8]}", exec_user=exec_user)
    failed = _create_task(live_server, f"summary failed {uuid.uuid4().hex[:8]}", exec_user=exec_user)

    _set_task_status(live_server, running["id"], "running", exec_user=exec_user)
    _set_task_status(live_server, reviewing["id"], "running", exec_user=exec_user)
    _set_task_status(live_server, reviewing["id"], "in_review", exec_user=exec_user)
    _set_task_status(live_server, failed["id"], "running", exec_user=exec_user)
    _set_task_status(live_server, failed["id"], "failed", exec_user=exec_user)

    page.goto(f"{live_server}/?page=task", wait_until="commit", timeout=20_000)
    _wait_for_task_page(page)

    page.evaluate(
        """(user) => {
            const select = document.getElementById('globalUserFilter');
            if (!select) return;
            if (![...select.options].some((opt) => opt.value === user)) {
                const option = document.createElement('option');
                option.value = user;
                option.textContent = user;
                select.appendChild(option);
            }
            select.value = user;
            select.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        exec_user,
    )
    page.wait_for_timeout(2500)

    assert page.locator('.summary-card[data-metric="total"] .summary-value').text_content() == "4"
    assert page.locator('.summary-card[data-metric="active"] .summary-value').text_content() == "3"
    assert page.locator('.summary-card[data-metric="running"] .summary-value').text_content() == "1"
    assert page.locator('.summary-card[data-metric="reviewing"] .summary-value').text_content() == "1"
    assert page.locator('.summary-card[data-metric="failed"] .summary-value').text_content() == "1"
    assert page.locator('.summary-card[data-metric="cancelled"] .summary-value').text_content() == "0"
    assert page.locator('.summary-card[data-metric="scheduled"] .summary-value').text_content() == "0"
    assert page.locator('.summary-card[data-metric="scheduled"] .summary-label').text_content() == "Scheduled"


def test_task_page_secondary_surfaces_cover_board_and_schedules_only(live_server, page):
    schedule_name = f"kanban schedule {uuid.uuid4().hex[:8]}"
    _create_schedule(live_server, schedule_name)

    page.goto(f"{live_server}/?page=task&taskSurface=schedules", wait_until="commit", timeout=20_000)
    _wait_for_task_page(page, require_board=False)

    assert page.locator('#taskSurfaceSwitcher-global [data-surface="board"]').is_visible()
    assert page.locator('#taskSurfaceSwitcher-global [data-surface="schedules"]').is_visible()
    assert page.locator('#taskSurfaceSwitcher-global [data-surface="workflows"]').count() == 0
    assert page.locator("#taskSurfaceSchedules-global").is_visible()
    assert schedule_name in page.locator("#scheduleList-global").text_content()
    assert page.locator('#kanbanBoard-global .kanban-column[data-status="cancelled"]').count() == 1

    page.goto(f"{live_server}/?page=task&taskSurface=workflows", wait_until="commit", timeout=20_000)
    _wait_for_task_page(page)
    assert "taskSurface=workflows" not in page.url
    assert page.locator("#taskSurfaceBoard-global").is_visible()
    assert page.locator('#taskSurfaceSwitcher-global [data-surface="workflows"]').count() == 0
