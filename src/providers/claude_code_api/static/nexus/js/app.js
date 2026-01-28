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

        // Task board UI state
        this.taskMultiSelectMode = false;
        this.selectedTaskIds = new Set();
        this.archivedGroupOpenKeys = new Set();

        // For task session (session_id = task_<taskId>) unified rendering
        this.taskConversationRefreshTimeout = null;

        // Create task modal
        this.createTaskModal = null;

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
        this.taskToolbar = document.getElementById('taskToolbar');
        this.taskDetail = document.getElementById('taskDetail');
        this.createTaskModal = document.getElementById('createTaskModal');

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
            
            let provider = (session && session.provider) ? session.provider : '';
            if (!provider && messagesData && Array.isArray(messagesData.messages)) {
                const hasGemini = messagesData.messages.some(
                    (msg) => typeof msg.id === 'string' && msg.id.startsWith('gemini-msg-')
                );
                if (hasGemini) provider = 'gemini';
            }
            this.currentSessionProvider = provider;
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
                
                <div id="sessionMessageList" class="space-y-4">
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

            followupInput.value = '';

            const messageList = document.getElementById('sessionMessageList');
            const localUserId = this._randomId('local-user');
            const localAssistantId = this._randomId('local-assistant');
            const placeholderId = this._randomId('thinking');
            const nowLabel = this.formatTime(Date.now());

            if (messageList) {
                const userHtml = `
                    <div class="ml-auto max-w-[80%]" data-local-id="${localUserId}">
                        <div class="bg-blue-600 rounded-lg p-4">
                            <div class="flex items-center space-x-2 mb-2">
                                <span class="text-xs font-medium text-blue-200">${this.escapeHtml(username)}</span>
                                <span class="text-xs text-gray-500">${nowLabel}</span>
                            </div>
                            <div class="message-content">
                                <div class="prose prose-invert prose-sm max-w-none"></div>
                            </div>
                        </div>
                    </div>
                `;
                messageList.insertAdjacentHTML('beforeend', userHtml);
                const userNode = messageList.querySelector(`[data-local-id="${localUserId}"] .message-content .prose`);
                if (userNode) {
                    userNode.textContent = prompt;
                }

                const thinkingHtml = `
                    <div class="mr-auto max-w-[90%]" data-local-id="${placeholderId}">
                        <div class="text-xs text-gray-400 italic">思考中...</div>
                    </div>
                `;
                messageList.insertAdjacentHTML('beforeend', thinkingHtml);
            }

            let assistantReady = false;
            const createAssistantBubble = () => {
                if (assistantReady) return;
                const list = document.getElementById('sessionMessageList');
                if (!list) return;
                const placeholder = list.querySelector(`[data-local-id="${placeholderId}"]`);
                if (placeholder) placeholder.remove();
                const assistantHtml = `
                    <div class="mr-auto max-w-[90%]" data-local-id="${localAssistantId}">
                        <div class="bg-gray-700 rounded-lg p-4">
                            <div class="flex items-center space-x-2 mb-2">
                                <span class="text-xs font-medium text-green-400">${this.escapeHtml(agentName)}</span>
                                <span class="text-xs text-gray-500">${nowLabel}</span>
                            </div>
                            <div class="message-content">
                                <div class="prose prose-invert prose-sm max-w-none"><div id="${localAssistantId}-content" class="space-y-2"></div></div>
                            </div>
                        </div>
                    </div>
                `;
                list.insertAdjacentHTML('beforeend', assistantHtml);
                assistantReady = true;
            };

            const streamState = {
                lastTextNode: null,
                toolBlocks: {},
            };

            const appendTextDelta = (delta) => {
                createAssistantBubble();
                const root = document.getElementById(`${localAssistantId}-content`);
                if (!root) return;
                if (!streamState.lastTextNode) {
                    const div = document.createElement('div');
                    div.setAttribute('data-seg', 'text');
                    root.appendChild(div);
                    streamState.lastTextNode = div;
                }
                streamState.lastTextNode.textContent += delta;
            };

            const ensureToolBlock = (toolId, toolName) => {
                createAssistantBubble();
                const root = document.getElementById(`${localAssistantId}-content`);
                if (!root) return null;
                if (streamState.toolBlocks[toolId]) return streamState.toolBlocks[toolId];

                const tc = {
                    id: toolId,
                    tool_name: toolName || toolId,
                    status: 'executing',
                    start_time: Date.now(),
                    args_string: '',
                    args: {},
                    result: '',
                };
                const wrapper = document.createElement('div');
                wrapper.innerHTML = this.renderToolCall(tc).trim();
                const details = wrapper.firstElementChild;
                if (!details) return null;
                details.setAttribute('data-seg', 'tool');
                details.open = true;

                root.appendChild(details);
                const block = { node: details, startTime: Date.now() };
                streamState.toolBlocks[toolId] = block;
                streamState.lastTextNode = null;
                return block;
            };

            const handleStreamEvent = (evt) => {
                if (!evt || !evt.type) return;
                if (evt.type === 'TOOL_CALL_START') {
                    ensureToolBlock(evt.toolCallId, evt.toolCallName);
                } else if (evt.type === 'TOOL_CALL_ARGS') {
                    const block = ensureToolBlock(evt.toolCallId, evt.toolCallName);
                    const node = block ? block.node : null;
                    if (node) {
                        const args = node.querySelector('[data-role="args"]');
                        if (args && typeof evt.delta === 'string') {
                            args.textContent += evt.delta;
                        }
                    }
                } else if (evt.type === 'TOOL_CALL_END' || evt.type === 'TOOL_CALL_RESULT') {
                    const block = ensureToolBlock(evt.toolCallId, evt.toolCallName);
                    const node = block ? block.node : null;
                    if (node) {
                        const result = node.querySelector('[data-role="result"]');
                        const resultWrap = node.querySelector('[data-role="result-wrap"]');
                        if (result && (evt.result || evt.content)) {
                            result.textContent = String(evt.result || evt.content);
                            if (resultWrap) resultWrap.classList.remove('hidden');
                        }
                        const status = node.querySelector('[data-role="status"]');
                        if (status) {
                            status.classList.remove('text-yellow-400');
                            status.classList.add('text-green-400');
                            status.textContent = '✓';
                        }
                        const duration = node.querySelector('[data-role="duration"]');
                        if (duration && block && block.startTime) {
                            duration.textContent = `${((Date.now() - block.startTime) / 1000).toFixed(1)}s`;
                        }
                        node.removeAttribute('open');
                    }
                }
            };

            try {
                const result = await this.sendFollowupMessage(this.currentSessionId, prompt, {
                    onDelta: (delta) => {
                        const el = document.getElementById(`${localAssistantId}-content`);
                        if (el) {
                            appendTextDelta(delta);
                        } else {
                            createAssistantBubble();
                            const el2 = document.getElementById(`${localAssistantId}-content`);
                            if (el2) {
                                appendTextDelta(delta);
                            } else {
                                liveEl.classList.remove('hidden');
                                liveEl.textContent += delta;
                            }
                        }
                    },
                    onEvent: handleStreamEvent,
                });

                statusEl.textContent = '完成。正在刷新会话...';
                if (result && result.userMessageId) {
                    await this.waitForSessionAssistant(this.currentSessionId, result.userMessageId);
                }
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
            if (e.key === 'Enter' && !e.shiftKey) {
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
            { key: 'archived', title: 'Archived', badge: 'bg-slate-500/20 text-slate-200' },
        ];

        const tasks = Array.isArray(this.tasks) ? this.tasks : [];

        if (!this.taskBoard) return;

        if (tasks.length === 0) {
            this.taskBoard.innerHTML = `
                <div class="text-center text-gray-500 py-8 w-full">
                    <p>暂无任务</p>
                </div>
            `;
            return;
        }

        const renderTaskCard = (task, { muted = false } = {}) => {
            const project = task.project_name || task.project_id || '';
            const workspace = task.workspace || '';
            const provider = (task.provider || '').toLowerCase();
            const updatedAt = task.updated_at || task.completed_at || task.started_at || task.created_at;
            const updatedLabel = updatedAt ? this.formatTime(updatedAt) : '';

            const taskId = String(task.id || '');
            const statusVal = String(task.status || '').toLowerCase();

            const isMulti = !!this.taskMultiSelectMode;
            const isSelected = this.selectedTaskIds.has(taskId);
            const cardClass = muted
                ? 'bg-gray-900/40 border-gray-800 hover:bg-gray-900/60'
                : 'bg-gray-800 border-gray-700 hover:bg-gray-750';

            const clickHandler = isMulti
                ? `app.toggleTaskSelectionFromCard('${this.escapeHtml(taskId)}')`
                : `app.selectTask('${this.escapeHtml(taskId)}')`;

            const selectBox = isMulti ? `
                <input
                    type="checkbox"
                    class="mt-0.5 h-4 w-4 rounded border-gray-600 bg-gray-900 text-blue-500 focus:ring-blue-500"
                    ${isSelected ? 'checked' : ''}
                    onclick="event.stopPropagation();"
                    onchange="app.toggleTaskSelection('${this.escapeHtml(taskId)}', this.checked)"
                    aria-label="选择任务 ${this.escapeHtml(taskId)}"
                />
            ` : '';

            const statusHint = isMulti ? `<span class="text-[10px] text-gray-600">${this.escapeHtml(statusVal)}</span>` : '';

            return `
                <div
                    class="${cardClass} border rounded-lg p-3 cursor-pointer transition-colors"
                    onclick="${clickHandler}"
                    data-task-id="${this.escapeHtml(taskId)}"
                >
                    <div class="flex items-start justify-between">
                        <div class="flex items-start space-x-2 min-w-0">
                            ${selectBox}
                            <div class="min-w-0">
                                <div class="flex items-center space-x-2">
                                    <div class="text-xs text-gray-500">#${this.escapeHtml(taskId)}</div>
                                    ${statusHint}
                                </div>
                                <div class="text-sm font-medium mt-1 line-clamp-2">${this.escapeHtml(task.description || '')}</div>
                            </div>
                        </div>
                        <div class="flex items-center space-x-2 ml-3">
                            <div class="text-xs text-gray-500 whitespace-nowrap">${updatedLabel}</div>
                            <button
                                class="text-gray-500 hover:text-red-400 transition-colors p-1"
                                onclick="event.stopPropagation(); app.showDeleteTaskModal('${this.escapeHtml(taskId)}')"
                                title="删除任务"
                            >
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                                </svg>
                            </button>
                        </div>
                    </div>

                    ${(project || workspace || provider) ? `
                        <div class="mt-2 space-y-1">
                            ${provider ? `<div class="text-[11px] text-emerald-300 truncate">provider: ${this.escapeHtml(provider)}</div>` : ''}
                            ${project ? `<div class="text-xs text-purple-300 truncate">${this.escapeHtml(project)}</div>` : ''}
                            ${workspace ? `<div class="text-xs text-gray-400 truncate">${this.escapeHtml(workspace)}</div>` : ''}
                        </div>
                    ` : ''}
                </div>
            `;
        };

        const toDateKey = (ts) => {
            try {
                const d = new Date(ts);
                if (isNaN(d.getTime())) return 'Unknown';
                return d.toISOString().slice(0, 10);
            } catch (e) {
                return 'Unknown';
            }
        };

        // Prune selection (tasks list updates frequently)
        const currentIds = new Set(tasks.map(t => String(t && t.id)));
        for (const id of Array.from(this.selectedTaskIds)) {
            if (!currentIds.has(id)) this.selectedTaskIds.delete(id);
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
            } else if (col.key === 'archived') {
                // Group archived tasks by updated_at date (YYYY-MM-DD)
                const groups = {};
                for (const task of colTasks) {
                    const updatedAt = task.updated_at || task.completed_at || task.started_at || task.created_at;
                    const key = toDateKey(updatedAt);
                    if (!groups[key]) groups[key] = [];
                    groups[key].push(task);
                }

                const dateKeys = Object.keys(groups).sort((a, b) => String(b).localeCompare(String(a)));
                dateKeys.forEach((dateKey, idx) => {
                    const groupTasks = groups[dateKey] || [];
                    const shouldOpen = this.archivedGroupOpenKeys.has(dateKey) || (this.archivedGroupOpenKeys.size === 0 && idx === 0);
                    const openAttr = shouldOpen ? 'open' : '';

                    html += `
                        <details
                            class="group rounded-lg border border-gray-800 bg-gray-950/40"
                            ${openAttr}
                            ontoggle="app.onArchivedGroupToggle('${dateKey}', this.open)"
                        >
                            <summary class="flex items-center justify-between cursor-pointer select-none px-3 py-2">
                                <div class="flex items-center space-x-2">
                                    <span class="text-xs font-semibold text-slate-200">${this.escapeHtml(dateKey)}</span>
                                    <span class="text-[11px] px-1.5 py-0.5 rounded bg-slate-500/10 text-slate-200">${groupTasks.length}</span>
                                </div>
                                <svg class="w-4 h-4 text-slate-400 transition-transform group-open:rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
                                </svg>
                            </summary>
                            <div class="px-3 pb-3 space-y-2">
                                ${groupTasks.map(t => renderTaskCard(t, { muted: true })).join('')}
                            </div>
                        </details>
                    `;
                });
            } else {
                for (const task of colTasks) {
                    html += renderTaskCard(task);
                }
            }

            html += `
                    </div>
                </div>
            `;
        }

        this.taskBoard.innerHTML = html;
        this.renderTaskToolbar();
    }

    onArchivedGroupToggle(dateKey, isOpen) {
        const key = String(dateKey || 'Unknown');
        if (isOpen) {
            this.archivedGroupOpenKeys.add(key);
        } else {
            this.archivedGroupOpenKeys.delete(key);
        }
    }

    toggleTaskMultiSelect() {
        this.setTaskMultiSelectMode(!this.taskMultiSelectMode);
    }

    setTaskMultiSelectMode(enabled) {
        this.taskMultiSelectMode = !!enabled;
        if (!this.taskMultiSelectMode) {
            this.selectedTaskIds.clear();
        }
        this.renderTaskBoard();
    }

    toggleTaskSelection(taskId, checked) {
        const id = String(taskId || '');
        if (!id) return;
        if (checked) {
            this.selectedTaskIds.add(id);
        } else {
            this.selectedTaskIds.delete(id);
        }
        this.renderTaskToolbar();
    }

    toggleTaskSelectionFromCard(taskId) {
        const id = String(taskId || '');
        if (!id) return;
        if (this.selectedTaskIds.has(id)) {
            this.selectedTaskIds.delete(id);
        } else {
            this.selectedTaskIds.add(id);
        }
        this.renderTaskBoard();
    }

    clearTaskSelection() {
        this.selectedTaskIds.clear();
        this.renderTaskBoard();
    }

    _getSelectedTasksByStatus(status) {
        const st = String(status || '').toLowerCase();
        const tasks = Array.isArray(this.tasks) ? this.tasks : [];
        return tasks.filter(t => this.selectedTaskIds.has(String(t && t.id)) && String(t && t.status || '').toLowerCase() === st);
    }

    async archiveSelectedTasks() {
        const items = this._getSelectedTasksByStatus('done');
        const ids = items.map(t => String(t.id));
        if (!ids.length) return;

        try {
            const res = await NexusAPI.bulkArchiveTasks(ids, { agentName: this.agentName });
            this.showToast(res.message || `已归档 ${ids.length} 个任务`, 'success');
            this.clearTaskSelection();
            this.loadTasks({ preserveDetail: true, silent: true });
        } catch (e) {
            this.showError(e.message || String(e));
        }
    }

    async unarchiveSelectedTasks() {
        const items = this._getSelectedTasksByStatus('archived');
        const ids = items.map(t => String(t.id));
        if (!ids.length) return;

        try {
            const res = await NexusAPI.bulkUnarchiveTasks(ids, { agentName: this.agentName });
            this.showToast(res.message || `已取消归档 ${ids.length} 个任务`, 'success');
            this.clearTaskSelection();
            this.loadTasks({ preserveDetail: true, silent: true });
        } catch (e) {
            this.showError(e.message || String(e));
        }
    }

    async clearSelectedTasks() {
        const items = this._getSelectedTasksByStatus('archived');
        const ids = items.map(t => String(t.id));
        if (!ids.length) return;

        const ok = confirm(`确定要永久清理 ${ids.length} 个已归档任务吗？此操作不可撤销。`);
        if (!ok) return;

        try {
            const res = await NexusAPI.bulkClearTasks(ids, { agentName: this.agentName });
            this.showToast(res.message || `已清理 ${ids.length} 个任务`, 'success');
            this.clearTaskSelection();
            this.loadTasks({ preserveDetail: true, silent: true });
        } catch (e) {
            this.showError(e.message || String(e));
        }
    }

    renderTaskToolbar() {
        if (!this.taskToolbar) return;

        const enabled = !!this.taskMultiSelectMode;
        const selectedCount = this.selectedTaskIds.size;
        const doneCount = this._getSelectedTasksByStatus('done').length;
        const archivedCount = this._getSelectedTasksByStatus('archived').length;

        const btnBase = 'px-3 py-1.5 text-xs rounded-lg border transition-colors';
        const primary = 'bg-blue-600 hover:bg-blue-700 border-blue-500/30 text-white';
        const ghost = 'bg-gray-900/40 hover:bg-gray-900/60 border-gray-700 text-gray-200';
        const danger = 'bg-red-600 hover:bg-red-700 border-red-500/30 text-white';
        const success = 'bg-emerald-600 hover:bg-emerald-700 border-emerald-500/30 text-white';
        const disabled = 'opacity-40 cursor-not-allowed';

        const canArchive = enabled && doneCount > 0;
        const canUnarchive = enabled && archivedCount > 0;
        const canClear = enabled && archivedCount > 0;

        this.taskToolbar.innerHTML = `
            <div class="px-4 py-3 flex items-center justify-between">
                <div class="flex items-center space-x-3">
                    <button
                        class="${btnBase} ${success}"
                        onclick="app.showCreateTaskModal()"
                        title="新建任务"
                    >
                        新建
                    </button>
                    <button
                        class="${btnBase} ${enabled ? primary : ghost}"
                        onclick="app.toggleTaskMultiSelect()"
                        title="多选"
                    >
                        ${enabled ? '退出多选' : '多选'}
                    </button>
                    ${enabled
                        ? `<div class="text-xs text-gray-400">已选 <span class=\"text-gray-200 font-semibold\">${selectedCount}</span>（Done: ${doneCount} / Archived: ${archivedCount}）</div>`
                        : `<div class="text-xs text-gray-500">开启多选后可批量归档 / 取消归档 / 清理</div>`
                    }
                </div>

                ${enabled ? `
                    <div class="flex items-center space-x-2">
                        <button class="${btnBase} ${ghost} ${canArchive ? '' : disabled}" onclick="app.archiveSelectedTasks()" ${canArchive ? '' : 'disabled'}>归档</button>
                        <button class="${btnBase} ${ghost} ${canUnarchive ? '' : disabled}" onclick="app.unarchiveSelectedTasks()" ${canUnarchive ? '' : 'disabled'}>取消归档</button>
                        <button class="${btnBase} ${danger} ${canClear ? '' : disabled}" onclick="app.clearSelectedTasks()" ${canClear ? '' : 'disabled'}>清理</button>
                        <button class="${btnBase} ${ghost}" onclick="app.clearTaskSelection()">清空选择</button>
                    </div>
                ` : ''}
            </div>
        `;
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

                        if (latestStatus === 'done' || latestStatus === 'failed' || latestStatus === 'cancelled' || latestStatus === 'archived') {
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
        const provider = (task.provider || '').toLowerCase();
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
                ${provider ? `<div class="text-xs text-emerald-300">provider：${this.escapeHtml(provider)}</div>` : ''}
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
        const argsText = tc.args_string || JSON.stringify(tc.args, null, 2) || '';
        const resultText = tc.result ? (typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2)) : '';
        const resultHidden = tc.result ? '' : 'hidden';
        
        return `
            <details class="bg-gray-800 rounded-lg overflow-hidden">
                <summary class="px-3 py-2 cursor-pointer hover:bg-gray-750 flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                        <span class="${statusClass}" data-role="status">${statusIcon}</span>
                        <span class="text-sm font-mono">${this.escapeHtml(tc.tool_name)}</span>
                    </div>
                    <span class="text-xs text-gray-500" data-role="duration">${tc.end_time ? ((tc.end_time - tc.start_time) / 1000).toFixed(1) + 's' : '...'}</span>
                </summary>
                <div class="px-3 py-2 border-t border-gray-700">
                    <div class="mb-2">
                        <p class="text-xs text-gray-500 mb-1">参数:</p>
                        <pre class="text-xs bg-gray-900 p-2 rounded overflow-x-auto" data-role="args">${this.escapeHtml(argsText)}</pre>
                    </div>
                    <div class="${resultHidden}" data-role="result-wrap">
                        <p class="text-xs text-gray-500 mb-1">结果:</p>
                        <pre class="text-xs bg-gray-900 p-2 rounded overflow-x-auto max-h-40" data-role="result">${this.escapeHtml(resultText)}</pre>
                    </div>
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

    showCreateTaskModal() {
        if (!this.createTaskModal) return;

        // Reset fields
        const providerEl = document.getElementById('createTaskProvider');
        const descEl = document.getElementById('createTaskDescription');
        const wsEl = document.getElementById('createTaskWorkspace');
        const agentEl = document.getElementById('createTaskAgent');

        if (providerEl) providerEl.value = 'claude';
        if (descEl) descEl.value = '';
        if (wsEl) wsEl.value = '';
        if (agentEl) agentEl.value = this.agentName || '';

        this.createTaskModal.classList.remove('hidden');
        this.createTaskModal.classList.add('flex');

        // focus description
        try { if (descEl) descEl.focus(); } catch (e) {}
    }

    hideCreateTaskModal() {
        if (!this.createTaskModal) return;
        this.createTaskModal.classList.add('hidden');
        this.createTaskModal.classList.remove('flex');
    }

    async submitCreateTask() {
        try {
            const provider = (document.getElementById('createTaskProvider')?.value || 'claude').trim();
            const description = (document.getElementById('createTaskDescription')?.value || '').trim();
            const workspace = (document.getElementById('createTaskWorkspace')?.value || '').trim();
            const agent = (document.getElementById('createTaskAgent')?.value || '').trim();

            if (!description) {
                this.showToast('请填写任务描述', 'error');
                return;
            }

            const payload = {
                provider,
                description,
                workspace: workspace || undefined,
                agent: agent || undefined,
            };

            const created = await NexusAPI.createTask(payload, { agentName: this.agentName });
            this.hideCreateTaskModal();
            this.showToast('任务已创建', 'success');

            // Refresh task board and auto-select newly created task
            await this.loadTasks({ preserveDetail: false, silent: true });
            if (created && created.id) {
                this.selectTask(String(created.id));
            }
        } catch (e) {
            this.showError(e.message || String(e));
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

    showToast(message, variant = 'error') {
        const toast = this.errorToast;
        const msg = this.errorMessage;
        if (!toast || !msg) return;

        msg.textContent = message;

        toast.classList.remove('hidden');
        toast.classList.remove('bg-red-600', 'bg-green-600', 'bg-yellow-600', 'bg-slate-700');

        if (variant === 'success') {
            toast.classList.add('bg-green-600');
        } else if (variant === 'warning') {
            toast.classList.add('bg-yellow-600');
        } else {
            toast.classList.add('bg-red-600');
        }

        setTimeout(() => {
            toast.classList.add('hidden');
        }, 5000);
    }

    showError(message) {
        this.showToast(message, 'error');
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

    async waitForSessionAssistant(sessionId, userMessageId, maxRetries = 6, delayMs = 500) {
        for (let i = 0; i < maxRetries; i++) {
            try {
                const data = await NexusAPI.getSessionMessages(sessionId);
                const messages = (data && data.messages) ? data.messages : [];
                const userIdx = messages.findIndex((msg) => msg.id === userMessageId);
                if (userIdx >= 0) {
                    const followup = messages.slice(userIdx + 1);
                    const hasAssistant = followup.some(
                        (msg) => msg.role === 'assistant' && msg.status === 'complete' && msg.content
                    );
                    if (hasAssistant) {
                        return true;
                    }
                }
            } catch (e) {
                // ignore and retry
            }

            await new Promise((resolve) => setTimeout(resolve, delayMs));
        }

        return false;
    }

    async sendFollowupMessage(sessionId, prompt, { onDelta, onEvent } = {}) {
        const userMessageId = this._randomId('user');
        const body = {
            threadId: sessionId,
            runId: this._randomId('run'),
            messages: [
                {
                    id: userMessageId,
                    role: 'user',
                    content: prompt,
                }
            ],
            tools: [],
            context: [],
            forwardedProps: {
                provider: this.currentSessionProvider || undefined,
            },
            provider: this.currentSessionProvider || undefined,
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
                        } else if (evt.type === 'TOOL_CALL_START' || evt.type === 'TOOL_CALL_ARGS' || evt.type === 'TOOL_CALL_END' || evt.type === 'TOOL_CALL_RESULT') {
                            if (onEvent) onEvent(evt);
                        }
                    }
                }
            }
        } finally {
            try { reader.releaseLock(); } catch (e) {}
        }

        return { userMessageId };
    }
}

// Initialize app
const app = new NexusApp();
// Expose to inline handlers (and avoid collision with <div id="app"> global)
window.app = app;
