/**
 * NexusHub API Client
 */

const API_BASE = '/api/nexus';

class NexusAPI {
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
}

// Export for use in other scripts
window.NexusAPI = NexusAPI;
