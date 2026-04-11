/**
 * TaskBoardPanel - Full-featured task management panel.
 *
 * Serves as the single entry point for the Tasks page, replacing the old TaskView.
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
        this._filter = '';
        this._projectFilter = '';
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
        this._paneId = 'global'; // fixed pane id for fullscreen mode
        this._sortField = localStorage.getItem('nexus-kanban-sortField') || 'position';
        this._sortDirection = localStorage.getItem('nexus-kanban-sortDir') || 'asc';

        // K-008: Done column infinite scroll state
        this._donePageSize = 20;
        this._doneLoadedCount = 20;
        this._doneAllTasks = [];
        this._doneLoading = false;
        this._doneObserver = null;

        // K-002: Drag state freeze
        this._isDragging = false;
        this._dragSnapshot = null; // frozen task list during drag
        this._pendingUpdates = []; // queued backend updates during drag

        // K-005: View mode
        this._viewMode = localStorage.getItem('nexus-kanban-viewMode') || 'board';
        this._listView = null;
        this._filterPanel = null;

        this.statusColumns = [
            { key: 'inbox', title: 'Inbox', color: 'var(--status-inbox)' },
            { key: 'assigned', title: 'Assigned', color: 'var(--status-assigned)' },
            { key: 'awaiting_owner', title: 'Awaiting Owner', color: 'var(--status-awaiting-owner)' },
            { key: 'in_progress', title: 'In Progress', color: 'var(--status-in-progress)' },
            { key: 'review', title: 'Review', color: 'var(--status-review)' },
            { key: 'quality_review', title: 'QA', color: 'var(--status-quality-review)' },
            { key: 'done', title: 'Done', color: 'var(--status-done)' },
        ];
        this.terminalColumns = [
            { key: 'failed', title: 'Failed', color: 'var(--status-failed)' },
            { key: 'cancelled', title: 'Cancelled', color: 'var(--status-cancelled)' },
        ];
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

        container.innerHTML = `
            <div class="task-container" style="height: 100%;">
                <div style="flex: 1; display: flex; flex-direction: column; overflow: hidden;">
                    <div class="task-toolbar">
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
                            <button class="action-btn" data-action="toggle-schedules" title="Show/hide scheduled tasks">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                </svg>
                                <span>Schedules</span>
                            </button>
                            <div class="selection-actions" id="selectionActions-${pid}" style="display: none;">
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
                            <div class="view-toggle-group" style="display:inline-flex;border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-right:8px;">
                                <button class="view-toggle-btn ${this._viewMode === 'board' ? 'active' : ''}" data-action="set-view" data-view="board" title="Board view" style="padding:4px 10px;font-size:12px;border:none;background:${this._viewMode === 'board' ? 'var(--primary-500)' : 'transparent'};color:${this._viewMode === 'board' ? '#fff' : 'var(--text-secondary)'};cursor:pointer;">Board</button>
                                <button class="view-toggle-btn ${this._viewMode === 'list' ? 'active' : ''}" data-action="set-view" data-view="list" title="List view" style="padding:4px 10px;font-size:12px;border:none;border-left:1px solid var(--border);background:${this._viewMode === 'list' ? 'var(--primary-500)' : 'transparent'};color:${this._viewMode === 'list' ? '#fff' : 'var(--text-secondary)'};cursor:pointer;">List</button>
                            </div>
                            <button class="action-btn" data-action="toggle-filters" title="Toggle filters" style="margin-right:8px;">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:16px;height:16px;">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"/>
                                </svg>
                                <span>Filter</span>
                            </button>
                            <select class="form-input form-select" id="sortFieldSelect-${pid}" style="width:130px;height:28px;font-size:12px;margin-right:4px;" title="Sort by">
                                <option value="position" ${this._sortField === 'position' ? 'selected' : ''}>Position</option>
                                <option value="priority" ${this._sortField === 'priority' ? 'selected' : ''}>Priority</option>
                                <option value="due_date" ${this._sortField === 'due_date' ? 'selected' : ''}>Due Date</option>
                                <option value="created_at" ${this._sortField === 'created_at' ? 'selected' : ''}>Created</option>
                            </select>
                            <button class="action-btn" data-action="toggle-sort-dir" title="Sort direction" style="padding:4px 6px;margin-right:8px;font-size:12px;">${this._sortDirection === 'asc' ? '&#9650;' : '&#9660;'}</button>
                            <select class="form-input form-select" style="width: 150px; margin-right: 8px;" id="taskProjectFilter-${pid}">
                                <option value="">All Projects</option>
                            </select>
                            <input type="text" class="form-input" placeholder="Search tasks..." style="width: 200px;" id="taskSearch-${pid}">
                        </div>
                    </div>
                    <!-- Schedules Panel (collapsible) -->
                    <div class="schedule-panel" id="schedulePanel-${pid}" style="display: none;">
                        <div class="schedule-panel-header">
                            <span class="schedule-panel-title">Scheduled Tasks</span>
                            <div class="schedule-panel-actions">
                                <select class="form-input form-select schedule-status-filter" id="scheduleStatusFilter-${pid}" style="width:120px; height:30px; font-size:12px;">
                                    <option value="">All Status</option>
                                    <option value="active">Active</option>
                                    <option value="paused">Paused</option>
                                    <option value="cancelled">Cancelled</option>
                                </select>
                                <button class="action-btn schedule-refresh-btn" data-action="refresh-schedules" title="Refresh schedules">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                        <div class="schedule-list" id="scheduleList-${pid}">
                            <div class="empty-state" style="padding: 16px;">
                                <div class="loading-spinner" style="width: 18px; height: 18px;"></div>
                            </div>
                        </div>
                    </div>
                    <div style="display:flex;flex:1;overflow:hidden;">
                        <div class="filter-sidebar" id="filterSidebar-${pid}" style="display:none;width:220px;border-right:1px solid var(--border);overflow-y:auto;flex-shrink:0;padding:8px;"></div>
                        <div style="flex:1;display:flex;flex-direction:column;overflow:hidden;">
                            <div class="kanban-board" id="kanbanBoard-${pid}" style="${this._viewMode === 'board' ? '' : 'display:none;'}">
                                <div class="kanban-primary-columns">
                                ${this.statusColumns.map(col => `
                                    <div class="kanban-column" data-status="${col.key}">
                                        <div class="kanban-column-header">
                                            <span class="kanban-column-title">
                                                <span style="width: 8px; height: 8px; border-radius: 50%; background: ${col.color};"></span>
                                                ${col.title}
                                            </span>
                                            <span class="kanban-column-count" id="count-${pid}-${col.key}">0</span>
                                        </div>
                                        <div class="kanban-column-items" id="items-${pid}-${col.key}">
                                            <div class="empty-state" style="padding: 24px 16px;">
                                                <div class="loading-spinner" style="width: 20px; height: 20px;"></div>
                                            </div>
                                        </div>
                                    </div>
                                `).join('')}
                                </div>
                                <div class="kanban-terminal-columns" id="terminalColumns-${pid}" style="display: none;"></div>
                            </div>
                            <div class="list-view-container" id="listViewContainer-${pid}" style="${this._viewMode === 'list' ? '' : 'display:none;'}flex:1;overflow-y:auto;"></div>
                            <div id="expansionPanels-${pid}" style="margin-top: 8px; border-top: 1px solid var(--border); padding-top: 8px; max-height: 260px; overflow-y: auto;">
                                <div class="empty-state" style="padding: 8px;">
                                    <div class="loading-spinner" style="width: 16px; height: 16px;"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="task-detail hidden" id="taskDetail-${pid}"></div>
            </div>
        `;

        this._bindToolbarEvents();
        this._initFilterPanel();
        this._initListView();
        this._loadTasks();
        this._startAutoPolling();
    }

    async refresh() {
        if (!this.container || this._destroyed) return;
        await this._loadTasks();
    }

    async destroy() {
        this._destroyed = true;
        this._stopAutoPolling();
        this._unsubscribeFromDataStore();
        if (this._poll) { this._poll.destroy(); this._poll = null; }
        if (this._doneObserver) {
            this._doneObserver.disconnect();
            this._doneObserver = null;
        }
        for (const [taskId] of this._activeStreams) {
            this._closeTaskStream(taskId);
        }
        this._mentionInputs.forEach(m => { try { m.destroy(); } catch {} });
        this._mentionInputs = [];
        this.container = null;
    }

    onRealtimeEvent(eventType) {
        if (eventType.startsWith('task.') && !this._isDragging) this.refresh();
    }

    // ------------------------------------------------------------------
    // Status normalization
    // ------------------------------------------------------------------

    _normalizeTaskStatus(status) {
        const s = String(status || '').trim().toLowerCase();
        if (s === 'pending' || s === 'todo') return 'inbox';
        if (s === 'in_progress' || s === 'running' || s === 'doing') return 'in_progress';
        if (s === 'completed') return 'done';
        if (['inbox','assigned','awaiting_owner','review','quality_review','done','failed','cancelled','archived'].includes(s)) return s;
        return 'inbox';
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------

    async _loadProjects() {
        const pid = this._paneId;
        const filterEl = document.getElementById(`taskProjectFilter-${pid}`);
        if (!filterEl) return;
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
            const current = filterEl.value;
            filterEl.innerHTML = '<option value="">All Projects</option>' +
                projects.map(p => {
                    const count = (p.todo || 0) + (p.doing || 0);
                    const label = p.project_name || p.project_id;
                    return `<option value="${p.project_id}">${label}${count > 0 ? ` (${count})` : ''}</option>`;
                }).join('');
            if (current && Array.from(filterEl.options).some(o => o.value === current)) {
                filterEl.value = current;
            }
        } catch (e) {
            console.error('Failed to load projects:', e);
        }
    }

    async _loadTasks() {
        const pid = this._paneId;
        const searchInput = document.getElementById(`taskSearch-${pid}`);
        const projectFilter = document.getElementById(`taskProjectFilter-${pid}`);

        try {
            if (projectFilter && projectFilter.options.length <= 1) {
                await this._loadProjects();
            }
            let data;
            const taskOpts = {
                execUser: this._getExecUser(),
                pageSize: 100,
                search: searchInput?.value || '',
                projectId: projectFilter?.value || '',
            };
            if (this._dataStore) {
                data = await this._dataStore.fetch('tasks', taskOpts);
            } else {
                data = await NexusAPI.getTasks(taskOpts);
            }
            this._tasks = (data.tasks || []).map(t => ({
                ...t,
                status: this._normalizeTaskStatus(t.status),
            }));
            this._ensurePositions();
            this._renderKanban();
            this._loadExpansionPanels();
            this._syncSelectedTaskDetail();
        } catch (e) {
            console.error('Failed to load tasks:', e);
            this.statusColumns.forEach(col => {
                const el = document.getElementById(`items-${pid}-${col.key}`);
                if (el) el.innerHTML = `<div class="empty-state" style="padding: 16px;"><p style="font-size: 12px; color: var(--error);">Failed to load</p></div>`;
            });
        }
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
                root.innerHTML = '<div style="font-size:12px;color:var(--text-muted);">Session monitor unavailable.</div>';
            }
        } catch (e) {
            root.innerHTML = '<div style="font-size:12px;color:var(--error);">Failed to load session monitor</div>';
        }
    }

    // ------------------------------------------------------------------
    // Kanban rendering
    // ------------------------------------------------------------------

    _renderKanban() {
        const pid = this._paneId;
        const tasks = this._getFilteredTasks();
        const grouped = {};
        this.statusColumns.forEach(col => { grouped[col.key] = []; });
        tasks.forEach(t => {
            const s = (t.status || 'inbox').toLowerCase();
            (grouped[s] || grouped['inbox']).push(t);
        });

        this.statusColumns.forEach(col => {
            const allItems = this._sortTasks(grouped[col.key] || []);
            const el = document.getElementById(`items-${pid}-${col.key}`);
            const countEl = document.getElementById(`count-${pid}-${col.key}`);
            if (countEl) countEl.textContent = allItems.length;

            // K-008: Done column infinite scroll — only render first N items
            let items = allItems;
            if (col.key === 'done') {
                this._doneAllTasks = allItems;
                items = allItems.slice(0, this._doneLoadedCount);
            }

            if (el) {
                if (allItems.length === 0) {
                    el.innerHTML = '<div class="empty-state" style="padding: 24px 16px;"><p style="font-size: 12px; color: var(--text-muted);">No tasks</p></div>';
                } else {
                    let html = items.map(t => this._renderTaskCard(t)).join('');
                    // Add sentinel for infinite scroll on Done column
                    if (col.key === 'done' && items.length < allItems.length) {
                        html += '<div class="done-scroll-sentinel" id="doneScrollSentinel-' + pid + '" style="padding:12px;text-align:center;"><div class="loading-spinner" style="width:16px;height:16px;margin:0 auto;"></div><p style="font-size:11px;color:var(--text-muted);margin-top:4px;">Loading more...</p></div>';
                    }
                    el.innerHTML = html;
                    this._bindCardEvents(el);
                    // Set up Intersection Observer for Done column
                    if (col.key === 'done') this._setupDoneInfiniteScroll(pid);
                }
            }
        });

        // Terminal columns
        const terminalContainer = document.getElementById(`terminalColumns-${pid}`);
        if (terminalContainer) {
            const terminalTasks = [];
            this.terminalColumns.forEach(col => {
                const items = tasks.filter(t => this._normalizeTaskStatus(t.status) === col.key);
                if (items.length > 0) terminalTasks.push({ col, items });
            });
            if (terminalTasks.length > 0) {
                terminalContainer.style.display = 'flex';
                terminalContainer.innerHTML = terminalTasks.map(({ col, items }) => `
                    <div class="kanban-column kanban-column-terminal" data-status="${col.key}">
                        <div class="kanban-column-header">
                            <span class="kanban-column-title">
                                <span style="width: 8px; height: 8px; border-radius: 50%; background: ${col.color};"></span>
                                ${col.title}
                            </span>
                            <span class="kanban-column-count">${items.length}</span>
                        </div>
                        <div class="kanban-column-items">
                            ${items.map(t => this._renderTaskCard(t)).join('')}
                        </div>
                    </div>
                `).join('');
                this._bindCardEvents(terminalContainer);
            } else {
                terminalContainer.style.display = 'none';
            }
        }

        this._bindKanbanDragDrop();

        // Update filter panel counts
        if (this._filterPanel) {
            this._filterPanel.updateCounts(this._tasks);
        }

        // Update list view if active
        if (this._viewMode === 'list' && this._listView) {
            this._listView.updateTasks(this._getFilteredTasks());
        }
    }

    _renderTaskCard(task) {
        const priorityClass = task.priority === 'critical' ? 'critical' : task.priority === 'serious' ? 'serious' : 'normal';
        const timeStr = this._formatTime(task.updated_at || task.created_at);
        const isSelected = this._selectedTask === task.id;
        const isChecked = this._selectedTaskIds.has(task.id);
        const alias = String(task?.alias || '').trim();
        const provider = String(task?.provider || '').trim();
        const targetPrimary = alias || provider;
        const targetSecondary = alias && provider && alias.toLowerCase() !== provider.toLowerCase() ? provider : '';
        const targetTooltip = targetSecondary ? `Alias: ${alias} · Provider: ${provider}` : (alias || provider);
        const priorityColors = { critical: 'var(--error)', serious: 'var(--warning)', normal: 'var(--primary-500)' };
        const agentName = task.assigned_to || alias || provider || '';
        const agentAvatar = agentName && typeof AgentAvatar !== 'undefined' ? AgentAvatar.render(agentName, { size: 'xs', status: this._normalizeTaskStatus(task.status) === 'in_progress' ? 'online' : 'none' }) : '';
        const tags = Array.isArray(task.tags) ? task.tags : [];
        const visibleTags = tags.slice(0, 3);
        const extraTagCount = tags.length > 3 ? tags.length - 3 : 0;
        const tagsHtml = tags.length > 0 ? `<div class="task-card-tags">${visibleTags.map(t => `<span class="task-card-tag">${this._esc(t)}</span>`).join('')}${extraTagCount > 0 ? `<span class="task-card-tag task-card-tag-more">+${extraTagCount}</span>` : ''}</div>` : '';
        const isOverdue = task.due_date && (task.due_date * 1000 < Date.now()) && this._normalizeTaskStatus(task.status) !== 'done';
        const overdueHtml = isOverdue ? '<span class="task-card-overdue">! Overdue</span>' : '';
        const isAwaitingOwner = this._detectAwaitingOwner(task);
        const awaitingBadge = isAwaitingOwner && this._normalizeTaskStatus(task.status) !== 'awaiting_owner' ? '<span class="task-card-awaiting-badge">Needs Attention</span>' : '';
        const ghLabel = this._resolveGitHubIssueLabel(task);
        const ghUrl = this._resolveGitHubIssueUrl(task);
        const ghState = String(task.github_state || '').trim().toLowerCase();
        const ghColor = ghState === 'closed' ? 'var(--success)' : 'var(--primary-500)';
        const ghBadge = ghLabel ? (ghUrl ? `<a href="${this._esc(ghUrl)}" target="_blank" rel="noopener noreferrer" style="font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid ${ghColor};color:${ghColor};text-decoration:none;">GH ${this._esc(ghLabel)}${ghState ? ` · ${this._esc(ghState)}` : ''}</a>` : `<span style="font-size:10px;padding:1px 6px;border-radius:4px;border:1px solid ${ghColor};color:${ghColor};">GH ${this._esc(ghLabel)}${ghState ? ` · ${this._esc(ghState)}` : ''}</span>`) : '';
        const aegisBadge = task.aegis_approved ? '<span style="font-size:10px;padding:1px 6px;border-radius:4px;background:rgba(16,185,129,0.16);color:var(--success);font-weight:600;">Aegis ✓</span>' : '';

        return `
            <div class="task-card ${isSelected ? 'selected' : ''} ${isChecked ? 'checked' : ''} ${isOverdue ? 'task-card-overdue-state' : ''} ${isAwaitingOwner ? 'task-card-needs-attention' : ''}" data-task-id="${task.id}" draggable="${!this._selectionMode}" style="border-left: 3px solid ${priorityColors[priorityClass] || 'transparent'};">
                ${this._selectionMode ? `<div class="task-card-checkbox" data-task-id="${task.id}"><input type="checkbox" ${isChecked ? 'checked' : ''}></div>` : ''}
                <div class="task-card-content">
                    <div class="task-card-header">
                        <span class="task-card-id">#${task.id.slice(0, 8)}</span>
                        ${task.ticket_ref ? `<span class="task-card-ticket-ref" title="Project ticket">${this._esc(task.ticket_ref)}</span>` : ''}
                        ${ghBadge}${aegisBadge}
                        ${task.priority ? `<span class="task-card-priority ${priorityClass}" data-inline-edit="priority" data-current-value="${this._esc(task.priority || 'normal')}" style="cursor:pointer;" title="Click to change priority">${task.priority}</span>` : ''}
                        ${task.loop_enabled ? `<span style="font-size:10px;padding:1px 6px;border-radius:4px;background:${task.loop_keyword_found ? 'var(--success,#22c55e)' : 'var(--accent,#6366f1)'};color:#fff;font-weight:600;">Loop ${task.loop_iteration||0}/${task.loop_max_iterations||1}${task.loop_keyword_found ? ' ✓' : ''}</span>` : ''}
                        ${overdueHtml}${awaitingBadge}
                    </div>
                    <p class="task-card-title">${this._esc(task.description || 'No description')}</p>
                    ${tagsHtml}
                    <div class="task-card-meta">
                        ${agentAvatar ? `<span class="task-card-meta-item" data-inline-edit="assignee" data-current-value="${this._esc(agentName)}" style="cursor:pointer;" title="Click to change assignee">${agentAvatar}</span>` : ''}
                        <span class="task-card-meta-item">
                            <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            ${timeStr}
                        </span>
                        ${targetPrimary ? `<span class="task-card-meta-item" title="${this._esc(targetTooltip)}"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg><span>${this._esc(targetPrimary)}</span>${targetSecondary ? `<span class="task-provider-base">${this._esc(targetSecondary)}</span>` : ''}</span>` : ''}
                    </div>
                    ${task.depends_on?.length ? `<div class="task-card-deps"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:12px;height:12px;color:var(--text-muted);"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>${task.depends_on.map(d => `<span class="task-card-dep">${d.slice(0, 8)}</span>`).join('')}</div>` : ''}
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
                onSelect: async (taskId, field, value) => {
                    try {
                        const update = {};
                        if (field === 'status') {
                            await NexusAPI.updateTaskStatus(taskId, value, { execUser: this._getExecUser() });
                        } else {
                            if (field === 'priority') update.priority = value;
                            if (field === 'assignee') update.assigned_to = value;
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

    async _selectTask(taskId) {
        this._selectedTask = taskId;
        const board = document.getElementById(`kanbanBoard-${this._paneId}`);
        board?.querySelectorAll('.task-card').forEach(c => c.classList.toggle('selected', c.dataset.taskId === taskId));
        await this._showTaskDetail(taskId);
    }

    async _showTaskDetail(taskId) {
        const pid = this._paneId;
        const detailPanel = document.getElementById(`taskDetail-${pid}`);
        if (!detailPanel) return;
        detailPanel.classList.remove('hidden');
        detailPanel.innerHTML = '<div class="empty-state"><div class="loading-spinner"></div></div>';
        try {
            const task = await NexusAPI.getTask(taskId, { execUser: this._getExecUser() });
            this._renderTaskDetail(task);
        } catch (e) {
            detailPanel.innerHTML = '<div class="empty-state"><p style="color: var(--error);">Failed to load task details</p></div>';
        }
    }

    _renderTaskDetail(task) {
        const pid = this._paneId;
        const detailPanel = document.getElementById(`taskDetail-${pid}`);
        if (!detailPanel) return;
        this._closeTaskStream(this._selectedTask);
        const statusClass = this._normalizeTaskStatus(task.status);
        const isRunning = statusClass === 'in_progress';
        const hasConversation = isRunning || statusClass === 'done' || statusClass === 'completed' || statusClass === 'failed';
        const alias = String(task?.alias || '').trim();
        const provider = String(task?.provider || '').trim();
        const targetPrimary = alias || provider;
        const targetSecondary = alias && provider && alias.toLowerCase() !== provider.toLowerCase() ? provider : '';
        const targetTooltip = targetSecondary ? `Alias: ${alias} · Provider: ${provider}` : (alias || provider);

        detailPanel.dataset.taskId = task.id;
        detailPanel.dataset.taskStatus = statusClass;

        detailPanel.innerHTML = `
            <div class="task-detail-header">
                <span class="task-detail-title">#${task.id.slice(0, 8)}</span>
                <button class="task-detail-close" data-action="close-detail">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                </button>
            </div>
            <div class="task-detail-content" style="display:flex;flex-direction:column;overflow:hidden;flex:1;">
                <div class="task-detail-section" style="flex-shrink:0;">
                    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                        <span class="status-badge ${statusClass}"><span class="status-dot"></span>${task.status || 'TODO'}</span>
                        ${targetPrimary ? `<span class="task-target-badge" title="${this._esc(targetTooltip)}">${this._esc(targetPrimary)}</span>` : ''}
                        ${targetSecondary ? `<span class="task-target-badge task-target-badge-base" title="Base provider">${this._esc(targetSecondary)}</span>` : ''}
                        ${task.workspace ? `<span style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono);" title="${this._esc(task.workspace)}">${this._esc(task.workspace.split('/').pop() || task.workspace)}</span>` : ''}
                    </div>
                    <p style="margin:6px 0 0;font-size:13px;color:var(--text-secondary);">${this._esc(task.description || 'No description')}</p>
                    ${task.error_message ? `<p style="margin:4px 0 0;font-size:12px;color:var(--error);">${this._esc(task.error_message)}</p>` : ''}
                    ${this._resolveGitHubIssueLabel(task) ? `<p style="margin:6px 0 0;font-size:12px;color:var(--text-secondary);">GitHub: ${this._resolveGitHubIssueUrl(task) ? `<a href="${this._esc(this._resolveGitHubIssueUrl(task))}" target="_blank" rel="noopener noreferrer" style="color:var(--primary-500);">${this._esc(this._resolveGitHubIssueLabel(task))}</a>` : this._esc(this._resolveGitHubIssueLabel(task))}${task.github_state ? `<span style="margin-left:6px;color:var(--text-muted);">(${this._esc(String(task.github_state))})</span>` : ''}</p>` : ''}
                    ${(task.aegis_status || task.aegis_approved) ? `<p style="margin:4px 0 0;font-size:12px;color:${task.aegis_approved ? 'var(--success)' : 'var(--warning)'};">Aegis: ${task.aegis_approved ? 'Approved' : this._esc(String(task.aegis_status || 'pending'))}${task.aegis_reason ? `<span style="color:var(--text-muted);"> · ${this._esc(task.aegis_reason)}</span>` : ''}</p>` : ''}
                    ${task.loop_enabled ? `<div style="margin-top:8px;padding:8px 10px;background:var(--bg-secondary);border-radius:6px;font-size:12px;"><div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;"><span style="font-weight:600;color:var(--text-primary);">Ralph Loop</span><span style="padding:1px 6px;border-radius:4px;background:${task.loop_keyword_found ? 'var(--success,#22c55e)' : 'var(--accent,#6366f1)'};color:#fff;font-weight:600;font-size:10px;">${task.loop_iteration||0}/${task.loop_max_iterations||1}${task.loop_keyword_found ? ' ✓ Found' : ''}</span></div><div style="color:var(--text-secondary);"><span>Keywords: </span>${(task.loop_keywords || []).map(kw => `<code style="background:var(--bg-tertiary,#374151);padding:1px 4px;border-radius:3px;font-size:11px;">${this._esc(kw)}</code>`).join(' ')}</div></div>` : ''}
                </div>
                <div class="task-conversation" style="flex:1;overflow:hidden;border-top:1px solid var(--border);margin-top:8px;padding-top:8px;display:flex;flex-direction:column;gap:8px;">
                    <div style="display:flex;gap:6px;flex-wrap:wrap;">
                        <button class="action-btn task-detail-tab active" data-task-tab="details" style="padding:4px 10px;">Details</button>
                        <button class="action-btn task-detail-tab" data-task-tab="comments" style="padding:4px 10px;">Comments</button>
                        <button class="action-btn task-detail-tab" data-task-tab="quality" style="padding:4px 10px;">Quality</button>
                        <button class="action-btn task-detail-tab" data-task-tab="timeline" style="padding:4px 10px;">Timeline</button>
                        <button class="action-btn task-detail-tab" data-task-tab="session" style="padding:4px 10px;">Session</button>
                    </div>
                    <div id="taskTabDetails-${pid}" data-task-tab-pane="details" style="flex:1;overflow-y:auto;">
                        <div id="taskDetailsPanel-${pid}" style="padding:8px 4px;font-size:12px;color:var(--text-secondary);"></div>
                    </div>
                    <div id="taskTabComments-${pid}" data-task-tab-pane="comments" style="display:none;overflow-y:auto;">
                        <div id="taskComments-${pid}" style="padding:8px 4px;font-size:12px;color:var(--text-secondary);"><div class="loading-spinner" style="width:18px;height:18px;"></div></div>
                    </div>
                    <div id="taskTabQuality-${pid}" data-task-tab-pane="quality" style="display:none;overflow-y:auto;">
                        <div id="taskQuality-${pid}" style="padding:8px 4px;font-size:12px;color:var(--text-secondary);"><div class="loading-spinner" style="width:18px;height:18px;"></div></div>
                    </div>
                    <div id="taskTabTimeline-${pid}" data-task-tab-pane="timeline" style="display:none;overflow-y:auto;">
                        <div id="taskTimeline-${pid}" style="padding:8px 4px;font-size:12px;color:var(--text-secondary);"><div class="loading-spinner" style="width:18px;height:18px;"></div></div>
                    </div>
                    <div id="taskTabSession-${pid}" data-task-tab-pane="session" style="display:none;flex:1;overflow-y:auto;">
                        ${hasConversation ? `<div class="chat-messages" id="taskConversation-${pid}" style="padding:0;"><div class="empty-state" style="padding:24px;"><div class="loading-spinner"></div><p style="font-size:12px;color:var(--text-muted);margin-top:8px;">${isRunning ? 'Connecting to live stream...' : 'Loading conversation...'}</p></div></div>` : `<div class="empty-state" style="padding:24px;"><p style="font-size:12px;color:var(--text-muted);">Session view is available after task execution starts.</p></div>`}
                    </div>
                </div>
                <div class="task-detail-section" style="flex-shrink:0;margin-top:8px;padding-top:8px;border-top:1px solid var(--border);">
                    <div style="display:flex;gap:8px;flex-wrap:wrap;">
                        ${hasConversation ? `<button class="action-btn" data-action="view-session" data-task-id="${task.id}" title="Open in Chat view"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>Open Session</button>` : ''}
                        <button class="action-btn" data-action="broadcast-task" data-task-id="${task.id}" title="Broadcast"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405C18.21 15.21 18 14.702 18 14.172V11a6.002 6.002 0 00-4-5.659V4a2 2 0 10-4 0v1.341C7.67 6.165 6 8.388 6 11v3.172c0 .53-.21 1.039-.595 1.423L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>Broadcast</button>
                        <button class="action-btn" data-action="delete-task" data-task-id="${task.id}" style="color:var(--error);"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>Delete</button>
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
        if (hasConversation) {
            if (isRunning) this._streamTaskConversation(task.id);
            else this._streamTaskConversation(task.id, true);
        }
    }

    _bindDetailEvents(panel, task) {
        const pid = this._paneId;
        panel.querySelector('[data-action="close-detail"]')?.addEventListener('click', () => {
            this._closeTaskStream(task.id);
            panel.classList.add('hidden');
            this._selectedTask = null;
            document.getElementById(`kanbanBoard-${pid}`)?.querySelectorAll('.task-card').forEach(c => c.classList.remove('selected'));
        });
        panel.querySelector('[data-action="delete-task"]')?.addEventListener('click', () => {
            this._getApp()?.showDeleteModal?.('task', task.id, () => this._deleteTask(task.id));
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
                buttons.forEach(b => b.classList.toggle('active', b === btn));
                Object.entries(panes).forEach(([key, pane]) => { if (pane) pane.style.display = key === target ? '' : 'none'; });
            });
        });
    }

    _loadDetailsTab(task) {
        const pid = this._paneId;
        const root = document.getElementById(`taskDetailsPanel-${pid}`);
        if (!root) return;
        const app = this._getApp();
        const descHtml = app?.chatView?.formatMessageContent ? app.chatView.formatMessageContent(task.description || '') : this._esc(task.description || '');
        root.innerHTML = `
            <div style="display:grid;grid-template-columns:120px 1fr;gap:6px 10px;font-size:12px;">
                <span style="color:var(--text-muted);">Task ID</span><span>${this._esc(task.id||'')}</span>
                <span style="color:var(--text-muted);">Status</span><span>${this._esc(task.status||'')}</span>
                <span style="color:var(--text-muted);">Priority</span><span>${this._esc(task.priority||'')}</span>
                <span style="color:var(--text-muted);">Assignee</span><span>${this._esc(task.assigned_to||'-')}</span>
                <span style="color:var(--text-muted);">Source Session</span><span>${this._esc(task.source_session_id||'-')}</span>
                <span style="color:var(--text-muted);">Created</span><span>${this._esc(task.created_at ? new Date(task.created_at).toLocaleString() : '-')}</span>
                <span style="color:var(--text-muted);">Updated</span><span>${this._esc(task.updated_at ? new Date(task.updated_at).toLocaleString() : '-')}</span>
                <span style="color:var(--text-muted);">Depends On</span><span>${Array.isArray(task.depends_on) && task.depends_on.length ? this._esc(task.depends_on.join(', ')) : '-'}</span>
            </div>
            <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);">
                <div style="font-size:11px;color:var(--text-muted);margin-bottom:6px;">Description (Markdown)</div>
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
                    const textId = `task-stream-text-${taskId}-seg${textSegmentIndex}`;
                    bubble.insertAdjacentHTML('beforeend', `<div class="message-text streaming" id="${textId}"></div>`);
                    currentTextEl = document.getElementById(textId);
                }
            }
            return currentTextEl;
        };

        es.onmessage = (event) => {
            if (runFinished) return;
            let data;
            try { data = JSON.parse(event.data); } catch { return; }

            if (data.type === 'TEXT_MESSAGE_START') {
                ensureBubble();
            } else if (data.type === 'TEXT_MESSAGE_CONTENT') {
                const delta = data.delta ?? data.content ?? data.text ?? data.response;
                if (delta != null && delta !== '') {
                    const textEl = ensureTextElement();
                    currentTextContent += (typeof delta === 'string' ? delta : JSON.stringify(delta, null, 2));
                    if (textEl && chatView) { textEl.innerHTML = chatView.formatMessageContent(currentTextContent); container.scrollTop = container.scrollHeight; }
                }
            } else if (data.type === 'result') {
                const resultText = data.content ?? data.result;
                if (resultText != null && resultText !== '') {
                    const textEl = ensureTextElement();
                    currentTextContent += (typeof resultText === 'string' ? resultText : JSON.stringify(resultText, null, 2));
                    if (textEl && chatView) { textEl.innerHTML = chatView.formatMessageContent(currentTextContent); container.scrollTop = container.scrollHeight; }
                }
            } else if (data.type === 'TEXT_MESSAGE_END') {
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                currentTextEl = null; currentTextContent = ''; textSegmentIndex++;
            } else if (data.type === 'TOOL_CALL_START') {
                const toolCallId = data.toolCallId || `tool-${Date.now()}`;
                const toolName = data.toolCallName || 'Tool';
                const toolTitle = chatView?.formatToolCallTitle?.(toolName, {}, '') || toolName;
                streamingToolCalls.set(toolCallId, { name: toolName, args: '', status: 'executing', result: '' });
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                currentTextEl = null; currentTextContent = ''; textSegmentIndex++;
                const bubble = ensureBubble();
                if (bubble && chatView) { bubble.insertAdjacentHTML('beforeend', chatView.renderStreamingToolCall(toolCallId, toolTitle, 'executing')); container.scrollTop = container.scrollHeight; }
            } else if (data.type === 'TOOL_CALL_ARGS') {
                const tc = streamingToolCalls.get(data.toolCallId);
                if (tc) {
                    tc.args += (data.delta || '');
                    const argsEl = document.getElementById(`streaming-tool-args-${data.toolCallId}`);
                    if (argsEl) argsEl.textContent = tc.args;
                    const titleEl = document.querySelector(`[data-streaming-tool-id="${data.toolCallId}"] .tool-call-name`);
                    if (titleEl && chatView) titleEl.textContent = chatView.formatToolCallTitle(tc.name, {}, tc.args);
                }
            } else if (data.type === 'TOOL_CALL_END') {
                const tc = streamingToolCalls.get(data.toolCallId);
                if (tc) {
                    tc.status = data.error ? 'failed' : 'completed';
                    tc.result = data.result || '';
                    const statusEl = document.querySelector(`[data-streaming-tool-id="${data.toolCallId}"] .tool-call-status-icon`);
                    if (statusEl) { statusEl.textContent = data.error ? '✗' : '✓'; statusEl.parentElement.style.color = data.error ? 'var(--error)' : 'var(--success)'; }
                    const resultSection = document.getElementById(`streaming-tool-result-section-${data.toolCallId}`);
                    const resultEl = document.getElementById(`streaming-tool-result-${data.toolCallId}`);
                    if (resultSection && resultEl && tc.result) { resultSection.style.display = 'block'; resultEl.textContent = typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2); }
                    container.scrollTop = container.scrollHeight;
                }
            } else if (data.type === 'TOOL_CALL_RESULT') {
                const tc = streamingToolCalls.get(data.toolCallId);
                if (tc) {
                    tc.result = data.result || data.content || '';
                    const s = document.getElementById(`streaming-tool-result-section-${data.toolCallId}`);
                    const el = document.getElementById(`streaming-tool-result-${data.toolCallId}`);
                    if (s && el && tc.result) { s.style.display = 'block'; el.textContent = typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2); }
                }
            } else if (data.type === 'RUN_FINISHED' || data.type === 'RUN_ERROR') {
                runFinished = true;
                if (currentTextEl) currentTextEl.classList.remove('streaming');
                const isError = data.type === 'RUN_ERROR';
                container.insertAdjacentHTML('beforeend', `<div style="padding:8px 12px;margin-top:8px;background:rgba(${isError ? '239,68,68' : '16,185,129'},0.1);border-radius:6px;font-size:12px;color:var(--${isError ? 'error' : 'success'});">${isError ? `Task failed${data.message ? ': ' + this._esc(data.message) : ''}` : '✓ Task completed'}</div>`);
                container.scrollTop = container.scrollHeight;
                this._closeTaskStream(taskId);
                if (!isReplay) { if (this._dataStore) this._dataStore.invalidate('tasks'); this._loadTasks(); app?.chatView?.loadSessions?.(0); }
            }
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

        c.querySelector('[data-action="create-task"]')?.addEventListener('click', () => this._getApp()?.showCreateTaskModal?.('single'));
        c.querySelector('[data-action="toggle-selection"]')?.addEventListener('click', () => this._toggleSelectionMode());
        c.querySelector('[data-action="select-all"]')?.addEventListener('click', () => this._selectAllTasks());
        c.querySelector('[data-action="deselect-all"]')?.addEventListener('click', () => this._deselectAllTasks());
        c.querySelector('[data-action="delete-selected"]')?.addEventListener('click', () => this._deleteSelectedTasks());
        c.querySelector('[data-action="toggle-schedules"]')?.addEventListener('click', () => this._toggleSchedulePanel());
        c.querySelector('[data-action="refresh-schedules"]')?.addEventListener('click', () => this._loadSchedules());

        // K-005: View toggle
        c.querySelectorAll('[data-action="set-view"]').forEach(btn => {
            btn.addEventListener('click', () => this._setViewMode(btn.dataset.view));
        });

        // K-003: Filter toggle
        c.querySelector('[data-action="toggle-filters"]')?.addEventListener('click', () => this._toggleFilterPanel());

        // K-006: Sort controls
        document.getElementById(`sortFieldSelect-${pid}`)?.addEventListener('change', (e) => {
            this._sortField = e.target.value;
            localStorage.setItem('nexus-kanban-sortField', this._sortField);
            this._renderKanban();
        });
        c.querySelector('[data-action="toggle-sort-dir"]')?.addEventListener('click', () => {
            this._sortDirection = this._sortDirection === 'asc' ? 'desc' : 'asc';
            localStorage.setItem('nexus-kanban-sortDir', this._sortDirection);
            const btn = c.querySelector('[data-action="toggle-sort-dir"]');
            if (btn) btn.innerHTML = this._sortDirection === 'asc' ? '&#9650;' : '&#9660;';
            this._renderKanban();
        });

        const searchInput = document.getElementById(`taskSearch-${pid}`);
        if (searchInput) {
            let t;
            searchInput.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => this._loadTasks(), 300); });
        }
        document.getElementById(`taskProjectFilter-${pid}`)?.addEventListener('change', () => this._loadTasks());
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
        if (el) el.style.display = this._selectionMode ? 'flex' : 'none';
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
            this._selectedTask = null;
            document.getElementById(`taskDetail-${this._paneId}`)?.classList.add('hidden');
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
                    await NexusAPI.updateTaskStatus(taskId, toStatus, { execUser: this._getExecUser() });
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
        const board = document.getElementById(`kanbanBoard-${pid}`);
        const listContainer = document.getElementById(`listViewContainer-${pid}`);
        if (board) board.style.display = mode === 'board' ? '' : 'none';
        if (listContainer) listContainer.style.display = mode === 'list' ? '' : 'none';

        // Update toggle button styles
        this.container?.querySelectorAll('[data-action="set-view"]').forEach(btn => {
            const active = btn.dataset.view === mode;
            btn.style.background = active ? 'var(--primary-500)' : 'transparent';
            btn.style.color = active ? '#fff' : 'var(--text-secondary)';
        });

        if (mode === 'list' && this._listView) {
            this._listView.updateTasks(this._getFilteredTasks());
        }
    }

    _toggleFilterPanel() {
        const pid = this._paneId;
        const sidebar = document.getElementById(`filterSidebar-${pid}`);
        if (!sidebar) return;
        const isVisible = sidebar.style.display !== 'none';
        sidebar.style.display = isVisible ? 'none' : '';
    }

    _initFilterPanel() {
        const pid = this._paneId;
        const sidebar = document.getElementById(`filterSidebar-${pid}`);
        if (!sidebar || typeof FilterPanel === 'undefined') return;
        this._filterPanel = new FilterPanel({
            container: sidebar,
            getStatusColumns: () => this.statusColumns,
            onFilterChange: () => {
                this._renderKanban();
                if (this._viewMode === 'list' && this._listView) {
                    this._listView.updateTasks(this._getFilteredTasks());
                }
            },
        });
        this._filterPanel.render();
    }

    _initListView() {
        const pid = this._paneId;
        const container = document.getElementById(`listViewContainer-${pid}`);
        if (!container || typeof ListView === 'undefined') return;
        this._listView = new ListView({
            container,
            tasks: [],
            statusColumns: this.statusColumns,
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
        if (this._filterPanel && this._filterPanel.hasActiveFilters) {
            return this._filterPanel.apply(this._tasks);
        }
        return this._tasks;
    }

    // ------------------------------------------------------------------
    // Schedules
    // ------------------------------------------------------------------

    _toggleSchedulePanel() {
        const pid = this._paneId;
        const panel = document.getElementById(`schedulePanel-${pid}`);
        if (!panel) return;
        this._schedulePanelOpen = !this._schedulePanelOpen;
        panel.style.display = this._schedulePanelOpen ? 'block' : 'none';
        if (this._schedulePanelOpen) this._loadSchedules();
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
            if (schedules.length === 0) {
                listEl.innerHTML = '<div class="empty-state" style="padding:16px;"><p style="color:var(--text-muted);font-size:13px;">No schedules found</p></div>';
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
            });
        } catch (e) {
            listEl.innerHTML = '<div class="empty-state" style="padding:16px;"><p style="color:var(--error);font-size:13px;">Failed to load schedules</p></div>';
        }
    }

    _renderScheduleCard(schedule) {
        const statusColors = { active: 'var(--status-doing)', paused: 'var(--status-todo)', cancelled: 'var(--status-cancelled)' };
        const statusColor = statusColors[schedule.status] || 'var(--text-muted)';
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
                        <span class="schedule-status-dot" style="background:${statusColor};"></span>
                        <span class="schedule-card-name">${this._esc(schedule.name)}</span>
                        ${kindBadge}${triggerBadge}
                    </div>
                    <div class="schedule-card-actions">
                        ${isActive ? `<button class="schedule-action-btn" data-action="trigger-schedule" title="Trigger now"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button><button class="schedule-action-btn" data-action="pause-schedule" title="Pause"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button>` : ''}
                        ${isPaused ? `<button class="schedule-action-btn" data-action="resume-schedule" title="Resume"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button>` : ''}
                        ${!isCancelled ? `<button class="schedule-action-btn" data-action="cancel-schedule" title="Cancel"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg></button>` : ''}
                        <button class="schedule-action-btn" data-action="edit-schedule" title="Edit" style="${isSystem ? 'display:none' : ''}"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
                        <button class="schedule-action-btn danger" data-action="delete-schedule" title="Delete" style="${isSystem ? 'display:none' : ''}"><svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:14px;height:14px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>
                    </div>
                </div>
                <div class="schedule-card-meta">
                    <span title="Provider">${this._esc(schedule.alias || schedule.provider || '-')}</span>
                    <span title="Runs">${maxRunsText} runs</span>
                    <span title="Next run">Next: ${nextRun}</span>
                    <span title="Last run">Last: ${lastRun}</span>
                </div>
                <div class="schedule-card-desc">${this._esc(schedule.description || '').substring(0, 120)}${(schedule.description || '').length > 120 ? '...' : ''}</div>
            </div>
        `;
    }

    async _triggerSchedule(id) { try { await NexusAPI.triggerSchedule(id); this._getApp()?.showToast?.('Schedule triggered', 'success'); this._loadSchedules(); } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); } }
    async _pauseSchedule(id) { try { await NexusAPI.pauseSchedule(id); this._getApp()?.showToast?.('Schedule paused', 'success'); this._loadSchedules(); } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); } }
    async _resumeSchedule(id) { try { await NexusAPI.resumeSchedule(id); this._getApp()?.showToast?.('Schedule resumed', 'success'); this._loadSchedules(); } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); } }
    async _cancelSchedule(id) { if (!confirm('Cancel this schedule permanently?')) return; try { await NexusAPI.cancelSchedule(id); this._getApp()?.showToast?.('Schedule cancelled', 'success'); this._loadSchedules(); } catch (e) { this._getApp()?.showToast?.(e.message, 'error'); } }
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
            const hasRunning = this._tasks.some(t => this._normalizeTaskStatus(t.status) === 'in_progress');
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
            this._closeTaskStream(this._selectedTask);
            this._selectedTask = null;
            if (detailPanel) detailPanel.classList.add('hidden');
        } else if (detailPanel) {
            const latestStatus = this._normalizeTaskStatus(latest.status);
            const renderedStatus = detailPanel.dataset.taskStatus || '';
            const renderedId = detailPanel.dataset.taskId || '';
            const hasConvDom = !!detailPanel.querySelector(`#taskConversation-${pid}`);
            const shouldHaveConv = ['in_progress', 'done', 'completed', 'failed'].includes(latestStatus);
            const isStreaming = this._activeStreams.has(this._selectedTask);
            if ((renderedId !== this._selectedTask || renderedStatus !== latestStatus || (shouldHaveConv && !hasConvDom)) && !isStreaming) {
                this._renderTaskDetail(latest);
            }
        }
    }

    // ------------------------------------------------------------------
    // Done column infinite scroll (K-008)
    // ------------------------------------------------------------------

    _setupDoneInfiniteScroll(pid) {
        // Disconnect previous observer
        if (this._doneObserver) {
            this._doneObserver.disconnect();
            this._doneObserver = null;
        }
        const sentinel = document.getElementById(`doneScrollSentinel-${pid}`);
        if (!sentinel) return;

        this._doneObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting && !this._doneLoading) {
                    this._loadMoreDoneTasks(pid);
                }
            });
        }, { root: sentinel.closest('.kanban-column-items'), threshold: 0.1 });

        this._doneObserver.observe(sentinel);
    }

    _loadMoreDoneTasks(pid) {
        if (this._doneLoading) return;
        if (this._doneLoadedCount >= this._doneAllTasks.length) return;

        this._doneLoading = true;
        const nextBatch = this._doneAllTasks.slice(
            this._doneLoadedCount,
            this._doneLoadedCount + this._donePageSize
        );
        this._doneLoadedCount += nextBatch.length;

        const el = document.getElementById(`items-${pid}-done`);
        if (!el) { this._doneLoading = false; return; }

        // Remove old sentinel
        const oldSentinel = document.getElementById(`doneScrollSentinel-${pid}`);
        if (oldSentinel) oldSentinel.remove();

        // Append new cards
        const fragment = document.createDocumentFragment();
        const temp = document.createElement('div');
        temp.innerHTML = nextBatch.map(t => this._renderTaskCard(t)).join('');
        while (temp.firstChild) fragment.appendChild(temp.firstChild);

        // Add new sentinel if more remain
        if (this._doneLoadedCount < this._doneAllTasks.length) {
            const sentinel = document.createElement('div');
            sentinel.className = 'done-scroll-sentinel';
            sentinel.id = `doneScrollSentinel-${pid}`;
            sentinel.style.cssText = 'padding:12px;text-align:center;';
            sentinel.innerHTML = '<div class="loading-spinner" style="width:16px;height:16px;margin:0 auto;"></div><p style="font-size:11px;color:var(--text-muted);margin-top:4px;">Loading more...</p>';
            fragment.appendChild(sentinel);
        }

        el.appendChild(fragment);
        this._bindCardEvents(el);
        this._doneLoading = false;

        // Re-observe new sentinel
        if (this._doneLoadedCount < this._doneAllTasks.length) {
            this._setupDoneInfiniteScroll(pid);
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
                    const order = { critical: 0, serious: 1, normal: 2 };
                    const pa = order[a.priority] ?? 2;
                    const pb = order[b.priority] ?? 2;
                    return (pa - pb) * dir;
                }
                case 'due_date': {
                    const da = a.due_date || Infinity;
                    const db = b.due_date || Infinity;
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
        if (this._normalizeTaskStatus(task.status) === 'awaiting_owner') return true;
        const s = String(task.status || '').toLowerCase();
        if (s.includes('awaiting') || s.includes('blocked')) return true;
        if (this._normalizeTaskStatus(task.status) === 'in_progress' && task.updated_at) {
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
        if (direct) return direct;
        const ref = String(task?.ticket_ref || '').trim();
        const m = ref.match(/^([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d+)$/);
        return m ? `https://github.com/${m[1]}/issues/${m[2]}` : '';
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
}

// Register globally
window.TaskBoardPanel = TaskBoardPanel;
