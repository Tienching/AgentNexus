/**
 * Nexus shell views extracted from a previously working app.js implementation.
 * Restores settings/search/plan-mode support that was dropped during shell splitting.
 */
(function initNexusShellViews(global) {
    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
        }[ch]));
    }

class ConfigView {
    constructor(app) {
        this.app = app;
        this.activeTab = 'parameters';
        this.bindEvents();
    }

    bindEvents() {
        // Config tab switching
        document.querySelectorAll('.config-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.switchTab(tab.dataset.configTab);
            });
        });

        // Parameters tab events (includes concurrency)
        this.bindParametersEvents();

        // MCP tab events
        this.bindMcpEvents();

        // Skills tab events
        this.bindSkillsEvents();
    }

    switchTab(tabName) {
        this.activeTab = tabName;

        // Update tab button states
        document.querySelectorAll('.config-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.configTab === tabName);
        });

        // Update tab content visibility
        document.querySelectorAll('.config-tab-content').forEach(content => {
            content.classList.toggle('active', content.dataset.configContent === tabName);
        });
    }

    refresh() {
        this.renderParameters();
        this.renderMcp();
        this.renderSkills();
    }

    // ============================================================
    // Parameters Tab
    // ============================================================
    bindParametersEvents() {
        // Default provider select
        const defaultProviderSelect = document.getElementById('configDefaultProvider');
        if (defaultProviderSelect) {
            defaultProviderSelect.addEventListener('change', (e) => {
                const provider = e.target.value;
                this.app.setDefaultProvider(provider);
                this.updateDefaultProviderStatus(provider, 'saved');
                this.app.showToast('Default provider updated', 'success');
                this.app.refreshChatProviders?.();
                this.app.taskFormController?.refreshSelectors?.();
                this.app.settingsPage?.sections?.provider?.renderSummary?.();
            });
        }

        // Add alias button
        const addAliasBtn = document.getElementById('addAliasBtn');
        if (addAliasBtn) {
            addAliasBtn.addEventListener('click', () => this.addAlias());
        }

        // Add alias on Enter key
        const newAliasName = document.getElementById('newAliasName');
        if (newAliasName) {
            newAliasName.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.addAlias();
            });
        }

        // Global concurrency
        const setGlobalBtn = document.getElementById('setGlobalConcurrencyBtn');
        if (setGlobalBtn) {
            setGlobalBtn.addEventListener('click', () => this.setGlobalConcurrency());
        }
        const globalInput = document.getElementById('globalConcurrencyInput');
        if (globalInput) {
            globalInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.setGlobalConcurrency();
            });
        }

        // Provider concurrency
        const setProviderBtn = document.getElementById('setProviderConcurrencyBtn');
        if (setProviderBtn) {
            setProviderBtn.addEventListener('click', () => this.setProviderConcurrency());
        }
    }

    renderParameters() {
        // Update default provider select
        const defaultProviderSelect = document.getElementById('configDefaultProvider');
        if (defaultProviderSelect) {
            const currentDefault = this.app.getDefaultProvider();
            const allProviders = this.app.getAllProviders();

            defaultProviderSelect.innerHTML = allProviders.map(p => {
                const label = this.app.isCustomAlias(p)
                    ? `${p} (${this.app.getBaseProvider(p)})`
                    : p;
                return `<option value="${escapeHtml(p)}" ${p === currentDefault ? 'selected' : ''}>${escapeHtml(label)}</option>`;
            }).join('');
            this.updateDefaultProviderStatus(currentDefault);
        }

        // Update base provider select for new alias
        const newAliasBase = document.getElementById('newAliasBase');
        if (newAliasBase) {
            newAliasBase.innerHTML = this.app.getDefaultProviders()
                .map(p => `<option value="${escapeHtml(p)}">${escapeHtml(p)}</option>`)
                .join('');
        }

        // Render alias list
        this.renderAliasList();

        // Render per-provider/alias default model settings
        this.renderProviderModels();

        // Update concurrency provider/alias dropdown
        const concurrencySelect = document.getElementById('providerConcurrencySelect');
        if (concurrencySelect) {
            const allProviders = this.app.getAllProviders();
            concurrencySelect.innerHTML = allProviders.map(p => {
                const label = this.app.isCustomAlias(p)
                    ? `${p} (${this.app.getBaseProvider(p)})`
                    : p;
                return `<option value="${escapeHtml(p)}">${escapeHtml(label)}</option>`;
            }).join('');
        }

        // Render concurrency data
        this.renderConcurrency();
    }

    updateDefaultProviderStatus(provider, state = 'current') {
        const status = document.getElementById('defaultProviderStatus');
        if (!status) return;
        const label = state === 'saved' ? 'Saved' : 'Current';
        status.textContent = `${label}: ${provider || 'claude'}`;
        status.dataset.state = state;
    }

    renderProviderModels() {
        const container = document.getElementById('providerModelsContainer');
        if (!container) return;

        const allProviders = this.app.getAllProviders();
        container.innerHTML = allProviders.map(name => {
            const currentModel = this.app.getProviderDefaultModel(name) || '';
            const isAlias = this.app.isCustomAlias(name);
            const safeName = escapeHtml(name);
            const safeBase = escapeHtml(this.app.getBaseProvider(name));
            const label = isAlias ? `${safeName} <span class="alias-item-base">${safeBase}</span>` : safeName;
            return `
                <div class="provider-model-row" data-provider="${safeName}">
                    <span class="provider-model-label">${label}</span>
                    <input type="text" class="form-input provider-model-input" data-provider="${safeName}"
                           value="${escapeHtml(currentModel)}" placeholder="Use provider default"
                          >
                    <button class="action-btn small provider-model-save" data-provider="${safeName}">Save</button>
                </div>
            `;
        }).join('');

        // Bind save buttons and Enter key
        container.querySelectorAll('.provider-model-save').forEach(btn => {
            btn.addEventListener('click', () => {
                const prov = btn.dataset.provider;
                const input = btn.closest('.provider-model-row')?.querySelector('.provider-model-input');
                if (input) {
                    this.app.setProviderDefaultModel(prov, input.value.trim());
                    this.app.showToast(`Default model for ${prov} updated`, 'success');
                }
            });
        });
        container.querySelectorAll('.provider-model-input').forEach(input => {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const prov = input.dataset.provider;
                    this.app.setProviderDefaultModel(prov, input.value.trim());
                    this.app.showToast(`Default model for ${prov} updated`, 'success');
                }
            });
        });
    }

    renderAliasList() {
        const container = document.getElementById('aliasListContainer');
        if (!container) return;

        const aliases = this.app.customProviders;

        if (aliases.length === 0) {
            container.innerHTML = '<div class="alias-empty">No custom aliases configured</div>';
            return;
        }

        container.innerHTML = aliases.map(alias => {
            const name = escapeHtml(alias.name);
            const baseProvider = escapeHtml(alias.baseProvider);
            const configPath = escapeHtml(alias.configPath || '');
            return `
            <div class="alias-item" data-alias="${name}">
                <div class="alias-item-info">
                    <span class="alias-item-name">${name}</span>
                    <span class="alias-item-base">${baseProvider}</span>
                    ${configPath ? `<span class="alias-item-path" title="${configPath}">${configPath}</span>` : ''}
                </div>
                <button class="alias-item-delete" title="Delete alias">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
            `;
        }).join('');

        // Bind delete buttons
        container.querySelectorAll('.alias-item-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const item = e.target.closest('.alias-item');
                const aliasName = item?.dataset.alias;
                if (aliasName) {
                    this.deleteAlias(aliasName);
                }
            });
        });
    }

    addAlias() {
        const nameInput = document.getElementById('newAliasName');
        const baseSelect = document.getElementById('newAliasBase');
        const configPathInput = document.getElementById('newAliasConfigPath');

        if (!nameInput || !baseSelect) return;

        const name = nameInput.value.trim();
        const base = baseSelect.value;
        const configPath = configPathInput?.value.trim() || '';

        if (!name) {
            this.app.showToast('Please enter an alias name', 'error');
            return;
        }

        if (this.app.addCustomProvider(name, base, configPath)) {
            this.app.showToast(`Alias "${name}" added`, 'success');
            nameInput.value = '';
            if (configPathInput) configPathInput.value = '';
            this.renderParameters();
            this.renderSkills();
            this.app.refreshChatProviders?.();
        } else {
            this.app.showToast('Alias already exists or is invalid', 'error');
        }
    }

    deleteAlias(name) {
        if (this.app.removeCustomProvider(name)) {
            this.app.showToast(`Alias "${name}" removed`, 'success');
            this.renderParameters();
            this.renderSkills();
            this.app.refreshChatProviders?.();
        } else {
            this.app.showToast('Cannot remove this alias', 'error');
        }
    }

    // ============================================================
    // MCP Tab
    // ============================================================
    bindMcpEvents() {
        // Add global MCP button
        const addGlobalMcpBtn = document.getElementById('addGlobalMcpBtn');
        if (addGlobalMcpBtn) {
            addGlobalMcpBtn.addEventListener('click', () => this.addGlobalMcp());
        }
    }

    renderMcp() {
        const mcpConfig = this.app.loadMcpConfig();

        // Render global MCP list
        this.renderMcpList('globalMcpList', mcpConfig.global, null);

        // Render provider panels
        this.renderProviderMcpPanels(mcpConfig.providers);
    }

    renderMcpList(containerId, mcpServers, provider) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!mcpServers || mcpServers.length === 0) {
            container.innerHTML = '<div class="mcp-empty">No MCP servers configured</div>';
            return;
        }

        container.innerHTML = mcpServers.map((mcp, index) => `
            <div class="mcp-item" data-index="${index}" data-provider="${escapeHtml(provider || 'global')}">
                <div class="mcp-item-info">
                    <div class="mcp-item-name">${escapeHtml(mcp.name)}</div>
                    <div class="mcp-item-command">${escapeHtml(mcp.command)} ${(mcp.args || []).map(escapeHtml).join(' ')}</div>
                </div>
                <button class="mcp-item-delete" title="Delete MCP server">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');

        // Bind delete buttons
        container.querySelectorAll('.mcp-item-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const item = e.target.closest('.mcp-item');
                const index = parseInt(item?.dataset.index);
                const prov = item?.dataset.provider;
                if (!isNaN(index)) {
                    this.deleteMcp(prov === 'global' ? null : prov, index);
                }
            });
        });
    }

    renderProviderMcpPanels(providersMcp) {
        const container = document.getElementById('providerMcpPanels');
        if (!container) return;

        const providers = this.app.getDefaultProviders();

        container.innerHTML = providers.map(provider => {
            const mcpList = providersMcp[provider] || [];
            return `
                <div class="provider-panel" data-provider="${escapeHtml(provider)}">
                    <div class="provider-panel-header">
                        <div class="provider-panel-title">
                            ${escapeHtml(provider)}
                            <span class="provider-panel-count">${mcpList.length}</span>
                        </div>
                        <svg class="provider-panel-toggle" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </div>
                    <div class="provider-panel-body">
                        <div class="mcp-form">
                            <input type="text" class="form-input provider-mcp-name" placeholder="Server name">
                            <input type="text" class="form-input provider-mcp-command" placeholder="Command">
                            <input type="text" class="form-input provider-mcp-args" placeholder="Args (comma-separated)">
                            <button class="action-btn primary provider-mcp-add">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="u-icon-sm">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                </svg>
                                Add
                            </button>
                        </div>
                        <div class="mcp-list" id="providerMcpList-${escapeHtml(provider)}">
                            ${this.renderProviderMcpItems(mcpList, provider)}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Bind panel toggle
        container.querySelectorAll('.provider-panel-header').forEach(header => {
            header.addEventListener('click', () => {
                header.closest('.provider-panel').classList.toggle('expanded');
            });
        });

        // Bind add buttons
        container.querySelectorAll('.provider-mcp-add').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const panel = e.target.closest('.provider-panel');
                const provider = panel?.dataset.provider;
                if (provider) {
                    this.addProviderMcp(provider, panel);
                }
            });
        });

        // Bind delete buttons
        container.querySelectorAll('.mcp-item-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const item = e.target.closest('.mcp-item');
                const index = parseInt(item?.dataset.index);
                const prov = item?.dataset.provider;
                if (!isNaN(index) && prov) {
                    this.deleteMcp(prov, index);
                }
            });
        });
    }

    renderProviderMcpItems(mcpList, provider) {
        if (!mcpList || mcpList.length === 0) {
            return '<div class="mcp-empty">No MCP servers for this provider</div>';
        }

        return mcpList.map((mcp, index) => `
            <div class="mcp-item" data-index="${index}" data-provider="${escapeHtml(provider)}">
                <div class="mcp-item-info">
                    <div class="mcp-item-name">${escapeHtml(mcp.name)}</div>
                    <div class="mcp-item-command">${escapeHtml(mcp.command)} ${(mcp.args || []).map(escapeHtml).join(' ')}</div>
                </div>
                <button class="mcp-item-delete" title="Delete MCP server">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');
    }

    addGlobalMcp() {
        const nameInput = document.getElementById('globalMcpName');
        const commandInput = document.getElementById('globalMcpCommand');
        const argsInput = document.getElementById('globalMcpArgs');

        if (!nameInput || !commandInput) return;

        const name = nameInput.value.trim();
        const command = commandInput.value.trim();
        const args = argsInput?.value.trim().split(',').map(s => s.trim()).filter(Boolean) || [];

        if (!name || !command) {
            this.app.showToast('Please enter server name and command', 'error');
            return;
        }

        const config = this.app.loadMcpConfig();
        config.global.push({ name, command, args });
        this.app.saveMcpConfig(config);

        nameInput.value = '';
        commandInput.value = '';
        if (argsInput) argsInput.value = '';

        this.app.showToast(`MCP server "${name}" added`, 'success');
        this.renderMcp();
    }

    addProviderMcp(provider, panel) {
        const nameInput = panel.querySelector('.provider-mcp-name');
        const commandInput = panel.querySelector('.provider-mcp-command');
        const argsInput = panel.querySelector('.provider-mcp-args');

        if (!nameInput || !commandInput) return;

        const name = nameInput.value.trim();
        const command = commandInput.value.trim();
        const args = argsInput?.value.trim().split(',').map(s => s.trim()).filter(Boolean) || [];

        if (!name || !command) {
            this.app.showToast('Please enter server name and command', 'error');
            return;
        }

        const config = this.app.loadMcpConfig();
        if (!config.providers[provider]) {
            config.providers[provider] = [];
        }
        config.providers[provider].push({ name, command, args });
        this.app.saveMcpConfig(config);

        nameInput.value = '';
        commandInput.value = '';
        if (argsInput) argsInput.value = '';

        this.app.showToast(`MCP server "${name}" added to ${provider}`, 'success');
        this.renderMcp();
    }

    deleteMcp(provider, index) {
        const config = this.app.loadMcpConfig();

        if (provider === null) {
            // Global
            if (config.global[index]) {
                const name = config.global[index].name;
                config.global.splice(index, 1);
                this.app.saveMcpConfig(config);
                this.app.showToast(`MCP server "${name}" removed`, 'success');
                this.renderMcp();
            }
        } else {
            // Provider specific
            if (config.providers[provider] && config.providers[provider][index]) {
                const name = config.providers[provider][index].name;
                config.providers[provider].splice(index, 1);
                this.app.saveMcpConfig(config);
                this.app.showToast(`MCP server "${name}" removed from ${provider}`, 'success');
                this.renderMcp();
            }
        }
    }

    // ============================================================
    // Skills Tab (backend API driven)
    // ============================================================
    bindSkillsEvents() {
        // Events are bound dynamically after rendering provider panels
    }

    async renderSkills() {
        const container = document.getElementById('providerSkillsPanels');
        if (!container) return;

        container.innerHTML = '<div class="skills-loading">Loading skills...</div>';

        try {
            const execUser = document.getElementById('globalUserFilter')?.value || NexusAPI.getDefaultExecUser();
            const customPaths = this.app.getAliasSkillsPaths();
            const data = await NexusAPI.getSkills({ execUser, customPaths: Object.keys(customPaths).length ? customPaths : undefined });
            this._skillsData = data.providers || {};
            this.renderProviderSkillsPanels(this._skillsData);
        } catch (error) {
            console.error('Failed to load skills:', error);
            container.innerHTML = '<div class="skills-empty">Failed to load skills. Check server connection.</div>';
        }
    }

    renderProviderSkillsPanels(providersSkills) {
        const container = document.getElementById('providerSkillsPanels');
        if (!container) return;

        const defaultProviders = this.app.getDefaultProviders
            ? this.app.getDefaultProviders()
            : ['claude', 'codex', 'codebuddy', 'hermes'];
        // Include custom aliases
        const aliasNames = this.app.getCustomProviderNames();
        const allProviders = [...defaultProviders, ...aliasNames.filter(n => !defaultProviders.includes(n))];
        // Also include any extra providers from the response
        for (const key of Object.keys(providersSkills)) {
            if (!allProviders.includes(key)) allProviders.push(key);
        }

        // Default provider config dirs (for display)
        const _DEFAULT_CONFIG_DIRS = {
            claude: '~/.claude',
            codex: '~/.codex',
            codebuddy: '~/.codebuddy',
            hermes: '~/.hermes',
        };

        container.innerHTML = allProviders.map(provider => {
            const skills = providersSkills[provider] || [];
            const isAlias = this.app.isCustomAlias(provider);
            const safeProvider = escapeHtml(provider);
            const baseInfo = isAlias ? ` <span class="alias-item-base">${escapeHtml(this.app.getBaseProvider(provider))}</span>` : '';
            // Show config path for both default providers and aliases
            let configPath;
            if (isAlias) {
                configPath = this.app.getAliasConfigPath(provider) || '';
            } else {
                configPath = _DEFAULT_CONFIG_DIRS[provider] || '';
            }
            const safeConfigPath = escapeHtml(configPath || '');
            const pathInfo = safeConfigPath ? ` <span class="alias-item-path" title="${safeConfigPath}">${safeConfigPath}</span>` : '';
            return `
                <div class="provider-panel expanded" data-provider="${safeProvider}" data-config-path="${safeConfigPath}">
                    <div class="provider-panel-header">
                        <div class="provider-panel-title">
                            ${safeProvider}${baseInfo}${pathInfo}
                            <span class="provider-panel-count">${skills.length}</span>
                        </div>
                        <svg class="provider-panel-toggle" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
                        </svg>
                    </div>
                    <div class="provider-panel-body">
                        <!-- Create Skill Form -->
                        <div class="skill-create-form">
                            <div class="skill-create-row">
                                <input type="text" class="form-input skill-new-name" placeholder="Skill name">
                                <input type="text" class="form-input skill-new-desc" placeholder="Description (optional)">
                                <button class="action-btn primary skill-create-btn" title="Create new skill">
                                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" class="u-icon-sm">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                                    </svg>
                                    Create
                                </button>
                            </div>
                            <textarea class="form-input skill-new-content" placeholder="SKILL.md content (markdown, optional)" rows="3" hidden></textarea>
                            <button class="skill-toggle-content-btn" title="Toggle content editor">+ Add content</button>
                        </div>
                        <!-- Skills List -->
                        <div class="skills-list" id="providerSkillsList-${safeProvider}">
                            ${this._renderSkillCards(skills, provider)}
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        // Bind panel toggle
        container.querySelectorAll('.provider-panel-header').forEach(header => {
            header.addEventListener('click', () => {
                header.closest('.provider-panel').classList.toggle('expanded');
            });
        });

        // Bind create skill buttons
        container.querySelectorAll('.skill-create-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const panel = e.target.closest('.provider-panel');
                const provider = panel?.dataset.provider;
                if (provider) this._createSkill(provider, panel);
            });
        });

        // Bind "Enter" on name input
        container.querySelectorAll('.skill-new-name').forEach(input => {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const panel = e.target.closest('.provider-panel');
                    const provider = panel?.dataset.provider;
                    if (provider) this._createSkill(provider, panel);
                }
            });
        });

        // Bind toggle content button
        container.querySelectorAll('.skill-toggle-content-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const form = e.target.closest('.skill-create-form');
                const textarea = form?.querySelector('.skill-new-content');
                if (textarea) {
                    const isHidden = textarea.hidden;
                    textarea.hidden = !isHidden;
                    e.target.textContent = isHidden ? '- Hide content' : '+ Add content';
                }
            });
        });

        // Bind delete skill buttons
        container.querySelectorAll('.skill-card-delete').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const card = e.target.closest('.skill-card');
                const provider = card?.dataset.provider;
                const skillName = card?.dataset.skillName;
                if (provider && skillName) this._deleteSkill(provider, skillName);
            });
        });
    }

    _renderSkillCards(skills, provider) {
        if (!skills || skills.length === 0) {
            return '<div class="skills-empty">No skills discovered for this provider</div>';
        }

        return skills.map(skill => {
            const name = escapeHtml(skill.name);
            const desc = skill.description ? String(skill.description) : '';
            const shortDesc = desc.length > 120 ? desc.slice(0, 120) + '...' : desc;
            const path = skill.path ? String(skill.path) : '';
            const shortPath = path.length > 40 ? '...' + path.slice(-37) : path;
            return `
            <div class="skill-card" data-provider="${escapeHtml(provider)}" data-skill-name="${name}">
                <div class="skill-card-info">
                    <div class="skill-card-name">${name}</div>
                    ${desc ? `<div class="skill-card-desc">${escapeHtml(shortDesc)}</div>` : ''}
                    <div class="skill-card-meta">
                        ${skill.version ? `<span class="skill-card-version">v${escapeHtml(skill.version)}</span>` : ''}
                        ${path ? `<span class="skill-card-path" title="${escapeHtml(path)}">${escapeHtml(shortPath)}</span>` : ''}
                    </div>
                </div>
                <button class="skill-card-delete" title="Delete skill">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
            `;
        }).join('');
    }

    async _createSkill(provider, panel) {
        const nameInput = panel.querySelector('.skill-new-name');
        const descInput = panel.querySelector('.skill-new-desc');
        const contentTextarea = panel.querySelector('.skill-new-content');

        const skillName = nameInput?.value.trim();
        if (!skillName) {
            this.app.showToast('Please enter a skill name', 'error');
            return;
        }

        const description = descInput?.value.trim() || '';
        const content = contentTextarea?.value.trim() || '';
        const configPath = panel.dataset.configPath || '';

        const payload = {
            provider,
            skill_name: skillName,
            description,
            content: content || `# ${skillName}\n`,
        };
        // If alias has custom config path, pass skills_path
        if (configPath) {
            payload.skills_path = configPath.endsWith('/skills') ? configPath : configPath + '/skills';
        }

        try {
            await NexusAPI.createSkill(payload);
            this.app.showToast(`Skill "${skillName}" created for ${provider}`, 'success');
            if (nameInput) nameInput.value = '';
            if (descInput) descInput.value = '';
            if (contentTextarea) contentTextarea.value = '';
            await this.renderSkills();
        } catch (error) {
            this.app.showToast(`Failed to create skill: ${error.message}`, 'error');
        }
    }

    async _deleteSkill(provider, skillName) {
        if (!confirm(`Delete skill "${skillName}" from ${provider}? This will remove the skill directory from the filesystem.`)) {
            return;
        }

        try {
            const execUser = document.getElementById('globalUserFilter')?.value || NexusAPI.getDefaultExecUser();
            const configPath = this.app.getAliasConfigPath(provider);
            const opts = { execUser };
            if (configPath) {
                opts.skillsPath = configPath.endsWith('/skills') ? configPath : configPath + '/skills';
            }
            await NexusAPI.deleteSkill(provider, skillName, opts);
            this.app.showToast(`Skill "${skillName}" deleted from ${provider}`, 'success');
            await this.renderSkills();
        } catch (error) {
            this.app.showToast(`Failed to delete skill: ${error.message}`, 'error');
        }
    }

    // ============================================================
    // Concurrency Tab
    // ============================================================
    async renderConcurrency() {
        try {
            const resp = await fetch('/api/nexus/concurrency');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();

            // Global
            const globalInput = document.getElementById('globalConcurrencyInput');
            const globalDisplay = document.getElementById('globalConcurrencyDisplay');
            if (globalInput) {
                globalInput.value = data.global_max_concurrency || 0;
            }
            if (globalDisplay) {
                globalDisplay.textContent = data.global_max_concurrency
                    ? `Current: ${data.global_max_concurrency}`
                    : 'Current: unlimited';
            }

            // Provider list
            this.renderProviderConcurrencyList(data.provider_concurrency || {});
        } catch (e) {
            console.error('Failed to load concurrency config:', e);
        }
    }

    renderProviderConcurrencyList(providerMap) {
        const container = document.getElementById('providerConcurrencyList');
        if (!container) return;

        const entries = Object.entries(providerMap).sort((a, b) => a[0].localeCompare(b[0]));
        if (entries.length === 0) {
            container.innerHTML = '<div class="mcp-empty">No provider concurrency limits configured</div>';
            return;
        }

        container.innerHTML = entries.map(([name, limit]) => `
            <div class="mcp-item" data-provider-name="${escapeHtml(name)}">
                <div class="mcp-item-info">
                    <div class="mcp-item-name">${escapeHtml(name)}</div>
                    <div class="mcp-item-command">Max: ${escapeHtml(limit)}</div>
                </div>
                <button class="mcp-item-delete concurrency-remove-btn" title="Remove limit" data-name="${escapeHtml(name)}">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');

        container.querySelectorAll('.concurrency-remove-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const name = e.target.closest('.concurrency-remove-btn')?.dataset.name;
                if (name) {
                    await this.removeProviderConcurrency(name);
                }
            });
        });
    }

    async setGlobalConcurrency() {
        const input = document.getElementById('globalConcurrencyInput');
        if (!input) return;
        const limit = parseInt(input.value) || 0;

        try {
            const resp = await fetch('/api/nexus/concurrency/global', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ limit }),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            this.app.showToast(`Global concurrency set to ${limit || 'unlimited'}`, 'success');
            this.renderConcurrency();
        } catch (e) {
            this.app.showToast(`Failed: ${e.message}`, 'error');
        }
    }

    async setProviderConcurrency() {
        const nameSelect = document.getElementById('providerConcurrencySelect');
        const limitInput = document.getElementById('providerConcurrencyLimit');
        if (!nameSelect || !limitInput) return;

        const name = nameSelect.value;
        const limit = parseInt(limitInput.value) || 0;

        if (!name) {
            this.app.showToast('Please select a provider or alias', 'error');
            return;
        }

        try {
            const resp = await fetch('/api/nexus/concurrency/provider', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, limit }),
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            limitInput.value = '';
            this.app.showToast(`Concurrency for "${name}" set to ${limit || 'unlimited'}`, 'success');
            this.renderConcurrency();
        } catch (e) {
            this.app.showToast(`Failed: ${e.message}`, 'error');
        }
    }

    async removeProviderConcurrency(name) {
        try {
            const resp = await fetch(`/api/nexus/concurrency/provider/${encodeURIComponent(name)}`, {
                method: 'DELETE',
            });
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${resp.status}`);
            }
            this.app.showToast(`Concurrency limit for "${name}" removed`, 'success');
            this.renderConcurrency();
        } catch (e) {
            this.app.showToast(`Failed: ${e.message}`, 'error');
        }
    }
}

// ============================================================
// Admin View
// ============================================================
class GlobalSearch {
    constructor(app) {
        this.app = app;
        this.modal = document.getElementById('globalSearchModal');
        this.input = document.getElementById('globalSearchInput');
        this.type = document.getElementById('globalSearchType');
        this.results = document.getElementById('globalSearchResults');
        this.submitBtn = document.getElementById('globalSearchSubmitBtn');
        this.triggerBtn = document.getElementById('globalSearchBtn');
        this.bindEvents();
    }

    bindEvents() {
        this.triggerBtn?.addEventListener('click', () => this.open());
        this.submitBtn?.addEventListener('click', () => this.search());
        this.input?.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                this.search();
            }
        });

        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                this.open();
            }
        });
    }

    open() {
        this.modal?.classList.add('open');
        setTimeout(() => this.input?.focus(), 0);
    }

    close() {
        this.modal?.classList.remove('open');
    }

    _esc(str) {
        return String(str || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    _openResult(type, id) {
        const resultType = String(type || '').trim().toLowerCase();
        const resultId = String(id || '').trim();
        if (!resultType || !resultId) return;

        if (resultType === 'task') {
            try {
                const url = new URL(window.location.href);
                url.searchParams.set('page', 'task');
                url.searchParams.set('task', resultId);
                url.searchParams.set('taskTab', 'details');
                window.history.pushState({}, '', url);
            } catch {
                // Best-effort URL sync only.
            }
            this.app?.pageManager?.setPage?.('task', { preserveTaskState: true, skipUrlSync: true });
            this.app?.taskBoardPanel?._restoreTaskFromUrl?.();
            this.close();
            return;
        }

        if (resultType === 'session') {
            this.app?.pageManager?.setPage?.('chat');
            window.setTimeout(() => this.app?.chatView?.selectSession?.(0, resultId), 150);
            this.close();
        }
    }

    async search() {
        const q = this.input?.value?.trim();
        if (!q || !this.results) return;
        const type = this.type?.value || 'all';
        this.results.innerHTML = '<div class="admin-loading">Searching...</div>';
        try {
            const data = await NexusAPI.globalSearch(q, type);
            const items = data.results || [];
            if (!items.length) {
                this.results.innerHTML = '<div class="u-empty-state-xl">No results found</div>';
                return;
            }
            this.results.innerHTML = items.map(i => `
                <div class="search-result-item u-pointer" data-result-type="${this._esc(i.type || '')}" data-result-id="${this._esc(i.id || '')}">
                    <span class="search-result-type"><span class="admin-badge info">${this._esc(i.type || 'item')}</span></span>
                    <div class="search-result-info">
                        <div class="search-result-title">${this._esc(i.title || i.id || '')}</div>
                        ${i.subtitle ? `<div class="search-result-subtitle">${this._esc(i.subtitle)}</div>` : ''}
                        ${i.excerpt ? `<div class="search-result-excerpt">${this._esc(i.excerpt)}</div>` : ''}
                    </div>
                </div>
            `).join('');
            this.results.querySelectorAll('.search-result-item').forEach(item => {
                item.addEventListener('click', () => {
                    this._openResult(item.dataset.resultType, item.dataset.resultId);
                });
            });
        } catch (e) {
            this.results.innerHTML = `<div class="admin-error">Search failed: ${this._esc(e.message)}</div>`;
        }
    }
}

// ============================================================
// Plan Mode UI Components
// ============================================================

    global.ConfigView = ConfigView;
    global.GlobalSearch = GlobalSearch;
    global.NexusShellViews = Object.freeze({
        ConfigView,
        GlobalSearch,
    });
})(window);
