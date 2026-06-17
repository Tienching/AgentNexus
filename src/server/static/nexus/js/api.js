/**
 * NexusHub API Client
 */

const API_BASE = '/api/nexus';

/**
 * Default exec_user, loaded from server defaults.
 * Updated by NexusApp after loading server defaults.
 */
let _defaultExecUser = 'ubuntu';

function _resolveExecUserOption(options = {}, key = 'execUser') {
    if (!Object.prototype.hasOwnProperty.call(options, key)) {
        return _defaultExecUser;
    }
    const rawValue = options[key];
    const normalized = String(rawValue ?? '').trim();
    return normalized || _defaultExecUser;
}

class NexusAPI {

    /**
     * Set the default exec_user for all API calls.
     * Called by NexusApp after loading server defaults.
     */
    static setDefaultExecUser(user) {
        _defaultExecUser = user || 'ubuntu';
    }

    static getDefaultExecUser() {
        return _defaultExecUser;
    }

    // ============ Auth API ============

    /**
     * Return auth headers for API requests.
     * Authentication is handled via HttpOnly cookies (automatically sent by browser),
     * so no explicit Authorization header is needed for same-origin requests.
     * @returns {Object} Headers object
     */
    static _authHeaders() {
        return {};
    }

    static async _request(url, options = {}, {
        errorMessage = 'Request failed',
        responseType = 'json',
        appendErrorText = false,
        statusMessages = {},
        preferErrorDetail = false,
        includeStatusText = true,
    } = {}) {
        const response = await fetch(url, options);

        if (!response.ok) {
            throw await NexusAPI._buildRequestError(response, {
                errorMessage,
                appendErrorText,
                statusMessages,
                preferErrorDetail,
                includeStatusText,
            });
        }

        if (responseType === 'text') {
            return response.text();
        }
        if (responseType === 'raw') {
            return response;
        }
        return response.json();
    }

    static async _buildRequestError(response, {
        errorMessage,
        appendErrorText = false,
        statusMessages = {},
        preferErrorDetail = false,
        includeStatusText = true,
    } = {}) {
        const statusMessage = statusMessages?.[response.status];
        if (statusMessage) {
            return new Error(statusMessage);
        }

        let bodyText = '';
        if (preferErrorDetail || appendErrorText) {
            bodyText = await response.text().catch(() => '');
        }

        if (preferErrorDetail && bodyText) {
            try {
                const data = JSON.parse(bodyText);
                const detailCandidates = typeof data === 'string'
                    ? [data]
                    : [data?.detail, data?.message, data?.error, data?.error_message];
                const detail = detailCandidates.find(value => typeof value === 'string' && value.trim());
                if (detail) {
                    return new Error(detail);
                }
            } catch (_) {
                // Ignore non-JSON error payloads and fall back to the default message below.
            }
        }

        let message = includeStatusText ? `${errorMessage}: ${response.statusText}` : errorMessage;
        if (appendErrorText && bodyText) {
            message += ` - ${bodyText}`;
        }

        return new Error(message);
    }

    /**
     * Check authentication status
     * @returns {Promise<Object>} Auth status response
     */
    static async getAuthStatus() {
        return NexusAPI._request(`${API_BASE}/auth/status`, {}, {
            errorMessage: 'Failed to fetch auth status',
        });
    }

    /**
     * Login to Nexus
     * @param {string} password - Login password
     * @returns {Promise<Object>} Login response
     */
    static async login(password) {
        return NexusAPI._request(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password }),
        }, {
            errorMessage: 'Login failed',
            statusMessages: {
                401: 'Invalid password',
            },
        });
    }

    /**
     * Logout from Nexus
     * @returns {Promise<Object>} Logout response
     */
    static async logout() {
        return NexusAPI._request(`${API_BASE}/auth/logout`, {
            method: 'POST',
        }, {
            errorMessage: 'Logout failed',
        });
    }

    /**
     * Get session list
     * @param {Object} options - Query options
     * @returns {Promise<Object>} Session list response
     */
    static async getSessions(options = {}) {
        const params = new URLSearchParams({
            page: options.page || 1,
            page_size: options.pageSize || 20,
        });
        
        if (options.search) {
            params.append('search', options.search);
        }
        if (options.status) {
            params.append('status', options.status);
        }
        if (options.username) {
            params.append('username', options.username);
        }
        
        return NexusAPI._request(`${API_BASE}/sessions?${params}`, {}, {
            errorMessage: 'Failed to fetch sessions',
        });
    }

    /**
     * Get session detail
     * @param {string} sessionId - Session ID
     * @returns {Promise<Object>} Session detail
     */
    static async getSession(sessionId) {
        const sid = encodeURIComponent(sessionId || '');
        return NexusAPI._request(`${API_BASE}/sessions/${sid}`, {}, {
            errorMessage: 'Failed to fetch session',
            statusMessages: {
                404: 'Session not found',
            },
        });
    }

    /**
     * Get session messages
     * @param {string} sessionId - Session ID
     * @returns {Promise<Object>} Messages response
     */
    static async getSessionMessages(sessionId) {
        const sid = encodeURIComponent(sessionId || '');
        return NexusAPI._request(`${API_BASE}/sessions/${sid}/messages`, {}, {
            errorMessage: 'Failed to fetch messages',
            statusMessages: {
                404: 'Session not found',
            },
        });
    }

    /**
     * Delete session
     * @param {string} sessionId - Session ID
     * @returns {Promise<Object>} Delete response
     */
    static async deleteSession(sessionId) {
        const raw = sessionId == null ? '' : String(sessionId);
        if (raw.trim() === '') {
            return NexusAPI.bulkDeleteSessions(['']);
        }

        const sid = encodeURIComponent(raw);
        return NexusAPI._request(`${API_BASE}/sessions/${sid}`, {
            method: 'DELETE',
        }, {
            errorMessage: 'Failed to delete session',
        });
    }

    static async bulkDeleteSessions(sessionIds = []) {
        return NexusAPI._request(`${API_BASE}/sessions/bulk_delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_ids: sessionIds }),
        }, {
            errorMessage: 'Failed to bulk delete sessions',
            appendErrorText: true,
        });
    }

    static async deleteAllSessions({ username, search, status } = {}) {
        const params = new URLSearchParams();
        if (username) params.set('username', username);
        if (search) params.set('search', search);
        if (status) params.set('status', status);
        const qs = params.toString();
        const url = `${API_BASE}/sessions/delete_all${qs ? '?' + qs : ''}`;
        return NexusAPI._request(url, { method: 'POST' }, {
            errorMessage: 'Failed to delete all sessions',
            appendErrorText: true,
        });
    }

    /**
     * Create new session
     * @param {Object} payload - Session data
     * @returns {Promise<Object>} Created session
     */
    static async createSession(payload = {}) {
        return NexusAPI._request(`${API_BASE}/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to create session',
            appendErrorText: true,
        });
    }

    /**
     * Cancel running session
     * @param {string} sessionId - Session ID
     * @returns {Promise<Object>} Cancel response
     */
    static async cancelSession(sessionId) {
        const sid = encodeURIComponent(sessionId || '');
        return NexusAPI._request(`${API_BASE}/sessions/${sid}/cancel`, {
            method: 'POST',
        }, {
            errorMessage: 'Failed to cancel session',
        });
    }

    /**
     * Get all usernames
     * @returns {Promise<Object>} Usernames response
     */
    static async getUsernames() {
        return NexusAPI._request(`${API_BASE}/usernames`, {}, {
            errorMessage: 'Failed to fetch usernames',
        });
    }

    /**
     * Get available agents
     * @returns {Promise<Object>} Agents response
     */
    static async getAgents() {
        return NexusAPI._request(`${API_BASE}/agents`, {}, {
            errorMessage: 'Failed to fetch agents',
        });
    }

    /**
     * Get unique projects
     * @param {Object} options - Query options
     * @returns {Promise<Array>} List of project items
     */
    static async getProjects(options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        return NexusAPI._request(`${API_BASE}/projects?${params}`, {}, {
            errorMessage: 'Failed to fetch projects',
        });
    }

    // ============ Server Defaults API ============

    /**
     * Get server-side default configuration from .env
     * @returns {Promise<Object>} Server defaults (exec_user, default_provider, default_model, etc.)
     */
    static async getDefaults() {
        return NexusAPI._request(`${API_BASE}/defaults`, {}, {
            errorMessage: 'Failed to fetch server defaults',
        });
    }

    // ============ Skills API ============

    /**
     * Get skills from all provider directories
     * @param {Object} options - Query options
     * @returns {Promise<Object>} Skills response { providers: { [provider]: SkillInfo[] } }
     */
    static async getSkills(options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        if (options.customPaths) {
            params.append('custom_paths', JSON.stringify(options.customPaths));
        }
        return NexusAPI._request(`${API_BASE}/skills?${params}`, {}, {
            errorMessage: 'Failed to fetch skills',
        });
    }

    /**
     * Create a new skill
     * @param {Object} payload - { provider, skill_name, description, content, skills_path? }
     * @returns {Promise<Object>} Success response
     */
    static async createSkill(payload) {
        return NexusAPI._request(`${API_BASE}/skills`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to create skill',
            appendErrorText: true,
        });
    }

    /**
     * Delete a skill
     * @param {string} provider - Provider name
     * @param {string} skillName - Skill name
     * @param {Object} options - { execUser?, skillsPath? }
     * @returns {Promise<Object>} Success response
     */
    static async deleteSkill(provider, skillName, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        if (options.skillsPath) {
            params.append('skills_path', options.skillsPath);
        }
        return NexusAPI._request(
            `${API_BASE}/skills/${encodeURIComponent(provider)}/${encodeURIComponent(skillName)}?${params}`,
            { method: 'DELETE' },
            {
                errorMessage: 'Failed to delete skill',
                appendErrorText: true,
            }
        );
    }

    // ============ Tasks API ============

    static async getTasks(options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
            page: options.page || 1,
            page_size: options.pageSize || 50,
        });

        if (options.status) params.append('status', options.status);
        if (options.projectId) params.append('project_id', options.projectId);
        if (options.workspace) params.append('workspace', options.workspace);
        if (options.search) params.append('search', options.search);

        const response = await fetch(`${API_BASE}/tasks?${params}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch tasks: ${response.statusText}`);
        }
        return response.json();
    }

    static async getTask(taskId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}?${params}`);
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('Task not found');
            }
            throw new Error(`Failed to fetch task: ${response.statusText}`);
        }
        return response.json();
    }

    static async createTask(payload, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });

        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to create task: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }

        return response.json();
    }

    static async deleteTask(taskId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}?${params}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            throw new Error(`Failed to delete task: ${response.statusText}`);
        }
        return response.json();
    }

    static async bulkArchiveTasks(taskIds = [], options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks/bulk_archive?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_ids: taskIds }),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to bulk archive tasks: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async bulkUnarchiveTasks(taskIds = [], options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks/bulk_unarchive?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_ids: taskIds }),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to bulk unarchive tasks: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async bulkClearTasks(taskIds = [], options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks/bulk_clear?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_ids: taskIds }),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to bulk clear tasks: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async bulkDeleteTasks(taskIds = [], options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks/bulk_delete?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_ids: taskIds }),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to bulk delete tasks: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    /**
     * Batch create multiple tasks at once
     * @param {Array} tasks - Array of task objects to create
     * @param {Object} options - Query options
     * @returns {Promise<Object>} Bulk create response with created tasks and errors
     */
    static async bulkCreateTasks(tasks = [], options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks/bulk?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tasks }),
        });

        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to bulk create tasks: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    /**
     * Update task status
     * @param {string} taskId - Task ID
     * @param {string} status - New status (todo/doing/done/failed/cancelled/archived)
     * @param {Object} options - Query options
     * @returns {Promise<Object>} Updated task
     */
    static async updateTaskStatus(taskId, status, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/status?${params}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status }),
        });

        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to update task status: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async updateTask(taskId, updates, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}?${params}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates),
        });

        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to update task: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    /**
     * Requeue an orphaned task back into the active queue
     * @param {string} taskId - Task ID
     * @param {Object} options - Query options
     * @returns {Promise<Object>} Requeue response
     */
    static async requeueOrphanTask(taskId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/requeue-orphan?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options.reason ? { reason: options.reason } : {}),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to requeue orphan task: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async getTaskQualityReviews(taskId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/quality-reviews?${params}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch task quality reviews: ${response.statusText}`);
        }
        return response.json();
    }

    static async submitTaskQualityReview(taskId, payload = {}, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/quality-reviews?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to submit quality review: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async getTaskComments(taskId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/comments?${params}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch task comments: ${response.statusText}`);
        }
        return response.json();
    }

    static async createTaskComment(taskId, payload = {}, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/comments?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to create task comment: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async broadcastTask(taskId, payload = {}, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/broadcast?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to broadcast task message: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async getTaskMessages(taskId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        if (options.tail) params.append('tail', options.tail);
        if (options.limit) params.append('limit', options.limit);

        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/agui/messages?${params}`);
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('Task conversation log not found');
            }
            throw new Error(`Failed to fetch task messages: ${response.statusText}`);
        }
        return response.json();
    }

    static streamTaskMessages(taskId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
            tail: options.tail || 200,
        });

        if (options.pollIntervalMs) params.append('poll_interval_ms', options.pollIntervalMs);

        const url = `${API_BASE}/tasks/${encodeURIComponent(taskId)}/agui/stream?${params}`;
        return new EventSource(url);
    }

    static streamSessionMessages(sessionId, options = {}) {
        const params = new URLSearchParams({
            tail: options.tail || 200,
        });
        if (options.pollIntervalMs) params.append('poll_interval_ms', options.pollIntervalMs);

        const url = `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/agui/stream?${params}`;
        return new EventSource(url);
    }

    // ============ AGUI Chat Streaming API ============

    /**
     * Send a message via AGUI protocol and get streaming response
     * @param {string} execUser - Linux exec user for the session
     * @param {Object} payload - AGUI request payload
     * @returns {Promise<Response>} Fetch response for streaming
     */
    static async chatStream(execUser, payload, providerOrAlias = '') {
        const resolvedExecUser = execUser || _defaultExecUser;
        const normalizedTarget = (providerOrAlias || '').trim();
        const params = new URLSearchParams();
        if (normalizedTarget) {
            params.set('alias', normalizedTarget);
        }
        const query = params.toString();
        const streamUrl = `/chat/stream/${encodeURIComponent(resolvedExecUser)}${query ? `?${query}` : ''}`;

        const response = await fetch(streamUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Chat stream failed: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }

        return response;
    }

    // ============ Session Files API ============

    // ============ History API ============

    /**
     * Get available workspace paths from local CLI history files
     * @param {Object} options - Query options
     * @returns {Promise<Array>} List of project entries
     */
    static async getHistoryProjects(options = {}) {
        const execUser = _resolveExecUserOption(options, 'execUser');
        const params = new URLSearchParams({
            exec_user: execUser,
        });
        if (options.provider) params.append('provider', options.provider);
        if (options.customPaths) params.append('custom_paths', JSON.stringify(options.customPaths));

        const response = await fetch(`${API_BASE}/history/projects?${params}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch history projects: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Get history sessions from local CLI files.
     * @param {Object} options - Query options (projectPath optional; omit to aggregate all projects)
     * @returns {Promise<Object>} Session list response
     */
    static async getHistorySessions(options = {}) {
        const execUser = _resolveExecUserOption(options, 'execUser');
        const params = new URLSearchParams({
            page: options.page || 1,
            page_size: options.pageSize || 50,
            exec_user: execUser,
        });
        if (options.projectPath) params.append('project_path', options.projectPath);
        if (options.provider) params.append('provider', options.provider);
        if (options.search) params.append('search', options.search);
        if (options.customPaths) params.append('custom_paths', JSON.stringify(options.customPaths));
        if (options.perAliasLimit && Number(options.perAliasLimit) > 0) {
            params.set('per_alias_limit', String(Number(options.perAliasLimit)));
        }
        return NexusAPI._request(`${API_BASE}/history/sessions?${params}`, {}, {
            errorMessage: 'Failed to fetch history sessions',
        });
    }

    /**
     * Get messages for a specific history session
     * @param {string} provider - Provider name (claude/codex/codebuddy/gemini)
     * @param {string} sessionId - Session ID
     * @param {Object} options - { execUser?, configPath? }
     * @returns {Promise<Object>} Messages response
     */
    static async getHistoryMessages(provider, sessionId, options = {}) {
        const execUser = _resolveExecUserOption(options, 'execUser');
        const params = new URLSearchParams({
            exec_user: execUser,
        });
        if (options.configPath) params.append('config_path', options.configPath);
        return NexusAPI._request(
            `${API_BASE}/history/sessions/${encodeURIComponent(provider)}/${encodeURIComponent(sessionId)}/messages?${params}`,
            {},
            {
                errorMessage: 'Failed to fetch history messages',
                statusMessages: {
                    404: 'History session not found',
                },
            }
        );
    }

    /**
     * Promote a history session into runtime session for continued chat
     * @param {string} provider - Provider or alias name
     * @param {string} sessionId - History session ID
     * @param {Object} options - { projectPath, execUser?, mode? ('full'|'windowed') }
     * @returns {Promise<Object>} { runtime_session_id, created }
     */
    static async promoteHistorySession(provider, sessionId, options = {}) {
        return NexusAPI._request(
            `${API_BASE}/history/sessions/${encodeURIComponent(provider)}/${encodeURIComponent(sessionId)}/promote`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_path: options.projectPath || '',
                    exec_user: _resolveExecUserOption(options, 'execUser'),
                    mode: options.mode || 'windowed',
                }),
            },
            {
                errorMessage: 'Failed to promote history session',
                appendErrorText: true,
            }
        );
    }

    /**
     * Resume a history session using the canonical bind/resume endpoint.
     * @param {string} provider
     * @param {string} sessionId
     * @param {Object} options
     */
    static async resumeHistorySession(provider, sessionId, options = {}) {
        return NexusAPI._request(
            `${API_BASE}/history/sessions/${encodeURIComponent(provider)}/${encodeURIComponent(sessionId)}/resume`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_path: options.projectPath || '',
                    exec_user: _resolveExecUserOption(options, 'execUser'),
                    mode: options.mode || 'windowed',
                }),
            },
            {
                errorMessage: 'Failed to resume history session',
                appendErrorText: true,
            }
        );
    }

    /**
     * Bind a history session using the canonical bind endpoint.
     * @param {string} provider
     * @param {string} sessionId
     * @param {Object} options
     */
    static async bindHistorySession(provider, sessionId, options = {}) {
        return NexusAPI._request(
            `${API_BASE}/history/sessions/${encodeURIComponent(provider)}/${encodeURIComponent(sessionId)}/bind`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_path: options.projectPath || '',
                    exec_user: _resolveExecUserOption(options, 'execUser'),
                    mode: options.mode || 'windowed',
                }),
            },
            {
                errorMessage: 'Failed to bind history session',
                appendErrorText: true,
            }
        );
    }

    /**
     * Continue a history session in a new runtime session.
     * This is the user-facing name used by the UI; it keeps the transport-level
     * promote endpoint behind a gentler compatibility wrapper.
     */
    static async continueHistorySession(provider, sessionId, options = {}) {
        return NexusAPI.resumeHistorySession(provider, sessionId, options);
    }

    /**
     * Fetch/refresh CLI file data into an existing runtime session
     * @param {string} sessionId - Runtime session ID
     * @param {Object} options - { execUser? }
     * @returns {Promise<Object>} { session_id, cli_session_id, provider, messages_imported, tool_calls_imported }
     */
    static async fetchFromCli(sessionId, options = {}) {
        const response = await fetch(
            `${API_BASE}/history/sessions/${encodeURIComponent(sessionId)}/fetch-from-cli`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    exec_user: _resolveExecUserOption(options, 'execUser'),
                }),
            }
        );

        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to fetch from CLI: ${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    // ============ Session Files API (continued) ============

    /**
     * List files in a session's folder
     * @param {string} sessionId - Session ID
     * @param {Object} options - Query options
     * @returns {Promise<Object>} Session files response
     */
    static async getSessionFiles(sessionId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });

        if (options.subpath) {
            params.append('subpath', options.subpath);
        }

        const response = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/files?${params}`);
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('Session folder not found');
            }
            throw new Error(`Failed to fetch session files: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Get download URL for a file in session folder
     * @param {string} sessionId - Session ID
     * @param {string} filePath - File path relative to session folder
     * @param {Object} options - Query options
     * @returns {string} Download URL
     */
    static getFileDownloadUrl(sessionId, filePath, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
            file_path: filePath,
        });
        return `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/files/download?${params}`;
    }

    // ==================== Tmux Command API ====================

    /**
     * Get tmux command for opening a session in tmux
     * @param {string} sessionId - Session ID
     * @returns {Promise<Object>} Object with tmux_command, cli_command, exec_dir etc.
     */
    static async getTmuxCommand(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/tmux-command`, {
            headers: this._authHeaders(),
        });
        if (!response.ok) {
            throw new Error(`Failed to get tmux command: ${response.statusText}`);
        }
        return response.json();
    }

    // ==================== Schedule API ====================

    /**
     * List schedules with pagination and optional status filter
     */
    static async getSchedules(options = {}) {
        const params = new URLSearchParams();
        params.append('page', options.page || 1);
        params.append('page_size', options.pageSize || 50);
        if (options.status) params.append('status', options.status);
        const response = await fetch(`${API_BASE}/schedules?${params}`, {
            headers: this._authHeaders(),
        });
        if (!response.ok) throw new Error(`Failed to fetch schedules: ${response.statusText}`);
        return response.json();
    }

    /**
     * Get schedule detail by ID
     */
    static async getSchedule(scheduleId) {
        const response = await fetch(`${API_BASE}/schedules/${encodeURIComponent(scheduleId)}`, {
            headers: this._authHeaders(),
        });
        if (!response.ok) throw new Error(`Failed to fetch schedule: ${response.statusText}`);
        return response.json();
    }

    /**
     * Create a new cron schedule
     */
    static async createSchedule(data) {
        const response = await fetch(`${API_BASE}/schedules`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...this._authHeaders() },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `Failed to create schedule: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Update schedule fields
     */
    static async updateSchedule(scheduleId, data) {
        const response = await fetch(`${API_BASE}/schedules/${encodeURIComponent(scheduleId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...this._authHeaders() },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `Failed to update schedule: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Delete a schedule
     */
    static async deleteSchedule(scheduleId) {
        const response = await fetch(`${API_BASE}/schedules/${encodeURIComponent(scheduleId)}`, {
            method: 'DELETE',
            headers: this._authHeaders(),
        });
        if (!response.ok) throw new Error(`Failed to delete schedule: ${response.statusText}`);
        return response.json();
    }

    /**
     * Pause a schedule
     */
    static async pauseSchedule(scheduleId) {
        const response = await fetch(`${API_BASE}/schedules/${encodeURIComponent(scheduleId)}/pause`, {
            method: 'POST',
            headers: this._authHeaders(),
        });
        if (!response.ok) throw new Error(`Failed to pause schedule: ${response.statusText}`);
        return response.json();
    }

    /**
     * Resume a paused schedule
     */
    static async resumeSchedule(scheduleId) {
        const response = await fetch(`${API_BASE}/schedules/${encodeURIComponent(scheduleId)}/resume`, {
            method: 'POST',
            headers: this._authHeaders(),
        });
        if (!response.ok) throw new Error(`Failed to resume schedule: ${response.statusText}`);
        return response.json();
    }

    /**
     * Cancel a schedule permanently
     */
    static async cancelSchedule(scheduleId) {
        const response = await fetch(`${API_BASE}/schedules/${encodeURIComponent(scheduleId)}/cancel`, {
            method: 'POST',
            headers: this._authHeaders(),
        });
        if (!response.ok) throw new Error(`Failed to cancel schedule: ${response.statusText}`);
        return response.json();
    }

    /**
     * Manually trigger a schedule (bypass cron timing)
     */
    static async triggerSchedule(scheduleId) {
        const response = await fetch(`${API_BASE}/schedules/${encodeURIComponent(scheduleId)}/trigger`, {
            method: 'POST',
            headers: this._authHeaders(),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `Failed to trigger schedule: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Get recent task IDs spawned by a schedule
     */
    static async getScheduleHistory(scheduleId, limit = 20) {
        const params = new URLSearchParams({ limit });
        const response = await fetch(`${API_BASE}/schedules/${encodeURIComponent(scheduleId)}/history?${params}`, {
            headers: this._authHeaders(),
        });
        if (!response.ok) throw new Error(`Failed to fetch schedule history: ${response.statusText}`);
        return response.json();
    }

    // ============ Agent Runtimes API ============

    /**
     * Detect installed agent runtimes (claude, codex, gemini, codebuddy, nexus)
     * @param {string} [runtimeId] - Optional: detect a specific runtime only
     * @returns {Promise<Object>} Runtimes detection result
     */
    static async getAgentRuntimes(runtimeId) {
        const params = new URLSearchParams();
        if (runtimeId) params.set('runtime_id', runtimeId);
        const query = params.toString();
        return NexusAPI._request(`${API_BASE}/agent-runtimes${query ? '?' + query : ''}`, {}, {
            errorMessage: 'Failed to detect runtimes',
        });
    }

    static async listRuntimeDaemons() {
        // Lists all aggregated daemon runtimes (multi-machine/multi-provider).
        return NexusAPI._request(`${API_BASE}/runtimes/daemons`, {}, {
            errorMessage: 'Failed to list runtime daemons',
        });
    }

    // ============ Admin / Ops APIs ============

    static async getDiagnostics() {
        return NexusAPI._request(`${API_BASE}/diagnostics`, {}, {
            errorMessage: 'Failed to fetch diagnostics',
        });
    }

    static async getSetupReadiness() {
        return NexusAPI._request(`${API_BASE}/setup/readiness`, {}, {
            errorMessage: 'Failed to fetch setup readiness',
        });
    }

    static async getSecurityScan() {
        return NexusAPI._request(`${API_BASE}/security-scan`, {}, {
            errorMessage: 'Failed to fetch security scan',
        });
    }

    static async getSystemMonitor() {
        return NexusAPI._request(`${API_BASE}/system-monitor`, {}, {
            errorMessage: 'Failed to fetch system monitor',
        });
    }

    static async getWorkload() {
        return NexusAPI._request(`${API_BASE}/workload`, {}, {
            errorMessage: 'Failed to fetch workload',
        });
    }

    static async getStandup() {
        return NexusAPI._request(`${API_BASE}/standup`, {}, {
            errorMessage: 'Failed to fetch standup',
        });
    }

    static async getAuditLog(params = {}) {
        const qs = new URLSearchParams();
        if (params.action) qs.set('action', params.action);
        if (params.task_id) qs.set('task_id', params.task_id);
        if (params.limit) qs.set('limit', params.limit);
        const query = qs.toString();
        return NexusAPI._request(`${API_BASE}/audit${query ? '?' + query : ''}`, {}, {
            errorMessage: 'Failed to fetch audit log',
        });
    }

    static async globalSearch(q, type) {
        const params = new URLSearchParams({ q });
        if (type && type !== 'all') params.set('type', type);
        return NexusAPI._request(`${API_BASE}/search?${params}`, {}, {
            errorMessage: 'Failed to search',
        });
    }

    static async getCleanupPreview() {
        return NexusAPI._request(`${API_BASE}/cleanup`, {}, {
            errorMessage: 'Failed to fetch cleanup preview',
        });
    }

    static async executeCleanup(dryRun = true) {
        const params = new URLSearchParams({ dry_run: dryRun });
        return NexusAPI._request(`${API_BASE}/cleanup?${params}`, { method: 'POST' }, {
            errorMessage: 'Failed to execute cleanup',
        });
    }

    static async parseSchedule(input) {
        const params = new URLSearchParams({ input });
        return NexusAPI._request(`${API_BASE}/schedule-parse?${params}`, {}, {
            errorMessage: 'Failed to parse schedule',
        });
    }

    static async exportData(type, format) {
        const params = new URLSearchParams({ type });
        if (format) params.set('format', format);
        const response = await NexusAPI._request(`${API_BASE}/export?${params}`, {}, {
            errorMessage: 'Failed to export data',
            responseType: 'raw',
        });
        const ct = response.headers.get('content-type') || '';
        if (ct.includes('text/csv') || (format && format.toLowerCase() === 'csv')) {
            return response.text();
        }
        return response.json();
    }

    // ============ Slash Commands API ============

    /**
     * List all registered slash commands
     * @returns {Promise<Array>} List of slash command objects with name and description
     */
    static async listSlashCommands() {
        return NexusAPI._request(`${API_BASE}/commands`, {}, {
            errorMessage: 'Failed to fetch slash commands',
        });
    }

    // ============ Plan Mode API ============

    /**
     * Enter plan mode (read-only exploration)
     * @returns {Promise<Object>} Plan action response
     */
    static async enterPlanMode() {
        return NexusAPI._request(`${API_BASE}/plan/enter`, { method: 'POST' }, {
            errorMessage: 'Failed to enter plan mode',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    /**
     * Submit a plan for approval
     * @param {string} content - The plan content
     * @returns {Promise<Object>} Plan action response
     */
    static async submitPlan(content) {
        return NexusAPI._request(`${API_BASE}/plan/submit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        }, {
            errorMessage: 'Failed to submit plan',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    /**
     * Approve the current plan
     * @returns {Promise<Object>} Plan action response
     */
    static async approvePlan() {
        return NexusAPI._request(`${API_BASE}/plan/approve`, { method: 'POST' }, {
            errorMessage: 'Failed to approve plan',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    /**
     * Reject the current plan
     * @returns {Promise<Object>} Plan action response
     */
    static async rejectPlan() {
        return NexusAPI._request(`${API_BASE}/plan/reject`, { method: 'POST' }, {
            errorMessage: 'Failed to reject plan',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    /**
     * Get current plan mode status
     * @returns {Promise<Object>} Plan status response
     */
    static async getPlanStatus() {
        return NexusAPI._request(`${API_BASE}/plan/status`, {}, {
            errorMessage: 'Failed to get plan status',
            includeStatusText: false,
        });
    }

    /**
     * Exit plan mode
     * @returns {Promise<Object>} Plan action response
     */
    static async exitPlanMode() {
        return NexusAPI._request(`${API_BASE}/plan/exit`, { method: 'POST' }, {
            errorMessage: 'Failed to exit plan mode',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    // ============ Agent Lifecycle API ============

    /**
     * Get agent statistics
     * @returns {Promise<Object>} Agent stats response
     */
    static async getAgentStats() {
        return NexusAPI._request(`${API_BASE}/agents/stats`, {}, {
            errorMessage: 'Failed to fetch agent stats',
        });
    }

    static async getAgentsOverview() {
        return NexusAPI._request(`${API_BASE}/agents/overview`, {}, {
            errorMessage: 'Failed to fetch agents overview',
        });
    }

    static async getAgentBinding(agentId) {
        return NexusAPI._request(`${API_BASE}/agents/${encodeURIComponent(agentId)}/binding`, {}, {
            errorMessage: 'Failed to fetch agent binding',
        });
    }

    static async updateAgentBinding(agentId, payload = {}) {
        return NexusAPI._request(`${API_BASE}/agents/${encodeURIComponent(agentId)}/binding`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to update agent binding',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    /**
     * Register a new agent
     * @param {Object} payload - Agent registration data
     * @returns {Promise<Object>} Registration response
     */
    static async registerAgent(payload) {
        return NexusAPI._request(`${API_BASE}/agents/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to register agent',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    /**
     * Send agent heartbeat
     * @param {string} agentId - Agent ID
     * @param {Object} payload - Heartbeat data
     * @returns {Promise<Object>} Heartbeat response
     */
    static async agentHeartbeat(agentId, payload = {}) {
        return NexusAPI._request(`${API_BASE}/agents/${encodeURIComponent(agentId)}/heartbeat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to send heartbeat',
        });
    }

    /**
     * Deregister an agent
     * @param {string} agentId - Agent ID
     * @returns {Promise<Object>} Deregistration response
     */
    static async deregisterAgent(agentId) {
        return NexusAPI._request(`${API_BASE}/agents/${encodeURIComponent(agentId)}`, {
            method: 'DELETE',
        }, {
            errorMessage: 'Failed to deregister agent',
        });
    }

    // ============ Agent Template API ============

    static async listAgentTemplates(options = {}) {
        const params = new URLSearchParams();
        if (options.source) params.set('source', options.source);
        const query = params.toString();
        return NexusAPI._request(`${API_BASE}/agent-templates${query ? '?' + query : ''}`, {}, {
            errorMessage: 'Failed to fetch agent templates',
        });
    }

    static async getAgentTemplate(name) {
        return NexusAPI._request(`${API_BASE}/agent-templates/${encodeURIComponent(name)}`, {}, {
            errorMessage: 'Failed to fetch agent template',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    static async createAgentTemplate(payload = {}) {
        return NexusAPI._request(`${API_BASE}/agent-templates`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to create agent template',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    static async updateAgentTemplate(name, payload = {}) {
        return NexusAPI._request(`${API_BASE}/agent-templates/${encodeURIComponent(name)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to update agent template',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    static async deleteAgentTemplate(name) {
        return NexusAPI._request(`${API_BASE}/agent-templates/${encodeURIComponent(name)}`, {
            method: 'DELETE',
        }, {
            errorMessage: 'Failed to delete agent template',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    static async resetAgentTemplate(name) {
        return NexusAPI._request(`${API_BASE}/agent-templates/${encodeURIComponent(name)}/reset`, {
            method: 'POST',
        }, {
            errorMessage: 'Failed to reset agent template',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    // ============ Swarm Team API ============

    static async createTeam(payload) {
        return NexusAPI._request(`${API_BASE}/agents/teams`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to create team',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    static async getTeamStatus(teamName) {
        return NexusAPI._request(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}`, {}, {
            errorMessage: 'Failed to get team status',
        });
    }

    static async getTeamConfig(teamName) {
        return NexusAPI._request(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}/config`, {}, {
            errorMessage: 'Failed to get team config',
        });
    }

    static async updateTeamConfig(teamName, payload = {}) {
        return NexusAPI._request(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}/config`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to update team config',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    static async shutdownTeam(teamName, options = {}) {
        return NexusAPI._request(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}/shutdown`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ graceful: options.graceful !== false }),
        }, {
            errorMessage: 'Failed to shutdown team',
        });
    }

    static async getAgentMailbox(teamName, agentId) {
        return NexusAPI._request(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}/mailbox/${encodeURIComponent(agentId)}`, {}, {
            errorMessage: 'Failed to get agent mailbox',
        });
    }

    static async claimTeamTask(teamName, payload = {}) {
        return NexusAPI._request(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}/tasks/claim`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to claim team task',
        });
    }

    static async getActivities(options = {}) {
        const params = new URLSearchParams();
        if (options.entityType) params.set('entity_type', options.entityType);
        if (options.activityType) params.set('activity_type', options.activityType);
        if (options.limit) params.set('limit', options.limit);
        const query = params.toString();
        return NexusAPI._request(`${API_BASE}/activities${query ? '?' + query : ''}`, {}, {
            errorMessage: 'Failed to fetch activities',
        });
    }

    static async getCosts(options = {}) {
        const params = new URLSearchParams();
        if (options.since) params.set('since', options.since);
        const query = params.toString();
        return NexusAPI._request(`${API_BASE}/costs${query ? '?' + query : ''}`, {}, {
            errorMessage: 'Failed to fetch costs',
        });
    }

    // ============ Feature Flags API ============

    static async getFeatures() {
        const response = await fetch(`${API_BASE}/features`);
        if (!response.ok) throw new Error(`Failed to fetch features: ${response.statusText}`);
        return response.json();
    }

    static async getFlag(name) {
        const response = await fetch(`${API_BASE}/features/${encodeURIComponent(name)}`);
        if (!response.ok) throw new Error(`Failed to fetch flag: ${response.statusText}`);
        return response.json();
    }

    static async patchFlag(name, value) {
        const response = await fetch(`${API_BASE}/features/${encodeURIComponent(name)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to patch flag');
        }
        return response.json();
    }

    static async resetFlag(name) {
        const response = await fetch(`${API_BASE}/features/${encodeURIComponent(name)}/reset`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reset flag: ${response.statusText}`);
        return response.json();
    }

    static async reloadFlags() {
        const response = await fetch(`${API_BASE}/features/reload`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reload flags: ${response.statusText}`);
        return response.json();
    }

    // ============ Security / Permission Sync API ============

    static async getPendingPermissions() {
        return NexusAPI._request(`${API_BASE}/security/permissions/pending`, {}, {
            errorMessage: 'Failed to fetch pending permissions',
        });
    }

    static async approvePermission(id) {
        return NexusAPI._request(`${API_BASE}/security/permissions/${encodeURIComponent(id)}/approve`, {
            method: 'POST',
        }, {
            errorMessage: 'Failed to approve permission',
        });
    }

    static async rejectPermission(id) {
        return NexusAPI._request(`${API_BASE}/security/permissions/${encodeURIComponent(id)}/reject`, {
            method: 'POST',
        }, {
            errorMessage: 'Failed to reject permission',
        });
    }

    static async getPermissionCache() {
        return NexusAPI._request(`${API_BASE}/security/permissions/cache`, {}, {
            errorMessage: 'Failed to fetch permission cache',
        });
    }

    static async triggerPermissionSync() {
        return NexusAPI._request(`${API_BASE}/security/permissions/sync`, {
            method: 'POST',
        }, {
            errorMessage: 'Failed to trigger permission sync',
        });
    }

    // ============ Hook Profile API ============

    static async getHookProfile() {
        return NexusAPI._request(`${API_BASE}/security/hook-profile`, {}, {
            errorMessage: 'Failed to fetch hook profile',
        });
    }

    static async updateHookProfile(profile) {
        return NexusAPI._request(`${API_BASE}/security/hook-profile`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(profile),
        }, {
            errorMessage: 'Failed to update hook profile',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    // ============ Permissions Mode API ============

    static async getPermissions() {
        return NexusAPI._request(`${API_BASE}/permissions`, {}, {
            errorMessage: 'Failed to fetch permissions',
        });
    }

    static async setPermissionMode(mode) {
        return NexusAPI._request(`${API_BASE}/permissions/mode`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode }),
        }, {
            errorMessage: 'Failed to set permission mode',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    static async clearPermissionCache() {
        return NexusAPI._request(`${API_BASE}/permissions/cache/clear`, {
            method: 'POST',
        }, {
            errorMessage: 'Failed to clear permission cache',
        });
    }

    // ============ Teleport REST API ============

    static async connectTeleport(payload = {}) {
        const response = await fetch(`${API_BASE}/teleport/connect`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to connect teleport');
        }
        return response.json();
    }

    static async disconnectTeleport() {
        const response = await fetch(`${API_BASE}/teleport/disconnect`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to disconnect teleport: ${response.statusText}`);
        return response.json();
    }

    static async listTeleportSessions() {
        const response = await fetch(`${API_BASE}/teleport/sessions`);
        if (!response.ok) throw new Error(`Failed to list teleport sessions: ${response.statusText}`);
        return response.json();
    }

    static async getTeleportSession(sessionId) {
        const response = await fetch(`${API_BASE}/teleport/sessions/${encodeURIComponent(sessionId)}`);
        if (!response.ok) throw new Error(`Failed to get teleport session: ${response.statusText}`);
        return response.json();
    }

    static async executeTeleport(payload) {
        const response = await fetch(`${API_BASE}/teleport/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to execute teleport command');
        }
        return response.json();
    }

    static async syncTeleport() {
        const response = await fetch(`${API_BASE}/teleport/sync`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to sync teleport: ${response.statusText}`);
        return response.json();
    }

    static streamTeleportOutput(sessionId) {
        return `${API_BASE}/teleport/sessions/${encodeURIComponent(sessionId)}/output`;
    }

    // ============ Session Recovery API ============

    static async getInterruptedTurns(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/interrupted`);
        if (!response.ok) throw new Error(`Failed to fetch interrupted turns: ${response.statusText}`);
        return response.json();
    }

    static async getMessageChain(sessionId, messageId) {
        const response = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/chain/${encodeURIComponent(messageId)}`);
        if (!response.ok) throw new Error(`Failed to fetch message chain: ${response.statusText}`);
        return response.json();
    }

    static async recoverInterruptedTurn(sessionId, messageId) {
        const response = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/recover/${encodeURIComponent(messageId)}`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to recover interrupted turn: ${response.statusText}`);
        return response.json();
    }

    static async findOrphanToolResults(sessionId) {
        const response = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/orphans`);
        if (!response.ok) throw new Error(`Failed to find orphan tool results: ${response.statusText}`);
        return response.json();
    }

    // ============ Doctor / Diagnostic API ============

    static async getDoctor() {
        return NexusAPI._request(`${API_BASE}/doctor`, {}, {
            errorMessage: 'Failed to run doctor',
        });
    }

    static async getDoctorBundle() {
        return NexusAPI._request(`${API_BASE}/doctor/bundle`, {}, {
            errorMessage: 'Failed to get doctor bundle',
        });
    }

    // ============ Task Continue / Outcome API ============

    static async continueTask(taskId, message, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const body = { message: message || '' };
        if (options.model) body.model = options.model;
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/continue?${params}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to continue task: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async updateTaskOutcome(taskId, data, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const payload = typeof data === 'string' ? { outcome: data } : { outcome: data.outcome, resolution: data.resolution, feedback_rating: data.feedback_rating, feedback_notes: data.feedback_notes };
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/outcome?${params}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to update task outcome: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async getTaskOutcomes(options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const response = await fetch(`${API_BASE}/tasks/outcomes?${params}`);
        if (!response.ok) throw new Error(`Failed to fetch task outcomes: ${response.statusText}`);
        return response.json();
    }

    // ============ Memory State API ============

    static async getMemoryState() {
        return NexusAPI._request(`${API_BASE}/history/memory/state`, {}, {
            errorMessage: 'Failed to fetch memory state',
        });
    }

    static async restoreMemoryContext(sessionId, options = {}) {
        return NexusAPI._request(`${API_BASE}/history/sessions/${encodeURIComponent(sessionId)}/restore-memory`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options),
        }, {
            errorMessage: 'Failed to restore memory context',
        });
    }

    // ============ Mission API ============

    static async listMissions(options = {}) {
        const params = new URLSearchParams();
        if (options.status) params.append('status', options.status);
        const qs = params.toString();
        const response = await fetch(`${API_BASE}/missions${qs ? '?' + qs : ''}`);
        if (!response.ok) throw new Error(`Failed to list missions: ${response.statusText}`);
        return response.json();
    }

    static async createMission(payload) {
        const response = await fetch(`${API_BASE}/missions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to create mission');
        }
        return response.json();
    }

    static async getMission(missionId) {
        const response = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}`);
        if (!response.ok) throw new Error(`Failed to get mission: ${response.statusText}`);
        return response.json();
    }

    static async approveMission(missionId) {
        const response = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/approve`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to approve mission: ${response.statusText}`);
        return response.json();
    }

    static async cancelMission(missionId) {
        const response = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/cancel`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to cancel mission: ${response.statusText}`);
        return response.json();
    }

    static async pauseMission(missionId) {
        const response = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/pause`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to pause mission: ${response.statusText}`);
        return response.json();
    }

    static async resumeMission(missionId) {
        const response = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/resume`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to resume mission: ${response.statusText}`);
        return response.json();
    }

    static async getMissionLog(missionId) {
        const response = await fetch(`${API_BASE}/missions/${encodeURIComponent(missionId)}/log`);
        if (!response.ok) throw new Error(`Failed to get mission log: ${response.statusText}`);
        return response.json();
    }

    // ============ Runs / Evals API ============

    static async listRuns(options = {}) {
        const params = new URLSearchParams();
        if (options.status) params.append('status', options.status);
        const qs = params.toString();
        const response = await fetch(`${API_BASE}/runs${qs ? '?' + qs : ''}`);
        if (!response.ok) throw new Error(`Failed to list runs: ${response.statusText}`);
        return response.json();
    }

    static async createRun(payload) {
        const response = await fetch(`${API_BASE}/runs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to create run');
        }
        return response.json();
    }

    static async getRun(runId) {
        const response = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}`);
        if (!response.ok) throw new Error(`Failed to get run: ${response.statusText}`);
        return response.json();
    }

    static async getRunProvenance(runId) {
        const response = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/provenance`);
        if (!response.ok) throw new Error(`Failed to get run provenance: ${response.statusText}`);
        return response.json();
    }

    static async updateRun(runId, data) {
        const response = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to update run');
        }
        return response.json();
    }

    static async evalRun(runId, payload = {}) {
        const response = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/eval`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to eval run');
        }
        return response.json();
    }

    static async getEvalsLeaderboard() {
        const response = await fetch(`${API_BASE}/evals/leaderboard`);
        if (!response.ok) throw new Error(`Failed to fetch evals leaderboard: ${response.statusText}`);
        return response.json();
    }

    // ============ Evolution API ============

    static async triggerEvolution(payload = {}) {
        return NexusAPI._request(`${API_BASE}/evolution/trigger`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to trigger evolution',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    static async evolutionSynthesis(payload = {}) {
        return NexusAPI._request(`${API_BASE}/evolution/synthesis`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }, {
            errorMessage: 'Failed to run evolution synthesis',
            preferErrorDetail: true,
            includeStatusText: false,
        });
    }

    static async getEvolutionStatus() {
        return NexusAPI._request(`${API_BASE}/evolution/status`, {}, {
            errorMessage: 'Failed to fetch evolution status',
        });
    }

    static async getEvolutionMemory() {
        return NexusAPI._request(`${API_BASE}/evolution/memory`, {}, {
            errorMessage: 'Failed to fetch evolution memory',
        });
    }

    // ============ Admin / Ops APIs (Newly Added) ============

    /**
     * Get system diagnostics data
     * @returns {Promise<Object>} Diagnostics response
     */
    static async getDiagnostics() {
        return NexusAPI._request(`${API_BASE}/diagnostics`, {}, {
            errorMessage: 'Failed to fetch diagnostics',
        });
    }

    /**
     * Get security scan results
     * @returns {Promise<Object>} Security scan response
     */
    static async getSecurityScan() {
        return NexusAPI._request(`${API_BASE}/security-scan`, {}, {
            errorMessage: 'Failed to fetch security scan',
        });
    }

    /**
     * Get system monitor data
     * @returns {Promise<Object>} System monitor response
     */
    static async getSystemMonitor() {
        return NexusAPI._request(`${API_BASE}/system-monitor`, {}, {
            errorMessage: 'Failed to fetch system monitor',
        });
    }

    /**
     * Get workload statistics
     * @returns {Promise<Object>} Workload response
     */
    static async getWorkload() {
        return NexusAPI._request(`${API_BASE}/workload`, {}, {
            errorMessage: 'Failed to fetch workload',
        });
    }

    /**
     * Get standup report
     * @returns {Promise<Object>} Standup response
     */
    static async getStandup() {
        return NexusAPI._request(`${API_BASE}/standup`, {}, {
            errorMessage: 'Failed to fetch standup',
        });
    }

    /**
     * Get audit log with filtering
     * @param {Object} params - Filter parameters {action, task_id, limit}
     * @returns {Promise<Object>} Audit log response
     */
    static async getAuditLog(params = {}) {
        const qs = new URLSearchParams();
        if (params.action) qs.set('action', params.action);
        if (params.task_id) qs.set('task_id', params.task_id);
        if (params.limit) qs.set('limit', params.limit);
        const query = qs.toString();
        return NexusAPI._request(`${API_BASE}/audit${query ? '?' + query : ''}`, {}, {
            errorMessage: 'Failed to fetch audit log',
        });
    }

    /**
     * Perform global search
     * @param {string} q - Search query
     * @param {string} type - Search type (all/task/session)
     * @returns {Promise<Object>} Search results
     */
    static async globalSearch(q, type) {
        const params = new URLSearchParams({ q });
        if (type && type !== 'all') params.set('type', type);
        return NexusAPI._request(`${API_BASE}/search?${params}`, {}, {
            errorMessage: 'Failed to search',
        });
    }

    /**
     * Get cleanup preview data
     * @returns {Promise<Object>} Cleanup preview response
     */
    static async getCleanupPreview() {
        return NexusAPI._request(`${API_BASE}/cleanup`, {}, {
            errorMessage: 'Failed to fetch cleanup preview',
        });
    }

    /**
     * Execute cleanup operation
     * @param {boolean} dryRun - Whether to perform dry run
     * @returns {Promise<Object>} Cleanup execution response
     */
    static async executeCleanup(dryRun = true) {
        const params = new URLSearchParams({ dry_run: dryRun });
        return NexusAPI._request(`${API_BASE}/cleanup?${params}`, { method: 'POST' }, {
            errorMessage: 'Failed to execute cleanup',
        });
    }

    /**
     * Parse schedule input
     * @param {string} input - Schedule input string
     * @returns {Promise<Object>} Schedule parse response
     */
    static async parseSchedule(input) {
        const params = new URLSearchParams({ input });
        return NexusAPI._request(`${API_BASE}/schedule-parse?${params}`, {}, {
            errorMessage: 'Failed to parse schedule',
        });
    }

    /**
     * Export data in specified format
     * @param {string} type - Data type to export
     * @param {string} format - Export format (JSON/CSV)
     * @returns {Promise<Object|string>} Export data
     */
    static async exportData(type, format) {
        const params = new URLSearchParams({ type });
        if (format) params.set('format', format);
        const response = await NexusAPI._request(`${API_BASE}/export?${params}`, {}, {
            errorMessage: 'Failed to export data',
            responseType: 'raw',
        });
        const ct = response.headers.get('content-type') || '';
        if (ct.includes('text/csv') || (format && format.toLowerCase() === 'csv')) {
            return response.text();
        }
        return response.json();
    }
}

// Export for use in other scripts
window.NexusAPI = NexusAPI;

// Load opt-in shell extensions that are not yet statically referenced by index.html.
// We keep this synchronous so dependent deferred scripts can assume the globals exist.
(function bootstrapDeferredNexusComponents() {
    if (typeof window === 'undefined' || typeof XMLHttpRequest === 'undefined') return;
    const needsAgentsShell = !window.NexusAgentsStore || !window.NexusAgentsViewShell;
    if (!needsAgentsShell) return;

    const sources = [];
    if (!window.NexusAgentsStore) {
        sources.push('js/components/agents-store.js');
    }
    if (!window.NexusAgentsViewShell) {
        sources.push('js/components/agents-view-shell.js');
    }

    for (const src of sources) {
        try {
            const xhr = new XMLHttpRequest();
            xhr.open('GET', src, false);
            xhr.send(null);
            if (xhr.status >= 200 && xhr.status < 400 && xhr.responseText) {
                (0, eval)(`${xhr.responseText}\n//# sourceURL=${src}`);
            } else {
                console.warn('[NexusAPI] Failed to bootstrap component:', src, xhr.status);
            }
        } catch (error) {
            console.warn('[NexusAPI] Failed to load deferred component:', src, error);
        }
    }
})();
