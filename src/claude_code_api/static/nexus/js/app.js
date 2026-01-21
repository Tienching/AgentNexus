/**
 * NexusHub Main Application
 */

class NexusApp {
    constructor() {
        this.currentView = 'chat'; // 'chat' | 'task'
        this.agentName = 'ubuntu';

        this.currentSessionId = null;
        this.sessions = [];

        this.currentTaskId = null;
        this.tasks = [];
        this.taskConversationStream = null;

        // For task session (session_id = task_<taskId>) unified rendering
        this.taskConversationRefreshTimeout = null;

        this.taskAutoRefreshTimer = null;
        this.taskDetailRefreshTimer = null;

        this.sessionAutoRefreshTimer = null;

        this.deleteTarget = null;

        this.searchTimeout = null;

        this.init();
    }

    init() {
        // Get DOM elements
        this.searchInput = document.getElementById('searchInput');
        this.usernameFilter = document.getElementById('usernameFilter');
        this.usernameFilterWrap = document.getElementById('usernameFilterWrap');
        this.refreshBtn = document.getElementById('refreshBtn');

        this.viewChatBtn = document.getElementById('viewChatBtn');
        this.viewTaskBtn = document.getElementById('viewTaskBtn');
        this.chatView = document.getElementById('chatView');
        this.taskView = document.getElementById('taskView');
        this.taskBoard = document.getElementById('taskBoard');
        this.taskDetail = document.getElementById('taskDetail');

        this.sessionList = document.getElementById('sessionList');
        this.sessionDetail = document.getElementById('sessionDetail');
        this.deleteModal = document.getElementById('deleteModal');
        this.deleteModalMessage = document.getElementById('deleteModalMessage');
        this.cancelDeleteBtn = document.getElementById('cancelDeleteBtn');
        this.confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
        this.errorToast = document.getElementById('errorToast');
        this.errorMessage = document.getElementById('errorMessage');

        // Bind events
        this.searchInput.addEventListener('input', () => {
            clearTimeout(this.searchTimeout);
            this.searchTimeout = setTimeout(() => {
                if (this.currentView === 'task') {
                    this.loadTasks();
                } else {
                    this.loadSessions();
                }
            }, 300);
        });

        this.usernameFilter.addEventListener('change', () => {
            if (this.currentView === 'chat') {
                this.loadSessions();
            }
        });

        this.refreshBtn.addEventListener('click', () => {
            if (this.currentView === 'task') {
                this.loadTasks();
            } else {
                this.loadUsernames();
                this.loadSessions();
            }
        });

        this.cancelDeleteBtn.addEventListener('click', () => this.hideDeleteModal());
        this.confirmDeleteBtn.addEventListener('click', () => this.confirmDelete());

        // View switcher
        this.viewChatBtn.addEventListener('click', () => this.switchView('chat'));
        this.viewTaskBtn.addEventListener('click', () => this.switchView('task'));

        // Initial load
        this.switchView('chat');
    }

    async loadUsernames() {
        try {
            const data = await NexusAPI.getUsernames();
            const select = this.usernameFilter;
            const currentValue = select.value;
            
            // Clear existing options except the first one
            while (select.options.length > 1) {
                select.remove(1);
            }
            
            // Add new options
            for (const username of data.usernames) {
                const option = document.createElement('option');
                option.value = username;
                option.textContent = username;
                select.appendChild(option);
            }
            
            // Restore selection if still valid
            if (currentValue && data.usernames.includes(currentValue)) {
                select.value = currentValue;
            }
        } catch (error) {
            console.error('Failed to load usernames:', error);
        }
    }

    async loadSessions(options = {}) {
        if (this.currentView !== 'chat') return;

        try {
            const search = this.searchInput.value;
            const username = this.usernameFilter.value;
            const data = await NexusAPI.getSessions({ search, username });
            this.sessions = data.sessions;
            this.renderSessionList();
        } catch (error) {
            if (!options.silent) {
                this.showError(error.message);
                this.sessionList.innerHTML = `
                    <div class="text-center text-gray-500 py-8">
                        <p>加载失败</p>
                        <button onclick="app.loadSessions()" class="text-blue-400 hover:text-blue-300 mt-2">重试</button>
                    </div>
                `;
            }
        }
    }

    renderSessionList() {
        if (this.sessions.length === 0) {
            this.sessionList.innerHTML = `
                <div class="text-center text-gray-500 py-8">
                    <svg class="w-12 h-12 mx-auto mb-3 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"></path>
                    </svg>
                    <p>暂无会话</p>
                </div>
            `;
            return;
        }

        // Group sessions by date
        const groups = this.groupSessionsByDate(this.sessions);
        
        let html = '';
        for (const [label, sessions] of Object.entries(groups)) {
            html += `<div class="mb-4">
                <h3 class="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 px-2">${label}</h3>
                <div class="space-y-1">
            `;
            
            for (const session of sessions) {
                const isActive = session.id === this.currentSessionId;
                const statusClass = this.getStatusClass(session.status);
                const statusLabel = this.getStatusLabel(session.status);
                
                html += `
                    <div 
                        class="session-item p-3 rounded-lg cursor-pointer transition-colors ${isActive ? 'bg-gray-700' : 'hover:bg-gray-800'}"
                        data-session-id="${session.id}"
                        onclick="app.selectSession('${session.id}')"
                    >
                        <div class="flex items-start justify-between">
                            <div class="flex-1 min-w-0">
                                <p class="text-sm font-medium truncate">${this.escapeHtml(session.title)}</p>
                                <div class="flex items-center space-x-2 mt-1">
                                    ${session.username ? `<span class="text-xs text-blue-400">@${this.escapeHtml(session.username)}</span>` : ''}
                                    <span class="text-xs text-gray-500">${this.formatTime(session.updated_at)}</span>
                                </div>
                            </div>
                            <div class="flex items-center space-x-2 ml-2">
                                <span class="px-2 py-0.5 text-xs rounded-full ${statusClass}">${statusLabel}</span>
                                <button 
                                    class="text-gray-500 hover:text-red-400 transition-colors p-1"
                                    onclick="event.stopPropagation(); app.showDeleteModal('${session.id}')"
                                >
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                                    </svg>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }
            
            html += '</div></div>';
        }
        
        this.sessionList.innerHTML = html;
    }

    groupSessionsByDate(sessions) {
        const groups = {};
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const yesterday = new Date(today.getTime() - 24 * 60 * 60 * 1000);
        const weekAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);

        for (const session of sessions) {
            const date = new Date(session.updated_at);
            let label;
            
            if (date >= today) {
                label = '今天';
            } else if (date >= yesterday) {
                label = '昨天';
            } else if (date >= weekAgo) {
                label = '本周';
            } else {
                label = '更早';
            }
            
            if (!groups[label]) {
                groups[label] = [];
            }
            groups[label].push(session);
        }
        
        return groups;
    }

    async selectSession(sessionId) {
        this.currentSessionId = sessionId;
        this.renderSessionList(); // Update active state
        
        try {
            const [session, messagesData] = await Promise.all([
                NexusAPI.getSession(sessionId),
                NexusAPI.getSessionMessages(sessionId),
            ]);
            
            this.renderSessionDetail(session, messagesData);
        } catch (error) {
            this.showError(error.message);
        }
    }

    renderSessionDetail(session, messagesData) {
        const { messages, tool_calls } = messagesData;
        
        // Create tool calls map for quick lookup
        const toolCallsMap = {};
        for (const tc of tool_calls) {
            toolCallsMap[tc.id] = tc;
        }
        
        // 获取用户名和 agent 名称
        const username = session.username || '用户';
        const agentName = session.agent_name || '助手';
        
        let html = `
            <div class="max-w-4xl mx-auto">
                <div class="mb-6">
                    <div class="flex items-center justify-between">
                        <h2 class="text-xl font-semibold">${this.escapeHtml(session.title)}</h2>
                        <span class="px-3 py-1 text-sm rounded-full ${this.getStatusClass(session.status)}">${this.getStatusLabel(session.status)}</span>
                    </div>
                    <p class="text-sm text-gray-500 mt-1">
                        ${session.username ? `<span class="text-blue-400">@${this.escapeHtml(session.username)}</span> · ` : ''}
                        创建于 ${this.formatTime(session.created_at)} · ${session.message_count} 条消息
                    </p>
                </div>
                
                <div class="space-y-4">
        `;
        
        for (const msg of messages) {
            const isUser = msg.role === 'user';
            const alignClass = isUser ? 'ml-auto' : 'mr-auto';
            const bgClass = isUser ? 'bg-blue-600' : 'bg-gray-700';
            const maxWidth = isUser ? 'max-w-[80%]' : 'max-w-[90%]';
            const roleLabel = isUser ? username : agentName;
            const roleLabelClass = isUser ? 'text-blue-200' : 'text-green-400';
            
            html += `
                <div class="${alignClass} ${maxWidth}">
                    <div class="${bgClass} rounded-lg p-4">
                        <div class="flex items-center space-x-2 mb-2">
                            <span class="text-xs font-medium ${roleLabelClass}">
                                ${this.escapeHtml(roleLabel)}
                            </span>
                            <span class="text-xs text-gray-500">${this.formatTime(msg.timestamp)}</span>
                        </div>
                        <div class="message-content">
            `;
            
            // Render by content_segments if available (preserves tool call order)
            if (msg.content_segments && msg.content_segments.length > 0) {
                // Sort segments by sequence
                const sortedSegments = [...msg.content_segments].sort((a, b) => a.sequence - b.sequence);
                
                for (const seg of sortedSegments) {
                    if (seg.type === 'text' && seg.content) {
                        html += `<div class="prose prose-invert prose-sm max-w-none">${this.renderMarkdown(seg.content)}</div>`;
                    } else if (seg.type === 'tool_call' && seg.tool_call_id) {
                        const tc = toolCallsMap[seg.tool_call_id];
                        if (tc) {
                            html += `<div class="my-2">${this.renderToolCall(tc)}</div>`;
                        }
                    }
                }
            } else {
                // Legacy: render content first, then tool calls at bottom
                html += `<div class="prose prose-invert prose-sm max-w-none">${this.renderMarkdown(msg.content)}</div>`;
                
                // Render tool calls if any (legacy behavior - at bottom)
                if (msg.tool_call_ids && msg.tool_call_ids.length > 0) {
                    html += '<div class="mt-3 space-y-2">';
                    for (const tcId of msg.tool_call_ids) {
                        const tc = toolCallsMap[tcId];
                        if (tc) {
                            html += this.renderToolCall(tc);
                        }
                    }
                    html += '</div>';
                }
            }
            
            html += '</div></div></div>';
        }
        
        html += `
                </div>

                <div class="mt-6 border-t border-gray-700 pt-4">
                    <h3 class="text-sm font-medium text-gray-300 mb-2">继续提问</h3>
                    <div class="flex items-start space-x-2">
                        <textarea
                            id="followupInput"
                            rows="3"
                            placeholder="在当前会话里继续提问..."
                            class="flex-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
                        ></textarea>
                        <button
                            id="sendFollowupBtn"
                            class="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                        >
                            发送
                        </button>
                    </div>
                    <p id="followupStatus" class="text-xs text-gray-500 mt-2"></p>
                    <pre id="liveAssistantResponse" class="hidden mt-3 text-xs bg-gray-900 p-3 rounded-lg overflow-x-auto max-h-56"></pre>
                </div>
            </div>
        `;
        
        this.sessionDetail.innerHTML = html;

        const followupInput = document.getElementById('followupInput');
        const sendBtn = document.getElementById('sendFollowupBtn');
        const statusEl = document.getElementById('followupStatus');
        const liveEl = document.getElementById('liveAssistantResponse');

        const send = async () => {
            const prompt = (followupInput.value || '').trim();
            if (!prompt) return;
            if (!this.currentSessionId) return;

            sendBtn.disabled = true;
            sendBtn.classList.add('opacity-50', 'cursor-not-allowed');
            statusEl.textContent = '发送中...';
            liveEl.textContent = '';
            liveEl.classList.add('hidden');

            try {
                await this.sendFollowupMessage(this.currentSessionId, prompt, {
                    onDelta: (delta) => {
                        liveEl.classList.remove('hidden');
                        liveEl.textContent += delta;
                    }
                });

                statusEl.textContent = '完成。正在刷新会话...';
                followupInput.value = '';
                await this.selectSession(this.currentSessionId);
                statusEl.textContent = '';
            } catch (err) {
                statusEl.textContent = `发送失败：${err.message || err}`;
                this.showError(err.message || String(err));
            } finally {
                sendBtn.disabled = false;
                sendBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        };

        sendBtn.addEventListener('click', send);
        followupInput.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                send();
            }
        });
    }

    switchView(view) {
        this.currentView = view;

        // Stop any timers when switching views
        if (this.taskAutoRefreshTimer) {
            try { clearInterval(this.taskAutoRefreshTimer); } catch (e) {}
            this.taskAutoRefreshTimer = null;
        }
        if (this.taskDetailRefreshTimer) {
            try { clearInterval(this.taskDetailRefreshTimer); } catch (e) {}
            this.taskDetailRefreshTimer = null;
        }
        if (this.sessionAutoRefreshTimer) {
            try { clearInterval(this.sessionAutoRefreshTimer); } catch (e) {}
            this.sessionAutoRefreshTimer = null;

        this.deleteTarget = null;
        }

        if (view === 'task') {
            this.chatView.classList.add('hidden');
            this.taskView.classList.remove('hidden');

            // Toggle buttons
            this.viewTaskBtn.classList.add('bg-gray-900', 'text-white');
            this.viewTaskBtn.classList.remove('text-gray-300');
            this.viewChatBtn.classList.remove('bg-gray-900', 'text-white');
            this.viewChatBtn.classList.add('text-gray-300');

            // Controls
            if (this.usernameFilterWrap) this.usernameFilterWrap.classList.add('hidden');
            this.searchInput.placeholder = '搜索任务...';

            // Load tasks
            this.loadTasks({ preserveDetail: true });

            // Auto refresh task board (so you don't need to manually refresh)
            this.taskAutoRefreshTimer = setInterval(() => {
                if (this.currentView !== 'task') return;
                this.loadTasks({ preserveDetail: true, silent: true });
            }, 2000);
        } else {
            // Leaving task view: stop any live task conversation stream
            this.stopTaskConversationStream();
            this.chatView.classList.remove('hidden');
            this.taskView.classList.add('hidden');

            this.viewChatBtn.classList.add('bg-gray-900', 'text-white');
            this.viewChatBtn.classList.remove('text-gray-300');
            this.viewTaskBtn.classList.remove('bg-gray-900', 'text-white');
            this.viewTaskBtn.classList.add('text-gray-300');

            if (this.usernameFilterWrap) this.usernameFilterWrap.classList.remove('hidden');
            this.searchInput.placeholder = '搜索会话...';

            // Load chat data
            this.loadUsernames();
            this.loadSessions({ silent: true });

            // Auto refresh session list/status (so you don't need to refresh page)
            this.sessionAutoRefreshTimer = setInterval(() => {
                if (this.currentView !== 'chat') return;
                this.loadSessions({ silent: true });
            }, 2000);
        }
    }

    async loadTasks(options = {}) {
        if (this.currentView !== 'task') return;

        try {
            const search = this.searchInput.value;
            const data = await NexusAPI.getTasks({
                agentName: this.agentName,
                search,
                page: 1,
                pageSize: 200,
            });
            this.tasks = data.tasks || [];
            this.renderTaskBoard({ preserveDetail: !!options.preserveDetail });
        } catch (error) {
            if (!options.silent) {
                this.showError(error.message);
                if (this.taskBoard) {
                    this.taskBoard.innerHTML = `
                        <div class="text-center text-gray-500 py-8 w-full">
                            <p>加载任务失败</p>
                            <button onclick="app.loadTasks()" class="text-blue-400 hover:text-blue-300 mt-2">重试</button>
                        </div>
                    `;
                }
            }
        }
    }

    renderTaskBoard() {
        const columns = [
            { key: 'todo', title: 'To Do', badge: 'bg-gray-500/20 text-gray-300' },
            { key: 'doing', title: 'Doing', badge: 'bg-yellow-500/20 text-yellow-300' },
            { key: 'done', title: 'Done', badge: 'bg-green-500/20 text-green-300' },
            { key: 'failed', title: 'Failed', badge: 'bg-red-500/20 text-red-300' },
            { key: 'cancelled', title: 'Cancelled', badge: 'bg-gray-600/20 text-gray-400' },
        ];

        const tasks = Array.isArray(this.tasks) ? this.tasks : [];

        if (!this.taskBoard) return;

        // Keep detail panel (avoid killing SSE) when refreshing list

        if (tasks.length === 0) {
            this.taskBoard.innerHTML = `
                <div class="text-center text-gray-500 py-8 w-full">
                    <p>暂无任务</p>
                </div>
            `;
            return;
        }

        let html = '';
        for (const col of columns) {
            const colTasks = tasks.filter(t => (t.status || '').toLowerCase() === col.key);

            html += `
                <div class="w-72 flex-shrink-0">
                    <div class="flex items-center justify-between mb-3 px-1">
                        <div class="flex items-center space-x-2">
                            <span class="text-sm font-semibold">${col.title}</span>
                            <span class="px-2 py-0.5 text-xs rounded-full ${col.badge}">${colTasks.length}</span>
                        </div>
                    </div>

                    <div class="space-y-3">
            `;

            if (colTasks.length === 0) {
                html += `<div class="text-xs text-gray-600 px-2 py-3">空</div>`;
            } else {
                for (const task of colTasks) {
                    const project = task.project_name || task.project_id || '';
                    const workspace = task.workspace || '';
                    const updatedAt = task.updated_at || task.completed_at || task.started_at || task.created_at;
                    const updatedLabel = updatedAt ? this.formatTime(updatedAt) : '';

                    html += `
                        <div
                            class="bg-gray-800 border border-gray-700 rounded-lg p-3 cursor-pointer hover:bg-gray-750 transition-colors"
                            onclick="app.selectTask('${this.escapeHtml(task.id)}')"
                        >
                            <div class="flex items-start justify-between">
                                <div class="min-w-0">
                                    <div class="text-xs text-gray-500">#${this.escapeHtml(task.id)}</div>
                                    <div class="text-sm font-medium mt-1 line-clamp-2">${this.escapeHtml(task.description || '')}</div>
                                </div>
                                <div class="flex items-center space-x-2 ml-3">
                                    <div class="text-xs text-gray-500 whitespace-nowrap">${updatedLabel}</div>
                                    <button
                                        class="text-gray-500 hover:text-red-400 transition-colors p-1"
                                        onclick="event.stopPropagation(); app.showDeleteTaskModal('${this.escapeHtml(task.id)}')"
                                        title="删除任务"
                                    >
                                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                                        </svg>
                                    </button>
                                </div>
                            </div>

                            ${(project || workspace) ? `
                                <div class="mt-2 space-y-1">
                                    ${project ? `<div class="text-xs text-purple-300 truncate">${this.escapeHtml(project)}</div>` : ''}
                                    ${workspace ? `<div class="text-xs text-gray-400 truncate">${this.escapeHtml(workspace)}</div>` : ''}
                                </div>
                            ` : ''}
                        </div>
                    `;
                }
            }

            html += `
                    </div>
                </div>
            `;
        }

        this.taskBoard.innerHTML = html;
    }

    async selectTask(taskId) {
        this.currentTaskId = taskId;
        if (!this.taskDetail) return;

        this.stopTaskConversationStream();

        this.taskDetail.classList.remove('hidden');
        this.taskDetail.innerHTML = `
            <div class="text-gray-500">加载中...</div>
        `;

        try {
            const task = await NexusAPI.getTask(taskId, { agentName: this.agentName });

            // Use task.session_id (format: {source_session_id}_{task_id} or task_{task_id} for legacy)
            const sessionId = task.session_id || `task_${taskId}`;
            this.currentTaskSessionId = sessionId;

            let session = null;
            let messagesData = { messages: [], tool_calls: [] };

            try {
                session = await NexusAPI.getSession(sessionId);
                messagesData = await NexusAPI.getSessionMessages(sessionId);
            } catch (e) {
                // Session may not be archived yet; keep it empty and let UI show placeholder.
                session = null;
                messagesData = { messages: [], tool_calls: [] };
            }

            this.currentTaskSession = session;
            this.currentTaskSessionMessagesData = messagesData;

            this.renderTaskDetail(task, { session, messagesData });
            this.startTaskConversationStream(taskId);

            // Poll task metadata while running (status/updated_at), so UI updates without refresh
            const st = String(task.status || '').toLowerCase();
            if (st === 'todo' || st === 'doing') {
                this.taskDetailRefreshTimer = setInterval(async () => {
                    if (this.currentView !== 'task') return;
                    if (this.currentTaskId !== taskId) return;

                    try {
                        const latest = await NexusAPI.getTask(taskId, { agentName: this.agentName });
                        const latestStatus = String(latest.status || '').toLowerCase();
                        const updatedAt = latest.updated_at || latest.completed_at || latest.started_at || latest.created_at;
                        const updatedLabel = updatedAt ? this.formatTime(updatedAt) : 'N/A';

                        const statusEl = document.getElementById('taskDetailStatus');
                        if (statusEl) statusEl.textContent = `状态：${latestStatus}`;
                        const updatedEl = document.getElementById('taskDetailUpdatedAt');
                        if (updatedEl) updatedEl.textContent = `更新时间：${updatedLabel}`;

                        if (latestStatus === 'done' || latestStatus === 'failed' || latestStatus === 'cancelled') {
                            if (this.taskDetailRefreshTimer) {
                                try { clearInterval(this.taskDetailRefreshTimer); } catch (e) {}
                                this.taskDetailRefreshTimer = null;
                            }
                        }
                    } catch (e) {
                        // ignore transient errors
                    }
                }, 1500);
            }
        } catch (error) {
            this.taskDetail.innerHTML = `
                <div class="text-red-400 text-sm">加载失败：${this.escapeHtml(error.message)}</div>
            `;
        }
    }

    renderTaskDetail(task, agui) {
        const project = task.project_name || task.project_id || '';
        const workspace = task.workspace || '';
        const status = (task.status || '').toLowerCase();

        const updatedAt = task.updated_at || task.completed_at || task.started_at || task.created_at;
        const updatedLabel = updatedAt ? this.formatTime(updatedAt) : 'N/A';

        const session = (agui && agui.session) ? agui.session : this.currentTaskSession;
        const messagesData = (agui && agui.messagesData) ? agui.messagesData : this.currentTaskSessionMessagesData;

        let html = `
            <div class="flex items-center justify-between mb-4">
                <div>
                    <div class="text-xs text-gray-500">Task</div>
                    <div class="text-lg font-semibold">#${this.escapeHtml(task.id)}</div>
                </div>
                <div class="flex items-center space-x-2">
                    <button
                        class="px-3 py-1.5 text-sm bg-red-600 hover:bg-red-700 rounded-lg transition-colors"
                        onclick="app.showDeleteTaskModal('${this.escapeHtml(task.id)}')"
                        title="删除任务"
                    >
                        删除
                    </button>
                    <button
                        class="text-gray-400 hover:text-white text-sm"
                        onclick="app.closeTaskDetail()"
                        title="关闭"
                    >
                        关闭
                    </button>
                </div>
            </div>

            <div class="space-y-2 mb-4">
                <div class="text-sm">${this.escapeHtml(task.description || '')}</div>
                <div id="taskDetailStatus" class="text-xs text-gray-500">状态：${this.escapeHtml(status)}</div>
                <div id="taskDetailUpdatedAt" class="text-xs text-gray-500">更新时间：${this.escapeHtml(updatedLabel)}</div>
                ${project ? `<div class="text-xs text-purple-300">项目：${this.escapeHtml(project)}</div>` : ''}
                ${workspace ? `<div class="text-xs text-gray-400">工作目录：<code class="bg-gray-800 px-1 py-0.5 rounded">${this.escapeHtml(workspace)}</code></div>` : ''}
                ${task.error_message ? `<div class="text-xs text-red-300">错误：<pre class="mt-1 text-xs bg-gray-900 p-2 rounded overflow-x-auto">${this.escapeHtml(task.error_message)}</pre></div>` : ''}
            </div>

            <div class="border-t border-gray-700 pt-4">
                <div class="flex items-center justify-between mb-3">
                    <div class="text-sm font-medium">对话记录</div>
                    <div id="taskConversationStatus" class="text-xs text-gray-500">实时更新中...</div>
                </div>
                <div id="taskConversationMessages" class="space-y-3">
                    ${this.renderTaskConversationFromSession(session, messagesData, status)}
                </div>
            </div>
        `;

        this.taskDetail.innerHTML = html;
    }

    closeTaskDetail() {
        if (!this.taskDetail) return;
        this.stopTaskConversationStream();
        this.taskDetail.classList.add('hidden');
        this.taskDetail.innerHTML = '';
        this.currentTaskId = null;
    }

    stopTaskConversationStream() {
        if (this.taskConversationStream) {
            try { this.taskConversationStream.close(); } catch (e) {}
            this.taskConversationStream = null;
        }
        if (this.taskDetailRefreshTimer) {
            try { clearInterval(this.taskDetailRefreshTimer); } catch (e) {}
            this.taskDetailRefreshTimer = null;
        }
        if (this.taskConversationRefreshTimeout) {
            try { clearTimeout(this.taskConversationRefreshTimeout); } catch (e) {}
            this.taskConversationRefreshTimeout = null;
        }

    }

    scheduleTaskConversationRefresh() {
        if (this.taskConversationRefreshTimeout) return;
        this.taskConversationRefreshTimeout = setTimeout(async () => {
            this.taskConversationRefreshTimeout = null;
            await this.refreshTaskConversationFromSession();
        }, 250);
    }

    async refreshTaskConversationFromSession() {
        if (this.currentView !== 'task') return;
        if (!this.currentTaskId) return;
        if (!this.currentTaskSessionId) return;

        try {
            const [session, messagesData] = await Promise.all([
                NexusAPI.getSession(this.currentTaskSessionId),
                NexusAPI.getSessionMessages(this.currentTaskSessionId),
            ]);

            this.currentTaskSession = session;
            this.currentTaskSessionMessagesData = messagesData;

            const box = document.getElementById('taskConversationMessages');
            if (box) {
                box.innerHTML = this.renderTaskConversationFromSession(session, messagesData);
            }
        } catch (e) {
            // ignore transient errors
        }
    }

    startTaskConversationStream(taskId) {
        this.stopTaskConversationStream();
        if (!taskId) return;

        const es = NexusAPI.streamTaskMessages(taskId, {
            agentName: this.agentName,
            tail: 200,
            pollIntervalMs: 600,
        });
        this.taskConversationStream = es;

        es.onmessage = (ev) => {
            // 只更新当前打开的任务
            if (this.currentTaskId !== taskId) return;

            let evt;
            try {
                evt = JSON.parse(ev.data);
            } catch (e) {
                return;
            }
            if (!evt || !evt.type) return;

            // Keep Task conversation consistent with Chat: refresh from the same session storage.
            // Debounce to avoid too many fetches.
            this.scheduleTaskConversationRefresh();

            const statusEl = document.getElementById('taskConversationStatus');
            if (statusEl && statusEl.textContent !== '已完成（仍会自动保持连接）') {
                statusEl.textContent = '实时更新中...';
            }

            if (evt.type === 'RUN_FINISHED') {
                if (statusEl) statusEl.textContent = '已完成（仍会自动保持连接）';
            }
        };

        es.onerror = () => {
            if (this.currentTaskId !== taskId) return;
            const statusEl = document.getElementById('taskConversationStatus');
            if (statusEl) {
                statusEl.textContent = '实时连接已断开（将自动重连）';
            }
            // EventSource 会自动重连；不手动 close
        };
    }

    renderTaskConversationFromSession(session, messagesData, status = '') {
        const st = (status || '').toLowerCase();
        const data = messagesData || {};
        const messages = Array.isArray(data.messages) ? data.messages : [];
        const toolCalls = Array.isArray(data.tool_calls) ? data.tool_calls : [];

        if (!messages || messages.length === 0) {
            if (st === 'doing' || st === 'todo') {
                return `<div class="text-xs text-gray-500">等待对话记录生成...</div>`;
            }
            return `<div class="text-xs text-gray-500">暂无对话记录</div>`;
        }

        // Tool calls map
        const toolCallsMap = {};
        for (const tc of toolCalls) {
            if (tc && tc.id) toolCallsMap[tc.id] = tc;
        }

        const username = (session && session.username) ? session.username : '用户';
        const agentName = (session && session.agent_name) ? session.agent_name : '助手';

        let html = '';
        for (const msg of messages) {
            const isUser = msg.role === 'user';
            const alignClass = isUser ? 'ml-auto' : 'mr-auto';
            const bgClass = isUser ? 'bg-blue-600' : 'bg-gray-700';
            const maxWidth = isUser ? 'max-w-[80%]' : 'max-w-[90%]';
            const roleLabel = isUser ? username : agentName;
            const roleLabelClass = isUser ? 'text-blue-200' : 'text-green-400';

            html += `
                <div class="${alignClass} ${maxWidth}">
                    <div class="${bgClass} rounded-lg p-4">
                        <div class="flex items-center space-x-2 mb-2">
                            <span class="text-xs font-medium ${roleLabelClass}">
                                ${this.escapeHtml(roleLabel)}
                            </span>
                            <span class="text-xs text-gray-500">${this.formatTime(msg.timestamp)}</span>
                        </div>
                        <div class="message-content">
            `;

            if (msg.content_segments && msg.content_segments.length > 0) {
                const sortedSegments = [...msg.content_segments].sort((a, b) => a.sequence - b.sequence);
                for (const seg of sortedSegments) {
                    if (seg.type === 'text' && seg.content) {
                        html += `<div class="prose prose-invert prose-sm max-w-none">${this.renderMarkdown(seg.content)}</div>`;
                    } else if (seg.type === 'tool_call' && seg.tool_call_id) {
                        const tc = toolCallsMap[seg.tool_call_id];
                        if (tc) {
                            html += `<div class="my-2">${this.renderToolCall(tc)}</div>`;
                        }
                    }
                }
            } else {
                html += `<div class="prose prose-invert prose-sm max-w-none">${this.renderMarkdown(msg.content)}</div>`;

                if (msg.tool_call_ids && msg.tool_call_ids.length > 0) {
                    html += '<div class="mt-3 space-y-2">';
                    for (const tcId of msg.tool_call_ids) {
                        const tc = toolCallsMap[tcId];
                        if (tc) {
                            html += this.renderToolCall(tc);
                        }
                    }
                    html += '</div>';
                }
            }

            html += '</div></div></div>';
        }

        return html;
    }

    renderTaskConversationMessages(messages, status = '') {
        const items = Array.isArray(messages) ? messages : [];
        const st = (status || '').toLowerCase();

        if (!items || items.length === 0) {
            if (st === 'doing' || st === 'todo') {
                return `<div class="text-xs text-gray-500">等待对话记录生成...</div>`;
            }
            return `<div class="text-xs text-gray-500">暂无对话记录</div>`;
        }

        let html = '';
        for (const msg of items) {
            const role = (msg.role || 'assistant').toLowerCase();
            const isUser = role === 'user';
            const alignClass = isUser ? 'ml-auto' : 'mr-auto';
            const bgClass = isUser ? 'bg-blue-600' : 'bg-gray-700';
            const maxWidth = isUser ? 'max-w-[80%]' : 'max-w-[90%]';
            const roleLabel = isUser ? '用户' : '助手';
            const roleLabelClass = isUser ? 'text-blue-200' : 'text-green-400';

            html += `
                <div class="${alignClass} ${maxWidth}">
                    <div class="${bgClass} rounded-lg p-3">
                        <div class="flex items-center space-x-2 mb-1">
                            <span class="text-xs font-medium ${roleLabelClass}">${roleLabel}</span>
                            ${msg.createdAt ? `<span class="text-xs text-gray-500">${this.escapeHtml(this.formatTime(msg.createdAt))}</span>` : ''}
                        </div>
                        <div class="prose prose-invert prose-sm max-w-none">${this.renderMarkdown(msg.content || '')}</div>
                    </div>
                </div>
            `;
        }

        return html;
    }

    renderToolCall(tc) {
        const statusClass = tc.status === 'completed' ? 'text-green-400' : 
                           tc.status === 'failed' ? 'text-red-400' : 'text-yellow-400';
        const statusIcon = tc.status === 'completed' ? '✓' : 
                          tc.status === 'failed' ? '✗' : '⋯';
        
        return `
            <details class="bg-gray-800 rounded-lg overflow-hidden">
                <summary class="px-3 py-2 cursor-pointer hover:bg-gray-750 flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                        <span class="${statusClass}">${statusIcon}</span>
                        <span class="text-sm font-mono">${this.escapeHtml(tc.tool_name)}</span>
                    </div>
                    <span class="text-xs text-gray-500">${tc.end_time ? ((tc.end_time - tc.start_time) / 1000).toFixed(1) + 's' : '...'}</span>
                </summary>
                <div class="px-3 py-2 border-t border-gray-700">
                    <div class="mb-2">
                        <p class="text-xs text-gray-500 mb-1">参数:</p>
                        <pre class="text-xs bg-gray-900 p-2 rounded overflow-x-auto">${this.escapeHtml(tc.args_string || JSON.stringify(tc.args, null, 2))}</pre>
                    </div>
                    ${tc.result ? `
                        <div>
                            <p class="text-xs text-gray-500 mb-1">结果:</p>
                            <pre class="text-xs bg-gray-900 p-2 rounded overflow-x-auto max-h-40">${this.escapeHtml(typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2))}</pre>
                        </div>
                    ` : ''}
                    ${tc.error ? `
                        <div>
                            <p class="text-xs text-red-400 mb-1">错误:</p>
                            <pre class="text-xs bg-gray-900 p-2 rounded overflow-x-auto text-red-300">${this.escapeHtml(tc.error)}</pre>
                        </div>
                    ` : ''}
                </div>
            </details>
        `;
    }

    renderMarkdown(content) {
        if (!content) return '';
        
        // Simple markdown rendering (basic support)
        let html = this.escapeHtml(content);
        
        // Code blocks
        html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
            return `<pre class="bg-gray-900 p-3 rounded-lg overflow-x-auto"><code class="language-${lang}">${code.trim()}</code></pre>`;
        });
        
        // Inline code
        html = html.replace(/`([^`]+)`/g, '<code class="bg-gray-800 px-1 py-0.5 rounded text-sm">$1</code>');
        
        // Bold
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        
        // Italic
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        
        // Line breaks
        html = html.replace(/\n/g, '<br>');
        
        return html;
    }

    showDeleteModal(id, type = 'session') {
        this.deleteTarget = { type, id };

        if (this.deleteModalMessage) {
            if (type === 'task') {
                this.deleteModalMessage.textContent = '确定要删除这个任务吗？此操作不可撤销。';
            } else {
                this.deleteModalMessage.textContent = '确定要删除这个会话吗？此操作不可撤销。';
            }
        }

        this.deleteModal.classList.remove('hidden');
        this.deleteModal.classList.add('flex');
    }

    showDeleteTaskModal(taskId) {
        this.showDeleteModal(taskId, 'task');
    }

    hideDeleteModal() {
        this.deleteModal.classList.add('hidden');
        this.deleteModal.classList.remove('flex');
        this.deleteTarget = null;

        if (this.deleteModalMessage) {
            this.deleteModalMessage.textContent = '确定要删除这个会话吗？此操作不可撤销。';
        }
    }

    async confirmDelete() {
        if (!this.deleteTarget) return;

        const { type, id } = this.deleteTarget;

        try {
            if (type === 'task') {
                await NexusAPI.deleteTask(id, { agentName: this.agentName });

                // Close task detail if needed
                if (this.currentTaskId === id) {
                    this.closeTaskDetail();
                }

                // If chat is currently showing the task session, clear it too
                const sid = `task_${id}`;
                if (this.currentSessionId === sid) {
                    this.currentSessionId = null;
                    this.sessionDetail.innerHTML = `
                        <div class="flex items-center justify-center h-full text-gray-500">
                            <div class="text-center">
                                <svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path>
                                </svg>
                                <p>选择一个会话查看详情</p>
                            </div>
                        </div>
                    `;
                }

                // Refresh both sides
                this.loadTasks({ preserveDetail: true, silent: true });
                this.loadSessions({ silent: true });
            } else {
                await NexusAPI.deleteSession(id);

                // Clear detail if deleted session was selected
                if (this.currentSessionId === id) {
                    this.currentSessionId = null;
                    this.sessionDetail.innerHTML = `
                        <div class="flex items-center justify-center h-full text-gray-500">
                            <div class="text-center">
                                <svg class="w-16 h-16 mx-auto mb-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path>
                                </svg>
                                <p>选择一个会话查看详情</p>
                            </div>
                        </div>
                    `;
                }

                // Keep UI consistent: session delete might also delete a task (when id starts with task_)
                this.loadSessions({ silent: true });
                this.loadTasks({ preserveDetail: true, silent: true });
            }

            this.hideDeleteModal();
        } catch (error) {
            this.showError(error.message);
        }
    }

    showError(message) {
        this.errorMessage.textContent = message;
        this.errorToast.classList.remove('hidden');
        setTimeout(() => {
            this.errorToast.classList.add('hidden');
        }, 5000);
    }

    getStatusClass(status) {
        switch (status) {
            case 'running': return 'bg-yellow-500/20 text-yellow-400';
            case 'completed': return 'bg-green-500/20 text-green-400';
            case 'error': return 'bg-red-500/20 text-red-400';
            default: return 'bg-gray-500/20 text-gray-400';
        }
    }

    getStatusLabel(status) {
        switch (status) {
            case 'running': return '运行中';
            case 'completed': return '已完成';
            case 'error': return '错误';
            default: return '空闲';
        }
    }

    formatTime(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diff = now - date;
        
        if (diff < 60000) {
            return '刚刚';
        } else if (diff < 3600000) {
            return `${Math.floor(diff / 60000)} 分钟前`;
        } else if (diff < 86400000) {
            return `${Math.floor(diff / 3600000)} 小时前`;
        } else if (diff < 604800000) {
            return `${Math.floor(diff / 86400000)} 天前`;
        } else {
            return date.toLocaleDateString('zh-CN');
        }
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    _randomId(prefix) {
        return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    async sendFollowupMessage(sessionId, prompt, { onDelta } = {}) {
        const body = {
            threadId: sessionId,
            runId: this._randomId('run'),
            messages: [
                {
                    id: this._randomId('user'),
                    role: 'user',
                    content: prompt,
                }
            ],
            tools: [],
            context: [],
            forwardedProps: {},
            state: {},
        };

        const response = await fetch('/chat/stream/ubuntu', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
            },
            body: JSON.stringify(body),
        });

        if (!response.ok) {
            const text = await response.text();
            throw new Error(text || `HTTP ${response.status}`);
        }

        if (!response.body) {
            throw new Error('Streaming not supported in this browser');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        try {
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });

                // Parse SSE blocks separated by blank line
                while (true) {
                    const idx = buffer.indexOf('\n\n');
                    if (idx === -1) break;

                    const chunk = buffer.slice(0, idx);
                    buffer = buffer.slice(idx + 2);

                    const lines = chunk.split('\n');
                    for (const line of lines) {
                        if (!line.startsWith('data:')) continue;
                        const payload = line.replace(/^data:\s*/, '').trim();
                        if (!payload) continue;

                        let evt;
                        try {
                            evt = JSON.parse(payload);
                        } catch (e) {
                            continue;
                        }

                        if (evt.type === 'TEXT_MESSAGE_CONTENT' && typeof evt.delta === 'string') {
                            if (onDelta) onDelta(evt.delta);
                        }
                    }
                }
            }
        } finally {
            try { reader.releaseLock(); } catch (e) {}
        }
    }
}

// Initialize app
const app = new NexusApp();
