/**
 * Panel Registry - Central registry for all Nexus panels.
 *
 * Each panel is registered with metadata (id, title, icon, category, module path).
 * Panels are lazy-loaded: the JS module is only fetched when the panel is first shown.
 *
 * Lifecycle: register() → create(id) → panel.init() → panel.render() → panel.refresh() / panel.destroy()
 */

class PanelRegistry {
    constructor() {
        /** @private @type {Map<string, Object>} id → definition */
        this._defs = new Map();
        /** @private @type {Map<string, import('./base-panel.js').BasePanel>} id → instance */
        this._instances = new Map();
        /** @private @type {Set<string>} ids of panels currently loading */
        this._loading = new Set();
    }

    // ----------------------------------------------------------
    // Registration
    // ----------------------------------------------------------

    /**
     * Register a panel definition.
     * @param {Object} def
     * @param {string} def.id          - Unique panel id (e.g. 'agent-registry')
     * @param {string} def.title       - Human-readable title
     * @param {string} def.icon        - SVG path data (24×24 viewbox)
     * @param {string} def.category    - Grouping category (agent, task, skill, …)
     * @param {string} def.module      - Relative path to the JS module (from panels/)
     * @param {string} [def.className] - Exported class name (defaults to PascalCase of id)
     * @param {string} [def.color]     - Accent colour token
     * @param {number} [def.refreshMs] - Auto-refresh interval (0 = manual only)
     */
    register(def) {
        if (!def.id || !def.module) {
            console.warn('PanelRegistry: skipping invalid definition', def);
            return;
        }
        this._defs.set(def.id, {
            title: def.id,
            icon: '',
            category: 'general',
            className: this._idToClassName(def.id),
            color: '',
            refreshMs: 0,
            ...def,
        });
    }

    /**
     * Bulk-register an array of definitions.
     * @param {Object[]} defs
     */
    registerAll(defs) {
        defs.forEach(d => this.register(d));
    }

    // ----------------------------------------------------------
    // Lookup
    // ----------------------------------------------------------

    /** Get a panel definition by id. */
    getDef(id) {
        return this._defs.get(id) || null;
    }

    /** Get all registered definitions. */
    getAllDefs() {
        return Array.from(this._defs.values());
    }

    /** Get definitions grouped by category. */
    getDefsByCategory() {
        const groups = {};
        for (const def of this._defs.values()) {
            (groups[def.category] = groups[def.category] || []).push(def);
        }
        return groups;
    }

    /** Get an existing panel instance (or null). */
    getInstance(id) {
        return this._instances.get(id) || null;
    }

    /** Check whether a panel has been instantiated. */
    isInstantiated(id) {
        return this._instances.has(id);
    }

    // ----------------------------------------------------------
    // Lifecycle
    // ----------------------------------------------------------

    /**
     * Create (or return existing) panel instance.
     * On first call the module is dynamically imported.
     *
     * @param {string} id   Panel id
     * @param {Object} opts Options forwarded to the panel constructor
     * @returns {Promise<import('./base-panel.js').BasePanel>}
     */
    async create(id, opts = {}) {
        const existing = this._instances.get(id);
        if (existing) return existing;

        const def = this._defs.get(id);
        if (!def) throw new Error(`PanelRegistry: unknown panel "${id}"`);

        if (this._loading.has(id)) {
            // Wait for the concurrent load to finish
            return new Promise((resolve) => {
                const check = setInterval(() => {
                    const inst = this._instances.get(id);
                    if (inst) { clearInterval(check); resolve(inst); }
                }, 50);
            });
        }

        this._loading.add(id);
        try {
            const mod = await import(`../panels/${def.module}`);
            const Cls = mod[def.className];
            if (!Cls) throw new Error(`PanelRegistry: "${def.className}" not exported by ${def.module}`);

            const instance = new Cls(id, def, opts);
            this._instances.set(id, instance);
            await instance.init();
            return instance;
        } finally {
            this._loading.delete(id);
        }
    }

    /**
     * Destroy a panel instance and remove it from the registry.
     * @param {string} id
     */
    async destroy(id) {
        const inst = this._instances.get(id);
        if (inst) {
            await inst.destroy();
            this._instances.delete(id);
        }
    }

    /** Destroy all instantiated panels. */
    async destroyAll() {
        const ids = Array.from(this._instances.keys());
        await Promise.all(ids.map(id => this.destroy(id)));
    }

    // ----------------------------------------------------------
    // Helpers
    // ----------------------------------------------------------

    /**
     * Convert kebab-case id to PascalCase class name.
     * e.g. 'agent-registry' → 'AgentRegistryPanel'
     * @private
     */
    _idToClassName(id) {
        return id
            .split('-')
            .map(s => s.charAt(0).toUpperCase() + s.slice(1))
            .join('') + 'Panel';
    }
}

// Singleton
window.PanelRegistry = new PanelRegistry();
