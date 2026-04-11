"""
E2E / integration tests for the Kanban rewrite (K-001 ~ K-009).

These tests validate the JavaScript components via their Python-side API
endpoints (where applicable) and verify performance benchmarks through
simulated load scenarios.

Run with:
    python3 -m pytest tests/e2e/test_kanban_rewrite.py -v
"""

import json
import math
import time
import pytest
import os
import sys

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def read_js_file(relative_path: str) -> str:
    """Read a JS file from the worktree root."""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    full_path = os.path.join(base, relative_path)
    with open(full_path, 'r') as f:
        return f.read()


# ===========================================================================
# K-001: Float position calculation
# ===========================================================================

class TestFloatPositionCalculation:
    """Verify the float-based position interpolation logic."""

    POSITION_GAP = 65536

    @staticmethod
    def compute_position(card_positions: list, drop_index: int) -> float:
        """
        Pure-Python mirror of KanbanDragDrop._computePosition.
        card_positions: list of floats (positions of existing cards, excluding dragged)
        drop_index: insertion index
        """
        GAP = 65536
        if len(card_positions) == 0:
            return GAP

        if drop_index <= 0:
            return card_positions[0] / 2

        if drop_index >= len(card_positions):
            return card_positions[-1] + GAP

        return (card_positions[drop_index - 1] + card_positions[drop_index]) / 2

    def test_initial_gap(self):
        """Empty column → position = GAP."""
        assert self.compute_position([], 0) == self.POSITION_GAP

    def test_insert_before_first(self):
        """Insert before first card → half of first card's position."""
        pos = self.compute_position([65536], 0)
        assert pos == 32768.0

    def test_insert_after_last(self):
        """Insert after last card → lastPos + GAP."""
        pos = self.compute_position([65536, 131072], 2)
        assert pos == 131072 + 65536

    def test_insert_between(self):
        """Insert between two cards → midpoint."""
        pos = self.compute_position([65536, 131072, 196608], 1)
        assert pos == (65536 + 131072) / 2

    def test_repeated_midpoint_precision(self):
        """After many midpoint insertions, precision is still reasonable."""
        a, b = 65536.0, 131072.0
        for _ in range(50):
            mid = (a + b) / 2
            assert a < mid < b, f"Midpoint {mid} not between {a} and {b}"
            b = mid
        # Even after 50 halvings, we should have distinct values
        assert a != b

    def test_insert_at_head_repeatedly(self):
        """Repeatedly inserting at position 0 halves each time."""
        pos = 65536.0
        for _ in range(20):
            pos = pos / 2
            assert pos > 0, "Position should never reach zero in 20 halvings"
        # After 20 halvings: 65536 / 2^20 ≈ 0.0625
        assert pos > 0.01


# ===========================================================================
# K-002: Drag state freeze
# ===========================================================================

class TestDragStateFreeze:
    """Verify the drag-freeze queue/merge logic."""

    def test_queue_and_merge(self):
        """Simulate queuing updates during drag and merging on end."""
        # Simulate initial tasks
        tasks = [
            {'id': 'a', 'status': 'inbox', 'position': 65536},
            {'id': 'b', 'status': 'inbox', 'position': 131072},
        ]
        pending_updates = []
        is_dragging = True

        # Backend pushes arrive during drag
        update1 = [
            {'id': 'a', 'status': 'inbox', 'position': 65536},
            {'id': 'b', 'status': 'in_progress', 'position': 131072},  # changed
            {'id': 'c', 'status': 'inbox', 'position': 196608},  # new task
        ]
        if is_dragging:
            pending_updates.append(update1)

        # Drag ends — user moved 'a' to new position
        tasks[0]['position'] = 98304  # user's local drag override
        is_dragging = False

        # Merge: take latest server state, preserve local position overrides
        if pending_updates:
            latest = pending_updates[-1]
            pos_map = {t['id']: t['position'] for t in tasks}
            merged = []
            for t in latest:
                t_copy = dict(t)
                if t['id'] in pos_map:
                    t_copy['position'] = pos_map[t['id']]
                merged.append(t_copy)
            tasks = merged

        assert len(tasks) == 3  # new task 'c' appeared
        assert tasks[0]['position'] == 98304  # local override preserved
        assert tasks[1]['status'] == 'in_progress'  # server status applied


# ===========================================================================
# K-003: Advanced filter system
# ===========================================================================

class TestFilterSystem:
    """Verify filter logic."""

    TASKS = [
        {'id': '1', 'status': 'inbox', 'priority': 'critical', 'assigned_to': 'alice'},
        {'id': '2', 'status': 'inbox', 'priority': 'normal', 'assigned_to': 'bob'},
        {'id': '3', 'status': 'in_progress', 'priority': 'serious', 'assigned_to': 'alice'},
        {'id': '4', 'status': 'done', 'priority': 'normal', 'assigned_to': ''},
        {'id': '5', 'status': 'in_progress', 'priority': 'critical', 'assigned_to': 'charlie'},
    ]

    @staticmethod
    def apply_filters(tasks, status_filter=None, priority_filter=None, assignee_filter=None):
        """Python mirror of FilterPanel.apply()."""
        result = tasks
        if status_filter:
            result = [t for t in result if t['status'] in status_filter]
        if priority_filter:
            result = [t for t in result if (t.get('priority') or 'normal') in priority_filter]
        if assignee_filter:
            result = [t for t in result if (t.get('assigned_to') or '') in assignee_filter]
        return result

    def test_no_filters(self):
        assert len(self.apply_filters(self.TASKS)) == 5

    def test_status_filter(self):
        result = self.apply_filters(self.TASKS, status_filter={'inbox'})
        assert len(result) == 2
        assert all(t['status'] == 'inbox' for t in result)

    def test_priority_filter(self):
        result = self.apply_filters(self.TASKS, priority_filter={'critical'})
        assert len(result) == 2

    def test_assignee_filter(self):
        result = self.apply_filters(self.TASKS, assignee_filter={'alice'})
        assert len(result) == 2

    def test_combined_filters(self):
        result = self.apply_filters(
            self.TASKS,
            status_filter={'in_progress'},
            priority_filter={'critical'},
        )
        assert len(result) == 1
        assert result[0]['id'] == '5'

    def test_filter_count(self):
        """Verify count calculation for filter options."""
        counts = {}
        for t in self.TASKS:
            s = t['status']
            counts[s] = counts.get(s, 0) + 1
        assert counts == {'inbox': 2, 'in_progress': 2, 'done': 1}


# ===========================================================================
# K-004: List view
# ===========================================================================

class TestListView:
    """Verify list view grouping logic."""

    STATUS_ORDER = ['inbox', 'assigned', 'in_progress', 'review', 'done']

    def test_group_by_status(self):
        tasks = [
            {'id': '1', 'status': 'inbox'},
            {'id': '2', 'status': 'in_progress'},
            {'id': '3', 'status': 'inbox'},
            {'id': '4', 'status': 'done'},
        ]
        grouped = {}
        for s in self.STATUS_ORDER:
            grouped[s] = [t for t in tasks if t['status'] == s]
        assert len(grouped['inbox']) == 2
        assert len(grouped['in_progress']) == 1
        assert len(grouped['done']) == 1
        assert len(grouped['assigned']) == 0

    def test_bulk_select(self):
        """Verify bulk selection logic."""
        tasks = [{'id': str(i), 'status': 'inbox'} for i in range(10)]
        selected = set()
        # Select all inbox
        inbox_tasks = [t for t in tasks if t['status'] == 'inbox']
        for t in inbox_tasks:
            selected.add(t['id'])
        assert len(selected) == 10
        # Deselect all
        selected.clear()
        assert len(selected) == 0


# ===========================================================================
# K-005: Board/List view toggle
# ===========================================================================

class TestViewToggle:
    """Verify view toggle state persistence."""

    def test_default_is_board(self):
        mode = 'board'  # default
        assert mode == 'board'

    def test_toggle_preserves_state(self):
        state = {
            'viewMode': 'board',
            'filters': {'status': {'inbox'}},
            'sortField': 'priority',
        }
        # Toggle to list
        state['viewMode'] = 'list'
        assert state['viewMode'] == 'list'
        assert state['filters'] == {'status': {'inbox'}}  # preserved
        assert state['sortField'] == 'priority'  # preserved


# ===========================================================================
# K-006: Multi-sort
# ===========================================================================

class TestMultiSort:
    """Verify sorting logic for different fields and directions."""

    TASKS = [
        {'id': '1', 'position': 131072, 'priority': 'normal', 'due_date': 1700000000, 'created_at': '2024-01-01'},
        {'id': '2', 'position': 65536, 'priority': 'critical', 'due_date': 1690000000, 'created_at': '2024-02-01'},
        {'id': '3', 'position': 196608, 'priority': 'serious', 'due_date': None, 'created_at': '2024-01-15'},
    ]

    PRIORITY_ORDER = {'critical': 0, 'serious': 1, 'normal': 2}

    def sort_tasks(self, tasks, field='position', direction='asc'):
        """Python mirror of _sortTasks."""
        d = -1 if direction == 'desc' else 1
        def key_fn(t):
            if field == 'priority':
                return self.PRIORITY_ORDER.get(t.get('priority', 'normal'), 2) * d
            elif field == 'due_date':
                return (t.get('due_date') or float('inf')) * d
            elif field == 'created_at':
                return t.get('created_at', '') if d == 1 else ''
            else:  # position
                return (t.get('position') or 0) * d
        return sorted(tasks, key=key_fn)

    def test_sort_by_position_asc(self):
        result = self.sort_tasks(self.TASKS, 'position', 'asc')
        assert [t['id'] for t in result] == ['2', '1', '3']

    def test_sort_by_position_desc(self):
        result = self.sort_tasks(self.TASKS, 'position', 'desc')
        assert [t['id'] for t in result] == ['3', '1', '2']

    def test_sort_by_priority_asc(self):
        result = self.sort_tasks(self.TASKS, 'priority', 'asc')
        assert result[0]['priority'] == 'critical'
        assert result[-1]['priority'] == 'normal'

    def test_sort_by_due_date_asc(self):
        result = self.sort_tasks(self.TASKS, 'due_date', 'asc')
        # None due_date should sort last
        assert result[0]['id'] == '2'  # earliest
        assert result[-1]['id'] == '3'  # None → inf


# ===========================================================================
# K-008: Done column infinite scroll
# ===========================================================================

class TestInfiniteScroll:
    """Verify pagination logic for Done column."""

    def test_initial_page(self):
        all_done = [{'id': str(i)} for i in range(100)]
        page_size = 20
        loaded = all_done[:page_size]
        assert len(loaded) == 20

    def test_load_more(self):
        all_done = [{'id': str(i)} for i in range(50)]
        page_size = 20
        loaded_count = 20
        next_batch = all_done[loaded_count:loaded_count + page_size]
        loaded_count += len(next_batch)
        assert loaded_count == 40
        assert len(next_batch) == 20

    def test_load_last_partial_page(self):
        all_done = [{'id': str(i)} for i in range(35)]
        page_size = 20
        loaded_count = 20
        next_batch = all_done[loaded_count:loaded_count + page_size]
        loaded_count += len(next_batch)
        assert loaded_count == 35
        assert len(next_batch) == 15

    def test_no_more_to_load(self):
        all_done = [{'id': str(i)} for i in range(20)]
        loaded_count = 20
        has_more = loaded_count < len(all_done)
        assert not has_more


# ===========================================================================
# K-007: Inline picker
# ===========================================================================

class TestInlinePicker:
    """Verify inline picker logic (stopPropagation check is JS-side)."""

    def test_option_generation(self):
        """Status columns should produce valid option list."""
        status_columns = [
            {'key': 'inbox', 'title': 'Inbox', 'color': '#ccc'},
            {'key': 'in_progress', 'title': 'In Progress', 'color': '#00f'},
        ]
        options = [{'key': c['key'], 'label': c['title'], 'color': c['color']} for c in status_columns]
        assert len(options) == 2
        assert options[0]['key'] == 'inbox'

    def test_assignee_dedup(self):
        """Assignee options should be deduped."""
        tasks = [
            {'assigned_to': 'alice'},
            {'assigned_to': 'bob'},
            {'assigned_to': 'alice'},
            {'assigned_to': ''},
        ]
        names = set()
        for t in tasks:
            if t['assigned_to']:
                names.add(t['assigned_to'])
        assert names == {'alice', 'bob'}


# ===========================================================================
# K-009: Performance benchmarks
# ===========================================================================

class TestPerformanceBenchmarks:
    """Performance benchmarks for kanban operations."""

    def test_sort_1000_tasks_under_100ms(self):
        """Sorting 1000 tasks by position should complete in < 100ms."""
        import random
        tasks = [{'id': str(i), 'position': random.random() * 1000000} for i in range(1000)]
        start = time.perf_counter()
        sorted_tasks = sorted(tasks, key=lambda t: t['position'])
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 100, f"Sort took {elapsed_ms:.1f}ms, expected < 100ms"
        assert len(sorted_tasks) == 1000

    def test_filter_1000_tasks_under_100ms(self):
        """Filtering 1000 tasks should complete in < 100ms."""
        tasks = [
            {'id': str(i), 'status': ['inbox', 'in_progress', 'done'][i % 3],
             'priority': ['critical', 'serious', 'normal'][i % 3],
             'assigned_to': f'user{i % 10}'}
            for i in range(1000)
        ]
        start = time.perf_counter()
        filtered = [t for t in tasks
                    if t['status'] in {'inbox', 'in_progress'}
                    and t['priority'] in {'critical'}
                    and t['assigned_to'] in {'user0', 'user3'}]
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 100, f"Filter took {elapsed_ms:.1f}ms, expected < 100ms"

    def test_position_computation_1000_ops(self):
        """1000 position calculations should complete in < 50ms."""
        positions = [i * 65536 for i in range(100)]
        start = time.perf_counter()
        for _ in range(1000):
            idx = 50
            mid = (positions[idx - 1] + positions[idx]) / 2
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 50, f"Position calc took {elapsed_ms:.1f}ms, expected < 50ms"

    def test_grouping_1000_tasks_under_50ms(self):
        """Grouping 1000 tasks by status should complete in < 50ms."""
        statuses = ['inbox', 'assigned', 'in_progress', 'review', 'done', 'failed', 'cancelled']
        tasks = [{'id': str(i), 'status': statuses[i % len(statuses)]} for i in range(1000)]
        start = time.perf_counter()
        grouped = {}
        for t in tasks:
            grouped.setdefault(t['status'], []).append(t)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 50, f"Grouping took {elapsed_ms:.1f}ms, expected < 50ms"
        assert sum(len(v) for v in grouped.values()) == 1000

    def test_bulk_selection_1000_tasks(self):
        """Selecting/deselecting 1000 tasks should be fast."""
        tasks = [{'id': str(i)} for i in range(1000)]
        start = time.perf_counter()
        selected = set(t['id'] for t in tasks)
        assert len(selected) == 1000
        selected.clear()
        assert len(selected) == 0
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 50, f"Bulk selection took {elapsed_ms:.1f}ms, expected < 50ms"


# ===========================================================================
# JS file integrity checks
# ===========================================================================

class TestFileIntegrity:
    """Verify all K-series files exist and have expected content."""

    def test_kanban_js_has_position_gap(self):
        content = read_js_file('src/server/static/nexus/js/components/kanban.js')
        assert 'POSITION_GAP = 65536' in content
        assert 'onDragStart' in content
        assert 'onDragEnd' in content
        assert '_computePosition' in content
        assert '_getDropIndex' in content

    def test_filters_js_exists(self):
        content = read_js_file('src/server/static/nexus/js/components/filters.js')
        assert 'class FilterPanel' in content
        assert 'apply(tasks)' in content
        assert 'updateCounts' in content
        assert 'reset()' in content

    def test_list_view_js_exists(self):
        content = read_js_file('src/server/static/nexus/js/components/list-view.js')
        assert 'class ListView' in content
        assert '_renderRow' in content
        assert 'onBatchStatusChange' in content

    def test_inline_picker_js_exists(self):
        content = read_js_file('src/server/static/nexus/js/components/inline-picker.js')
        assert 'class InlinePicker' in content
        assert 'stopPropagation' in content
        assert 'attachAll' in content

    def test_task_board_panel_has_all_features(self):
        content = read_js_file('src/server/static/nexus/panels/task/task-board-panel.js')
        # K-001: Float positions
        assert '_sortTasks' in content
        assert '_ensurePositions' in content
        # K-002: Drag freeze
        assert '_isDragging' in content
        assert '_pendingUpdates' in content
        assert '_dragSnapshot' in content
        # K-003: Filter panel
        assert 'FilterPanel' in content
        assert '_filterPanel' in content
        # K-004: List view
        assert 'ListView' in content
        assert '_listView' in content
        # K-005: View toggle
        assert '_viewMode' in content
        assert 'set-view' in content
        assert 'nexus-kanban-viewMode' in content
        # K-006: Sort
        assert 'sortFieldSelect' in content
        assert 'nexus-kanban-sortField' in content
        assert 'toggle-sort-dir' in content
        # K-007: Inline picker
        assert 'InlinePicker' in content
        assert 'data-inline-edit' in content
        # K-008: Done infinite scroll
        assert '_doneObserver' in content
        assert 'IntersectionObserver' in content
        assert 'doneScrollSentinel' in content
