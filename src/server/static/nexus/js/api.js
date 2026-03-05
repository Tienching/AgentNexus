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
    static async chatStream(execUser, payload) {
        const response = await fetch(`/chat/stream/${execUser}`, {
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
}

// Export for use in other scripts
window.NexusAPI = NexusAPI;
