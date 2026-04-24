(function initNexusAgentsStore(global) {
    class NexusAgentsStore {
        constructor(options = {}) {
            this.storageKey = options.storageKey || 'nexus_agents_view_state';
            this._subscribers = new Set();
            this._state = this._getDefaultState();
            this._loadPersistedState();
        }

        _getDefaultState() {
            return {
                initialized: false,
                loading: false,
                saving: false,
                error: '',
                mode: 'overview',
                searchQuery: '',
                statusFilter: 'all',
                selectedAgentId: null,
                selectedTeamName: null,
                selectedTemplateName: null,
                overview: null,
                memoryState: null,
                agentBinding: null,
                teamConfig: null,
                agentTemplates: [],
                templateDraft: null,
                templateDirty: false,
                lastLoadedAt: null,
            };
        }

        getState() {
            return {
                ...this._state,
                overview: this._clone(this._state.overview),
                memoryState: this._clone(this._state.memoryState),
                agentBinding: this._clone(this._state.agentBinding),
                teamConfig: this._clone(this._state.teamConfig),
                agentTemplates: this._clone(this._state.agentTemplates || []),
                templateDraft: this._clone(this._state.templateDraft),
            };
        }

        _clone(value) {
            return value == null ? value : JSON.parse(JSON.stringify(value));
        }

        subscribe(callback) {
            if (typeof callback !== 'function') return () => {};
            this._subscribers.add(callback);
            callback(this.getState());
            return () => this._subscribers.delete(callback);
        }

        _notify() {
            const snapshot = this.getState();
            for (const callback of this._subscribers) {
                try {
                    callback(snapshot);
                } catch (error) {
                    console.error('[NexusAgentsStore] subscriber error:', error);
                }
            }
        }

        _setState(partial = {}) {
            this._state = {
                ...this._state,
                ...partial,
            };
            this._persistState();
            this._notify();
        }

        _loadPersistedState() {
            try {
                const raw = localStorage.getItem(this.storageKey);
                if (!raw) return;
                const saved = JSON.parse(raw);
                this._state.mode = saved.mode || this._state.mode;
                this._state.searchQuery = saved.searchQuery || '';
                this._state.statusFilter = saved.statusFilter || 'all';
                this._state.selectedAgentId = saved.selectedAgentId || null;
                this._state.selectedTeamName = saved.selectedTeamName || null;
                this._state.selectedTemplateName = saved.selectedTemplateName || null;
            } catch (error) {
                console.warn('[NexusAgentsStore] failed to restore state:', error);
            }
        }

        _persistState() {
            try {
                localStorage.setItem(this.storageKey, JSON.stringify({
                    mode: this._state.mode,
                    searchQuery: this._state.searchQuery,
                    statusFilter: this._state.statusFilter,
                    selectedAgentId: this._state.selectedAgentId,
                    selectedTeamName: this._state.selectedTeamName,
                    selectedTemplateName: this._state.selectedTemplateName,
                }));
            } catch (_) {
                // Best effort only.
            }
        }

        async init() {
            if (this._state.initialized && this._state.overview) {
                return this.refresh({ restoreSelection: true });
            }
            this._setState({ initialized: true });
            return this.refresh({ restoreSelection: true });
        }

        async refresh(options = {}) {
            const restoreSelection = options.restoreSelection !== false;
            this._setState({ loading: true, error: '' });
            try {
                const [overview, memoryState, templatePayload] = await Promise.all([
                    NexusAPI.getAgentsOverview(),
                    NexusAPI.getMemoryState().catch(() => null),
                    NexusAPI.listAgentTemplates().catch(() => ({ items: [] })),
                ]);
                this._setState({
                    overview,
                    memoryState,
                    agentTemplates: templatePayload.items || [],
                    loading: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
                if (restoreSelection) {
                    await this._restoreSelectionAfterRefresh();
                }
                return overview;
            } catch (error) {
                this._setState({ loading: false, error: error.message || 'Failed to load agents overview' });
                throw error;
            }
        }

        async _restoreSelectionAfterRefresh() {
            const overview = this._state.overview || {};
            const agents = overview.agents || [];
            const teams = overview.teams || [];
            const templates = this._state.agentTemplates || [];
            if (this._state.mode === 'agent_detail' && this._state.selectedAgentId) {
                const exists = agents.some((agent) => agent.id === this._state.selectedAgentId);
                if (exists) {
                    return this.selectAgent(this._state.selectedAgentId, { preserveMode: true });
                }
            }
            if (this._state.mode === 'team_detail' && this._state.selectedTeamName) {
                const exists = teams.some((team) => team.team_name === this._state.selectedTeamName || team.name === this._state.selectedTeamName);
                if (exists) {
                    return this.selectTeam(this._state.selectedTeamName, { preserveMode: true });
                }
            }
            if (this._state.mode === 'template_detail' && this._state.selectedTemplateName) {
                const exists = templates.some((template) => template.name === this._state.selectedTemplateName);
                if (exists) {
                    return this.selectTemplate(this._state.selectedTemplateName, { preserveMode: true });
                }
            }
            if (this._state.mode === 'templates') {
                this.showTemplates();
                return null;
            }
            this.showOverview();
            return null;
        }

        setSearchQuery(searchQuery = '') {
            this._setState({ searchQuery });
        }

        setStatusFilter(statusFilter = 'all') {
            this._setState({ statusFilter: statusFilter || 'all' });
        }

        showOverview() {
            this._setState({
                mode: 'overview',
                selectedAgentId: null,
                selectedTeamName: null,
                selectedTemplateName: null,
                agentBinding: null,
                teamConfig: null,
                templateDraft: null,
                templateDirty: false,
                error: '',
            });
        }

        showTemplates() {
            this._setState({
                mode: 'templates',
                selectedAgentId: null,
                selectedTeamName: null,
                agentBinding: null,
                teamConfig: null,
                templateDraft: null,
                templateDirty: false,
                error: '',
            });
        }

        async selectAgent(agentId, options = {}) {
            if (!agentId) {
                this.showOverview();
                return null;
            }
            this._setState({
                mode: 'agent_detail',
                selectedAgentId: agentId,
                selectedTeamName: null,
                selectedTemplateName: null,
                teamConfig: null,
                templateDraft: null,
                templateDirty: false,
                loading: true,
                error: '',
            });
            try {
                const binding = await NexusAPI.getAgentBinding(agentId);
                this._setState({
                    agentBinding: binding,
                    loading: false,
                    error: '',
                });
                return binding;
            } catch (error) {
                this._setState({
                    agentBinding: null,
                    loading: false,
                    error: error.message || 'Failed to load agent binding',
                });
                if (!options.preserveMode) {
                    this.showOverview();
                }
                throw error;
            }
        }

        async selectTeam(teamName, options = {}) {
            if (!teamName) {
                this.showOverview();
                return null;
            }
            this._setState({
                mode: 'team_detail',
                selectedAgentId: null,
                selectedTeamName: teamName,
                selectedTemplateName: null,
                agentBinding: null,
                templateDraft: null,
                templateDirty: false,
                loading: true,
                error: '',
            });
            try {
                const config = await NexusAPI.getTeamConfig(teamName);
                this._setState({
                    teamConfig: config,
                    loading: false,
                    error: '',
                });
                return config;
            } catch (error) {
                this._setState({
                    teamConfig: null,
                    loading: false,
                    error: error.message || 'Failed to load team config',
                });
                if (!options.preserveMode) {
                    this.showOverview();
                }
                throw error;
            }
        }

        async selectTemplate(templateName, options = {}) {
            if (!templateName) {
                this.showTemplates();
                return null;
            }
            const existing = (this._state.agentTemplates || []).find((template) => template.name === templateName);
            this._setState({
                mode: 'template_detail',
                selectedAgentId: null,
                selectedTeamName: null,
                selectedTemplateName: templateName,
                agentBinding: null,
                teamConfig: null,
                templateDraft: existing ? this._clone(existing) : null,
                templateDirty: false,
                loading: true,
                error: '',
            });
            try {
                const template = await NexusAPI.getAgentTemplate(templateName);
                this._setState({
                    templateDraft: this._clone(template),
                    agentTemplates: (this._state.agentTemplates || []).some((item) => item.name === template.name)
                        ? (this._state.agentTemplates || []).map((item) => item.name === template.name ? template : item)
                        : [...(this._state.agentTemplates || []), template],
                    loading: false,
                    error: '',
                });
                return template;
            } catch (error) {
                this._setState({ loading: false, error: error.message || 'Failed to load agent template' });
                if (!options.preserveMode) {
                    this.showTemplates();
                }
                throw error;
            }
        }

        updateTemplateDraft(patch = {}) {
            const draft = this._state.templateDraft || {};
            this._setState({
                templateDraft: {
                    ...draft,
                    ...patch,
                },
                templateDirty: true,
            });
        }

        async saveTemplateDraft() {
            const draft = this._state.templateDraft;
            const name = this._state.selectedTemplateName || draft?.name;
            if (!name || !draft) {
                throw new Error('No template selected');
            }
            this._setState({ saving: true, error: '' });
            try {
                const updated = await NexusAPI.updateAgentTemplate(name, this._templatePatchPayload(draft));
                this._setState({
                    templateDraft: this._clone(updated),
                    agentTemplates: (this._state.agentTemplates || []).map((item) => item.name === updated.name ? updated : item),
                    selectedTemplateName: updated.name,
                    templateDirty: false,
                    saving: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
                return updated;
            } catch (error) {
                this._setState({ saving: false, error: error.message || 'Failed to save agent template' });
                throw error;
            }
        }

        async createTemplate(payload = {}) {
            this._setState({ saving: true, error: '' });
            try {
                const created = await NexusAPI.createAgentTemplate(payload);
                this._setState({
                    agentTemplates: [...(this._state.agentTemplates || []).filter((item) => item.name !== created.name), created],
                    selectedTemplateName: created.name,
                    templateDraft: this._clone(created),
                    templateDirty: false,
                    mode: 'template_detail',
                    saving: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
                return created;
            } catch (error) {
                this._setState({ saving: false, error: error.message || 'Failed to create agent template' });
                throw error;
            }
        }

        async resetTemplate(templateName = '') {
            const name = templateName || this._state.selectedTemplateName;
            if (!name) throw new Error('No template selected');
            this._setState({ saving: true, error: '' });
            try {
                const reset = await NexusAPI.resetAgentTemplate(name);
                this._setState({
                    agentTemplates: (this._state.agentTemplates || []).some((item) => item.name === reset.name)
                        ? (this._state.agentTemplates || []).map((item) => item.name === reset.name ? reset : item)
                        : [...(this._state.agentTemplates || []), reset],
                    selectedTemplateName: reset.name,
                    templateDraft: this._clone(reset),
                    templateDirty: false,
                    saving: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
                return reset;
            } catch (error) {
                this._setState({ saving: false, error: error.message || 'Failed to reset agent template' });
                throw error;
            }
        }

        async deleteTemplate(templateName = '') {
            const name = templateName || this._state.selectedTemplateName;
            if (!name) throw new Error('No template selected');
            this._setState({ saving: true, error: '' });
            try {
                await NexusAPI.deleteAgentTemplate(name);
                const templates = (this._state.agentTemplates || []).filter((item) => item.name !== name);
                this._setState({
                    agentTemplates: templates,
                    selectedTemplateName: null,
                    templateDraft: null,
                    templateDirty: false,
                    mode: 'templates',
                    saving: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
            } catch (error) {
                this._setState({ saving: false, error: error.message || 'Failed to delete agent template' });
                throw error;
            }
        }

        _templatePatchPayload(draft) {
            const payload = { ...draft };
            delete payload.id;
            delete payload.name;
            delete payload.source;
            delete payload.hasDefault;
            delete payload.createdAt;
            delete payload.updatedAt;
            return payload;
        }

        async updateAgentBinding(patch = {}) {
            const agentId = this._state.selectedAgentId;
            if (!agentId) {
                throw new Error('No agent selected');
            }
            this._setState({ saving: true, error: '' });
            try {
                const binding = await NexusAPI.updateAgentBinding(agentId, patch);
                const overview = await NexusAPI.getAgentsOverview().catch(() => this._state.overview);
                this._setState({
                    agentBinding: binding,
                    overview,
                    saving: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
                return binding;
            } catch (error) {
                this._setState({ saving: false, error: error.message || 'Failed to update agent binding' });
                throw error;
            }
        }

        async updateTeamConfig(patch = {}) {
            const teamName = this._state.selectedTeamName;
            if (!teamName) {
                throw new Error('No team selected');
            }
            this._setState({ saving: true, error: '' });
            try {
                const config = await NexusAPI.updateTeamConfig(teamName, patch);
                const overview = await NexusAPI.getAgentsOverview().catch(() => this._state.overview);
                this._setState({
                    teamConfig: config,
                    overview,
                    saving: false,
                    error: '',
                    lastLoadedAt: Date.now(),
                });
                return config;
            } catch (error) {
                this._setState({ saving: false, error: error.message || 'Failed to update team config' });
                throw error;
            }
        }

        getCurrentAgentSummary() {
            const overview = this._state.overview || {};
            return (overview.agents || []).find((agent) => agent.id === this._state.selectedAgentId) || null;
        }

        getCurrentTeamSummary() {
            const overview = this._state.overview || {};
            return (overview.teams || []).find((team) => (team.team_name || team.name) === this._state.selectedTeamName) || null;
        }

        getCurrentTemplate() {
            const name = this._state.selectedTemplateName;
            return (this._state.agentTemplates || []).find((template) => template.name === name) || null;
        }

        _matchesStatus(item, statusFilter) {
            if (!statusFilter || statusFilter === 'all') return true;
            const runtime = item.runtime || item.runtime_detail || {};
            const status = String(runtime.status || item.status || '').trim().toLowerCase();
            if (statusFilter === 'online') {
                return status && status !== 'offline';
            }
            return status === String(statusFilter).trim().toLowerCase();
        }

        _matchesSearch(item, query) {
            if (!query) return true;
            const runtime = item.runtime || item.runtime_detail || {};
            const identity = item.identity || {};
            const haystack = [
                item.id,
                item.team_name,
                item.name,
                item.display_name,
                item.role,
                item.description,
                identity.title,
                identity.subtitle,
                identity.owner,
                identity.provider,
                runtime.workspace,
                ...(item.capabilities || []),
            ].filter(Boolean).join(' ').toLowerCase();
            return haystack.includes(String(query).trim().toLowerCase());
        }

        getFilteredTemplates() {
            const searchQuery = this._state.searchQuery || '';
            return (this._state.agentTemplates || [])
                .filter((template) => this._matchesSearch(template, searchQuery))
                .map((template) => ({
                    kind: 'template',
                    key: `template:${template.name}`,
                    id: template.name,
                    title: template.name,
                    subtitle: template.role || template.description || '',
                    status: template.hasDefault ? 'preset' : (template.source || 'custom'),
                    item: template,
                }));
        }

        getFilteredItems() {
            if (this._state.mode === 'templates' || this._state.mode === 'template_detail') {
                return this.getFilteredTemplates();
            }
            const overview = this._state.overview || {};
            const searchQuery = this._state.searchQuery || '';
            const statusFilter = this._state.statusFilter || 'all';
            const agentItems = (overview.agents || [])
                .filter((agent) => this._matchesSearch(agent, searchQuery) && this._matchesStatus(agent, statusFilter))
                .map((agent) => ({
                    kind: 'agent',
                    key: `agent:${agent.id}`,
                    id: agent.id,
                    title: agent.identity?.title || agent.display_name || agent.id,
                    subtitle: agent.identity?.subtitle || agent.agent_type || '',
                    status: agent.runtime?.status || (agent.available ? 'online' : 'offline'),
                    item: agent,
                }));
            const teamItems = (overview.teams || [])
                .filter((team) => this._matchesSearch(team, searchQuery) && this._matchesStatus(team, statusFilter))
                .map((team) => ({
                    kind: 'team',
                    key: `team:${team.team_name || team.name}`,
                    id: team.team_name || team.name,
                    title: team.identity?.title || team.team_name || team.name,
                    subtitle: team.identity?.subtitle || `${team.member_count || 0} members`,
                    status: team.runtime?.status || team.status || 'idle',
                    item: team,
                }));
            return [...agentItems, ...teamItems];
        }
    }

    global.NexusAgentsStore = NexusAgentsStore;
})(window);
