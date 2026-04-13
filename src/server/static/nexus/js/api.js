/**
 * NexusHub API Client
 */

const API_BASE = '/api/nexus';

/**
 * Default exec_user, loaded from server defaults.
 * Updated by NexusApp after loading server defaults.
 */
let _defaultExecUser = 'ubuntu';

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

    /**
     * Check authentication status
     * @returns {Promise<Object>} Auth status response
     */
    static async getAuthStatus() {
        const response = await fetch(`${API_BASE}/auth/status`);
        if (!response.ok) {
            throw new Error(`Failed to fetch auth status: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Login to Nexus
     * @param {string} password - Login password
     * @returns {Promise<Object>} Login response
     */
    static async login(password) {
        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password }),
        });
        if (!response.ok) {
            if (response.status === 401) {
                throw new Error('Invalid password');
            }
            throw new Error(`Login failed: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Logout from Nexus
     * @returns {Promise<Object>} Logout response
     */
    static async logout() {
        const response = await fetch(`${API_BASE}/auth/logout`, {
            method: 'POST',
        });
        if (!response.ok) {
            throw new Error(`Logout failed: ${response.statusText}`);
        }
        return response.json();
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
        
        const response = await fetch(`${API_BASE}/sessions?${params}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch sessions: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Get session detail
     * @param {string} sessionId - Session ID
     * @returns {Promise<Object>} Session detail
     */
    static async getSession(sessionId) {
        const sid = encodeURIComponent(sessionId || '');
        const response = await fetch(`${API_BASE}/sessions/${sid}`);
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('Session not found');
            }
            throw new Error(`Failed to fetch session: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Get session messages
     * @param {string} sessionId - Session ID
     * @returns {Promise<Object>} Messages response
     */
    static async getSessionMessages(sessionId) {
        const sid = encodeURIComponent(sessionId || '');
        const response = await fetch(`${API_BASE}/sessions/${sid}/messages`);
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('Session not found');
            }
            throw new Error(`Failed to fetch messages: ${response.statusText}`);
        }
        return response.json();
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
        const response = await fetch(`${API_BASE}/sessions/${sid}`, {
            method: 'DELETE',
        });
        if (!response.ok) {
            throw new Error(`Failed to delete session: ${response.statusText}`);
        }
        return response.json();
    }

    static async bulkDeleteSessions(sessionIds = []) {
        const response = await fetch(`${API_BASE}/sessions/bulk_delete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_ids: sessionIds }),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to bulk delete sessions: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async deleteAllSessions({ username, search, status } = {}) {
        const params = new URLSearchParams();
        if (username) params.set('username', username);
        if (search) params.set('search', search);
        if (status) params.set('status', status);
        const qs = params.toString();
        const url = `${API_BASE}/sessions/delete_all${qs ? '?' + qs : ''}`;
        const response = await fetch(url, { method: 'POST' });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to delete all sessions: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    /**
     * Create new session
     * @param {Object} payload - Session data
     * @returns {Promise<Object>} Created session
     */
    static async createSession(payload = {}) {
        const response = await fetch(`${API_BASE}/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to create session: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    /**
     * Cancel running session
     * @param {string} sessionId - Session ID
     * @returns {Promise<Object>} Cancel response
     */
    static async cancelSession(sessionId) {
        const sid = encodeURIComponent(sessionId || '');
        const response = await fetch(`${API_BASE}/sessions/${sid}/cancel`, {
            method: 'POST',
        });
        if (!response.ok) {
            throw new Error(`Failed to cancel session: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Get all usernames
     * @returns {Promise<Object>} Usernames response
     */
    static async getUsernames() {
        const response = await fetch(`${API_BASE}/usernames`);
        if (!response.ok) {
            throw new Error(`Failed to fetch usernames: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Get available agents
     * @returns {Promise<Object>} Agents response
     */
    static async getAgents() {
        const response = await fetch(`${API_BASE}/agents`);
        if (!response.ok) {
            throw new Error(`Failed to fetch agents: ${response.statusText}`);
        }
        return response.json();
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
        const response = await fetch(`${API_BASE}/projects?${params}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch projects: ${response.statusText}`);
        }
        return response.json();
    }

    // ============ Server Defaults API ============

    /**
     * Get server-side default configuration from .env
     * @returns {Promise<Object>} Server defaults (exec_user, default_provider, default_model, etc.)
     */
    static async getDefaults() {
        const response = await fetch(`${API_BASE}/defaults`);
        if (!response.ok) {
            throw new Error(`Failed to fetch server defaults: ${response.statusText}`);
        }
        return response.json();
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
        const response = await fetch(`${API_BASE}/skills?${params}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch skills: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Create a new skill
     * @param {Object} payload - { provider, skill_name, description, content, skills_path? }
     * @returns {Promise<Object>} Success response
     */
    static async createSkill(payload) {
        const response = await fetch(`${API_BASE}/skills`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to create skill: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
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
        const response = await fetch(
            `${API_BASE}/skills/${encodeURIComponent(provider)}/${encodeURIComponent(skillName)}?${params}`,
            { method: 'DELETE' }
        );
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to delete skill: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
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
     * Get available project paths from local CLI history files
     * @param {Object} options - Query options
     * @returns {Promise<Array>} List of project entries
     */
    static async getHistoryProjects(options = {}) {
        const execUser = Object.prototype.hasOwnProperty.call(options, 'execUser')
            ? (options.execUser ?? '')
            : _defaultExecUser;
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
     * Get history sessions from local CLI files
     * @param {Object} options - Query options (projectPath required)
     * @returns {Promise<Object>} Session list response
     */
    static async getHistorySessions(options = {}) {
        const execUser = Object.prototype.hasOwnProperty.call(options, 'execUser')
            ? (options.execUser ?? '')
            : _defaultExecUser;
        const params = new URLSearchParams({
            project_path: options.projectPath || '',
            page: options.page || 1,
            page_size: options.pageSize || 50,
            exec_user: execUser,
        });
        if (options.provider) params.append('provider', options.provider);
        if (options.search) params.append('search', options.search);
        if (options.customPaths) params.append('custom_paths', JSON.stringify(options.customPaths));

        const response = await fetch(`${API_BASE}/history/sessions?${params}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch history sessions: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Get messages for a specific history session
     * @param {string} provider - Provider name (claude/codex/codebuddy/gemini)
     * @param {string} sessionId - Session ID
     * @param {Object} options - { execUser?, configPath? }
     * @returns {Promise<Object>} Messages response
     */
    static async getHistoryMessages(provider, sessionId, options = {}) {
        const execUser = Object.prototype.hasOwnProperty.call(options, 'execUser')
            ? (options.execUser ?? '')
            : _defaultExecUser;
        const params = new URLSearchParams({
            exec_user: execUser,
        });
        if (options.configPath) params.append('config_path', options.configPath);

        const response = await fetch(
            `${API_BASE}/history/sessions/${encodeURIComponent(provider)}/${encodeURIComponent(sessionId)}/messages?${params}`
        );
        if (!response.ok) {
            if (response.status === 404) {
                throw new Error('History session not found');
            }
            throw new Error(`Failed to fetch history messages: ${response.statusText}`);
        }
        return response.json();
    }

    /**
     * Promote a history session into runtime session for continued chat
     * @param {string} provider - Provider or alias name
     * @param {string} sessionId - History session ID
     * @param {Object} options - { projectPath, execUser?, mode? ('full'|'windowed') }
     * @returns {Promise<Object>} { runtime_session_id, created }
     */
    static async promoteHistorySession(provider, sessionId, options = {}) {
        const response = await fetch(
            `${API_BASE}/history/sessions/${encodeURIComponent(provider)}/${encodeURIComponent(sessionId)}/promote`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_path: options.projectPath || '',
                    exec_user: options.execUser || _defaultExecUser,
                    mode: options.mode || 'full',
                }),
            }
        );

        if (!response.ok) {
            const text = await response.text().catch(() => '');
            const err = new Error(`Failed to promote history session: ${response.status} ${response.statusText}${text ? ` - ${text}` : ''}`);
            err.status = response.status;
            throw err;
        }
        return response.json();
    }

    /**
     * Fetch/refresh CLI file data into an existing Runtime session
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
                    exec_user: options.execUser || _defaultExecUser,
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
     * Detect installed agent runtimes (claude, codex, gemini, codebuddy, nanobot)
     * @param {string} [runtimeId] - Optional: detect a specific runtime only
     * @returns {Promise<Object>} Runtimes detection result
     */
    static async getAgentRuntimes(runtimeId) {
        const params = new URLSearchParams();
        if (runtimeId) params.set('runtime_id', runtimeId);
        const query = params.toString();
        const response = await fetch(`${API_BASE}/agent-runtimes${query ? '?' + query : ''}`);
        if (!response.ok) throw new Error(`Failed to detect runtimes: ${response.statusText}`);
        return response.json();
    }

    // ============ Admin / Ops APIs ============

    static async getDiagnostics() {
        const response = await fetch(`${API_BASE}/diagnostics`);
        if (!response.ok) throw new Error(`Failed to fetch diagnostics: ${response.statusText}`);
        return response.json();
    }

    static async getSecurityScan() {
        const response = await fetch(`${API_BASE}/security-scan`);
        if (!response.ok) throw new Error(`Failed to fetch security scan: ${response.statusText}`);
        return response.json();
    }

    static async getSystemMonitor() {
        const response = await fetch(`${API_BASE}/system-monitor`);
        if (!response.ok) throw new Error(`Failed to fetch system monitor: ${response.statusText}`);
        return response.json();
    }

    static async getWorkload() {
        const response = await fetch(`${API_BASE}/workload`);
        if (!response.ok) throw new Error(`Failed to fetch workload: ${response.statusText}`);
        return response.json();
    }

    static async getStandup() {
        const response = await fetch(`${API_BASE}/standup`);
        if (!response.ok) throw new Error(`Failed to fetch standup: ${response.statusText}`);
        return response.json();
    }

    static async getAuditLog(params = {}) {
        const qs = new URLSearchParams();
        if (params.action) qs.set('action', params.action);
        if (params.task_id) qs.set('task_id', params.task_id);
        if (params.limit) qs.set('limit', params.limit);
        const query = qs.toString();
        const response = await fetch(`${API_BASE}/audit${query ? '?' + query : ''}`);
        if (!response.ok) throw new Error(`Failed to fetch audit log: ${response.statusText}`);
        return response.json();
    }

    static async globalSearch(q, type) {
        const params = new URLSearchParams({ q });
        if (type && type !== 'all') params.set('type', type);
        const response = await fetch(`${API_BASE}/search?${params}`);
        if (!response.ok) throw new Error(`Failed to search: ${response.statusText}`);
        return response.json();
    }

    static async getCleanupPreview() {
        const response = await fetch(`${API_BASE}/cleanup`);
        if (!response.ok) throw new Error(`Failed to fetch cleanup preview: ${response.statusText}`);
        return response.json();
    }

    static async executeCleanup(dryRun = true) {
        const params = new URLSearchParams({ dry_run: dryRun });
        const response = await fetch(`${API_BASE}/cleanup?${params}`, { method: 'POST' });
        if (!response.ok) throw new Error(`Failed to execute cleanup: ${response.statusText}`);
        return response.json();
    }

    static async parseSchedule(input) {
        const params = new URLSearchParams({ input });
        const response = await fetch(`${API_BASE}/schedule-parse?${params}`);
        if (!response.ok) throw new Error(`Failed to parse schedule: ${response.statusText}`);
        return response.json();
    }

    static async exportData(type, format) {
        const params = new URLSearchParams({ type });
        if (format) params.set('format', format);
        const response = await fetch(`${API_BASE}/export?${params}`);
        if (!response.ok) throw new Error(`Failed to export data: ${response.statusText}`);
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
        const response = await fetch(`${API_BASE}/commands`);
        if (!response.ok) {
            throw new Error(`Failed to fetch slash commands: ${response.statusText}`);
        }
        return response.json();
    }

    // ============ Plan Mode API ============

    /**
     * Enter plan mode (read-only exploration)
     * @returns {Promise<Object>} Plan action response
     */
    static async enterPlanMode() {
        const response = await fetch(`${API_BASE}/plan/enter`, { method: 'POST' });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to enter plan mode');
        }
        return response.json();
    }

    /**
     * Submit a plan for approval
     * @param {string} content - The plan content
     * @returns {Promise<Object>} Plan action response
     */
    static async submitPlan(content) {
        const response = await fetch(`${API_BASE}/plan/submit`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to submit plan');
        }
        return response.json();
    }

    /**
     * Approve the current plan
     * @returns {Promise<Object>} Plan action response
     */
    static async approvePlan() {
        const response = await fetch(`${API_BASE}/plan/approve`, { method: 'POST' });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to approve plan');
        }
        return response.json();
    }

    /**
     * Reject the current plan
     * @returns {Promise<Object>} Plan action response
     */
    static async rejectPlan() {
        const response = await fetch(`${API_BASE}/plan/reject`, { method: 'POST' });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to reject plan');
        }
        return response.json();
    }

    /**
     * Get current plan mode status
     * @returns {Promise<Object>} Plan status response
     */
    static async getPlanStatus() {
        const response = await fetch(`${API_BASE}/plan/status`);
        if (!response.ok) throw new Error('Failed to get plan status');
        return response.json();
    }

    /**
     * Exit plan mode
     * @returns {Promise<Object>} Plan action response
     */
    static async exitPlanMode() {
        const response = await fetch(`${API_BASE}/plan/exit`, { method: 'POST' });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to exit plan mode');
        }
        return response.json();
    }

    // ============ Agent Lifecycle API ============

    /**
     * Get agent statistics
     * @returns {Promise<Object>} Agent stats response
     */
    static async getAgentStats() {
        const response = await fetch(`${API_BASE}/agents/stats`);
        if (!response.ok) throw new Error(`Failed to fetch agent stats: ${response.statusText}`);
        return response.json();
    }

    /**
     * Register a new agent
     * @param {Object} payload - Agent registration data
     * @returns {Promise<Object>} Registration response
     */
    static async registerAgent(payload) {
        const response = await fetch(`${API_BASE}/agents/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to register agent');
        }
        return response.json();
    }

    /**
     * Send agent heartbeat
     * @param {string} agentId - Agent ID
     * @param {Object} payload - Heartbeat data
     * @returns {Promise<Object>} Heartbeat response
     */
    static async agentHeartbeat(agentId, payload = {}) {
        const response = await fetch(`${API_BASE}/agents/${encodeURIComponent(agentId)}/heartbeat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error(`Failed to send heartbeat: ${response.statusText}`);
        return response.json();
    }

    /**
     * Deregister an agent
     * @param {string} agentId - Agent ID
     * @returns {Promise<Object>} Deregistration response
     */
    static async deregisterAgent(agentId) {
        const response = await fetch(`${API_BASE}/agents/${encodeURIComponent(agentId)}`, {
            method: 'DELETE',
        });
        if (!response.ok) throw new Error(`Failed to deregister agent: ${response.statusText}`);
        return response.json();
    }

    // ============ Swarm Team API ============

    static async createTeam(payload) {
        const response = await fetch(`${API_BASE}/agents/teams`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to create team');
        }
        return response.json();
    }

    static async getTeamStatus(teamName) {
        const response = await fetch(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}`);
        if (!response.ok) throw new Error(`Failed to get team status: ${response.statusText}`);
        return response.json();
    }

    static async shutdownTeam(teamName) {
        const response = await fetch(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}/shutdown`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to shutdown team: ${response.statusText}`);
        return response.json();
    }

    static async getAgentMailbox(teamName, agentId) {
        const response = await fetch(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}/mailbox/${encodeURIComponent(agentId)}`);
        if (!response.ok) throw new Error(`Failed to get agent mailbox: ${response.statusText}`);
        return response.json();
    }

    static async claimTeamTask(teamName, payload = {}) {
        const response = await fetch(`${API_BASE}/agents/teams/${encodeURIComponent(teamName)}/tasks/claim`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error(`Failed to claim team task: ${response.statusText}`);
        return response.json();
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
        const response = await fetch(`${API_BASE}/security/permissions/pending`);
        if (!response.ok) throw new Error(`Failed to fetch pending permissions: ${response.statusText}`);
        return response.json();
    }

    static async approvePermission(id) {
        const response = await fetch(`${API_BASE}/security/permissions/${encodeURIComponent(id)}/approve`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to approve permission: ${response.statusText}`);
        return response.json();
    }

    static async rejectPermission(id) {
        const response = await fetch(`${API_BASE}/security/permissions/${encodeURIComponent(id)}/reject`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to reject permission: ${response.statusText}`);
        return response.json();
    }

    static async getPermissionCache() {
        const response = await fetch(`${API_BASE}/security/permissions/cache`);
        if (!response.ok) throw new Error(`Failed to fetch permission cache: ${response.statusText}`);
        return response.json();
    }

    static async triggerPermissionSync() {
        const response = await fetch(`${API_BASE}/security/permissions/sync`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to trigger permission sync: ${response.statusText}`);
        return response.json();
    }

    // ============ Hook Profile API ============

    static async getHookProfile() {
        const response = await fetch(`${API_BASE}/security/hook-profile`);
        if (!response.ok) throw new Error(`Failed to fetch hook profile: ${response.statusText}`);
        return response.json();
    }

    static async updateHookProfile(profile) {
        const response = await fetch(`${API_BASE}/security/hook-profile`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(profile),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to update hook profile');
        }
        return response.json();
    }

    // ============ Permissions Mode API ============

    static async getPermissions() {
        const response = await fetch(`${API_BASE}/permissions`);
        if (!response.ok) throw new Error(`Failed to fetch permissions: ${response.statusText}`);
        return response.json();
    }

    static async setPermissionMode(mode) {
        const response = await fetch(`${API_BASE}/permissions/mode`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to set permission mode');
        }
        return response.json();
    }

    static async clearPermissionCache() {
        const response = await fetch(`${API_BASE}/permissions/cache/clear`, {
            method: 'POST',
        });
        if (!response.ok) throw new Error(`Failed to clear permission cache: ${response.statusText}`);
        return response.json();
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
        const response = await fetch(`${API_BASE}/doctor`);
        if (!response.ok) throw new Error(`Failed to run doctor: ${response.statusText}`);
        return response.json();
    }

    static async getDoctorBundle() {
        const response = await fetch(`${API_BASE}/doctor/bundle`);
        if (!response.ok) throw new Error(`Failed to get doctor bundle: ${response.statusText}`);
        return response.json();
    }

    // ============ Task Continue / Outcome API ============

    static async continueTask(taskId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/continue?${params}`, {
            method: 'POST',
        });
        if (!response.ok) {
            const text = await response.text().catch(() => '');
            throw new Error(`Failed to continue task: ${response.statusText}${text ? ` - ${text}` : ''}`);
        }
        return response.json();
    }

    static async updateTaskOutcome(taskId, outcome, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || _defaultExecUser,
        });
        const response = await fetch(`${API_BASE}/tasks/${encodeURIComponent(taskId)}/outcome?${params}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ outcome }),
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
        const response = await fetch(`${API_BASE}/history/memory/state`);
        if (!response.ok) throw new Error(`Failed to fetch memory state: ${response.statusText}`);
        return response.json();
    }

    static async restoreMemoryContext(sessionId, options = {}) {
        const response = await fetch(`${API_BASE}/history/sessions/${encodeURIComponent(sessionId)}/restore-memory`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options),
        });
        if (!response.ok) throw new Error(`Failed to restore memory context: ${response.statusText}`);
        return response.json();
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
        const response = await fetch(`${API_BASE}/evolution/trigger`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to trigger evolution');
        }
        return response.json();
    }

    static async evolutionSynthesis(payload = {}) {
        const response = await fetch(`${API_BASE}/evolution/synthesis`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Failed to run evolution synthesis');
        }
        return response.json();
    }

    static async getEvolutionStatus() {
        const response = await fetch(`${API_BASE}/evolution/status`);
        if (!response.ok) throw new Error(`Failed to fetch evolution status: ${response.statusText}`);
        return response.json();
    }

    static async getEvolutionMemory() {
        const response = await fetch(`${API_BASE}/evolution/memory`);
        if (!response.ok) throw new Error(`Failed to fetch evolution memory: ${response.statusText}`);
        return response.json();
    }
}

// Export for use in other scripts
window.NexusAPI = NexusAPI;
