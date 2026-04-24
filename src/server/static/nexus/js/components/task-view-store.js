/**
 * TaskViewStore — unified workspace-scoped view-state for the Task Workbench.
 *
 * Manages board/list mode, search, filters, sort, project, detail tab,
 * schedule open state. Persists to URL params (primary) and localStorage
 * (fallback). Notifies subscribers on state changes.
 *
 * Two-tier persistence:
 *   1. URL params — primary source of truth, overrides localStorage on load
 *   2. localStorage — workspace-scoped preferences (keyed by
 *      `nexus_task_prefs_${workspace}`)
 *
 * Subscriber pattern:
 *   store.subscribe(callback)  → unsubscribe function
 *   store.getState()           → shallow snapshot of current state
 *   store.setState(partial)    → merge + notify
 */

class TaskViewStore {
    /**
     * @param {object} options
     * @param {string} [options.workspace='default'] - workspace identifier
     */
    constructor(options = {}) {
        this._workspace = options.workspace || 'default';
        this._subscribers = new Set();
        this._state = this._getDefaultState();
        this._storageKey = `nexus_task_prefs_${this._workspace}`;

        // Mapping: state key → URL param name
        this._urlParamMap = {
            viewMode:        'view',
            searchQuery:     'q',
            'filters.status':  'status',
            'filters.priority': 'priority',
            'filters.assignee': 'assignee',
            sortField:       'sort',
            sortDirection:   'dir',
            projectFilter:   'project',
            detailTaskId:    'task',
            detailTab:       'tab',
            scheduleOpen:    'schedule',
        };

        // Load from localStorage first, then URL overrides
        this._loadFromStorage();
        this._loadFromUrl();
    }

    // ── Default state ──────────────────────────────────────────────────

    _getDefaultState() {
        return {
            viewMode: 'board',
            searchQuery: '',
            filters: {
                status: [],
                priority: [],
                assignee: [],
                dueDate: null,
            },
            sortField: 'position',
            sortDirection: 'asc',
            projectFilter: null,
            detailTaskId: null,
            detailTab: 'details',
            scheduleOpen: false,
            selectionMode: false,
            selectedTaskIds: new Set(),
        };
    }

    // ── Public API ─────────────────────────────────────────────────────

    /**
     * Return a shallow snapshot of the current state.
     * `selectedTaskIds` is cloned so callers cannot mutate the internal Set.
     */
    getState() {
        return {
            ...this._state,
            selectedTaskIds: new Set(this._state.selectedTaskIds),
        };
    }

    /**
     * Merge a partial state update and notify subscribers.
     *
     * Special handling:
     *  - `filters` is shallow-merged with existing filters
     *  - `selectedTaskIds` can be an array or a Set
     */
    setState(partial) {
        if (!partial || typeof partial !== 'object') return;

        // Merge filters separately to avoid wholesale replacement
        if (partial.filters && typeof partial.filters === 'object') {
            this._state.filters = {
                ...this._state.filters,
                ...partial.filters,
            };
        }

        // Convert selectedTaskIds to Set
        if ('selectedTaskIds' in partial) {
            const ids = partial.selectedTaskIds;
            this._state.selectedTaskIds = ids instanceof Set
                ? new Set(ids)
                : new Set(Array.isArray(ids) ? ids : []);
        }

        // Merge remaining top-level keys (skip filters & selectedTaskIds — already handled)
        for (const key of Object.keys(partial)) {
            if (key !== 'filters' && key !== 'selectedTaskIds') {
                this._state[key] = partial[key];
            }
        }

        this._notify();
    }

    /**
     * Subscribe to state changes.
     * @param {Function} callback - called with no arguments after every setState
     * @returns {Function} unsubscribe function
     */
    subscribe(callback) {
        if (typeof callback !== 'function') {
            console.warn('TaskViewStore.subscribe: callback must be a function');
            return () => {};
        }
        this._subscribers.add(callback);
        return () => {
            this._subscribers.delete(callback);
        };
    }

    // ── URL sync ───────────────────────────────────────────────────────

    /**
     * Push current state to URL search params using history.replaceState.
     */
    syncToUrl() {
        if (typeof window === 'undefined') return;

        try {
            const url = new URL(window.location.href);
            const s = this._state;

            // viewMode
            this._setUrlParam(url, 'view', s.viewMode === 'board' ? '' : s.viewMode);

            // searchQuery
            this._setUrlParam(url, 'q', s.searchQuery || '');

            // filters — comma-separated
            this._setUrlParam(url, 'status', s.filters.status.length ? s.filters.status.join(',') : '');
            this._setUrlParam(url, 'priority', s.filters.priority.length ? s.filters.priority.join(',') : '');
            this._setUrlParam(url, 'assignee', s.filters.assignee.length ? s.filters.assignee.join(',') : '');

            // sort
            this._setUrlParam(url, 'sort', s.sortField === 'position' ? '' : s.sortField);
            this._setUrlParam(url, 'dir', s.sortDirection === 'asc' ? '' : s.sortDirection);

            // projectFilter
            this._setUrlParam(url, 'project', s.projectFilter || '');

            // detailTaskId
            this._setUrlParam(url, 'task', s.detailTaskId || '');

            // detailTab
            this._setUrlParam(url, 'tab', s.detailTab === 'details' ? '' : s.detailTab);

            // scheduleOpen
            this._setUrlParam(url, 'schedule', s.scheduleOpen ? '1' : '');

            window.history.replaceState({}, '', url);
        } catch {
            // Best-effort URL sync only.
        }
    }

    /**
     * Read URL params and update state (called on init).
     */
    syncFromUrl() {
        this._loadFromUrl();
    }

    // ── Reset ──────────────────────────────────────────────────────────

    /**
     * Reset filters, search, sort, and project to defaults.
     */
    resetFilters() {
        const defaults = this._getDefaultState();
        this._state.searchQuery = defaults.searchQuery;
        this._state.filters = defaults.filters;
        this._state.sortField = defaults.sortField;
        this._state.sortDirection = defaults.sortDirection;
        this._state.projectFilter = defaults.projectFilter;
        this._notify();
    }

    /**
     * Reset everything including view mode and detail state.
     */
    resetAll() {
        this._state = this._getDefaultState();
        this._notify();
    }

    // ── localStorage persistence ───────────────────────────────────────

    /**
     * Persist current view preferences to localStorage.
     */
    _saveToStorage() {
        if (typeof localStorage === 'undefined') return;

        try {
            const data = {
                viewMode: this._state.viewMode,
                sortField: this._state.sortField,
                sortDirection: this._state.sortDirection,
            };
            localStorage.setItem(this._storageKey, JSON.stringify(data));
        } catch {
            // Storage may be full or disabled — best-effort only.
        }
    }

    /**
     * Load preferences from localStorage (called on init).
     */
    _loadFromStorage() {
        if (typeof localStorage === 'undefined') return;

        try {
            const raw = localStorage.getItem(this._storageKey);
            if (!raw) return;
            const data = JSON.parse(raw);
            if (data.viewMode && (data.viewMode === 'board' || data.viewMode === 'list')) {
                this._state.viewMode = data.viewMode;
            }
            if (data.sortField) {
                this._state.sortField = data.sortField;
            }
            if (data.sortDirection && (data.sortDirection === 'asc' || data.sortDirection === 'desc')) {
                this._state.sortDirection = data.sortDirection;
            }
        } catch {
            // Corrupted entry — ignore.
        }
    }

    // ── URL param helpers ──────────────────────────────────────────────

    /**
     * Load state from URL params (called on init after localStorage).
     * URL values override localStorage.
     */
    _loadFromUrl() {
        if (typeof window === 'undefined') return;

        try {
            const params = new URLSearchParams(window.location.search);

            const view = params.get('view');
            if (view === 'board' || view === 'list') {
                this._state.viewMode = view;
            }

            const q = params.get('q');
            if (q !== null) {
                this._state.searchQuery = q;
            }

            const status = params.get('status');
            if (status) {
                this._state.filters.status = status.split(',').map(s => s.trim()).filter(Boolean);
            }

            const priority = params.get('priority');
            if (priority) {
                this._state.filters.priority = priority.split(',').map(s => s.trim()).filter(Boolean);
            }

            const assignee = params.get('assignee');
            if (assignee) {
                this._state.filters.assignee = assignee.split(',').map(s => s.trim()).filter(Boolean);
            }

            const sort = params.get('sort');
            if (sort) {
                this._state.sortField = sort;
            }

            const dir = params.get('dir');
            if (dir === 'asc' || dir === 'desc') {
                this._state.sortDirection = dir;
            }

            const project = params.get('project');
            if (project !== null) {
                this._state.projectFilter = project || null;
            }

            const task = params.get('task');
            if (task) {
                this._state.detailTaskId = task;
            }

            const tab = params.get('tab');
            if (tab) {
                this._state.detailTab = tab;
            }

            const schedule = params.get('schedule');
            if (schedule === '1') {
                this._state.scheduleOpen = true;
            }
        } catch {
            // Best-effort URL read only.
        }
    }

    /**
     * Set or delete a URL search param.
     * Empty string → delete the param.
     */
    _setUrlParam(url, key, value) {
        if (value === '' || value === null || value === undefined) {
            url.searchParams.delete(key);
        } else {
            url.searchParams.set(key, value);
        }
    }

    // ── Subscriber notification ────────────────────────────────────────

    _notify() {
        this._saveToStorage();
        for (const cb of this._subscribers) {
            try {
                cb();
            } catch (err) {
                console.error('TaskViewStore: subscriber error', err);
            }
        }
    }
}

window.TaskViewStore = TaskViewStore;
