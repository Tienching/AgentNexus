/**
 * NexusHub Main Application
 */

class NexusApp {
    constructor() {
        this.currentSessionId = null;
        this.sessions = [];
        this.searchTimeout = null;
        
        this.init();
    }

    init() {
        // Get DOM elements
        this.searchInput = document.getElementById('searchInput');
        this.usernameFilter = document.getElementById('usernameFilter');
        this.refreshBtn = document.getElementById('refreshBtn');
        this.sessionList = document.getElementById('sessionList');
        this.sessionDetail = document.getElementById('sessionDetail');
        this.deleteModal = document.getElementById('deleteModal');
        this.cancelDeleteBtn = document.getElementById('cancelDeleteBtn');
        this.confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
        this.errorToast = document.getElementById('errorToast');
        this.errorMessage = document.getElementById('errorMessage');

        // Bind events
        this.searchInput.addEventListener('input', () => {
            clearTimeout(this.searchTimeout);
            this.searchTimeout = setTimeout(() => this.loadSessions(), 300);
        });

        this.usernameFilter.addEventListener('change', () => {
            this.loadSessions();
        });

        this.refreshBtn.addEventListener('click', () => {
            this.loadUsernames();
            this.loadSessions();
        });

        this.cancelDeleteBtn.addEventListener('click', () => this.hideDeleteModal());
        this.confirmDeleteBtn.addEventListener('click', () => this.confirmDelete());

        // Initial load
        this.loadUsernames();
        this.loadSessions();
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

    async loadSessions() {
        try {
            const search = this.searchInput.value;
            const username = this.usernameFilter.value;
            const data = await NexusAPI.getSessions({ search, username });
            this.sessions = data.sessions;
            this.renderSessionList();
        } catch (error) {
            this.showError(error.message);
            this.sessionList.innerHTML = `
                <div class="text-center text-gray-500 py-8">
                    <p>加载失败</p>
                    <button onclick="app.loadSessions()" class="text-blue-400 hover:text-blue-300 mt-2">重试</button>
                </div>
            `;
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

    showDeleteModal(sessionId) {
        this.deleteSessionId = sessionId;
        this.deleteModal.classList.remove('hidden');
        this.deleteModal.classList.add('flex');
    }

    hideDeleteModal() {
        this.deleteModal.classList.add('hidden');
        this.deleteModal.classList.remove('flex');
        this.deleteSessionId = null;
    }

    async confirmDelete() {
        if (!this.deleteSessionId) return;
        
        try {
            await NexusAPI.deleteSession(this.deleteSessionId);
            this.hideDeleteModal();
            
            // Clear detail if deleted session was selected
            if (this.currentSessionId === this.deleteSessionId) {
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
            
            this.loadSessions();
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
