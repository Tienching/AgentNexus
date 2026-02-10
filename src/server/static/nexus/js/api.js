/**
 * NexusHub API Client
 */

const API_BASE = '/api/nexus';

class NexusAPI {
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
        const response = await fetch(`${API_BASE}/sessions/${sessionId}`);
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
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/messages`);
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
        const response = await fetch(`${API_BASE}/sessions/${sessionId}`, {
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
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/cancel`, {
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
            exec_user: options.execUser || 'ubuntu',
        });
        const response = await fetch(`${API_BASE}/projects?${params}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch projects: ${response.statusText}`);
        }
        return response.json();
    }

    // ============ Tasks API ============

    static async getTasks(options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
            tail: options.tail || 200,
        });

        if (options.pollIntervalMs) params.append('poll_interval_ms', options.pollIntervalMs);

        const url = `${API_BASE}/tasks/${encodeURIComponent(taskId)}/agui/stream?${params}`;
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

    /**
     * List files in a session's folder
     * @param {string} sessionId - Session ID
     * @param {Object} options - Query options
     * @returns {Promise<Object>} Session files response
     */
    static async getSessionFiles(sessionId, options = {}) {
        const params = new URLSearchParams({
            exec_user: options.execUser || 'ubuntu',
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
            exec_user: options.execUser || 'ubuntu',
            file_path: filePath,
        });
        return `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/files/download?${params}`;
    }
}

// Export for use in other scripts
window.NexusAPI = NexusAPI;
