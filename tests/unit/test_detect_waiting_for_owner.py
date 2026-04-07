# -*- coding: utf-8 -*-
"""Unit tests for detect_waiting_for_owner() and TaskItem.effective_status.

Ported from mission-control task-board-panel.tsx detectAwaitingOwner design
(commit fc4384b):
  - Active tasks (TODO/DOING) with matching keyword phrases → True
  - Terminal tasks (DONE/FAILED/CANCELLED/ARCHIVED) → never flagged
  - task_to_item() propagates effective_status = "waiting_for_owner" or None
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from src.server.routers.nexus_models import (
    detect_waiting_for_owner,
    task_to_item,
    TaskItem,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task(description: str, status: str = "todo") -> MagicMock:
    t = MagicMock()
    t.description = description
    t.status = status
    t.priority = "thought"
    t.project_id = None
    t.project_name = None
    t.workspace = None
    t.exec_user = None
    t.provider = "claude"
    t.alias = "claude"
    t.session_id = "sess_abc"
    t.id = "task001"
    t.created_at = datetime.now(timezone.utc)
    t.started_at = None
    t.completed_at = None
    t.archived_at = None
    t.attempt_count = 0
    t.error_message = None
    t.depends_on = []
    t.loop_enabled = False
    t.loop_iteration = 0
    t.loop_max_iterations = 1
    t.loop_keywords = []
    t.loop_keyword_found = False
    return t


# ---------------------------------------------------------------------------
# detect_waiting_for_owner — active statuses trigger on keyword match
# ---------------------------------------------------------------------------

class TestDetectWaitingForOwnerActiveStatuses:
    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_waiting_for_keyword_triggers(self, status: str):
        task = _task("Please complete this — waiting for your approval", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_needs_human_keyword_triggers(self, status: str):
        task = _task("This task needs human input to proceed", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_approval_needed_keyword_triggers(self, status: str):
        task = _task("approval needed before we can deploy", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_manual_action_keyword_triggers(self, status: str):
        task = _task("manual action required on the production server", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_browser_login_keyword_triggers(self, status: str):
        task = _task("Requires browser login to complete OAuth flow", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_account_creation_keyword_triggers(self, status: str):
        task = _task("account creation is needed for the new environment", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_blocked_on_owner_keyword_triggers(self, status: str):
        task = _task("blocked on owner — need credentials", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_awaiting_owner_keyword_triggers(self, status: str):
        task = _task("awaiting owner to merge the PR", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_awaiting_human_keyword_triggers(self, status: str):
        task = _task("awaiting human approval before continuing", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_human_required_keyword_triggers(self, status: str):
        task = _task("human required to validate the form", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_needs_owner_keyword_triggers(self, status: str):
        task = _task("this step needs owner sign-off", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_owner_action_keyword_triggers(self, status: str):
        task = _task("owner action required to unlock the resource", status)
        assert detect_waiting_for_owner(task) is True

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_waiting_on_keyword_triggers(self, status: str):
        task = _task("waiting on the client to provide access", status)
        assert detect_waiting_for_owner(task) is True

    def test_keyword_match_is_case_insensitive(self):
        task = _task("WAITING FOR approval from manager", "todo")
        assert detect_waiting_for_owner(task) is True

    def test_keyword_match_in_middle_of_description(self):
        task = _task("Task started; now needs human review of output", "doing")
        assert detect_waiting_for_owner(task) is True


# ---------------------------------------------------------------------------
# detect_waiting_for_owner — no match on ordinary descriptions
# ---------------------------------------------------------------------------

class TestDetectWaitingForOwnerNoMatch:
    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_normal_description_returns_false(self, status: str):
        task = _task("Implement the login feature", status)
        assert detect_waiting_for_owner(task) is False

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_empty_description_returns_false(self, status: str):
        task = _task("", status)
        assert detect_waiting_for_owner(task) is False

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_partial_keyword_no_match(self, status: str):
        # "waiting" alone is not a trigger — must be "waiting for" or "waiting on"
        task = _task("waiting to see the results", status)
        assert detect_waiting_for_owner(task) is False

    @pytest.mark.parametrize("status", ["todo", "doing"])
    def test_human_word_alone_no_match(self, status: str):
        # "human" alone is not a trigger — must be "needs human" or "human required"
        task = _task("optimize human-computer interaction", status)
        assert detect_waiting_for_owner(task) is False


# ---------------------------------------------------------------------------
# detect_waiting_for_owner — terminal statuses NEVER trigger
# ---------------------------------------------------------------------------

class TestDetectWaitingForOwnerTerminalStatuses:
    @pytest.mark.parametrize("status", ["done", "failed", "cancelled", "archived"])
    def test_terminal_status_never_flagged(self, status: str):
        task = _task("waiting for approval needed", status)
        assert detect_waiting_for_owner(task) is False

    @pytest.mark.parametrize("status", ["done", "failed", "cancelled", "archived"])
    def test_terminal_status_with_all_keywords(self, status: str):
        desc = (
            "waiting for waiting on needs human manual action approval needed "
            "owner action human required blocked on owner awaiting owner"
        )
        task = _task(desc, status)
        assert detect_waiting_for_owner(task) is False


# ---------------------------------------------------------------------------
# task_to_item — effective_status propagation
# ---------------------------------------------------------------------------

class TestTaskToItemEffectiveStatus:
    def test_effective_status_set_when_waiting_keyword_todo(self):
        task = _task("waiting for client credentials", "todo")
        item = task_to_item(task)
        assert item.effective_status == "waiting_for_owner"

    def test_effective_status_set_when_waiting_keyword_doing(self):
        task = _task("needs human approval at this step", "doing")
        item = task_to_item(task)
        assert item.effective_status == "waiting_for_owner"

    def test_effective_status_none_for_normal_task(self):
        task = _task("Write unit tests for the auth module", "todo")
        item = task_to_item(task)
        assert item.effective_status is None

    def test_effective_status_none_for_done_task_with_keyword(self):
        task = _task("was waiting for approval — now done", "done")
        item = task_to_item(task)
        assert item.effective_status is None

    def test_raw_status_unchanged_when_flagged(self):
        """effective_status is an overlay; the stored status is NOT modified."""
        task = _task("waiting for owner sign-off", "todo")
        item = task_to_item(task)
        assert item.status == "todo"            # stored status intact
        assert item.effective_status == "waiting_for_owner"

    def test_task_item_is_taskitem_instance(self):
        task = _task("Build a new feature", "todo")
        item = task_to_item(task)
        assert isinstance(item, TaskItem)
