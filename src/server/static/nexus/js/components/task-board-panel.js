/**
 * TaskBoardPanel - Full-featured task management panel.
 *
 * Serves as the single entry point for the Tasks page.
 * Features: Kanban board, task create modal, task detail (5-tab), editing,
 * status transitions via drag-drop, filtering/search, schedules, batch operations,
 * SSE streaming for live task conversations.
 *
 * Standalone class — no BasePanel dependency. Uses AppDataStore for data
 * caching with fallback to direct NexusAPI calls.
 */

class TaskBoardPanel {
    constructor(id, def, opts) {
        this.id = id;
        this.def = def;
        this.opts = opts || {};
        this.container = null;
        this._destroyed = false;
        this._tasks = [];
        this._enrichedTasks = []; // TV-001: enriched tasks with read-model fields
        this._summaryMetrics = null; // TV-007: summary metrics for strip
        this._summaryStrip = null; // TV-007: TaskSummaryStrip instance
        this._taskTotalCount = 0;
        this._scheduleSummaryCount = 0;
        this._filter = '';
        this._projectFilter = '';
        this._projectsList = [];
        this._sortBtn = null;
        this._projectBtn = null;
        this._selectedTask = null;
        this._selectionMode = false;
        this._selectedTaskIds = new Set();
        this._activeStreams = new Map();
        this._smartPoll = null;
        this._pollInterval = 10000;
        this._mentionInputs = [];
        this._dataStore = (typeof AppDataStore !== 'undefined') ? AppDataStore.getInstance() : null;
        this._dataStoreSubscriptions = [];
        this._schedulePanelOpen = false;
        this._secondarySurfaceStorageKey = 'nexus-task-secondarySurface';
        this._secondarySurface = 'board';
        this._paneId = 'global'; // fixed pane id for fullscreen mode
        this._sortField = localStorage.getItem('nexus-kanban-sortField') || 'position';
        this._sortDirection = localStorage.getItem('nexus-kanban-sortDir') || 'asc';
        this._urlTaskTab = 'details';
        this._popstateHandler = null;

        // TV-002: Initialize TaskViewStore for unified state management
        this._viewStore = (typeof TaskViewStore !== 'undefined')
            ? new TaskViewStore({ workspace: this._getExecUser?.() || 'default' })
            : null;
        if (this._viewStore) {
            this._viewStore.subscribe(() => this._onViewStoreChange(this._viewStore.getState()));
            const storeState = this._viewStore.getState();
            this._sortField = storeState.sortField;
            this._sortDirection = storeState.sortDirection;
            this._filter = storeState.searchQuery;
            this._projectFilter = storeState.projectFilter;
        }

        // K-008: Completed column infinite scroll state
        this._completedPageSize = 20;
        this._completedLoadedCount = 20;
        this._completedAllTasks = [];
        this._completedLoading = false;
        this._completedObserver = null;

        // K-002: Drag state freeze
        this._isDragging = false;
        this._dragSnapshot = null; // frozen task list during drag
        this._pendingUpdates = []; // queued backend updates during drag

        // K-005: View mode (synced with TaskViewStore if available)
        this._viewMode = this._viewStore?.getState().viewMode || localStorage.getItem('nexus-kanban-viewMode') || 'board';
        this._listView = null;
        this._filterBar = null;
        this._secondarySurface = this._readInitialSecondarySurface();
        this._schedulePanelOpen = this._secondarySurface === 'schedules';

        // Netharness-aligned: visible board lanes + archived (toggleable)
        this.statusColumns = [
            { key: 'pending',   title: 'To Do',     color: 'var(--status-pending)' },
            { key: 'running',   title: 'Doing',     color: 'var(--status-running)' },
            { key: 'in_review', title: 'In Review', color: 'var(--status-in-review)' },
            { key: 'completed', title: 'Done',      color: 'var(--status-completed)' },
            { key: 'failed',    title: 'Failed',    color: 'var(--status-failed)' },
            { key: 'cancelled', title: 'Cancelled', color: 'var(--status-cancelled)' },
        ];
        this.terminalColumns = [
            { key: 'archived',  title: 'Archived',  color: 'var(--status-archived)' },
        ];
        this._showArchived = true; // Default visible
        this._autoCollapseEmptyColumns = new Set(['archived']);
    }

    _normalizeProviderName(provider) {
        const app = this._getApp?.();
        if (app && typeof app.normalizeProviderName === 'function') {
            return app.normalizeProviderName(provider);
        }
        const normalized = String(provider || '').trim().toLowerCase();
        return normalized;
    }

    _normalizeSecondarySurface(surface) {
        const normalized = String(surface || '').trim().toLowerCase();
        return ['board', 'schedules'].includes(normalized) ? normalized : 'board';
    }

    _readInitialSecondarySurface() {
        const urlState = this._readUrlTaskState?.() || {};
        if (urlState.taskSurface) return this._normalizeSecondarySurface(urlState.taskSurface);

        try {
            const rawStoredSurface = localStorage.getItem(this._secondarySurfaceStorageKey);
            if (rawStoredSurface) return this._normalizeSecondarySurface(rawStoredSurface);
        } catch {}

        if (this._viewStore?.getState?.().scheduleOpen) {
            return 'schedules';
        }
        return 'board';
    }

    _getSecondarySurfaceHint(surface = this._secondarySurface) {
        if (surface === 'schedules') return 'Manage recurring and one-time schedules without leaving Tasks.';
        return 'Use board/list to manage tasks; switch surfaces for schedules when needed.';
    }

    _persistSecondarySurface(surface) {
        try {
            localStorage.setItem(this._secondarySurfaceStorageKey, this._normalizeSecondarySurface(surface));
        } catch {}
    }

    _applySecondarySurface(surface = this._secondarySurface) {
        const pid = this._paneId;
        const normalized = this._normalizeSecondarySurface(surface);
        this._secondarySurface = normalized;
        this._schedulePanelOpen = normalized === 'schedules';
        this._persistSecondarySurface(normalized);

        const boardSurface = document.getElementById(`taskSurfaceBoard-${pid}`);
        const schedulesSurface = document.getElementById(`taskSurfaceSchedules-${pid}`);
        if (boardSurface) boardSurface.hidden = normalized !== 'board';
        if (schedulesSurface) schedulesSurface.hidden = normalized !== 'schedules';

        const listContainer = document.getElementById(`listViewContainer-${pid}`);
        if (listContainer) listContainer.hidden = normalized !== 'board' || this._viewMode !== 'list';
        const expansionPanels = document.getElementById(`expansionPanels-${pid}`);
        if (expansionPanels) expansionPanels.hidden = normalized !== 'board';

        const hint = document.getElementById(`taskSurfaceHint-${pid}`);
        if (hint) {
            hint.textContent = this._getSecondarySurfaceHint(normalized);
            hint.hidden = !hint.textContent;
        }

        this.container?.querySelectorAll('[data-action="set-surface"]').forEach((btn) => {
            const active = btn.dataset.surface === normalized;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        this._syncBoardVisibility(this._getFilteredTasks().length > 0, this._viewMode);
    }

    async _setSecondarySurface(surface, { syncUrl = true, replace = true } = {}) {
        const normalized = this._normalizeSecondarySurface(surface);
        const previous = this._secondarySurface;
        this._applySecondarySurface(normalized);

        if (normalized === 'schedules' && (previous !== 'schedules' || !this._scheduleSummaryCount)) {
            await this._loadSchedules();
        }
        if (syncUrl) {
            this._syncUrlState({ taskSurface: normalized }, { replace });
        }
    }

    // ------------------------------------------------------------------
    // Lifecycle
    // ------------------------------------------------------------------

    async init() {
        // Subscribe to data store updates if available
        this._subscribeToDataStore();
        // Start auto-refresh if configured
        if (this.def.refreshMs > 0 && typeof SmartPoll !== 'undefined') {
            this._poll = new SmartPoll(() => this.refresh(), { intervalMs: this.def.refreshMs });
            this._poll.start();
        }
        // Load initial tasks
        await this._loadTasks();
    }

    render(container) {
        this.container = container;
        const pid = this._paneId;
        const isBoardSurface = this._secondarySurface === 'board';
        const isSchedulesSurface = this._secondarySurface === 'schedules';

        container.innerHTML = `
            <div class="task-container task-shell">
                <div class="task-shell-fill">
                    <div class="task-toolbar">
                        <div class="task-toolbar-left">
                            <div class="task-toggle-group" id="taskSurfaceSwitcher-${pid}" aria-label="Task surface">
                                <button class="view-toggle-btn task-toggle-btn ${isBoardSurface ? 'is-active' : ''}" data-action="set-surface" data-surface="board" title="Board surface" aria-pressed="${isBoardSurface ? 'true' : 'false'}">Board</button>
                                <button class="view-toggle-btn task-toggle-btn ${isSchedulesSurface ? 'is-active' : ''}" data-action="set-surface" data-surface="schedules" title="Schedules surface" aria-pressed="${isSchedulesSurface ? 'true' : 'false'}">Schedules</button>
                            </div>
                            <span class="task-muted-note" id="taskSurfaceHint-${pid}"></span>
                        </div>
                    </div>
                    <div id="summaryStrip-${pid}" class="task-summary-strip-container" hidden></div>
                    <div class="task-shell-fill task-surface-shell" id="taskSurfaceBoard-${pid}" ${isBoardSurface ? '' : 'hidden'}>
                        <div class="task-toolbar" id="taskBoardToolbar-${pid}">
                            <div class="task-toolbar-left">
                                <button class="action-btn primary" data-action="create-task">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                    </svg>
                                    <span>New Task</span>
                                </button>
                                <button class="action-btn" data-action="toggle-selection" title="Toggle selection mode">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
                                    </svg>
                                    <span>Select</span>
                                </button>
                                <button class="action-btn ${this._showArchived ? '' : 'is-outlined'}" data-action="toggle-archived" title="Show/hide archived tasks" id="toggleArchivedBtn-${pid}">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"/>
                                    </svg>
                                    <span>${this._showArchived ? 'Hide Archived' : 'Show Archived'}</span>
                                </button>
                                <div class="selection-actions" id="selectionActions-${pid}" hidden>
                                    <button class="action-btn" data-action="select-all"><span>Select All</span></button>
                                    <button class="action-btn" data-action="deselect-all"><span>Clear</span></button>
                                    <button class="action-btn danger" data-action="delete-selected" id="deleteSelectedBtn-${pid}">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                        </svg>
                                        <span>Delete (0)</span>
                                    </button>
                                </div>
                            </div>
                            <div class="task-toolbar-right">
                                <div class="task-toggle-group" aria-label="Task view mode">
                                    <button class="view-toggle-btn task-toggle-btn ${this._viewMode === 'board' ? 'is-active' : ''}" data-action="set-view" data-view="board" title="Board view" aria-pressed="${this._viewMode === 'board' ? 'true' : 'false'}">Board</button>
                                    <button class="view-toggle-btn task-toggle-btn ${this._viewMode === 'list' ? 'is-active' : ''}" data-action="set-view" data-view="list" title="List view" aria-pressed="${this._viewMode === 'list' ? 'true' : 'false'}">List</button>
                                </div>
                                <div id="filterBar-${pid}" class="task-toolbar-inline-group"></div>
                                <div id="toolbarDropdowns-${pid}" class="task-inline-panel spread"></div>
                                <input type="text" class="form-input task-search-input" placeholder="Search..." id="taskSearch-${pid}">
                            </div>
                        </div>
                        <div class="task-shell-fill task-board-content">
                            <div class="task-shell-fill">
                                <div class="task-board-empty-state" id="taskBoardEmptyState-${pid}" ${this._viewMode === 'board' ? '' : 'hidden'}>
                                    <div class="empty-state inline">
                                        <svg class="empty-state-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" d="M9 5H7a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-7 8h6m-6 4h6"/>
                                        </svg>
                                        <div class="empty-state-title">No tasks in board view</div>
                                        <div class="empty-state-text" id="taskBoardEmptyStateText-${pid}">Create a task or change filters to populate the board.</div>
                                    </div>
                                </div>
                                <div class="kanban-board" id="kanbanBoard-${pid}" ${this._viewMode === 'board' ? '' : 'hidden'}>
                                    <div class="kanban-primary-columns">
                                    ${[...this.statusColumns, ...this.terminalColumns].map(col => `
                                        <div class="kanban-column ${col.key === 'archived' && !this._showArchived ? 'kanban-column-hidden' : ''}" data-status="${col.key}" ${col.key === 'archived' && !this._showArchived ? 'hidden' : ''}>
                                            <div class="kanban-column-header">
                                                <span class="kanban-column-title">
                                                    <span class="task-status-dot status-${col.key}"></span>
                                                    ${col.title}
                                                </span>
                                                <span class="kanban-column-count" id="count-${pid}-${col.key}">0</span>
                                            </div>
                                            <div class="kanban-column-items" id="items-${pid}-${col.key}">
                                                <div class="empty-state compact">
                                                    <div class="loading-spinner lg"></div>
                                                </div>
                                            </div>
                                        </div>
                                    `).join('')}
                                    </div>
                                </div>
                                <div class="list-view-container task-list-shell" id="listViewContainer-${pid}" ${this._viewMode === 'list' ? '' : 'hidden'}></div>
                                <div id="expansionPanels-${pid}" class="task-expansion-panels">
                                    <div class="empty-state tight">
                                        <div class="loading-spinner sm"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="task-shell-fill task-surface-shell" id="taskSurfaceSchedules-${pid}" ${isSchedulesSurface ? '' : 'hidden'}>
                        <div class="schedule-panel" id="schedulePanel-${pid}">
                            <div class="schedule-panel-header">
                                <span class="schedule-panel-title">Scheduled Tasks</span>
                                <div class="schedule-panel-actions">
                                    <select class="form-input form-select schedule-status-filter" id="scheduleStatusFilter-${pid}">
                                        <option value="">All Status</option>
                                        <option value="active">Active</option>
                                        <option value="paused">Paused</option>
                                        <option value="cancelled">Cancelled</option>
                                    </select>
                                    <button class="action-btn schedule-refresh-btn" data-action="refresh-schedules" title="Refresh schedules">
                                        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="icon-14">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                                        </svg>
                                    </button>
                                </div>
                            </div>
                            <div class="schedule-list" id="scheduleList-${pid}">
                                <div class="empty-state compact">
                                    <div class="loading-spinner md"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="task-detail hidden" id="taskDetail-${pid}"></div>
                <div class="task-detail-backdrop hidden" id="taskDetailBackdrop-${pid}"></div>
            </div>
        `;

        this._bindToolbarEvents();
        this._bindUrlState();
        this._initFilterBar();
        this._initListView();
        this._applySecondarySurface(this._secondarySurface);
        this._loadTasks();
        if (this._secondarySurface === 'schedules') this._loadSchedules();
        this._startAutoPolling();
    }

    async refresh() {
        if (!this.container || this._destroyed) return;
        await this._loadTasks();
        if (this._secondarySurface === 'schedules') {
            await this._loadSchedules();
        }
    }

    async refreshTasks(opts = {}) {
        if (opts.force && this._dataStore) {
            this._dataStore.invalidate('tasks');
        }
        await this.refresh();
    }

    async refreshSchedules(opts = {}) {
        if (opts.force && this._dataStore) {
            this._dataStore.invalidate('schedules');
        }
        if (opts.onlyIfVisible && !this.isSchedulePanelOpen()) {
            return;
        }
        if (!this.container || this._destroyed) {
            return;
        }
        await this._loadSchedules();
    }

    startAutoPolling() {
        this._startAutoPolling();
    }

    stopAutoPolling() {
        this._stopAutoPolling();
    }

    closeAllTaskStreams() {
        for (const [taskId] of this._activeStreams) {
            this._closeTaskStream(taskId);
        }
    }

    isSchedulePanelOpen() {
        const surface = document.getElementById(`taskSurfaceSchedules-${this._paneId}`);
        return !!surface && !surface.hidden && this._schedulePanelOpen;
    }

    async destroy() {
        this._destroyed = true;
        this._stopAutoPolling();
        this._unsubscribeFromDataStore();
        if (this._poll) { this._poll.destroy(); this._poll = null; }
        if (this._completedObserver) {
            this._completedObserver.disconnect();
            this._completedObserver = null;
        }
        this.closeAllTaskStreams();
        this._mentionInputs.forEach(m => { try { m.destroy(); } catch {} });
        this._mentionInputs = [];
        if (this._popstateHandler && typeof window !== 'undefined') {
            window.removeEventListener('popstate', this._popstateHandler);
            this._popstateHandler = null;
        }
        this.container = null;
    }

    onRealtimeEvent(eventType) {
        if (eventType.startsWith('task.') && !this._isDragging) this.refresh();
    }

    // ------------------------------------------------------------------
    // Status normalization
    // ------------------------------------------------------------------

    _normalizeTaskStatus(status) {
        // TV-001: Delegate to TaskViewModel if available
        if (typeof TaskViewModel !== 'undefined') {
            return TaskViewModel.normalizeLaneStatus(status);
        }
        const s = String(status || '').trim().toLowerCase();
        const statusMap = {
            // Old 10-status model → new 7-status model
            inbox:          'pending',
            assigned:       'pending',
            awaiting_owner: 'pending',
            todo:           'pending',
            in_progress:    'running',
            doing:          'running',
            review:         'in_review',
            quality_review: 'in_review',
            in_review:      'in_review',
            done:           'completed',
            completed:      'completed',
            orphaned:       'pending',
        };
        const normalized = statusMap[s] || s;
        const knownStatuses = new Set([
            ...this.statusColumns.map(col => col.key),
            ...this.terminalColumns.map(col => col.key),
        ]);
        if (knownStatuses.has(normalized)) return normalized;
        return 'pending';
    }

    _normalizePriority(priority) {
        const value = String(priority || '').trim().toLowerCase();
        return ['project', 'serious', 'thought', 'generated'].includes(value) ? value : 'thought';
    }

    _getPriorityLabel(priority) {
        const key = this._normalizePriority(priority);
        return {
            project: 'Project',
            serious: 'Serious',
            thought: 'Thought',
            generated: 'Generated',
        }[key] || 'Thought';
    }

    _getDueDateMs(rawDueDate) {
        if (!rawDueDate) return null;
        if (typeof rawDueDate === 'number') {
            return rawDueDate < 1e12 ? rawDueDate * 1000 : rawDueDate;
        }
        const value = String(rawDueDate).trim();
        if (!value) return null;
        if (/^-?\d+(\.\d+)?$/.test(value)) {
            const numeric = Number(value);
            return numeric < 1e12 ? numeric * 1000 : numeric;
        }
        const millis = Date.parse(value);
        return Number.isNaN(millis) ? null : millis;
    }

    _getDueDateUpdateValue(rawDate) {
        const value = String(rawDate || '').trim();
        return value ? `${value}T00:00:00` : null;
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------

    async _loadProjects() {
        try {
            let projects;
            if (this._dataStore) {
                const data = await this._dataStore.fetch('projects', {
                    execUser: this._getExecUser()
                });
                projects = Array.isArray(data) ? data : (data.projects || []);
            } else {
                projects = await NexusAPI.getProjects({
                    execUser: this._getExecUser()
                });
            }
            this._projectsList = projects || [];
            if (this._projectBtn) {
                this._projectBtn.setProjects(this._projectsList);
            }
        } catch (e) {
            console.error('Failed to load projects:', e);
        }
    }

    async _loadTasks() {
        const pid = this._paneId;
        const searchInput = document.getElementById(`taskSearch-${pid}`);

        try {
            if (!this._projectsList || this._projectsList.length === 0) {
                await this._loadProjects();
            }
            const taskOpts = {
                execUser: this._getExecUser(),
                search: searchInput?.value || '',
                projectId: this._projectFilter || '',
            };
            const data = await this._fetchAllTasks(taskOpts);
            this._taskTotalCount = Number(data?.total) || 0;
            this._tasks = (data.tasks || []).map(t => ({
                ...t,
                status: this._normalizeTaskStatus(t.status),
            }));
            this._ensurePositions();
            this._renderKanban();
            this._renderSummaryStrip(); // TV-007: Update summary metrics
            this._updateActiveFilterSummary(); // TV-011: Update filter summary
            this._loadExpansionPanels();
            this._syncSelectedTaskDetail();
            await this._restoreTaskFromUrl();
        } catch (e) {
            console.error('Failed to load tasks:', e);
            this.statusColumns.forEach(col => {
                const el = document.getElementById(`items-${pid}-${col.key}`);
                if (el) el.innerHTML = `<div class="empty-state compact"><p class="task-muted-note error">Failed to load</p></div>`;
            });
        }
    }

    async _fetchAllTasks(taskOpts = {}) {
        const pageSize = 200;
        let page = 1;
        let total = 0;
        const tasks = [];

        while (page <= 25) {
            const pageData = await NexusAPI.getTasks({ ...taskOpts, page, pageSize });
            const pageTasks = Array.isArray(pageData?.tasks) ? pageData.tasks : [];
            total = Number(pageData?.total) || total || pageTasks.length;
            tasks.push(...pageTasks);
            if (pageTasks.length === 0 || tasks.length >= total) break;
            page += 1;
        }

        return {
            total: total || tasks.length,
            page: 1,
            page_size: pageSize,
            tasks,
        };
    }

    async _loadExpansionPanels() {
        const pid = this._paneId;
        const root = document.getElementById(`expansionPanels-${pid}`);
        if (!root) return;
        try {
            const data = await (this._dataStore
                ? this._dataStore.fetch('sessions', { page: 1, pageSize: 200, username: this._getUsername() || undefined })
                : NexusAPI.getSessions({ page: 1, pageSize: 200, username: this._getUsername() || undefined }));
            const sessions = Array.isArray(data?.sessions) ? data.sessions : [];
            if (window.ExpansionPanels?.render) {
                window.ExpansionPanels.render(root, sessions);
            } else {
                root.innerHTML = '<div class="task-muted-note">Run monitor unavailable.</div>';
            }
        } catch (e) {
            root.innerHTML = '<div class="task-muted-note error">Failed to load run monitor</div>';
        }
    }

    // ------------------------------------------------------------------
    // Kanban rendering
    // ------------------------------------------------------------------

    _renderKanban() {
        const pid = this._paneId;
        const tasks = this._getFilteredTasks();
        const board = document.getElementById(`kanbanBoard-${pid}`);
        const emptyState = document.getElementById(`taskBoardEmptyState-${pid}`);
        const emptyStateText = document.getElementById(`taskBoardEmptyStateText-${pid}`);
        const hasVisibleTasks = tasks.length > 0;
        const hasAnyTasks = this._tasks.length > 0;
        const boardEmptyMessage = hasAnyTasks
            ? 'No tasks match the current filters. Reset filters or search to see more work.'
            : 'Create a task or change filters to populate the board.';
        const allColumns = [...this.statusColumns, ...this.terminalColumns];
        const grouped = {};
        allColumns.forEach(col => { grouped[col.key] = []; });
        tasks.forEach(t => {
            const s = this._normalizeTaskStatus(t.status || 'pending');
            (grouped[s] || grouped['pending']).push(t);
        });

        if (emptyStateText) emptyStateText.textContent = boardEmptyMessage;
        this._syncBoardVisibility(hasVisibleTasks);

        allColumns.forEach(col => {
            const allItems = this._sortTasks(grouped[col.key] || []);
            const el = document.getElementById(`items-${pid}-${col.key}`);
            const countEl = document.getElementById(`count-${pid}-${col.key}`);
            const columnEl = board?.querySelector(`.kanban-column[data-status="${col.key}"]`);
            if (countEl) countEl.textContent = allItems.length;

            const hiddenByArchivedToggle = col.key === 'archived' && !this._showArchived;
            const hiddenBecauseEmpty = this._autoCollapseEmptyColumns.has(col.key) && allItems.length === 0 && !hiddenByArchivedToggle && !this._isDragging;
            if (columnEl) {
                columnEl.hidden = hiddenByArchivedToggle || hiddenBecauseEmpty;
                columnEl.classList.toggle('kanban-column-hidden', hiddenByArchivedToggle || hiddenBecauseEmpty);
            }

            // K-008: Completed column infinite scroll — only render first N items
            let items = allItems;
            if (col.key === 'completed') {
                this._completedAllTasks = allItems;
                items = allItems.slice(0, this._completedLoadedCount);
            }

            if (el) {
                if (allItems.length === 0) {
                    const emptyMessage = col.key === 'cancelled'
                        ? 'Only To Do or Doing tasks enter Cancelled. Delete is separate from cancel.'
                        : 'No tasks';
                    el.innerHTML = `<div class="empty-state compact"><p class="task-muted-note">${this._esc(emptyMessage)}</p></div>`;
                } else {
                    let html = items.map(t => this._renderTaskCard(t)).join('');
                    // Add sentinel for infinite scroll on Done column
                    if (col.key === 'completed' && items.length < allItems.length) {
                        html += '<div class="completed-scroll-sentinel task-scroll-sentinel" id="completedScrollSentinel-' + pid + '"><div class="loading-spinner sm task-scroll-spinner"></div><p class="task-muted-note">Loading more...</p></div>';
                    }
                    el.innerHTML = html;
                    this._bindCardEvents(el);
                    // Set up Intersection Observer for Done column
                    if (col.key === 'completed') this._setupCompletedInfiniteScroll(pid);
                }
            }
        });

        if (hasVisibleTasks && board && !board.hidden && emptyState && emptyState.hidden) {
            this._bindKanbanDragDrop();
        }

        // Update filter bar counts
        if (this._filterBar) {
            this._filterBar.updateCounts(this._tasks);
        }

        // Update list view if active
        if (this._viewMode === 'list' && this._listView) {
            this._listView.updateTasks(this._getFilteredTasks());
        }
    }

    _renderTaskCard(task) {
        const priorityClass = this._normalizePriority(task.priority);
        const priorityLabel = this._getPriorityLabel(task.priority);
        const timeStr = this._formatTime(task.updated_at || task.created_at);
        const isSelected = this._selectedTask === task.id;
        const isChecked = this._selectedTaskIds.has(task.id);
        const alias = String(task?.alias || '').trim();
        const provider = String(task?.provider || '').trim();
        const displayAlias = this._normalizeProviderName(alias);
        const displayProvider = this._normalizeProviderName(provider);
        const targetPrimary = displayAlias || displayProvider;
        const targetSecondary = displayAlias && displayProvider && displayAlias.toLowerCase() !== displayProvider.toLowerCase() ? displayProvider : '';
        const targetTooltip = targetSecondary ? `Alias: ${displayAlias} · Provider: ${displayProvider}` : (displayAlias || displayProvider);
        const agentName = task.assigned_to || displayAlias || displayProvider || '';
        const agentAvatar = agentName && typeof AgentAvatar !== 'undefined' ? AgentAvatar.render(agentName, { size: 'xs', status: this._normalizeTaskStatus(task.status) === 'running' ? 'online' : 'none' }) : '';
        const tags = Array.isArray(task.tags) ? task.tags : [];
        const visibleTags = tags.slice(0, 3);
        const extraTagCount = tags.length > 3 ? tags.length - 3 : 0;
        const tagsHtml = tags.length > 0 ? `<div class="task-card-tags">${visibleTags.map(t => `<span class="task-card-tag">${this._esc(t)}</span>`).join('')}${extraTagCount > 0 ? `<span class="task-card-tag task-card-tag-more">+${extraTagCount}</span>` : ''}</div>` : '';
        const dueDateMs = this._getDueDateMs(task.due_date);
        const isOverdue = dueDateMs !== null && dueDateMs < Date.now() && this._normalizeTaskStatus(task.status) !== 'completed';
        const overdueHtml = isOverdue ? '<span class="task-card-overdue">! Overdue</span>' : '';
        const isAwaitingOwner = this._detectAwaitingOwner(task);
        const awaitingBadge = isAwaitingOwner ? '<span class="task-card-awaiting-badge">Needs Attention</span>' : '';
        const ghLabel = this._resolveGitHubIssueLabel(task);
        const ghUrl = this._resolveGitHubIssueUrl(task);
        const ghState = String(task.github_state || '').trim().toLowerCase();
        const ghBadgeClass = ghState === 'closed' ? 'is-closed' : 'is-open';
        const ghBadge = ghLabel
            ? (ghUrl
                ? `<a href="${this._esc(ghUrl)}" target="_blank" rel="noopener noreferrer" class="task-card-gh-badge ${ghBadgeClass}">GH ${this._esc(ghLabel)}${ghState ? ` · ${this._esc(ghState)}` : ''}</a>`
                : `<span class="task-card-gh-badge ${ghBadgeClass}">GH ${this._esc(ghLabel)}${ghState ? ` · ${this._esc(ghState)}` : ''}</span>`)
            : '';
        const isOrphaned = Boolean(task.runtime_orphaned) || String(task.runtime_status || '').trim().toLowerCase() === 'orphaned';
        const requeueBtn = isOrphaned ? `<button class="task-card-requeue-btn" data-action="requeue-orphan" data-task-id="${task.id}" title="Requeue this orphaned task">Requeue</button>` : '';
        const aegisBadge = task.aegis_approved ? '<span class="task-card-aegis-badge">Aegis ✓</span>' : '';
        const loopBadge = task.loop_enabled ? `<span class="task-card-loop-badge ${task.loop_keyword_found ? 'is-found' : 'is-running'}">Loop ${task.loop_iteration||0}/${task.loop_max_iterations||1}${task.loop_keyword_found ? ' ✓' : ''}</span>` : '';

        return `
            <div class="task-card task-card-priority-${priorityClass} ${isSelected ? 'selected' : ''} ${isChecked ? 'checked' : ''} ${isOverdue ? 'task-card-overdue-state' : ''} ${isAwaitingOwner ? 'task-card-needs-attention' : ''}" data-task-id="${task.id}" draggable="${!this._selectionMode}">
                ${this._selectionMode ? `<div class="task-card-checkbox" data-task-id="${task.id}"><input type="checkbox" ${isChecked ? 'checked' : ''}></div>` : ''}
                <div class="task-card-content">
                    <div class="task-card-header">
                        <span class="task-card-id">#${task.id.slice(0, 8)}</span>
                        ${task.ticket_ref ? `<span class="task-card-ticket-ref" title="Project ticket">${this._esc(task.ticket_ref)}</span>` : ''}
                        ${ghBadge}${aegisBadge}
                        ${task.priority ? `<span class="task-card-priority ${priorityClass}" data-inline-edit="priority" data-current-value="${this._esc(priorityClass)}" title="Click to change priority">${this._esc(priorityLabel)}</span>` : ''}
                        ${loopBadge}
                        ${overdueHtml}${awaitingBadge}${requeueBtn}
                    </div>
                    <p class="task-card-title">${this._esc(task.description || 'No description')}</p>
                    ${tagsHtml}
                    <div class="task-card-meta">
                        ${agentAvatar ? `<span class="task-card-meta-item" data-inline-edit="assignee" data-current-value="${this._esc(agentName)}" title="Click to change assignee">${agentAvatar}</span>` : ''}
                        ${dueDateMs ? (() => { const dd = new Date(dueDateMs); const fmt = dd.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); return `<span class="task-card-meta-item" data-inline-edit="due_date" data-current-value="${this._esc(String(task.due_date))}" title="Click to change due date"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="task-meta-icon task-meta-icon-xs"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>${fmt}</span>`; })() : ''}
                        ${tags.length > 0 ? `<span class="task-card-meta-item" data-inline-edit="labels" data-current-labels="${this._esc(tags.join(','))}" title="Click to edit labels"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="task-meta-icon task-meta-icon-xs"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"/></svg>${tags.length} label${tags.length > 1 ? 's' : ''}</span>` : ''}
                        <span class="task-card-meta-item">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            ${timeStr}
                        </span>
                        ${targetPrimary ? `<span class="task-card-meta-item" title="${this._esc(targetTooltip)}"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg><span>${this._esc(targetPrimary)}</span>${targetSecondary ? `<span class="task-provider-base">${this._esc(targetSecondary)}</span>` : ''}</span>` : ''}
                    </div>
                    ${task.depends_on?.length ? `<div class="task-card-deps"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="task-meta-icon task-meta-icon-xs task-card-deps-icon"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>${task.depends_on.map(d => `<span class="task-card-dep">${d.slice(0, 8)}</span>`).join('')}</div>` : ''}
                </div>
            </div>
        `;
    }

    _bindCardEvents(root) {
        root.querySelectorAll('.task-card').forEach(card => {
            card.addEventListener('click', (e) => {
                if (e.target.closest('.task-card-checkbox')) return;
                if (e.target.closest('[data-inline-edit]')) return;
                this._selectTask(card.dataset.taskId);
            });
        });
        root.querySelectorAll('.task-card-checkbox').forEach(cb => {
            cb.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleTaskSelection(cb.dataset.taskId);
            });
        });
        // Requeue orphan task buttons
        root.querySelectorAll('.task-card-requeue-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._requeueOrphanTask(btn.dataset.taskId);
            });
        });
        // K-007: Inline picker
        if (typeof InlinePicker !== 'undefined') {
            InlinePicker.attachAll(root, {
                getStatusColumns: () => this.statusColumns.map(c => ({ key: c.key, label: c.title, color: c.color })),
                getAssigneeOptions: () => {
                    const names = new Set();
                    this._tasks.forEach(t => {
                        if (t.assigned_to) names.add(t.assigned_to);
                        if (t.alias) names.add(t.alias);
                    });
                    return Array.from(names).sort().map(n => ({ key: n, label: n, color: null }));
                },
                getAllLabels: () => {
                    const labels = new Set();
                    this._tasks.forEach(t => {
                        if (Array.isArray(t.tags)) t.tags.forEach(l => labels.add(l));
                    });
                    return Array.from(labels).sort();
                },
                onSelect: async (taskId, field, value) => {
                    try {
                        const update = {};
                        if (field === 'status') {
                            await NexusAPI.updateTaskStatus(taskId, value, { execUser: this._getExecUser() });
                        } else {
                            if (field === 'priority') update.priority = value;
                            if (field === 'assignee') update.assignee = value;
                            if (field === 'due_date') {
                                update.due_date = this._getDueDateUpdateValue(value);
                            }
                            if (field === 'labels') update.labels = value;
                            await NexusAPI.updateTask(taskId, update, { execUser: this._getExecUser() });
                        }
                        // Invalidate data store cache so next fetch gets fresh data
                        if (this._dataStore) this._dataStore.invalidate('tasks');
                        // Optimistic local update
                        const local = this._tasks.find(t => t.id === taskId);
                        if (local) {
                            if (field === 'status') local.status = this._normalizeTaskStatus(value);
                            if (field === 'priority') local.priority = value;
                            if (field === 'assignee') local.assigned_to = value;
                            if (field === 'due_date') local.due_date = this._getDueDateUpdateValue(value);
                            if (field === 'labels') local.tags = value;
                        }
                        this._renderKanban();
                        this._getApp()?.showToast?.(`Updated ${field}`, 'success');
                    } catch (e) {
                        this._getApp()?.showToast?.(`Update failed: ${e.message}`, 'error');
                        await this._loadTasks();
                    }
                },
            });
        }
    }

    // ------------------------------------------------------------------
    // Task detail
    // ------------------------------------------------------------------

    _closeTaskDetail({ syncUrl = true } = {}) {
        const pid = this._paneId;
        const taskId = this._selectedTask;
        this._closeTaskStream(taskId);
        const detailPanel = document.getElementById(`taskDetail-${pid}`);
        const backdrop = document.getElementById(`taskDetailBackdrop-${pid}`);
        if (detailPanel) {
            detailPanel.classList.add('hidden');
            detailPanel.classList.remove('open');
            delete detailPanel.dataset.taskId;
            delete detailPanel.dataset.taskStatus;
        }
        if (backdrop) {
            backdrop.classList.add('hidden');
        }
        this._selectedTask = null;
        this._urlTaskTab = 'details';
        document.querySelectorAll(`.task-card.selected[data-task-id="${taskId || ''}"]`).forEach((card) => card.classList.remove('selected'));
        if (syncUrl) {
            this._syncUrlState({ taskId: null, taskTab: null });
        }
    }

    async _selectTask(taskId) {
        this._selectedTask = taskId;
        const board = document.getElementById(`kanbanBoard-${this._paneId}`);
        board?.querySelectorAll('.task-card').forEach(c => c.classList.toggle('selected', c.dataset.taskId === taskId));
        await this._showTaskDetail(taskId);
        this._syncUrlState({ taskId, taskTab: this._urlTaskTab || 'details' });
    }

    async _showTaskDetail(taskId) {
        const pid = this._paneId;
        const detailPanel = document.getElementById(`taskDetail-${pid}`);
        const backdrop = document.getElementById(`taskDetailBackdrop-${pid}`);
        if (!detailPanel) return;
        detailPanel.classList.remove('hidden');
        detailPanel.classList.add('open');
        if (backdrop) { backdrop.classList.remove('hidden'); }
        detailPanel.innerHTML = '<div class="empty-state"><div class="loading-spinner"></div></div>';
        try {
            const task = await NexusAPI.getTask(taskId, { execUser: this._getExecUser() });
            this._renderTaskDetail(task);
        } catch (e) {
            detailPanel.innerHTML = '<div class="empty-state"><p class="task-muted-note error">Failed to load task details</p></div>';
        }
    }

    _renderTaskDetail(task) {
        const pid = this._paneId;
        const detailPanel = document.getElementById(`taskDetail-${pid}`);
        if (!detailPanel) return;
        this._closeTaskStream(this._selectedTask);
        const statusClass = this._normalizeTaskStatus(task.status);
        const isRunning = statusClass === 'running';
        const hasConversation = isRunning || statusClass === 'completed' || statusClass === 'failed';
        const canCancelTask = this._canCancelTask(task);
        const alias = String(task?.alias || '').trim();
        const provider = String(task?.provider || '').trim();
        const displayAlias = this._normalizeProviderName(alias);
        const displayProvider = this._normalizeProviderName(provider);
        const targetPrimary = displayAlias || displayProvider;
        const targetSecondary = displayAlias && displayProvider && displayAlias.toLowerCase() !== displayProvider.toLowerCase() ? displayProvider : '';
        const targetTooltip = targetSecondary ? `Alias: ${displayAlias} · Provider: ${displayProvider}` : (displayAlias || displayProvider);
        const githubLabel = this._resolveGitHubIssueLabel(task);
        const githubUrl = this._resolveGitHubIssueUrl(task);

        detailPanel.dataset.taskId = task.id;
        detailPanel.dataset.taskStatus = statusClass;

        detailPanel.innerHTML = `
            <div class="task-detail-header">
                <span class="task-detail-title">#${task.id.slice(0, 8)}</span>
                <button class="task-detail-close" data-action="close-detail">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                </button>
            </div>
            <div class="task-detail-content task-detail-content-shell">
                <div class="task-detail-section task-detail-section-static">
                    <div class="task-detail-badge-row">
                        <span class="status-badge ${statusClass}"><span class="status-dot"></span>${task.status || 'TODO'}</span>
                        ${targetPrimary ? `<span class="task-target-badge" title="${this._esc(targetTooltip)}">${this._esc(targetPrimary)}</span>` : ''}
                        ${targetSecondary ? `<span class="task-target-badge task-target-badge-base" title="Base provider">${this._esc(targetSecondary)}</span>` : ''}
                        ${task.workspace ? `<span class="task-detail-workspace" title="${this._esc(task.workspace)}">${this._esc(task.workspace.split('/').pop() || task.workspace)}</span>` : ''}
                    </div>
                    <p class="task-detail-summary">${this._esc(task.description || 'No description')}</p>
                    ${task.error_message ? `<p class="task-detail-error">${this._esc(task.error_message)}</p>` : ''}
                    ${githubLabel ? `<p class="task-detail-meta-line">GitHub: ${githubUrl ? `<a href="${this._esc(githubUrl)}" target="_blank" rel="noopener noreferrer" class="task-detail-link">${this._esc(githubLabel)}</a>` : this._esc(githubLabel)}${task.github_state ? `<span class="task-detail-meta-inline">(${this._esc(String(task.github_state))})</span>` : ''}</p>` : ''}
                    ${(task.aegis_status || task.aegis_approved) ? `<p class="task-detail-meta-line ${task.aegis_approved ? 'is-success' : 'is-warning'}">Aegis: ${task.aegis_approved ? 'Approved' : this._esc(String(task.aegis_status || 'pending'))}${task.aegis_reason ? `<span class="task-detail-meta-inline"> · ${this._esc(task.aegis_reason)}</span>` : ''}</p>` : ''}
                    ${task.loop_enabled ? `<div class="task-loop-summary"><div class="task-loop-summary-header"><span class="task-loop-summary-title">Ralph Loop</span><span class="task-card-loop-badge ${task.loop_keyword_found ? 'is-found' : 'is-running'}">${task.loop_iteration||0}/${task.loop_max_iterations||1}${task.loop_keyword_found ? ' ✓ Found' : ''}</span></div><div class="task-loop-summary-keywords"><span>Keywords: </span>${(task.loop_keywords || []).map(kw => `<code class="task-loop-keyword">${this._esc(kw)}</code>`).join(' ')}</div></div>` : ''}
                </div>
                <div class="task-conversation task-conversation-shell">
                    <div class="task-detail-tab-row">
                        <button class="action-btn task-detail-tab active task-detail-tab-btn" data-task-tab="details">Details</button>
                        <button class="action-btn task-detail-tab task-detail-tab-btn" data-task-tab="comments">Comments</button>
                        <button class="action-btn task-detail-tab task-detail-tab-btn" data-task-tab="quality">Quality</button>
                        <button class="action-btn task-detail-tab task-detail-tab-btn" data-task-tab="timeline">Timeline</button>
                        <button class="action-btn task-detail-tab task-detail-tab-btn" data-task-tab="session">Run</button>
                    </div>
                    <div id="taskTabDetails-${pid}" data-task-tab-pane="details" class="task-detail-pane task-detail-pane-fill">
                        <div id="taskDetailsPanel-${pid}" class="task-detail-pane-body"></div>
                    </div>
                    <div id="taskTabComments-${pid}" data-task-tab-pane="comments" class="task-detail-pane" hidden>
                        <div id="taskComments-${pid}" class="task-detail-pane-body"><div class="loading-spinner task-pane-spinner"></div></div>
                    </div>
                    <div id="taskTabQuality-${pid}" data-task-tab-pane="quality" class="task-detail-pane" hidden>
                        <div id="taskQuality-${pid}" class="task-detail-pane-body"><div class="loading-spinner task-pane-spinner"></div></div>
                    </div>
                    <div id="taskTabTimeline-${pid}" data-task-tab-pane="timeline" class="task-detail-pane" hidden>
                        <div id="taskTimeline-${pid}" class="task-detail-pane-body"><div class="loading-spinner task-pane-spinner"></div></div>
                    </div>
                    <div id="taskTabSession-${pid}" data-task-tab-pane="session" class="task-detail-pane task-detail-pane-fill" hidden>
                        ${hasConversation ? `<div class="chat-messages task-conversation-messages" id="taskConversation-${pid}"><div class="empty-state task-conversation-empty"><div class="loading-spinner"></div><p class="task-muted-note">${isRunning ? 'Connecting to live stream...' : 'Loading conversation...'}</p></div></div>` : `<div class="empty-state task-conversation-empty"><p class="task-muted-note">Run view is available after task execution starts.</p></div>`}
                    </div>
                </div>
                <div class="task-detail-section task-detail-actions-section">
                    <div class="task-detail-action-row">
                        ${hasConversation ? `<button class="action-btn" data-action="view-session" data-task-id="${task.id}" title="Open in Chat view"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>Open Run</button>` : ''}
                        <button class="action-btn" data-action="broadcast-task" data-task-id="${task.id}" title="Broadcast"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405C18.21 15.21 18 14.702 18 14.172V11a6.002 6.002 0 00-4-5.659V4a2 2 0 10-4 0v1.341C7.67 6.165 6 8.388 6 11v3.172c0 .53-.21 1.039-.595 1.423L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>Broadcast</button>
                        ${canCancelTask ? `<button class="action-btn danger" data-action="cancel-task" data-task-id="${task.id}" title="Cancel task execution"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>Cancel</button>` : ''}
                        ${statusClass === 'completed' || statusClass === 'failed' ? `<button class="action-btn primary" data-action="continue-task" data-task-id="${task.id}" title="Continue task conversation"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/></svg>Continue</button>` : ''}
                        ${statusClass === 'completed' || statusClass === 'failed' ? `<button class="action-btn" data-action="set-outcome" data-task-id="${task.id}" title="Set task outcome">Outcome</button>` : ''}
                        <button class="action-btn task-detail-delete-btn" data-action="delete-task" data-task-id="${task.id}"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>Delete</button>
                    </div>
                </div>
            </div>
        `;

        this._bindDetailEvents(detailPanel, task);
        this._bindDetailTabs(detailPanel);
        this._loadDetailsTab(task);
        this._loadCommentsTab(task.id);
        this._loadQualityTab(task.id);
        this._loadTimelineTab(task.id);
        this._applyTaskTab(this._urlTaskTab || 'details', detailPanel);
        if (hasConversation) {
            if (isRunning) this._streamTaskConversation(task.id);
            else this._streamTaskConversation(task.id, true);
        }
    }

    _bindDetailEvents(panel, task) {
        panel.querySelector('[data-action="close-detail"]')?.addEventListener('click', () => {
            this._closeTaskDetail();
        });
        panel.querySelector('[data-action="delete-task"]')?.addEventListener('click', () => {
            this._getApp()?.showDeleteModal?.('task', task.id, () => this._deleteTask(task.id));
        });
        panel.querySelector('[data-action="cancel-task"]')?.addEventListener('click', async () => {
            await this._cancelTask(task);
        });
        panel.querySelector('[data-action="broadcast-task"]')?.addEventListener('click', async () => {
            const message = window.prompt('Broadcast message to task subscribers:');
            if (!message?.trim()) return;
            try {
                const result = await NexusAPI.broadcastTask(task.id, { message: message.trim(), sender: 'user', include_assignee: true }, { execUser: this._getExecUser() });
                this._getApp()?.showToast?.(`Broadcast sent to ${result.delivered || 0} subscribers`, 'success');
            } catch (e) {
                this._getApp()?.showToast?.(e.message || 'Failed to broadcast', 'error');
            }
        });
        panel.querySelector('[data-action="view-session"]')?.addEventListener('click', () => {
            const sessionId = task.session_id || `task_${task.id}`;
            const app = this._getApp();
            app?.pageManager?.setPage('chat');
            setTimeout(() => app?.chatView?.selectSession(0, sessionId), 300);
        });
        panel.querySelector('[data-action="continue-task"]')?.addEventListener('click', async () => {
            const message = window.prompt('Enter follow-up message for the task:');
            if (!message?.trim()) return;
            try {
                await NexusAPI.continueTask(task.id, message.trim(), { execUser: this._getExecUser() });
                this._getApp()?.showToast?.('Task continued', 'success');
                if (this._dataStore) this._dataStore.invalidate('tasks');
                await this._loadTasks();
            } catch (e) {
                this._getApp()?.showToast?.(e.message, 'error');
            }
        });
        panel.querySelector('[data-action="set-outcome"]')?.addEventListener('click', async () => {
            const outcomes = ['success', 'failed', 'partial', 'abandoned'];
            const outcome = window.prompt(`Set task outcome (${outcomes.join('/')}):`);
            if (!outcome?.trim()) return;
            if (!outcomes.includes(outcome.trim().toLowerCase())) {
                this._getApp()?.showToast?.(`Invalid outcome. Must be one of: ${outcomes.join(', ')}`, 'error');
                return;
            }
            const resolution = window.prompt('Resolution notes (optional):') || '';
            const ratingStr = window.prompt('Rating 1-5 (optional, leave empty to skip):') || '';
            const rating = ratingStr.trim() ? parseInt(ratingStr.trim(), 10) : null;
            if (rating !== null && (rating < 1 || rating > 5 || isNaN(rating))) {
                this._getApp()?.showToast?.('Rating must be between 1 and 5', 'error');
                return;
            }
            try {
                const data = { outcome: outcome.trim().toLowerCase(), resolution: resolution.trim() || undefined, feedback_rating: rating || undefined };
                await NexusAPI.updateTaskOutcome(task.id, data, { execUser: this._getExecUser() });
                this._getApp()?.showToast?.('Outcome set', 'success');
            } catch (e) {
                this._getApp()?.showToast?.(e.message, 'error');
            }
        });
    }

    _canCancelTaskStatus(status) {
        const normalized = this._normalizeTaskStatus(status);
        return normalized === 'pending' || normalized === 'running';
    }

    _canCancelTask(task) {
        return this._canCancelTaskStatus(task?.lane_status || task?.status);
    }

    async _cancelTask(task) {
        if (!task?.id) return;
        if (!this._canCancelTask(task)) {
            this._getApp()?.showToast?.('Only To Do or Doing tasks can enter Cancelled.', 'warning');
            return;
        }
        if (!confirm('Cancel this task?')) return;
        try {
            await NexusAPI.updateTaskStatus(task.id, 'cancelled', { execUser: this._getExecUser() });
            this._getApp()?.showToast?.('Task cancelled', 'success');
            if (this._dataStore) this._dataStore.invalidate('tasks');
            await this._loadTasks();
            if (this._selectedTask === task.id) {
                await this._showTaskDetail(task.id);
            }
        } catch (e) {
            this._getApp()?.showToast?.(e.message || 'Failed to cancel task', 'error');
        }
    }

    _bindDetailTabs(panel) {
        const pid = this._paneId;
        const buttons = panel.querySelectorAll('.task-detail-tab');
        const panes = {
            details: panel.querySelector(`#taskTabDetails-${pid}`),
            comments: panel.querySelector(`#taskTabComments-${pid}`),
            quality: panel.querySelector(`#taskTabQuality-${pid}`),
            timeline: panel.querySelector(`#taskTabTimeline-${pid}`),
            session: panel.querySelector(`#taskTabSession-${pid}`),
        };
        buttons.forEach(btn => {
            btn.addEventListener('click', () => {
                const target = btn.getAttribute('data-task-tab') || 'details';
                this._applyTaskTab(target, panel, panes);
                this._syncUrlState({ taskId: this._selectedTask, taskTab: target });
            });
        });
    }

    _applyTaskTab(target, panel = null, providedPanes = null) {
        const pid = this._paneId;
        const root = panel || document.getElementById(`taskDetail-${pid}`);
        if (!root) return;
        const buttons = root.querySelectorAll('.task-detail-tab');
        const panes = providedPanes || {
            details: root.querySelector(`#taskTabDetails-${pid}`),
            comments: root.querySelector(`#taskTabComments-${pid}`),
            quality: root.querySelector(`#taskTabQuality-${pid}`),
            timeline: root.querySelector(`#taskTabTimeline-${pid}`),
            session: root.querySelector(`#taskTabSession-${pid}`),
        };
        this._urlTaskTab = target || 'details';
        buttons.forEach(btn => {
            btn.classList.toggle('active', (btn.getAttribute('data-task-tab') || 'details') === this._urlTaskTab);
        });
        Object.entries(panes).forEach(([key, pane]) => {
            if (pane) pane.hidden = key !== this._urlTaskTab;
        });
    }

    _bindUrlState() {
        if (this._popstateHandler || typeof window === 'undefined') return;
        this._popstateHandler = () => {
            this._restoreTaskFromUrl().catch((error) => console.warn('Failed to restore task URL state:', error));
        };
        window.addEventListener('popstate', this._popstateHandler);
    }

    _readUrlTaskState() {
        if (typeof window === 'undefined') {
            return { page: 'chat', taskId: null, taskTab: 'details', taskSurface: 'board', taskSurfaceInvalid: false };
        }
        const params = new URLSearchParams(window.location.search);
        const explicitSurface = params.get('taskSurface');
        const legacyScheduleSurface = params.get('schedule') === '1' ? 'schedules' : null;
        const rawTaskSurface = explicitSurface || legacyScheduleSurface;
        const normalizedTaskSurface = rawTaskSurface ? this._normalizeSecondarySurface(rawTaskSurface) : null;
        return {
            page: (params.get('page') || 'chat').trim().toLowerCase(),
            taskId: (params.get('task') || '').trim() || null,
            taskTab: (params.get('taskTab') || params.get('tab') || 'details').trim().toLowerCase(),
            taskSurface: normalizedTaskSurface,
            taskSurfaceInvalid: Boolean(rawTaskSurface && normalizedTaskSurface === 'board' && rawTaskSurface !== 'board'),
        };
    }

    _syncUrlState({ taskId, taskTab, taskSurface } = {}, { replace = true } = {}) {
        if (typeof window === 'undefined') return;
        try {
            const url = new URL(window.location.href);
            const resolvedTaskId = taskId === undefined ? this._selectedTask : taskId;
            const resolvedTaskTab = taskTab === undefined ? this._urlTaskTab : taskTab;
            const resolvedTaskSurface = this._normalizeSecondarySurface(taskSurface === undefined ? this._secondarySurface : taskSurface);
            url.searchParams.set('page', 'task');
            if (resolvedTaskId) {
                url.searchParams.set('task', resolvedTaskId);
            } else {
                url.searchParams.delete('task');
            }
            if (resolvedTaskTab && resolvedTaskId) {
                url.searchParams.set('taskTab', resolvedTaskTab);
                url.searchParams.set('tab', resolvedTaskTab);
            } else {
                url.searchParams.delete('taskTab');
                url.searchParams.delete('tab');
            }
            if (resolvedTaskSurface && resolvedTaskSurface !== 'board') {
                url.searchParams.set('taskSurface', resolvedTaskSurface);
            } else {
                url.searchParams.delete('taskSurface');
            }
            if (resolvedTaskSurface === 'schedules') {
                url.searchParams.set('schedule', '1');
            } else {
                url.searchParams.delete('schedule');
            }
            const method = replace ? 'replaceState' : 'pushState';
            window.history[method]({}, '', url);
        } catch {
            // Best-effort URL sync only.
        }
    }

    async _restoreTaskFromUrl() {
        const { page, taskId, taskTab, taskSurface, taskSurfaceInvalid } = this._readUrlTaskState();
        if (page !== 'task') {
            return;
        }

        if (taskSurface && taskSurface !== this._secondarySurface) {
            await this._setSecondarySurface(taskSurface, { syncUrl: false });
        } else {
            this._applySecondarySurface(this._secondarySurface);
        }
        if (taskSurfaceInvalid) {
            this._syncUrlState({ taskSurface: this._secondarySurface }, { replace: true });
        }

        if (taskTab) {
            this._urlTaskTab = taskTab;
        }

        if (!taskId) {
            const detailPanel = document.getElementById(`taskDetail-${this._paneId}`);
            if (detailPanel && !detailPanel.classList.contains('hidden')) {
                this._closeTaskDetail({ syncUrl: false });
            }
            this._selectedTask = null;
            return;
        }

        if (!this._tasks.some(task => task.id === taskId)) {
            return;
        }

        if (this._selectedTask !== taskId) {
            await this._selectTask(taskId);
            return;
        }

        this._applyTaskTab(this._urlTaskTab || 'details');
    }

    _loadDetailsTab(task) {
        const pid = this._paneId;
        const root = document.getElementById(`taskDetailsPanel-${pid}`);
        if (!root) return;
        const app = this._getApp();
        const descHtml = app?.chatView?.formatMessageContent ? app.chatView.formatMessageContent(task.description || '') : this._esc(task.description || '');
        root.innerHTML = `
            <div class="task-detail-grid">
                <span class="task-detail-label">Task ID</span><span>${this._esc(task.id||'')}</span>
                <span class="task-detail-label">Status</span><span>${this._esc(task.status||'')}</span>
                <span class="task-detail-label">Priority</span><span>${this._esc(task.priority||'')}</span>
                <span class="task-detail-label">Assignee</span><span>${this._esc(task.assigned_to||'-')}</span>
                <span class="task-detail-label">Source Run</span><span>${this._esc(task.source_session_id||'-')}</span>
                <span class="task-detail-label">Created</span><span>${this._esc(task.created_at ? new Date(task.created_at).toLocaleString() : '-')}</span>
                <span class="task-detail-label">Updated</span><span>${this._esc(task.updated_at ? new Date(task.updated_at).toLocaleString() : '-')}</span>
                <span class="task-detail-label">Depends On</span><span>${Array.isArray(task.depends_on) && task.depends_on.length ? this._esc(task.depends_on.join(', ')) : '-'}</span>
            </div>
            <div class="task-detail-divider">
                <div class="task-detail-description-label">Description (Markdown)</div>
                <div class="message-text">${descHtml}</div>
            </div>
        `;
    }

    async _loadCommentsTab(taskId) {
        if (typeof TaskComponents?.renderTaskComments !== 'function') return;
        const pid = this._paneId;
        const container = document.getElementById(`taskComments-${pid}`);
        if (!container) return;
        this._mentionInputs.forEach(m => { try { m.destroy(); } catch {} });
        this._mentionInputs = [];
        await TaskComponents.renderTaskComments(container, taskId, {
            paneId: pid,
            mentionInputsByPane: { [pid]: this._mentionInputs },
        });
    }

    async _loadQualityTab(taskId) {
        if (typeof TaskComponents?.renderQualityGate !== 'function') return;
        const pid = this._paneId;
        const container = document.getElementById(`taskQuality-${pid}`);
        if (!container) return;
        await TaskComponents.renderQualityGate(container, taskId, {
            paneId: pid,
            onRefresh: async (tid) => {
                await this._loadTasks();
                await this._showTaskDetail(tid);
            },
        });
    }

    async _loadTimelineTab(taskId) {
        if (typeof TaskComponents?.renderTaskTimeline !== 'function') return;
        const pid = this._paneId;
        const container = document.getElementById(`taskTimeline-${pid}`);
        if (!container) return;
        await TaskComponents.renderTaskTimeline(container, taskId, { paneId: pid });
    }

    // ------------------------------------------------------------------
    // SSE streaming
    // ------------------------------------------------------------------

    _streamTaskConversation(taskId, isReplay = false) {
        this._closeTaskStream(taskId);
        const pid = this._paneId;
        const container = document.getElementById(`taskConversation-${pid}`);
        if (!container) return;
        const es = NexusAPI.streamTaskMessages(taskId, { execUser: this._getExecUser(), tail: 5000 });
        this._activeStreams.set(taskId, es);
        let bubbleEl = null, currentTextEl = null, currentTextContent = '', textSegmentIndex = 0;
        const streamingToolCalls = new Map();
        let initialized = false, runFinished = false;
        const app = this._getApp();
        const chatView = app?.chatView;

        const ensureBubble = () => {
            if (!bubbleEl) {
                if (!initialized) { container.innerHTML = ''; initialized = true; }
                const msgId = `task-stream-msg-${Date.now()}`;
                container.insertAdjacentHTML('beforeend', `<div class="message assistant" id="${msgId}"><div class="message-avatar assistant"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg></div><div class="message-content"><div class="message-bubble streaming-bubble" id="task-bubble-${msgId}"></div></div></div>`);
                bubbleEl = document.getElementById(`task-bubble-${msgId}`);
            }
            return bubbleEl;
        };
        const ensureTextElement = () => {
            if (!currentTextEl) {
                const bubble = ensureBubble();
                if (bubble) {
                    const textId = `task-stream-text-${taskId}-seg${streamingController.currentTextSegmentIndex}`;
                    bubble.insertAdjacentHTML('beforeend', `<div class="message-text streaming" id="${textId}"></div>`);
                    currentTextEl = document.getElementById(textId);
                }
            }
            return currentTextEl;
        };

        const finishStream = (data) => {
            runFinished = true;
            if (currentTextEl) currentTextEl.classList.remove('streaming');
            const isError = data?.type === 'RUN_ERROR';
            container.insertAdjacentHTML(
                'beforeend',
                `<div class="task-stream-banner ${isError ? 'error' : 'success'}">${isError ? `Task failed${data?.message ? ': ' + this._esc(data.message) : ''}` : '✓ Task completed'}</div>`,
            );
            container.scrollTop = container.scrollHeight;
            this._closeTaskStream(taskId);
            if (!isReplay) {
                if (this._dataStore) this._dataStore.invalidate('tasks');
                this._loadTasks();
                app?.chatView?.loadSessions?.(0);
            }
        };

        const streamingController = NexusStreamingController.create({
            onTextStart: () => ensureBubble(),
            onTextContent: (text) => {
                const textEl = ensureTextElement();
                currentTextContent = text;
                if (textEl && chatView) {
                    textEl.innerHTML = chatView.formatMessageContent(currentTextContent);
                    container.scrollTop = container.scrollHeight;
                }
            },
            onTextEnd: () => {
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                currentTextEl = null;
                currentTextContent = '';
            },
            onToolCallStart: (toolCall, data = {}) => {
                const toolCallId = toolCall.id;
                const toolName = toolCall.name;
                const toolTitle = chatView?.formatToolCallTitle?.(toolName, {}, '') || toolName;
                streamingToolCalls.set(toolCallId, {
                    name: toolName,
                    displayName: '',
                    description: '',
                    args: '',
                    status: 'executing',
                    result: '',
                });
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                currentTextEl = null;
                currentTextContent = '';
                const bubble = ensureBubble();
                if (bubble && chatView) {
                    bubble.insertAdjacentHTML('beforeend', chatView.renderStreamingToolCall(toolCallId, toolTitle, 'executing'));
                    container.scrollTop = container.scrollHeight;
                }
            },
            onToolCallArgs: (toolCall) => {
                const tc = streamingToolCalls.get(toolCall.id);
                if (tc) {
                    tc.args = toolCall.args || '';
                    const domToken = NexusStreamingController.toolCallDomToken(toolCall.id);
                    const argsEl = document.getElementById(`streaming-tool-args-${domToken}`);
                    if (argsEl) argsEl.textContent = tc.args;
                    const titleEl = document.querySelector(`[data-streaming-tool-token="${domToken}"] .tool-call-name`);
                    if (titleEl && chatView) {
                        titleEl.textContent = tc.displayName
                            || chatView.formatToolCallTitle(tc.name, tc.description ? { description: tc.description } : {}, tc.args);
                    }
                }
            },
            onToolCallEnd: (toolCall, data) => {
                const tc = streamingToolCalls.get(toolCall.id);
                if (tc) {
                    tc.status = toolCall.status;
                    tc.result = toolCall.result || '';
                    const domToken = NexusStreamingController.toolCallDomToken(toolCall.id);
                    const statusEl = document.querySelector(`[data-streaming-tool-token="${domToken}"] .tool-call-status-icon`);
                    if (statusEl) {
                        NexusStreamingController.setToolCallStatus(statusEl, !!data.error);
                    }
                    const resultSection = document.getElementById(`streaming-tool-result-section-${domToken}`);
                    const resultEl = document.getElementById(`streaming-tool-result-${domToken}`);
                    if (resultSection && resultEl && tc.result) {
                        NexusStreamingController.setElementVisibility(resultSection, true);
                        resultEl.textContent = typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2);
                    }
                    container.scrollTop = container.scrollHeight;
                }
            },
            onToolCallResult: (toolCall) => {
                const tc = streamingToolCalls.get(toolCall.id);
                if (tc) {
                    tc.result = toolCall.result || '';
                    const domToken = NexusStreamingController.toolCallDomToken(toolCall.id);
                    const s = document.getElementById(`streaming-tool-result-section-${domToken}`);
                    const el = document.getElementById(`streaming-tool-result-${domToken}`);
                    if (s && el && tc.result) {
                        NexusStreamingController.setElementVisibility(s, true);
                        el.textContent = typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2);
                    }
                }
            },
            onRunFinished: () => finishStream({ type: 'RUN_FINISHED' }),
            onRunError: (data) => finishStream(data || { type: 'RUN_ERROR' }),
        });

        es.onmessage = (event) => {
            if (runFinished) return;
            let data;
            try { data = JSON.parse(event.data); } catch { return; }
            streamingController.processEvent(data);
        };
        es.onerror = () => { if (!runFinished && es.readyState !== EventSource.CLOSED) console.warn(`Task ${taskId} SSE error`); };
    }

    _closeTaskStream(taskId) {
        if (!taskId) return;
        const es = this._activeStreams.get(taskId);
        if (es) { es.close(); this._activeStreams.delete(taskId); }
    }

    // ------------------------------------------------------------------
    // Toolbar event bindings
    // ------------------------------------------------------------------

    _bindToolbarEvents() {
        const c = this.container;
        if (!c) return;
        const pid = this._paneId;

        // Backdrop click closes detail overlay
        const backdrop = document.getElementById(`taskDetailBackdrop-${pid}`);
        if (backdrop) {
            backdrop.addEventListener('click', () => {
                const detailPanel = document.getElementById(`taskDetail-${pid}`);
                if (detailPanel && !detailPanel.classList.contains('hidden')) {
                    this._closeTaskDetail();
                }
            });
        }

        c.querySelector('[data-action="create-task"]')?.addEventListener('click', () => this._getApp()?.taskFormController?.showCreateTaskModal?.('single'));
        c.querySelector('[data-action="toggle-selection"]')?.addEventListener('click', () => this._toggleSelectionMode());
        c.querySelector('[data-action="select-all"]')?.addEventListener('click', () => this._selectAllTasks());
        c.querySelector('[data-action="deselect-all"]')?.addEventListener('click', () => this._deselectAllTasks());
        c.querySelector('[data-action="delete-selected"]')?.addEventListener('click', () => this._deleteSelectedTasks());
        c.querySelector('[data-action="toggle-archived"]')?.addEventListener('click', () => this._toggleArchived());
        c.querySelector('[data-action="refresh-schedules"]')?.addEventListener('click', () => this._loadSchedules());

        c.querySelectorAll('[data-action="set-surface"]').forEach((btn) => {
            btn.addEventListener('click', () => this._setSecondarySurface(btn.dataset.surface, { replace: false }));
        });

        // K-005: View toggle
        c.querySelectorAll('[data-action="set-view"]').forEach(btn => {
            btn.addEventListener('click', () => this._setViewMode(btn.dataset.view));
        });

        // Sort and project filter are now handled by SortButton/ProjectButton in FilterBar

        const searchInput = document.getElementById(`taskSearch-${pid}`);
        if (searchInput) {
            let t;
            searchInput.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => this._loadTasks(), 300); });
        }
        document.getElementById(`scheduleStatusFilter-${pid}`)?.addEventListener('change', () => this._loadSchedules());
    }

    // ------------------------------------------------------------------
    // Selection mode
    // ------------------------------------------------------------------

    _toggleSelectionMode() {
        this._selectionMode = !this._selectionMode;
        if (!this._selectionMode) this._selectedTaskIds = new Set();
        const pid = this._paneId;
        const el = document.getElementById(`selectionActions-${pid}`);
        if (el) el.hidden = !this._selectionMode;
        this._renderKanban();
        this._updateDeleteBtnCount();
    }

    _toggleTaskSelection(taskId) {
        if (this._selectedTaskIds.has(taskId)) this._selectedTaskIds.delete(taskId);
        else this._selectedTaskIds.add(taskId);
        const card = this.container?.querySelector(`.task-card[data-task-id="${taskId}"]`);
        if (card) {
            card.classList.toggle('checked', this._selectedTaskIds.has(taskId));
            const cb = card.querySelector('.task-card-checkbox input');
            if (cb) cb.checked = this._selectedTaskIds.has(taskId);
        }
        this._updateDeleteBtnCount();
    }

    _selectAllTasks() {
        this._selectedTaskIds = new Set(this._tasks.map(t => t.id));
        this.container?.querySelectorAll('.task-card').forEach(c => {
            c.classList.add('checked');
            const cb = c.querySelector('.task-card-checkbox input');
            if (cb) cb.checked = true;
        });
        this._updateDeleteBtnCount();
    }

    _deselectAllTasks() {
        this._selectedTaskIds = new Set();
        this.container?.querySelectorAll('.task-card').forEach(c => {
            c.classList.remove('checked');
            const cb = c.querySelector('.task-card-checkbox input');
            if (cb) cb.checked = false;
        });
        this._updateDeleteBtnCount();
    }

    _updateDeleteBtnCount() {
        const count = this._selectedTaskIds.size;
        const btn = document.getElementById(`deleteSelectedBtn-${this._paneId}`);
        if (btn) {
            const span = btn.querySelector('span');
            if (span) span.textContent = `Delete (${count})`;
            btn.disabled = count === 0;
        }
    }

    async _deleteSelectedTasks() {
        const ids = Array.from(this._selectedTaskIds);
        if (ids.length === 0) { this._getApp()?.showToast?.('No tasks selected', 'warning'); return; }
        this._getApp()?.showDeleteModal?.('tasks', `${ids.length} tasks`, async () => {
            try {
                const result = await NexusAPI.bulkDeleteTasks(ids, { execUser: this._getExecUser() });
                this._getApp()?.showToast?.(`Deleted ${result.result?.count || ids.length} tasks`, 'success');
                this._selectedTaskIds = new Set();
                this._updateDeleteBtnCount();
                if (this._dataStore) this._dataStore.invalidate('tasks');
                await this._loadTasks();
            } catch (e) {
                this._getApp()?.showToast?.('Failed to delete tasks', 'error');
            }
        });
    }

    async _deleteTask(taskId) {
        try {
            await NexusAPI.deleteTask(taskId, { execUser: this._getExecUser() });
            this._getApp()?.showToast?.('Task deleted', 'success');
            this._closeTaskDetail();
            if (this._dataStore) this._dataStore.invalidate('tasks');
            await this._loadTasks();
        } catch (e) {
            this._getApp()?.showToast?.('Failed to delete task', 'error');
        }
    }

    // ------------------------------------------------------------------
    // Kanban drag-drop
    // ------------------------------------------------------------------

    _bindKanbanDragDrop() {
        const pid = this._paneId;
        const board = document.getElementById(`kanbanBoard-${pid}`);
        if (!board || typeof KanbanDragDrop === 'undefined') return;
        KanbanDragDrop.mount(board, {
            getTaskStatus: (taskId) => {
                const task = this._tasks.find(t => t.id === taskId);
                return task ? this._normalizeTaskStatus(task.status) : null;
            },
            getTaskPosition: (taskId) => {
                const task = this._tasks.find(t => t.id === taskId);
                return task?.position ?? 0;
            },
            onDragStart: () => {
                this._isDragging = true;
                this._dragSnapshot = this._tasks.map(t => ({ ...t }));
                this._pendingUpdates = [];
            },
            onDragEnd: () => {
                this._isDragging = false;
                // Merge any queued updates
                if (this._pendingUpdates.length > 0) {
                    const latest = this._pendingUpdates[this._pendingUpdates.length - 1];
                    // Preserve local position overrides from the drag
                    const posMap = new Map();
                    this._tasks.forEach(t => { if (t.position != null) posMap.set(t.id, t.position); });
                    this._tasks = latest.map(t => ({
                        ...t,
                        position: posMap.has(t.id) ? posMap.get(t.id) : t.position,
                    }));
                }
                this._pendingUpdates = [];
                this._dragSnapshot = null;
                this._renderKanban();
            },
            onMove: async (taskId, toStatus, fromStatus, newPosition) => {
                try {
                    if (toStatus === 'cancelled' && !this._canCancelTaskStatus(fromStatus)) {
                        this._getApp()?.showToast?.('Only To Do or Doing tasks can enter Cancelled.', 'warning');
                        this._renderKanban();
                        return;
                    }
                    await NexusAPI.updateTaskStatus(taskId, toStatus, { execUser: this._getExecUser() });
                    await NexusAPI.updateTask(taskId, { position: newPosition }, { execUser: this._getExecUser() });
                    const local = this._tasks.find(t => t.id === taskId);
                    if (local) {
                        local.status = toStatus;
                        local.position = newPosition;
                    }
                    this._renderKanban();
                    if (this._selectedTask === taskId) {
                        const task = this._tasks.find(t => t.id === taskId);
                        if (task) this._renderTaskDetail(task);
                    }
                    this._getApp()?.showToast?.(`Task moved: ${fromStatus} → ${toStatus}`, 'success');
                    if (this._dataStore) this._dataStore.invalidate('tasks');
                } catch (e) {
                    this._getApp()?.showToast?.(`Move failed: ${e.message}`, 'error');
                    await this._loadTasks();
                }
            },
            onReorder: async (taskId, status, newPosition) => {
                const local = this._tasks.find(t => t.id === taskId);
                if (local) local.position = newPosition;
                this._renderKanban();
                try {
                    await NexusAPI.updateTask(taskId, { position: newPosition }, { execUser: this._getExecUser() });
                    if (this._dataStore) this._dataStore.invalidate('tasks');
                } catch (e) {
                    this._getApp()?.showToast?.(`Reorder failed: ${e.message}`, 'error');
                    await this._loadTasks();
                }
            },
        });
    }

    // ------------------------------------------------------------------
    // View mode (K-005) & Filter panel (K-003)
    // ------------------------------------------------------------------

    _setViewMode(mode) {
        if (mode === this._viewMode) return;
        this._viewMode = mode;
        localStorage.setItem('nexus-kanban-viewMode', mode);
        const pid = this._paneId;
        const listContainer = document.getElementById(`listViewContainer-${pid}`);
        this._syncBoardVisibility(this._getFilteredTasks().length > 0, mode);
        if (listContainer) listContainer.hidden = this._secondarySurface !== 'board' || mode !== 'list';

        // Update toggle button styles
        this.container?.querySelectorAll('[data-action="set-view"]').forEach(btn => {
            const active = btn.dataset.view === mode;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        if (mode === 'list' && this._listView) {
            this._listView.updateTasks(this._getFilteredTasks());
        }
    }

    _syncBoardVisibility(hasVisibleTasks = this._getFilteredTasks().length > 0, mode = this._viewMode) {
        const pid = this._paneId;
        const board = document.getElementById(`kanbanBoard-${pid}`);
        const emptyState = document.getElementById(`taskBoardEmptyState-${pid}`);
        const showBoard = this._secondarySurface === 'board' && mode === 'board' && hasVisibleTasks;
        const showEmptyState = this._secondarySurface === 'board' && mode === 'board' && !hasVisibleTasks;
        if (board) board.hidden = !showBoard;
        if (emptyState) emptyState.hidden = !showEmptyState;
    }

    _initFilterBar() {
        const pid = this._paneId;
        const container = document.getElementById(`filterBar-${pid}`);
        if (!container || typeof FilterBar === 'undefined') return;
        this._filterBar = new FilterBar(this);
        this._filterBar.render(container);

        // Init SortButton and ProjectButton
        const dropdownsContainer = document.getElementById(`toolbarDropdowns-${pid}`);
        if (dropdownsContainer) {
            if (typeof SortButton !== 'undefined') {
                this._sortBtn = new SortButton(this);
                this._sortBtn.render(dropdownsContainer);
            }
            if (typeof ProjectButton !== 'undefined') {
                this._projectBtn = new ProjectButton(this);
                this._projectBtn.render(dropdownsContainer);
            }
        }
    }

    _initListView() {
        const pid = this._paneId;
        const container = document.getElementById(`listViewContainer-${pid}`);
        if (!container || typeof ListView === 'undefined') return;
        this._listView = new ListView({
            container,
            tasks: [],
            statusColumns: this.statusColumns,
            terminalColumns: this.terminalColumns,
            onTaskClick: (taskId) => this._selectTask(taskId),
            onBatchStatusChange: async (ids, newStatus) => {
                try {
                    for (const id of ids) {
                        await NexusAPI.updateTaskStatus(id, newStatus, { execUser: this._getExecUser() });
                    }
                    this._getApp()?.showToast?.(`Updated ${ids.length} tasks`, 'success');
                    if (this._dataStore) this._dataStore.invalidate('tasks');
                    await this._loadTasks();
                } catch (e) {
                    this._getApp()?.showToast?.(`Batch update failed: ${e.message}`, 'error');
                }
            },
            onBatchPriorityChange: async (ids, newPriority) => {
                try {
                    for (const id of ids) {
                        await NexusAPI.updateTask(id, { priority: newPriority }, { execUser: this._getExecUser() });
                    }
                    this._getApp()?.showToast?.(`Updated priority for ${ids.length} tasks`, 'success');
                    if (this._dataStore) this._dataStore.invalidate('tasks');
                    await this._loadTasks();
                } catch (e) {
                    this._getApp()?.showToast?.(`Batch priority update failed: ${e.message}`, 'error');
                }
            },
            onBatchAssign: async (ids, assignee) => {
                try {
                    for (const id of ids) {
                        await NexusAPI.updateTask(id, { assignee }, { execUser: this._getExecUser() });
                    }
                    this._getApp()?.showToast?.(`Assigned ${ids.length} tasks to ${assignee}`, 'success');
                    if (this._dataStore) this._dataStore.invalidate('tasks');
                    await this._loadTasks();
                } catch (e) {
                    this._getApp()?.showToast?.(`Batch assign failed: ${e.message}`, 'error');
                }
            },
            onDeleteTasks: async (ids) => {
                this._getApp()?.showDeleteModal?.('tasks', `${ids.length} tasks`, async () => {
                    try {
                        await NexusAPI.bulkDeleteTasks(ids, { execUser: this._getExecUser() });
                        this._getApp()?.showToast?.(`Deleted ${ids.length} tasks`, 'success');
                        if (this._dataStore) this._dataStore.invalidate('tasks');
                        await this._loadTasks();
                    } catch (e) {
                        this._getApp()?.showToast?.('Failed to delete tasks', 'error');
                    }
                });
            },
        });
    }

    /**
     * Get tasks after applying the filter panel.
     */
    _getFilteredTasks() {
        if (this._filterBar && this._filterBar.hasActiveFilters()) {
            return this._filterBar.applyFilter(this._tasks);
        }
        return this._tasks;
    }

    // ------------------------------------------------------------------
    // Schedules
    // ------------------------------------------------------------------

    _toggleSchedulePanel() {
        const nextSurface = this._secondarySurface === 'schedules' ? 'board' : 'schedules';
        this._setSecondarySurface(nextSurface, { replace: false });
    }

    _toggleArchived() {
        const pid = this._paneId;
        this._showArchived = !this._showArchived;
        // Toggle archived column visibility
        const archivedCol = this.container?.querySelector(`.kanban-column[data-status="archived"]`);
        if (archivedCol) {
            archivedCol.hidden = !this._showArchived;
        }
        // Update button label
        const btn = document.getElementById(`toggleArchivedBtn-${pid}`);
        if (btn) {
            const span = btn.querySelector('span');
            if (span) span.textContent = this._showArchived ? 'Hide Archived' : 'Show Archived';
            btn.classList.toggle('is-outlined', !this._showArchived);
        }
    }

    async _loadSchedules() {
        const pid = this._paneId;
        const listEl = document.getElementById(`scheduleList-${pid}`);
        if (!listEl) return;
        const statusFilter = document.getElementById(`scheduleStatusFilter-${pid}`)?.value || '';
        try {
            const schedOpts = { status: statusFilter || undefined, pageSize: 100 };
            const data = await (this._dataStore
                ? this._dataStore.fetch('schedules', schedOpts)
                : NexusAPI.getSchedules(schedOpts));
            const schedules = data.schedules || [];
            this._scheduleSummaryCount = schedules.filter(s => String(s?.status || '').trim().toLowerCase() === 'active').length;
            this._renderSummaryStrip();
            if (schedules.length === 0) {
                listEl.innerHTML = '<div class="empty-state schedule-empty-state"><p class="u-text-muted u-text-sm">No schedules found</p></div>';
                return;
            }
            listEl.innerHTML = schedules.map(s => this._renderScheduleCard(s)).join('');
            listEl.querySelectorAll('.schedule-card').forEach(card => {
                const sid = card.dataset.scheduleId;
                card.querySelector('[data-action="trigger-schedule"]')?.addEventListener('click', e => { e.stopPropagation(); this._triggerSchedule(sid); });
                card.querySelector('[data-action="pause-schedule"]')?.addEventListener('click', e => { e.stopPropagation(); this._pauseSchedule(sid); });
                card.querySelector('[data-action="resume-schedule"]')?.addEventListener('click', e => { e.stopPropagation(); this._resumeSchedule(sid); });
                card.querySelector('[data-action="cancel-schedule"]')?.addEventListener('click', e => { e.stopPropagation(); this._cancelSchedule(sid); });
                card.querySelector('[data-action="edit-schedule"]')?.addEventListener('click', e => { e.stopPropagation(); this._showEditScheduleModal(sid); });
                card.querySelector('[data-action="delete-schedule"]')?.addEventListener('click', e => { e.stopPropagation(); this._deleteSchedule(sid); });
                card.querySelector('[data-action="toggle-history"]')?.addEventListener('click', e => { e.stopPropagation(); this._toggleScheduleHistory(sid); });
            });
        } catch (e) {
            this._scheduleSummaryCount = 0;
            this._renderSummaryStrip();
            listEl.innerHTML = '<div class="empty-state schedule-empty-state"><p class="u-text-error u-text-sm">Failed to load schedules</p></div>';
        }
    }

    _renderScheduleCard(schedule) {
        const isActive = schedule.status === 'active';
        const isPaused = schedule.status === 'paused';
        const isCancelled = schedule.status === 'cancelled';
        const nextRun = schedule.next_run_at ? new Date(schedule.next_run_at).toLocaleString() : '-';
        const lastRun = schedule.last_run_at ? new Date(schedule.last_run_at).toLocaleString() : 'Never';
        const maxRunsText = schedule.max_runs ? `${schedule.run_count}/${schedule.max_runs}` : `${schedule.run_count}`;
        let triggerBadge = schedule.run_at
            ? `<code class="schedule-cron-badge" title="One-time schedule">Once @ ${this._esc(new Date(schedule.run_at).toLocaleString())}</code>`
            : `<code class="schedule-cron-badge">${this._esc(schedule.cron_expression || '-')}</code>`;
        const kindBadge = schedule.schedule_kind === 'evolution' ? `<span class="schedule-kind-badge evolution" title="Evolution schedule">♻ ${this._esc(schedule.evolution_phase || 'evolve')}</span>` : '';
        const isSystem = schedule.schedule_kind === 'evolution';

        return `
            <div class="schedule-card" data-schedule-id="${schedule.id}">
                <div class="schedule-card-header">
                    <div class="schedule-card-info">
                        <span class="schedule-status-dot ${this._esc(schedule.status || "default")}"></span>
                        <span class="schedule-card-name">${this._esc(schedule.name)}</span>
                        ${kindBadge}${triggerBadge}
                    </div>
                    <div class="schedule-card-actions">
                        ${isActive ? `<button class="schedule-action-btn" data-action="trigger-schedule" title="Trigger now"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="u-icon-xs"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button><button class="schedule-action-btn" data-action="pause-schedule" title="Pause"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="u-icon-xs"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button>` : ''}
                        ${isPaused ? `<button class="schedule-action-btn" data-action="resume-schedule" title="Resume"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="u-icon-xs"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button>` : ''}
                        ${!isCancelled ? `<button class="schedule-action-btn" data-action="cancel-schedule" title="Cancel"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="u-icon-xs"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button>` : ''}
                        <button class="schedule-action-btn${isSystem ? ' is-hidden' : ''}" data-action="edit-schedule" title="Edit"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="u-icon-xs"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
                        <button class="schedule-action-btn" data-action="toggle-history" title="Execution History"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="u-icon-xs"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button>
                        <button class="schedule-action-btn danger${isSystem ? ' is-hidden' : ''}" data-action="delete-schedule" title="Delete"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="u-icon-xs"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>
                    </div>
                </div>
                <div class="schedule-card-meta">
                    <span title="Provider">${this._esc(schedule.alias || schedule.provider || '-')}</span>
                    <span title="Runs">${maxRunsText} runs</span>
                    <span title="Next run">Next: ${nextRun}</span>
                    <span title="Last run">Last: ${lastRun}</span>
                </div>
                <div class="schedule-card-desc">${this._esc(schedule.description || '').substring(0, 120)}${(schedule.description || '').length > 120 ? '...' : ''}</div>
                <div class="schedule-history schedule-history-panel" id="scheduleHistory-${schedule.id}" hidden>
                    <div class="schedule-history-loading">Loading history...</div>
                </div>
            </div>
        `;
    }

    async _toggleScheduleHistory(scheduleId) {
        const histEl = document.getElementById(`scheduleHistory-${scheduleId}`);
        if (!histEl) return;
        if (!histEl.hidden) {
            histEl.hidden = true;
            return;
        }
        histEl.hidden = false;
        histEl.innerHTML = '<div class="schedule-history-loading">Loading history...</div>';
        try {
            const data = await NexusAPI.getScheduleHistory(scheduleId);
            const taskIds = data.task_ids || data.history || [];
            if (taskIds.length === 0) {
                histEl.innerHTML = '<div class="schedule-history-empty">No execution history</div>';
                return;
            }
            histEl.innerHTML = `<div class="schedule-history-header">Execution History (${taskIds.length})</div>` +
                taskIds.slice(0, 20).map(id => {
                    const tid = typeof id === 'string' ? id : (id.task_id || id.id || '');
                    const ts = id.created_at ? new Date(id.created_at).toLocaleString() : '';
                    const status = id.status || '';
                    return `<div class="schedule-history-row">
                        <button type="button" class="schedule-history-task-link" data-action="open-task-history" data-task-id="${this._esc(tid)}">#${this._esc(tid.slice(0, 8))}</button>
                        ${ts ? `<span class="schedule-history-meta">${ts}</span>` : ''}
                        ${status ? `<span class="schedule-history-meta">${this._esc(status)}</span>` : ''}
                    </div>`;
                }).join('');
            histEl.querySelectorAll('[data-action="open-task-history"]').forEach((btn) => {
                btn.addEventListener('click', () => {
                    const tid = btn.dataset.taskId;
                    if (tid) {
                        this._selectTask(tid);
                    }
                });
            });
        } catch (e) {
            histEl.innerHTML = `<div class="schedule-history-error">Failed to load history: ${this._esc(e.message)}</div>`;
        }
    }

    async _triggerSchedule(id) { try { await NexusAPI.triggerSchedule(id); this._getApp()?.showToast?.('Schedule triggered', 'success'); this._loadSchedules(); } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); } }
    async _pauseSchedule(id) { try { await NexusAPI.pauseSchedule(id); this._getApp()?.showToast?.('Schedule paused', 'success'); this._loadSchedules(); } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); } }
    async _resumeSchedule(id) { try { await NexusAPI.resumeSchedule(id); this._getApp()?.showToast?.('Schedule resumed', 'success'); this._loadSchedules(); } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); } }
    async _cancelSchedule(id) { if (!confirm('Cancel this schedule permanently?')) return; try { await NexusAPI.cancelSchedule(id); this._getApp()?.showToast?.('Schedule cancelled', 'success'); this._loadSchedules(); } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); } }
    async _requeueOrphanTask(taskId) {
        if (!confirm('Requeue this orphaned task?')) return;
        try {
            await NexusAPI.requeueOrphanTask(taskId, { execUser: this._getExecUser() });
            this._getApp()?.showToast?.('Task requeued', 'success');
            if (this._dataStore) this._dataStore.invalidate('tasks');
            await this._loadTasks();
        } catch (e) {
            this._getApp()?.showToast?.(e.message, 'error');
        }
    }

    async _deleteSchedule(id) { if (!confirm('Delete this schedule?')) return; try { await NexusAPI.deleteSchedule(id); if (this._dataStore) this._dataStore.invalidate('schedules'); this._getApp()?.showToast?.('Schedule deleted', 'success'); this._loadSchedules(); } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); } }
    async _showEditScheduleModal(id) {
        try {
            const s = await NexusAPI.getSchedule(id);
            const modal = document.getElementById('editScheduleModal');
            if (!modal) return;
            document.getElementById('editScheduleId').value = s.id;
            document.getElementById('editScheduleName').value = s.name || '';
            document.getElementById('editScheduleCron').value = s.cron_expression || '';
            document.getElementById('editScheduleTimezone').value = s.timezone || 'UTC';
            document.getElementById('editScheduleDescription').value = s.description || '';
            document.getElementById('editScheduleWorkspace').value = s.workspace || '';
            document.getElementById('editScheduleMaxRuns').value = s.max_runs || '';
            modal.classList.add('open');
        } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); }
    }

    // ------------------------------------------------------------------
    // Auto-polling
    // ------------------------------------------------------------------

    _startAutoPolling() {
        if (this._smartPoll) return;
        if (typeof SmartPoll === 'undefined') return;
        this._smartPoll = new SmartPoll(async () => {
            const app = this._getApp();
            if (app?.pageManager?.currentPage !== 'task') return;
            if (this._dataStore) {
                this._dataStore.invalidate('tasks');
            }
            await this._loadTasks();
            const hasRunning = this._tasks.some(t => this._normalizeTaskStatus(t.status) === 'running');
            if (hasRunning) app?.chatView?.loadSessions?.(0);
        }, { intervalMs: this._pollInterval });
        this._smartPoll.start();
    }

    _stopAutoPolling() {
        if (this._smartPoll) { this._smartPoll.destroy(); this._smartPoll = null; }
    }

    // ------------------------------------------------------------------
    // Sync selected task detail after refresh
    // ------------------------------------------------------------------

    _syncSelectedTaskDetail() {
        if (!this._selectedTask) return;
        const pid = this._paneId;
        const latest = this._tasks.find(t => t.id === this._selectedTask);
        const detailPanel = document.getElementById(`taskDetail-${pid}`);
        if (!latest) {
            this._closeTaskDetail();
        } else if (detailPanel) {
            const latestStatus = this._normalizeTaskStatus(latest.status);
            const renderedStatus = detailPanel.dataset.taskStatus || '';
            const renderedId = detailPanel.dataset.taskId || '';
            const hasConvDom = !!detailPanel.querySelector(`#taskConversation-${pid}`);
            const shouldHaveConv = ['running', 'completed', 'failed'].includes(latestStatus);
            const isStreaming = this._activeStreams.has(this._selectedTask);
            if ((renderedId !== this._selectedTask || renderedStatus !== latestStatus || (shouldHaveConv && !hasConvDom)) && !isStreaming) {
                this._renderTaskDetail(latest);
            }
        }
    }

    // ------------------------------------------------------------------
    // Completed column infinite scroll (K-008)
    // ------------------------------------------------------------------

    _setupCompletedInfiniteScroll(pid) {
        // Disconnect previous observer
        if (this._completedObserver) {
            this._completedObserver.disconnect();
            this._completedObserver = null;
        }
        const sentinel = document.getElementById(`completedScrollSentinel-${pid}`);
        if (!sentinel) return;

        this._completedObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && !this._completedLoading) {
                    this._loadMoreCompletedTasks(pid);
                }
            });
        }, { root: sentinel.closest('.kanban-column-items'), threshold: 0.1 });

        this._completedObserver.observe(sentinel);
    }

    _loadMoreCompletedTasks(pid) {
        if (this._completedLoading) return;
        if (this._completedLoadedCount >= this._completedAllTasks.length) return;

        this._completedLoading = true;
        const nextBatch = this._completedAllTasks.slice(
            this._completedLoadedCount,
            this._completedLoadedCount + this._completedPageSize
        );
        this._completedLoadedCount += nextBatch.length;

        const el = document.getElementById(`items-${pid}-completed`);
        if (!el) { this._completedLoading = false; return; }

        // Remove old sentinel
        const oldSentinel = document.getElementById(`completedScrollSentinel-${pid}`);
        if (oldSentinel) oldSentinel.remove();

        // Append new cards
        const fragment = document.createDocumentFragment();
        const temp = document.createElement('div');
        temp.innerHTML = nextBatch.map(t => this._renderTaskCard(t)).join('');
        while (temp.firstChild) fragment.appendChild(temp.firstChild);

        // Add new sentinel if more remain
        if (this._completedLoadedCount < this._completedAllTasks.length) {
            const sentinel = document.createElement('div');
            sentinel.className = 'completed-scroll-sentinel';
            sentinel.id = `completedScrollSentinel-${pid}`;
            sentinel.innerHTML = '<div class="loading-spinner sm loading-spinner-centered"></div><p class="task-muted-note">Loading more...</p>';
            fragment.appendChild(sentinel);
        }

        el.appendChild(fragment);
        this._bindCardEvents(el);
        this._completedLoading = false;

        // Re-observe new sentinel
        if (this._completedLoadedCount < this._completedAllTasks.length) {
            this._setupCompletedInfiniteScroll(pid);
        }
    }

    // ------------------------------------------------------------------
    // Sorting
    // ------------------------------------------------------------------

    _sortTasks(tasks) {
        const dir = this._sortDirection === 'desc' ? -1 : 1;
        return [...tasks].sort((a, b) => {
            switch (this._sortField) {
                case 'priority': {
                    const order = { project: 0, serious: 1, thought: 2, generated: 3 };
                    const pa = order[this._normalizePriority(a.priority)] ?? 2;
                    const pb = order[this._normalizePriority(b.priority)] ?? 2;
                    return (pa - pb) * dir;
                }
                case 'due_date': {
                    const da = this._getDueDateMs(a.due_date) ?? Infinity;
                    const db = this._getDueDateMs(b.due_date) ?? Infinity;
                    return (da - db) * dir;
                }
                case 'created_at': {
                    const ca = new Date(a.created_at || 0).getTime();
                    const cb = new Date(b.created_at || 0).getTime();
                    return (ca - cb) * dir;
                }
                case 'position':
                default: {
                    const pa = a.position ?? 0;
                    const pb = b.position ?? 0;
                    return (pa - pb) * dir;
                }
            }
        });
    }

    _setProjectFilter(projectId) {
        this._projectFilter = projectId || '';
        this._loadTasks();
    }

    _setSortField(field) {
        this._sortField = field;
        localStorage.setItem('nexus-kanban-sortField', field);
        this._renderKanban();
    }

    _setSortDirection(dir) {
        this._sortDirection = dir;
        localStorage.setItem('nexus-kanban-sortDir', dir);
        this._renderKanban();
    }

    /**
     * Assign initial float positions to tasks that lack a position field.
     * Uses 65536 gap (same as KanbanDragDrop.POSITION_GAP).
     */
    _ensurePositions() {
        const GAP = 65536;
        const grouped = {};
        this._tasks.forEach(t => {
            const s = this._normalizeTaskStatus(t.status);
            (grouped[s] = grouped[s] || []).push(t);
        });
        for (const tasks of Object.values(grouped)) {
            let needsAssign = tasks.some(t => t.position == null || t.position === 0);
            if (needsAssign) {
                tasks.forEach((t, i) => {
                    if (t.position == null || t.position === 0) {
                        t.position = (i + 1) * GAP;
                    }
                });
            }
        }
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    _getApp() { return window.nexusApp || window.app; }
    _getExecUser() { return document.getElementById('globalUserFilter')?.value || NexusAPI.getDefaultExecUser(); }
    _getUsername() { return document.getElementById('globalUserFilter')?.value || ''; }

    _detectAwaitingOwner(task) {
        if (!task) return false;
        if (task.metadata?.awaiting_human) return true;
        const s = String(task.status || '').toLowerCase();
        if (s.includes('awaiting') || s.includes('blocked')) return true;
        if (this._normalizeTaskStatus(task.status) === 'running' && task.updated_at) {
            if (Date.now() - new Date(task.updated_at).getTime() > 30 * 60 * 1000) return true;
        }
        return false;
    }

    _resolveGitHubIssueLabel(task) {
        if (Number.isInteger(task?.github_issue_number)) return `#${task.github_issue_number}`;
        const ref = String(task?.ticket_ref || '').trim();
        const m = ref.match(/^([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d+)$/);
        return m ? `${m[1]}#${m[2]}` : '';
    }

    _resolveGitHubIssueUrl(task) {
        const direct = String(task?.github_url || '').trim();
        if (direct && this._isSafeHttpUrl(direct)) return direct;
        const ref = String(task?.ticket_ref || '').trim();
        const m = ref.match(/^([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d+)$/);
        return m ? `https://github.com/${m[1]}/issues/${m[2]}` : '';
    }

    _isSafeHttpUrl(url) {
        try {
            const parsed = new URL(url);
            return parsed.protocol === 'https:' || parsed.protocol === 'http:';
        } catch {
            return false;
        }
    }

    _formatTime(timestamp) {
        if (!timestamp) return '';
        const d = new Date(timestamp);
        const diff = Date.now() - d;
        if (diff < 60000) return 'Just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        return d.toLocaleDateString();
    }

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str || '';
        return d.innerHTML;
    }

    // ------------------------------------------------------------------
    // AppDataStore integration
    // ------------------------------------------------------------------

    _subscribeToDataStore() {
        if (!this._dataStore) return;
        const onTasksChange = (data) => {
            if (this._destroyed || this._isDragging) return;
            const tasks = (data?.tasks || []).map(t => ({
                ...t,
                status: this._normalizeTaskStatus(t.status),
            }));
            this._tasks = tasks;
            this._ensurePositions();
            this._renderKanban();
            this._syncSelectedTaskDetail();
        };
        this._dataStore.subscribe('tasks', onTasksChange);
        this._dataStoreSubscriptions.push({ key: 'tasks', cb: onTasksChange });
    }

    _unsubscribeFromDataStore() {
        if (!this._dataStore) return;
        for (const { key, cb } of this._dataStoreSubscriptions) {
            this._dataStore.unsubscribe(key, cb);
        }
        this._dataStoreSubscriptions = [];
    }

    // ------------------------------------------------------------------
    // TV-002/TV-003: ViewStore change handler & URL sync
    // ------------------------------------------------------------------

    _onViewStoreChange(state) {
        if (!state) return;
        if (state.viewMode !== this._viewMode) {
            this._viewMode = state.viewMode;
            this._setViewMode(state.viewMode);
        }
        if (state.searchQuery !== this._filter) {
            this._filter = state.searchQuery;
            this._renderKanban();
        }
        if (state.sortField !== this._sortField || state.sortDirection !== this._sortDirection) {
            this._sortField = state.sortField;
            this._sortDirection = state.sortDirection;
            this._renderKanban();
        }
        if (state.projectFilter !== this._projectFilter) {
            this._projectFilter = state.projectFilter;
            this._renderKanban();
        }
        if (state.scheduleOpen !== this._schedulePanelOpen) {
            this._applySecondarySurface(state.scheduleOpen ? 'schedules' : (this._secondarySurface === 'schedules' ? 'board' : this._secondarySurface));
        }
        if (state.detailTaskId && state.detailTaskId !== this._selectedTask) {
            this._selectTask(state.detailTaskId);
        } else if (!state.detailTaskId && this._selectedTask) {
            this._closeTaskDetail({ syncUrl: false });
        }
        if (state.detailTab && state.detailTab !== this._urlTaskTab) {
            this._urlTaskTab = state.detailTab;
            this._applyTaskTab(state.detailTab);
        }
        if (this._viewStore) this._viewStore.syncToUrl();
    }

    // ------------------------------------------------------------------
    // TV-007: Summary strip rendering
    // ------------------------------------------------------------------

    _renderSummaryStrip() {
        const pid = this._paneId;
        const container = document.getElementById(`summaryStrip-${pid}`);
        if (!container) return;
        if (typeof TaskViewModel !== 'undefined') {
            const { summary } = TaskViewModel.enrichTasks(this._tasks);
            this._summaryMetrics = {
                ...summary,
                total: this._taskTotalCount || summary.total || this._tasks.length,
                scheduled: this._scheduleSummaryCount,
            };
        } else {
            this._summaryMetrics = {
                total: this._taskTotalCount || this._tasks.length,
                pending: this._tasks.filter(t => this._normalizeTaskStatus(t.status) === 'pending').length,
                running: this._tasks.filter(t => this._normalizeTaskStatus(t.status) === 'running').length,
                in_review: this._tasks.filter(t => this._normalizeTaskStatus(t.status) === 'in_review').length,
                completed: this._tasks.filter(t => this._normalizeTaskStatus(t.status) === 'completed').length,
                failed: this._tasks.filter(t => this._normalizeTaskStatus(t.status) === 'failed').length,
                cancelled: this._tasks.filter(t => this._normalizeTaskStatus(t.status) === 'cancelled').length,
                scheduled: this._scheduleSummaryCount,
            };
        }
        const shouldShow = Object.values(this._summaryMetrics || {}).some(value => Number(value) > 0);
        container.hidden = !shouldShow;
        if (!shouldShow) {
            container.innerHTML = '';
            return;
        }
        if (typeof TaskSummaryStrip !== 'undefined') {
            if (!this._summaryStrip) {
                this._summaryStrip = new TaskSummaryStrip({ onMetricClick: (key) => this._onSummaryMetricClick(key) });
            }
            this._summaryStrip.render(container, this._summaryMetrics);
        }
    }

    _onSummaryMetricClick(key) {
        if (key === 'scheduled') {
            this._setSecondarySurface('schedules', { replace: false });
            return;
        }
        const filterMap = {
            pending: ['pending'],
            running: ['running'],
            in_review: ['in_review'],
            completed: ['completed'],
            failed: ['failed'],
            cancelled: ['cancelled'],
        };
        const statuses = filterMap[key];
        this._setSecondarySurface('board', { replace: false });
        if (statuses && this._filterBar) {
            // Set status filter via the FilterBar's internal state
            this._filterBar.filters.status.values = new Set(statuses);
            this._filterBar._renderButtons();
            this._loadTasks();
        } else if (!statuses && this._filterBar) {
            this._filterBar.resetAll();
        }
    }

    // ------------------------------------------------------------------
    // TV-011: Active filter summary
    // ------------------------------------------------------------------

    _updateActiveFilterSummary() {
        const el = document.getElementById(`activeFilterSummary-${this._paneId}`);
        if (!el) return;
        const parts = [];
        if (this._filter) parts.push(`Search: "${this._filter}"`);
        if (this._projectFilter) parts.push(`Project: ${this._projectFilter}`);
        if (this._sortField !== 'position') parts.push(`Sort: ${this._sortField}`);
        if (parts.length > 0) { el.textContent = parts.join(' · '); el.hidden = false; }
        else { el.hidden = true; }
    }
}

// Register globally
window.TaskBoardPanel = TaskBoardPanel;

if (typeof window !== 'undefined' && typeof document !== 'undefined' && !window.__nexusTaskSurfaceSettingsMigrationInstalled) {
    window.__nexusTaskSurfaceSettingsMigrationInstalled = true;
    const hideMigratedSettingsTabs = () => {
        document.querySelectorAll('.settings-tab[data-settings-tab="scheduling"]').forEach((tab) => {
            tab.hidden = true;
            tab.setAttribute('aria-hidden', 'true');
            tab.style.display = 'none';
        });
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', hideMigratedSettingsTabs, { once: true });
    } else {
        hideMigratedSettingsTabs();
    }
    const observer = new MutationObserver(() => hideMigratedSettingsTabs());
    observer.observe(document.documentElement, { childList: true, subtree: true });
}
