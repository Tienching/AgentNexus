/**
 * AgentAvatar Component
 * Deterministic colored-circle avatar with initials and optional status indicator
 *
 * CSS to add to styles.css:
 *
 * ========== Agent Avatar ==========
 * .agent-avatar {
 *     display: inline-flex;
 *     align-items: center;
 *     justify-content: center;
 *     border-radius: var(--radius-full);
 *     position: relative;
 *     flex-shrink: 0;
 *     user-select: none;
 * }
 *
 * .agent-avatar-initials {
 *     color: white;
 *     font-weight: 700;
 *     letter-spacing: -0.02em;
 *     line-height: 1;
 *     text-transform: uppercase;
 * }
 *
 * Size variants
 * .agent-avatar-xs {
 *     width: 20px;
 *     height: 20px;
 * }
 * .agent-avatar-xs .agent-avatar-initials {
 *     font-size: 8px;
 * }
 *
 * .agent-avatar-sm {
 *     width: 24px;
 *     height: 24px;
 * }
 * .agent-avatar-sm .agent-avatar-initials {
 *     font-size: 9px;
 * }
 *
 * .agent-avatar-md {
 *     width: 28px;
 *     height: 28px;
 * }
 * .agent-avatar-md .agent-avatar-initials {
 *     font-size: 10px;
 * }
 *
 * .agent-avatar-lg {
 *     width: 36px;
 *     height: 36px;
 * }
 * .agent-avatar-lg .agent-avatar-initials {
 *     font-size: 13px;
 * }
 *
 * Status indicator
 * .agent-avatar-status {
 *     position: absolute;
 *     bottom: 0;
 *     right: 0;
 *     width: 7px;
 *     height: 7px;
 *     border-radius: var(--radius-full);
 *     border: 1.5px solid var(--bg-primary);
 * }
 *
 * .agent-avatar-xs .agent-avatar-status {
 *     width: 6px;
 *     height: 6px;
 *     border-width: 1px;
 * }
 *
 * .agent-avatar-status-online {
 *     background: var(--success);
 * }
 *
 * .agent-avatar-status-busy {
 *     background: var(--warning);
 * }
 *
 * .agent-avatar-status-offline {
 *     background: var(--text-disabled);
 * }
 */

class AgentAvatar {
    /** @type {string[]} Color palette for deterministic avatar backgrounds */
    static COLORS = [
        '#3b82f6', // blue-500
        '#8b5cf6', // violet-500
        '#ec4899', // pink-500
        '#f97316', // orange-500
        '#eab308', // yellow-500
        '#22c55e', // green-500
        '#06b6d4', // cyan-500
        '#6366f1', // indigo-500
        '#14b8a6', // teal-500
        '#f43f5e', // rose-500
    ];

    /** @type {Object<string, number>} Size variant pixel values */
    static SIZES = {
        xs: 20,
        sm: 24,
        md: 28,
        lg: 36,
    };

    /** @type {string[]} Valid status values */
    static STATUSES = ['online', 'busy', 'offline', 'none'];

    /**
     * Deterministic hash of a string to a palette index.
     * Uses simple DJB2 hash — fast and sufficient for color assignment.
     * @param {string} name - Agent name to hash
     * @returns {number} Index into COLORS array
     */
    static _hash(name) {
        let hash = 5381;
        for (let i = 0; i < name.length; i++) {
            hash = ((hash << 5) + hash) + name.charCodeAt(i);
            hash = hash & hash; // Convert to 32-bit integer
        }
        return Math.abs(hash) % AgentAvatar.COLORS.length;
    }

    /**
     * Extract initials from an agent name.
     * Takes the first character, and if the name contains spaces or hyphens,
     * also takes the first character after the first separator.
     * @param {string} name - Agent name
     * @returns {string} 1-2 character initials (uppercase)
     */
    static _initials(name) {
        if (!name) return '?';
        const trimmed = name.trim();
        if (!trimmed) return '?';

        // Split on spaces, hyphens, or underscores
        const parts = trimmed.split(/[\s\-_]+/).filter(Boolean);

        if (parts.length >= 2) {
            return (parts[0][0] + parts[1][0]).toUpperCase();
        }

        // Single word — take first two characters
        return trimmed.slice(0, 2).toUpperCase();
    }

    /**
     * Get the deterministic CSS color for a given agent name.
     * @param {string} name - Agent name
     * @returns {string} CSS color value from the palette
     */
    static getColor(name) {
        if (!name) return AgentAvatar.COLORS[0];
        return AgentAvatar.COLORS[AgentAvatar._hash(name)];
    }

    /**
     * Render an agent avatar as an HTML string.
     * @param {string} name - Agent name (used for initials and color)
     * @param {Object} [options={}] - Rendering options
     * @param {string} [options.size='md'] - Size variant: 'xs' | 'sm' | 'md' | 'lg'
     * @param {string} [options.status='none'] - Status indicator: 'online' | 'busy' | 'offline' | 'none'
     * @returns {string} HTML string for the avatar element
     *
     * @example
     * AgentAvatar.render('claude', { size: 'xs', status: 'online' })
     * // => '<div class="agent-avatar agent-avatar-xs" style="background: #8b5cf6;"><span class="agent-avatar-initials">Cl</span><span class="agent-avatar-status agent-avatar-status-online"></span></div>'
     *
     * AgentAvatar.render('codex', { size: 'sm' })
     * // => '<div class="agent-avatar agent-avatar-sm" style="background: #f97316;"><span class="agent-avatar-initials">Co</span></div>'
     */
    static render(name, options = {}) {
        const size = options.size || 'md';
        const status = options.status || 'none';

        const color = AgentAvatar.getColor(name);
        const initials = AgentAvatar._initials(name);

        const sizeClass = `agent-avatar-${size}`;
        const parts = [`<div class="agent-avatar ${sizeClass}" style="background: ${color};">`];
        parts.push(`<span class="agent-avatar-initials">${initials}</span>`);

        if (status && status !== 'none' && AgentAvatar.STATUSES.includes(status)) {
            parts.push(`<span class="agent-avatar-status agent-avatar-status-${status}"></span>`);
        }

        parts.push('</div>');
        return parts.join('');
    }
}

// Expose globally (no ES modules)
window.AgentAvatar = AgentAvatar;
