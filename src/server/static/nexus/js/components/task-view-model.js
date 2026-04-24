/**
 * TaskViewModel — centralized read-model adapter for the Task Workbench.
 *
 * Provides stable lane_status, runtime_status, review_state, display_group
 * and summary metrics, replacing scattered normalize logic across components.
 *
 * Status model: 7-value lane model aligned with netharness
 *   Primary: pending, running, in_review, completed
 *   Terminal: failed, cancelled, archived
 *
 * Normalization mappings are aligned with:
 *   - task-board-panel.js  _normalizeTaskStatus()
 *   - filters.js           FilterBar.STATUS_MAP
 *
 * Usage:
 *   const enriched = TaskViewModel.enrichTask(rawTask);
 *   const { tasks, summary } = TaskViewModel.enrichTasks(rawTasks);
 *   const lane = TaskViewModel.normalizeLaneStatus('inbox'); // → 'pending'
 */
class TaskViewModel {
    // ── Lane statuses (7-value model) ─────────────────────────────
    // Aligned with netharness TaskStatus enum
    static LANE_STATUSES = [
        'pending', 'running', 'in_review', 'completed',
        'failed', 'cancelled', 'archived',
    ];

    // ── Runtime statuses ────────────────────────────────────────────
    static RUNTIME_STATUSES = [
        'queued', 'running', 'completed', 'failed', 'cancelled', 'orphaned',
    ];

    // ── Review states ──────────────────────────────────────────────
    static REVIEW_STATES = [
        'none', 'requested', 'approved',
    ];

    // ── Primary board columns (netharness: 6 active) ───────────
    static PRIMARY_COLUMNS = [
        'pending', 'running', 'in_review', 'completed', 'failed', 'cancelled',
    ];

    // ── Terminal sections (archived only, toggleable) ─────────────
    static TERMINAL_STATUSES = ['archived'];

    // ── Active statuses (non-archived) ──────────────────────────────
    static ACTIVE_STATUSES = [
        'pending', 'running', 'in_review', 'completed', 'failed', 'cancelled',
    ];

    // ── Known lane-status set (fast lookup) ────────────────────────
    static _KNOWN_LANE_SET = new Set(TaskViewModel.LANE_STATUSES);

    // ── Known runtime-status set ───────────────────────────────────
    static _KNOWN_RUNTIME_SET = new Set(TaskViewModel.RUNTIME_STATUSES);

    // ── Status normalization map ───────────────────────────────────
    // Old 10-status model → new 7-status model
    // Aligns with task-board-panel.js _normalizeTaskStatus() and
    // filters.js FilterBar.STATUS_MAP.
    static STATUS_MAP = {
        // Old 10-status model → new 7-status model
        inbox:          'pending',
        assigned:       'pending',
        awaiting_owner: 'pending',
        todo:           'pending',
        in_progress:    'running',
        doing:          'running',
        review:         'in_review',
        quality_review: 'in_review',
        in_review:      'in_review',  // pass-through
        done:           'completed',
        completed:      'completed',  // pass-through
        orphaned:       'pending',    // runtime-only → pending
    };

    // ── Review-state mapping from aegis_status ────────────────────
    static AEGIS_REVIEW_MAP = {
        pending:   'requested',
        approved:  'approved',
        rejected:  'requested',  // rejected review → still requested (needs re-review)
    };

    // ── Label configuration ────────────────────────────────────────

    static STATUS_LABELS = {
        pending:   'To Do',
        running:   'Doing',
        in_review: 'In Review',
        completed: 'Done',
        failed:    'Failed',
        cancelled: 'Cancelled',
        archived:  'Archived',
    };

    static STATUS_COLORS = {
        pending:   '#f59e0b',  // amber
        running:   '#3b82f6',  // blue
        in_review: '#8b5cf6',  // purple
        completed: '#10b981',  // green
        failed:    '#ef4444',  // red
        cancelled: '#9ca3af',  // gray
        archived:  '#6b7280',  // dark gray
    };

    static PRIORITY_LABELS = {
        project:  'Project',
        serious:  'Serious',
        thought:  'Thought',
        generated:'Generated',
    };

    static PRIORITY_COLORS = {
        project:  'var(--error)',
        serious:  'var(--warning)',
        thought:  'var(--primary-500)',
        generated:'#9ca3af',
    };

    static REVIEW_LABELS = {
        none:      'None',
        requested: 'Requested',
        approved:  'Approved',
    };

    static REVIEW_COLORS = {
        none:      '#6b7280',
        requested: '#f59e0b',
        approved:  '#10b981',
    };

    // ── Normalization methods ──────────────────────────────────────

    /**
     * Normalize a raw status string to a canonical lane_status.
     * Mirrors task-board-panel.js _normalizeTaskStatus() exactly:
     *   1. Trim + lowercase
     *   2. Look up in STATUS_MAP
     *   3. If already a known lane status, keep it
     *   4. Otherwise fall back to 'pending'
     *
     * @param {string} rawStatus
     * @returns {string} canonical lane_status
     */
    static normalizeLaneStatus(rawStatus) {
        const s = String(rawStatus || '').trim().toLowerCase();
        // Check mapping first (legacy aliases)
        if (TaskViewModel.STATUS_MAP[s]) {
            return TaskViewModel.STATUS_MAP[s];
        }
        // Already a canonical lane status?
        if (TaskViewModel._KNOWN_LANE_SET.has(s)) {
            return s;
        }
        // Unknown → pending
        return 'pending';
    }

    /**
     * Normalize a raw runtime_status string.
     * Returns the raw value if it's a known runtime status, otherwise 'queued'.
     *
     * @param {string} rawRuntimeStatus
     * @returns {string} canonical runtime_status
     */
    static normalizeRuntimeStatus(rawRuntimeStatus) {
        const s = String(rawRuntimeStatus || '').trim().toLowerCase();
        if (TaskViewModel._KNOWN_RUNTIME_SET.has(s)) {
            return s;
        }
        // Default: not yet started → queued
        return 'queued';
    }

    /**
     * Compute the review state from aegis_status / aegis_approved fields.
     *
     * Rules:
     *   - aegis_approved === true → 'approved'
     *   - aegis_status is null/undefined → 'none'
     *   - aegis_status is a known value → mapped to review_state
     *   - otherwise → 'none'
     *
     * @param {Object} task - raw task object
     * @returns {string} review state ('none', 'requested', 'approved')
     */
    static computeReviewState(task) {
        if (!task) return 'none';
        // Explicit approval flag takes precedence
        if (task.aegis_approved === true) return 'approved';
        // No aegis_status → no review requested
        if (task.aegis_status == null) return 'none';
        const s = String(task.aegis_status).trim().toLowerCase();
        return TaskViewModel.AEGIS_REVIEW_MAP[s] || 'none';
    }

    /**
     * Compute the display group for a given lane_status.
     * Primary columns and terminal statuses are themselves;
     * anything unknown falls back to 'pending'.
     *
     * @param {string} laneStatus - normalized lane status
     * @returns {string} display group
     */
    static computeDisplayGroup(laneStatus) {
        if (TaskViewModel._KNOWN_LANE_SET.has(laneStatus)) {
            return laneStatus;
        }
        return 'pending';
    }

    /**
     * Check whether a lane_status is terminal (failed / cancelled / archived).
     *
     * @param {string} laneStatus
     * @returns {boolean}
     */
    static isTerminal(laneStatus) {
        return TaskViewModel.TERMINAL_STATUSES.includes(laneStatus);
    }

    /**
     * Check whether a lane_status is active (non-terminal).
     *
     * @param {string} laneStatus
     * @returns {boolean}
     */
    static isActive(laneStatus) {
        return TaskViewModel.ACTIVE_STATUSES.includes(laneStatus);
    }

    // ── Enrichment methods ─────────────────────────────────────────

    /**
     * Enrich a single raw API task object with computed fields.
     * Returns a shallow copy with the following added:
     *   - lane_status    {string}  normalized lane status
     *   - runtime_status {string}  normalized runtime status
     *   - review_state   {string}  computed review state
     *   - display_group  {string}  computed display group
     *   - is_terminal    {boolean} whether status is terminal
     *   - is_active      {boolean} whether status is active (non-terminal)
     *
     * @param {Object} rawTask - raw task from API
     * @returns {Object} enriched task (shallow copy)
     */
    static enrichTask(rawTask) {
        if (!rawTask) return null;
        const laneStatus = TaskViewModel.normalizeLaneStatus(rawTask.status);
        const runtimeStatus = TaskViewModel.normalizeRuntimeStatus(rawTask.runtime_status);
        const reviewState = TaskViewModel.computeReviewState(rawTask);
        const displayGroup = TaskViewModel.computeDisplayGroup(laneStatus);

        return {
            ...rawTask,
            lane_status:    laneStatus,
            runtime_status: runtimeStatus,
            review_state:   reviewState,
            display_group:  displayGroup,
            is_terminal:    TaskViewModel.isTerminal(laneStatus),
            is_active:      TaskViewModel.isActive(laneStatus),
        };
    }

    /**
     * Enrich an array of raw tasks and compute summary metrics.
     *
     * @param {Array<Object>} rawTasks - array of raw API task objects
     * @returns {{ tasks: Array<Object>, summary: Object }}
     */
    static enrichTasks(rawTasks) {
        const tasks = (rawTasks || []).map(t => TaskViewModel.enrichTask(t)).filter(Boolean);
        const summary = TaskViewModel.computeSummaryMetrics(tasks);
        return { tasks, summary };
    }

    // ── Summary metrics ────────────────────────────────────────────

    /**
     * Compute summary metrics from an array of enriched tasks.
     *
     * Returns:
 *   - total     {number}  total task count
 *   - active    {number}  tasks in pending / running / in_review lanes
 *   - running   {number}  tasks with lane_status === 'running'
 *   - reviewing {number}  tasks with lane_status === 'in_review'
 *   - failed    {number}  tasks with lane_status === 'failed'
 *   - cancelled {number}  tasks with lane_status === 'cancelled'
 *   - scheduled {number}  loop-enabled / scheduled tasks
     *
     * @param {Array<Object>} enrichedTasks - array of enriched task objects
     * @returns {Object} summary metrics
     */
    static computeSummaryMetrics(enrichedTasks) {
        const tasks = enrichedTasks || [];
        const activeStatuses = new Set(['pending', 'running', 'in_review']);
        return {
            total:     tasks.length,
            active:    tasks.filter(t => activeStatuses.has(t.lane_status)).length,
            running:   tasks.filter(t => t.lane_status === 'running').length,
            reviewing: tasks.filter(t => t.lane_status === 'in_review').length,
            failed:    tasks.filter(t => t.lane_status === 'failed').length,
            cancelled: tasks.filter(t => t.lane_status === 'cancelled').length,
            scheduled: tasks.filter(t => !!t.loop_enabled).length,
        };
    }
}

window.TaskViewModel = TaskViewModel;
