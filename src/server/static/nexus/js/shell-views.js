/**
 * Nexus shell views extracted from a previously working app.js implementation.
 * Restores settings/search/plan-mode support that was dropped during shell splitting.
 */
(function initNexusShellViews(global) {
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
                this.app.setDefaultProvider(e.target.value);
                this.app.showToast('Default provider updated', 'success');
                this.app.refreshChatProviders?.();
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
                return `<option value="${p}" ${p === currentDefault ? 'selected' : ''}>${label}</option>`;
            }).join('');
        }

        // Update base provider select for new alias
        const newAliasBase = document.getElementById('newAliasBase');
        if (newAliasBase) {
            newAliasBase.innerHTML = this.app.getDefaultProviders()
                .map(p => `<option value="${p}">${p}</option>`)
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
                return `<option value="${p}">${label}</option>`;
            }).join('');
        }

        // Render concurrency data
        this.renderConcurrency();
    }

    renderProviderModels() {
        const container = document.getElementById('providerModelsContainer');
        if (!container) return;

        const allProviders = this.app.getAllProviders();
        container.innerHTML = allProviders.map(name => {
            const currentModel = this.app.getProviderDefaultModel(name);
            const isAlias = this.app.isCustomAlias(name);
            const label = isAlias ? `${name} <span class="alias-item-base">${this.app.getBaseProvider(name)}</span>` : name;
            return `
                <div class="provider-model-row" data-provider="${name}">
                    <span class="provider-model-label">${label}</span>
                    <input type="text" class="form-input provider-model-input" data-provider="${name}"
                           value="${currentModel}" placeholder="Use provider default"
                          >
                    <button class="action-btn small provider-model-save" data-provider="${name}">Save</button>
                </div>
            `;
        }).join('');

        // Bind save buttons and Enter key
        container.querySelectorAll('.provider-model-save').forEach(btn => {
            btn.addEventListener('click', () => {
                const prov = btn.dataset.provider;
                const input = container.querySelector(`.provider-model-input[data-provider="${prov}"]`);
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

        container.innerHTML = aliases.map(alias => `
            <div class="alias-item" data-alias="${alias.name}">
                <div class="alias-item-info">
                    <span class="alias-item-name">${alias.name}</span>
                    <span class="alias-item-base">${alias.baseProvider}</span>
                    ${alias.configPath ? `<span class="alias-item-path" title="${alias.configPath}">${alias.configPath}</span>` : ''}
                </div>
                <button class="alias-item-delete" title="Delete alias">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');

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
            <div class="mcp-item" data-index="${index}" data-provider="${provider || 'global'}">
                <div class="mcp-item-info">
                    <div class="mcp-item-name">${mcp.name}</div>
                    <div class="mcp-item-command">${mcp.command} ${(mcp.args || []).join(' ')}</div>
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
                <div class="provider-panel" data-provider="${provider}">
                    <div class="provider-panel-header">
                        <div class="provider-panel-title">
                            ${provider}
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
                        <div class="mcp-list" id="providerMcpList-${provider}">
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
            <div class="mcp-item" data-index="${index}" data-provider="${provider}">
                <div class="mcp-item-info">
                    <div class="mcp-item-name">${mcp.name}</div>
                    <div class="mcp-item-command">${mcp.command} ${(mcp.args || []).join(' ')}</div>
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

        const defaultProviders = ['claude', 'codebuddy', 'codex', 'gemini'];
        // Include custom aliases
        const aliasNames = this.app.getCustomProviderNames();
        const allProviders = [...defaultProviders, ...aliasNames.filter(n => !defaultProviders.includes(n))];
        // Also include any extra providers from the response
        for (const key of Object.keys(providersSkills)) {
            if (!allProviders.includes(key)) allProviders.push(key);
        }

        // Default provider config dirs (for display)
        const _DEFAULT_CONFIG_DIRS = {
            claude: '~/.claude', codebuddy: '~/.codebuddy', codex: '~/.codex', gemini: '~/.gemini'
        };

        container.innerHTML = allProviders.map(provider => {
            const skills = providersSkills[provider] || [];
            const isAlias = this.app.isCustomAlias(provider);
            const baseInfo = isAlias ? ` <span class="alias-item-base">${this.app.getBaseProvider(provider)}</span>` : '';
            // Show config path for both default providers and aliases
            let configPath;
            if (isAlias) {
                configPath = this.app.getAliasConfigPath(provider) || '';
            } else {
                configPath = _DEFAULT_CONFIG_DIRS[provider] || '';
            }
            const pathInfo = configPath ? ` <span class="alias-item-path" title="${configPath}">${configPath}</span>` : '';
            return `
                <div class="provider-panel expanded" data-provider="${provider}" data-config-path="${configPath || ''}">
                    <div class="provider-panel-header">
                        <div class="provider-panel-title">
                            ${provider}${baseInfo}${pathInfo}
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
                        <div class="skills-list" id="providerSkillsList-${provider}">
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

        return skills.map(skill => `
            <div class="skill-card" data-provider="${provider}" data-skill-name="${skill.name}">
                <div class="skill-card-info">
                    <div class="skill-card-name">${skill.name}</div>
                    ${skill.description ? `<div class="skill-card-desc">${skill.description.length > 120 ? skill.description.slice(0, 120) + '...' : skill.description}</div>` : ''}
                    <div class="skill-card-meta">
                        ${skill.version ? `<span class="skill-card-version">v${skill.version}</span>` : ''}
                        ${skill.path ? `<span class="skill-card-path" title="${skill.path}">${skill.path.length > 40 ? '...' + skill.path.slice(-37) : skill.path}</span>` : ''}
                    </div>
                </div>
                <button class="skill-card-delete" title="Delete skill">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                    </svg>
                </button>
            </div>
        `).join('');
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
            <div class="mcp-item" data-provider-name="${name}">
                <div class="mcp-item-info">
                    <div class="mcp-item-name">${name}</div>
                    <div class="mcp-item-command">Max: ${limit}</div>
                </div>
                <button class="mcp-item-delete concurrency-remove-btn" title="Remove limit" data-name="${name}">
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
class AdminView {
    constructor(app) {
        this.app = app;
        this.activeTab = 'overview';
        this.container = document.getElementById('adminContent');
        this.bindEvents();
    }

    bindEvents() {
        document.querySelectorAll('.admin-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.switchTab(tab.dataset.adminTab);
            });
        });
    }

    switchTab(tabName) {
        this.activeTab = tabName;
        document.querySelectorAll('.admin-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.adminTab === tabName);
        });
        this.renderActiveTab();
    }

    refresh() { this.renderActiveTab(); }

    renderActiveTab() {
        if (!this.container) return;
        const renderers = {
            overview: () => this.renderOverview(),
            onboarding: () => this.renderOnboardingTab(),
            security: () => this.renderSecurity(),
            runtimes: () => this.renderRuntimes(),
            search: () => this.renderSearch(),
            audit: () => this.renderAudit(),
            cleanup: () => this.renderCleanup(),
            tools: () => this.renderTools(),
            // New tabs — merged from panels
            agents: () => this.renderAgentsTab(),
            activity: () => this.renderActivityTab(),
            memory: () => this.renderMemoryTab(),
            integrations: () => this.renderIntegrationsTab(),
            admin: () => this.renderAdminTab(),
            permissions: () => this.renderPermissionsTab(),
            sessions: () => this.renderSessionsTab(),
            missions: () => this.renderMissionsTab(),
            runs: () => this.renderRunsTab(),
            evolution: () => this.renderEvolutionTab(),
            // Extended tabs — panel content appended
            scheduling: () => this.renderSchedulingTab(),
        };
        (renderers[this.activeTab] || renderers.overview)();
    }

    _esc(str) { return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
    _showLoading() { this.container.innerHTML = '<div class="admin-loading">Loading...</div>'; }
    _showError(msg) { this.container.innerHTML = `<div class="admin-error">${this._esc(msg)}</div>`; }
    _fmtBytes(b) { if(!b)return'0 B';const u=['B','KB','MB','GB','TB'];const i=Math.floor(Math.log(b)/Math.log(1024));return(b/Math.pow(1024,i)).toFixed(1)+' '+u[i]; }

    // ── Overview Tab ──
    async renderOverview() {
        this._showLoading();
        try {
            const [diag, workload] = await Promise.all([
                NexusAPI.getDiagnostics().catch(() => null),
                NexusAPI.getWorkload().catch(() => null),
            ]);
            if (!diag) { this._showError('Failed to load diagnostics'); return; }
            const sys = diag.system || {}, redis = diag.redis || {}, tasks = diag.tasks || {}, sessions = diag.sessions || {}, wl = workload || {};
            const sig = (wl.recommendation?.action||'normal').toLowerCase().replace(/[^a-z-]/g,'');
            this.container.innerHTML = `
                <div class="admin-section">
                    <h3 class="admin-section-title">System Overview</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">System Info</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Python</span><span class="admin-metric-value">${this._esc(sys.python_version||'N/A')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Platform</span><span class="admin-metric-value">${this._esc(sys.platform||'N/A')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Memory</span><span class="admin-metric-value">${this._fmtBytes(sys.memory_usage_bytes)}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Uptime</span><span class="admin-metric-value">${sys.uptime_seconds?Math.floor(sys.uptime_seconds/3600)+'h':'N/A'}</span></div>
                        </div></div>
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">Redis</span><span class="admin-badge ${redis.connected?'pass':'fail'}">${redis.connected?'Connected':'Down'}</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Version</span><span class="admin-metric-value">${this._esc(redis.version||'N/A')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Memory</span><span class="admin-metric-value">${this._esc(redis.memory_human||'N/A')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Keys</span><span class="admin-metric-value">${redis.total_keys??'N/A'}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Clients</span><span class="admin-metric-value">${redis.connected_clients??'N/A'}</span></div>
                        </div></div>
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">Tasks</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value large">${tasks.total??0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Todo</span><span class="admin-metric-value">${tasks.by_status?.todo??0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Doing</span><span class="admin-metric-value">${tasks.by_status?.doing??0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Done</span><span class="admin-metric-value">${tasks.by_status?.done??0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Failed</span><span class="admin-metric-value">${tasks.by_status?.failed??0}</span></div>
                        </div></div>
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">Sessions</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value large">${sessions.total??0}</span></div>
                        </div></div>
                        <div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">Workload</span><span class="admin-badge ${sig}">${this._esc(wl.recommendation?.action||'N/A')}</span></div><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Active Tasks</span><span class="admin-metric-value">${wl.active_tasks??'N/A'}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Queue Depth</span><span class="admin-metric-value">${wl.queue_depth??'N/A'}</span></div>
                        </div></div>
                    </div>
                    <div class="admin-actions">
                        <button class="action-btn primary" id="adminRefreshBtn">Refresh</button>
                        <button class="action-btn" id="adminExportTasksBtn">Export Tasks</button>
                        <button class="action-btn" id="adminDoctorBtn">Run Diagnostics</button>
                        <button class="action-btn" id="adminDoctorBundleBtn">Download Bundle</button>
                    </div>
                    <div id="adminDoctorResult"></div>
                </div>`;
            document.getElementById('adminRefreshBtn')?.addEventListener('click', () => this.renderOverview());
            document.getElementById('adminExportTasksBtn')?.addEventListener('click', async () => {
                try { const d=await NexusAPI.exportData('tasks','json');const b=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download='tasks_export.json';a.click();URL.revokeObjectURL(u); } catch(e){alert('Export failed: '+e.message);}
            });
            // Doctor/Diagnostic buttons
            document.getElementById('adminDoctorBtn')?.addEventListener('click', async () => {
                const area = document.getElementById('adminDoctorResult');
                if (!area) return;
                area.innerHTML = '<div class="admin-loading">Running diagnostics...</div>';
                try {
                    const result = await NexusAPI.getDoctor();
                    area.innerHTML = `<div class="admin-tool-result"><pre class="admin-json-pre">${this._esc(JSON.stringify(result, null, 2))}</pre></div>`;
                } catch (e) { area.innerHTML = `<div class="admin-error">${this._esc(e.message)}</div>`; }
            });
            document.getElementById('adminDoctorBundleBtn')?.addEventListener('click', async () => {
                try {
                    const result = await NexusAPI.getDoctorBundle();
                    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'doctor-bundle.json';
                    a.click();
                    URL.revokeObjectURL(url);
                } catch (e) { alert('Bundle failed: ' + e.message); }
            });
        } catch(e) { this._showError('Failed to load overview: '+e.message); }
    }

    // ── Onboarding / Setup Tab ──
    async renderOnboardingTab() {
        this._showLoading();
        try {
            const readiness = await NexusAPI.getSetupReadiness();
            const checks = readiness.checks || [];
            const readyBadge = readiness.ready ? 'badge-ok' : 'badge-warn';
            const readyLabel = readiness.ready ? 'Ready' : 'Needs attention';

            this.container.innerHTML = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Setup Readiness</h3>
                    <div class="admin-cards">
                        <div class="admin-card">
                            <div class="admin-card-header">
                                <span class="admin-card-title">Onboarding Status</span>
                                <span class="admin-badge ${readyBadge}">${readyLabel}</span>
                            </div>
                            <div class="admin-card-body">
                                <div class="admin-metric"><span class="admin-metric-label">Backend</span><span class="admin-metric-value">${this._esc(readiness.backend || 'sqlite')}</span></div>
                                <div class="admin-metric"><span class="admin-metric-label">Required checks</span><span class="admin-metric-value">${readiness.passed_required || 0}/${readiness.total_required || 0}</span></div>
                            </div>
                        </div>
                    </div>
                    <div class="admin-actions">
                        <button class="action-btn primary" id="setupRefreshBtn">Refresh checks</button>
                        <button class="action-btn" id="setupTipsBtn">Show setup tips</button>
                    </div>
                    <div id="setupTipsArea"></div>
                    <div class="u-mt-lg">
                        ${checks.length === 0 ? '<div class="admin-empty">No setup checks available.</div>' : checks.map(check => `
                            <div class="panel-list-item">
                                <div class="panel-list-item-body">
                                    <div class="panel-list-item-title">${this._esc(check.name || '')}</div>
                                    <div class="panel-list-item-sub">${this._esc(check.message || '')}</div>
                                    ${check.detail && Object.keys(check.detail).length ? `<pre class="admin-json-pre-secondary">${this._esc(JSON.stringify(check.detail, null, 2))}</pre>` : ''}
                                </div>
                                <span class="panel-badge ${check.status === 'ready' ? 'badge-ok' : (check.status === 'warning' ? 'badge-warn' : 'badge-fail')}">${this._esc(check.status || 'unknown')}</span>
                            </div>
                        `).join('')}
                    </div>
                    <div class="u-mt-lg">
                        <h4 class="admin-section-subtitle">Next steps</h4>
                        ${readiness.next_steps && readiness.next_steps.length ? readiness.next_steps.map(step => `<div class="panel-list-item"><div class="panel-list-item-body"><div class="panel-list-item-title">${this._esc(step)}</div></div></div>`).join('') : '<div class="admin-empty">No next steps — you are ready to go.</div>'}
                    </div>
                </div>
            `;

            document.getElementById('setupRefreshBtn')?.addEventListener('click', () => this.renderOnboardingTab());
            document.getElementById('setupTipsBtn')?.addEventListener('click', () => {
                const area = document.getElementById('setupTipsArea');
                if (!area) return;
                area.innerHTML = `
                    <div class="admin-card u-mt-md">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">SQLite</span><span class="admin-metric-value">Primary storage backend</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Tip</span><span class="admin-metric-value">Refresh Overview after first task creation to verify the runtime loop</span></div>
                        </div>
                    </div>
                `;
            });
        } catch(e) {
            this._showError('Failed to load onboarding readiness: '+e.message);
        }
    }

    // ── Security Tab (extended with panel content) ──
    async renderSecurity() {
        this._showLoading();
        try {
            const [secData, auditData, pendingPerms, hookProfile] = await Promise.all([
                NexusAPI.getSecurityScan().catch(() => null),
                NexusAPI.getAuditLog({ limit: 50 }).catch(() => ({ entries: [] })),
                NexusAPI.getPendingPermissions().catch(() => ({ requests: [] })),
                NexusAPI.getHookProfile().catch(() => null),
            ]);
            if (!secData) { this._showError('Failed to load security scan'); return; }
            const grade = (secData.overall||'unknown').toLowerCase().replace(/[^a-z-]/g,'');
            const ico = (s) => s==='pass'||s===true?'&#x2705;':s==='warn'||s==='warning'?'&#x26A0;&#xFE0F;':'&#x274C;';
            let cats = '';
            for (const [n, cd] of Object.entries(secData.categories||{})) {
                const cks = (cd.checks||[]).map(c=>`<div class="security-check"><span class="security-check-icon">${ico(c.status)}</span><div class="security-check-info"><div class="security-check-name">${this._esc(c.name||c.check||'')}</div>${c.detail?`<div class="security-check-detail">${this._esc(c.detail)}</div>`:''}${c.fix?`<div class="security-check-fix">Fix: ${this._esc(c.fix)}</div>`:''}</div></div>`).join('');
                cats += `<div class="admin-card"><div class="admin-card-header"><span class="admin-card-title">${this._esc(n)}</span><span class="admin-badge ${(cd.status||'').toLowerCase()}">${cd.score??''}/100</span></div><div class="security-checks">${cks||'<div class="admin-metric-label">No checks</div>'}</div></div>`;
            }

            // Security Audit (from security-audit panel)
            const secEntries = auditData.entries || auditData.logs || [];
            const highRisk = secEntries.filter(e => e.level === 'error' || e.severity === 'high').length;
            let secAuditHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Security Audit</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Entries</span><span class="admin-metric-value">${secEntries.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">High Risk</span><span class="admin-metric-value admin-metric-value-error">${highRisk}</span></div>
                        </div></div>
                    </div>
                    ${secEntries.length === 0 ? '<div class="u-empty-state-lg">No audit entries</div>' :
                      secEntries.slice(0, 20).map(e => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(e.action || e.event_type || 'Audit Event')}</div>
                                <div class="panel-list-item-sub">${e.timestamp ? new Date(e.timestamp).toLocaleString() : ''} ${e.username ? '&middot; ' + this._esc(e.username) : ''}</div>
                            </div>
                            <span class="panel-badge ${e.level === 'error' || e.severity === 'high' ? 'badge-error' : e.level === 'warning' ? 'badge-warn' : 'badge-ok'}">${e.level || e.severity || 'info'}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Trust Scores (from trust-score panel)
            const trustScores = secData.trust_scores || secData.scores || [];
            let trustHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Trust Scores</h3>
                    ${trustScores.length === 0 ? '<div class="u-empty-state-lg">No trust scores available</div>' :
                      trustScores.map(s => {
                        const score = s.score ?? s.trust_score ?? 0;
                        const level = score >= 80 ? 'high' : score >= 50 ? 'medium' : 'low';
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(s.agent_id || s.name || 'Agent')}</div>
                                <div class="panel-list-item-sub">${this._esc(s.reason || level + ' trust level')}</div>
                            </div>
                            <div class="panel-trust-score score-${level}">
                                <span class="score-value">${score}</span><span class="score-max">/100</span>
                            </div>
                        </div>`;
                    }).join('')}
                </div>`;

            // Hook Profiles from API
            const apiHooks = hookProfile ? (hookProfile.hooks || hookProfile.profiles || []) : [];
            const allHooks = [...(secData.hook_profiles || secData.hooks || []), ...apiHooks];
            let hooksHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Hook Profiles</h3>
                    ${allHooks.length === 0 ? '<div class="u-empty-state-lg">No hook profiles configured</div>' :
                      allHooks.map(h => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(h.name || h.id || 'Hook')}</div>
                                <div class="panel-list-item-sub">${this._esc(h.type || h.event || '')} &middot; ${this._esc(h.action || 'log')}</div>
                            </div>
                            <span class="panel-badge ${h.enabled !== false ? 'badge-ok' : 'badge-muted'}">${h.enabled !== false ? 'Active' : 'Disabled'}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Pending Permission Requests from API
            const pendingRequests = pendingPerms.requests || pendingPerms.pending || [];
            let pendingPermsHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Pending Permission Requests ${pendingRequests.length > 0 ? `<span class="admin-badge warn u-ml-sm">${pendingRequests.length}</span>` : ''}</h3>
                    ${pendingRequests.length === 0 ? '<div class="u-empty-state-lg">No pending requests</div>' :
                      pendingRequests.map(p => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(p.tool || p.action || p.permission || 'Request')}</div>
                                <div class="panel-list-item-sub">${this._esc(p.agent_id || p.requester || '')} &middot; ${this._esc(p.reason || '')}</div>
                            </div>
                            <button class="action-btn compact btn-success" data-perm-id="${this._esc(p.id)}" data-action="approve-perm">Approve</button>
                            <button class="action-btn danger compact" data-perm-id="${this._esc(p.id)}" data-action="reject-perm">Reject</button>
                        </div>
                    `).join('')}
                    <div class="u-mt-sm">
                        <button class="action-btn u-text-sm" id="syncPermsBtn">Sync Permissions</button>
                    </div>
                </div>`;

            // Permissions (from permission panel)
            const permissions = secData.permissions || secData.acl || [];
            let permHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Permissions</h3>
                    ${permissions.length === 0 ? '<div class="u-empty-state-lg">No permission entries</div>' :
                      permissions.map(p => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(p.subject || p.role || 'Role')}</div>
                                <div class="panel-list-item-sub">${this._esc(p.resource || p.scope || '')}: ${this._esc(p.action || p.permission || 'read')}</div>
                            </div>
                            <span class="panel-badge ${p.granted !== false ? 'badge-ok' : 'badge-error'}">${p.granted !== false ? 'Granted' : 'Denied'}</span>
                        </div>
                    `).join('')}
                </div>`;

            this.container.innerHTML = `<div class="admin-section"><div class="admin-inline-heading"><h3 class="admin-section-title u-mb-0">Security Scan</h3><span class="admin-badge ${grade} admin-badge-lg">${secData.score}/100 — ${this._esc(secData.overall||'Unknown')}</span></div><div class="admin-cards">${cats}</div><div class="admin-actions"><button class="action-btn primary" id="adminRescanBtn">Re-scan</button></div></div>` + secAuditHtml + trustHtml + hooksHtml + pendingPermsHtml + permHtml;
            document.getElementById('adminRescanBtn')?.addEventListener('click', () => this.renderSecurity());

            // Bind permission actions
            this.container.querySelectorAll('[data-action="approve-perm"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try { await NexusAPI.approvePermission(btn.dataset.permId); this.renderSecurity(); }
                    catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="reject-perm"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try { await NexusAPI.rejectPermission(btn.dataset.permId); this.renderSecurity(); }
                    catch (e) { alert(e.message); }
                });
            });
            document.getElementById('syncPermsBtn')?.addEventListener('click', async () => {
                try { await NexusAPI.triggerPermissionSync(); this.app?.showToast?.('Permission sync triggered', 'success'); }
                catch (e) { this.app?.showToast?.(e.message, 'error'); }
            });
        } catch(e) { this._showError('Failed to load security scan: '+e.message); }
    }

    // ── Runtimes Tab ──
    async renderRuntimes() {
        this._showLoading();
        try {
            const data = await NexusAPI.getAgentRuntimes();
            const runtimes = data.runtimes || [];
            let cards = runtimes.map(r => `
                <div class="admin-card">
                    <div class="admin-card-header">
                        <span class="admin-card-title">${this._esc(r.name)}</span>
                        <span class="admin-badge ${r.installed ? 'pass' : 'fail'}">${r.installed ? 'Installed' : 'Not Found'}</span>
                    </div>
                    <div class="admin-card-body">
                        <div class="admin-metric"><span class="admin-metric-label">ID</span><span class="admin-metric-value">${this._esc(r.id)}</span></div>
                        <div class="admin-metric"><span class="admin-metric-label">Version</span><span class="admin-metric-value">${this._esc(r.version || 'N/A')}</span></div>
                        <div class="admin-metric"><span class="admin-metric-label">Binary</span><span class="admin-metric-value u-text-xs">${this._esc(r.binary_path || 'N/A')}</span></div>
                        <div class="admin-metric"><span class="admin-metric-label">Auth</span><span class="admin-metric-value">${r.auth_required ? (r.authenticated ? '&#x2705; Authenticated' : '&#x274C; Not authenticated') : '&#x2796; Not required'}</span></div>
                        ${r.auth_hint && !r.authenticated ? `<div class="u-text-xs u-note-primary">${this._esc(r.auth_hint)}</div>` : ''}
                    </div>
                </div>
            `).join('');
            this.container.innerHTML = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Agent Runtimes</h3>
                    <p class="admin-section-desc">${data.installed_count} of ${data.total} runtimes installed</p>
                    <div class="admin-cards">${cards}</div>
                    <div class="admin-actions"><button class="action-btn primary" id="adminRuntimeRefreshBtn">Re-detect</button></div>
                </div>`;
            document.getElementById('adminRuntimeRefreshBtn')?.addEventListener('click', () => this.renderRuntimes());
        } catch(e) { this._showError('Failed to detect runtimes: '+e.message); }
    }

    // ── Search Tab ──
    renderSearch() {
        this.container.innerHTML = `<div class="admin-section"><h3 class="admin-section-title">Global Search</h3><div class="admin-search-box"><input type="text" class="form-input" id="adminSearchInput" placeholder="Search tasks, sessions..." autofocus><select class="form-input form-select u-w-140" id="adminSearchType"><option value="all">All</option><option value="task">Tasks</option><option value="session">Sessions</option></select><button class="action-btn primary" id="adminSearchBtn">Search</button></div><div id="adminSearchResults" class="search-results"><div class="u-empty-state-xl">Enter a search query above</div></div></div>`;
        const doSearch = async () => {
            const q=document.getElementById('adminSearchInput')?.value?.trim(); if(!q)return;
            const type=document.getElementById('adminSearchType')?.value||'all';
            const res=document.getElementById('adminSearchResults');
            res.innerHTML='<div class="admin-loading">Searching...</div>';
            try {
                const data=await NexusAPI.globalSearch(q,type); const items=data.results||[];
                if(!items.length){res.innerHTML='<div class="u-empty-state-xl">No results found</div>';return;}
                res.innerHTML=items.map(i=>`<div class="search-result-item"><span class="search-result-type"><span class="admin-badge info">${this._esc(i.type||'item')}</span></span><div class="search-result-info"><div class="search-result-title">${this._esc(i.title||i.id||'')}</div>${i.subtitle?`<div class="search-result-subtitle">${this._esc(i.subtitle)}</div>`:''}${i.excerpt?`<div class="search-result-excerpt">${this._esc(i.excerpt)}</div>`:''}</div></div>`).join('');
            } catch(e){res.innerHTML=`<div class="admin-error">Search failed: ${this._esc(e.message)}</div>`;}
        };
        document.getElementById('adminSearchBtn')?.addEventListener('click',doSearch);
        document.getElementById('adminSearchInput')?.addEventListener('keydown',e=>{if(e.key==='Enter')doSearch();});
    }

    // ── Audit Tab ──
    async renderAudit(params={}) {
        this._showLoading();
        try {
            const data=await NexusAPI.getAuditLog({limit:params.limit||100,action:params.action||''});
            const events=data.events||data.entries||[];
            let tbl='';
            if(!events.length){tbl='<div class="u-empty-state-xl">No audit events found</div>';}
            else{const rows=events.map(e=>`<tr><td class="u-font-mono u-text-xs">${this._esc(e.id||e.event_id||'-')}</td><td><span class="admin-badge info">${this._esc(e.action||'')}</span></td><td>${this._esc(e.actor||e.user||'-')}</td><td class="u-max-w-300 u-ellipsis">${this._esc(e.detail||e.details||'-')}</td><td class="u-nowrap">${this._esc(e.timestamp||e.created_at||'-')}</td></tr>`).join('');
                tbl=`<div class="audit-table-wrapper"><table class="audit-table"><thead><tr><th>ID</th><th>Action</th><th>Actor</th><th>Detail</th><th>Timestamp</th></tr></thead><tbody>${rows}</tbody></table></div>`;}
            this.container.innerHTML=`<div class="admin-section"><h3 class="admin-section-title">Audit Log</h3><div class="admin-filter-row"><select class="form-input form-select" id="auditActionFilter"><option value="">All Actions</option><option value="task.create">task.create</option><option value="task.update">task.update</option><option value="task.delete">task.delete</option><option value="session.create">session.create</option><option value="session.delete">session.delete</option></select><button class="action-btn primary" id="auditFilterBtn">Filter</button><button class="action-btn" id="auditRefreshBtn">Refresh</button></div>${tbl}</div>`;
            document.getElementById('auditFilterBtn')?.addEventListener('click',()=>{this.renderAudit({action:document.getElementById('auditActionFilter')?.value||''});});
            document.getElementById('auditRefreshBtn')?.addEventListener('click',()=>this.renderAudit(params));
        } catch(e){this._showError('Failed to load audit log: '+e.message);}
    }

    // ── Cleanup Tab ──
    async renderCleanup() {
        this._showLoading();
        try {
            const data=await NexusAPI.getCleanupPreview();const policy=data.retention_policy||data.policy||{};const preview=data.preview||data.expired||[];
            let pol='';for(const[k,d]of Object.entries(policy)){pol+=`<div class="cleanup-policy-card"><div class="cleanup-policy-label">${this._esc(k)}</div><div class="cleanup-policy-value">${this._esc(d)}<span class="cleanup-policy-unit"> days</span></div></div>`;}
            let prev='';
            if(Array.isArray(preview)&&preview.length>0){const rows=preview.map(p=>`<tr><td>${this._esc(p.category||p.type||'-')}</td><td>${p.retention_days??'-'}</td><td>${this._esc(p.cutoff_date||'-')}</td><td><strong>${p.expired_count??p.count??0}</strong></td></tr>`).join('');prev=`<div class="audit-table-wrapper"><table class="audit-table"><thead><tr><th>Category</th><th>Retention (days)</th><th>Cutoff Date</th><th>Expired Count</th></tr></thead><tbody>${rows}</tbody></table></div>`;}
            else{prev='<div class="u-empty-state-lg">No expired data found</div>';}
            this.container.innerHTML=`<div class="admin-section"><h3 class="admin-section-title">Data Retention & Cleanup</h3><p class="admin-section-desc">Review retention policies and clean up expired data.</p>${pol?`<div class="cleanup-policy-cards">${pol}</div>`:''}<h4 class="u-font-semibold u-text-primary u-mb-sm">Expired Data Preview</h4>${prev}<div class="admin-actions u-mt-lg"><button class="action-btn" id="adminDryRunBtn">Dry Run</button><button class="action-btn primary btn-danger-solid" id="adminExecuteCleanupBtn">Execute Cleanup</button><button class="action-btn" id="adminCleanupRefreshBtn">Refresh</button></div><div id="cleanupResultArea"></div></div>`;
            document.getElementById('adminDryRunBtn')?.addEventListener('click',async()=>{const a=document.getElementById('cleanupResultArea');a.innerHTML='<div class="admin-loading">Running dry run...</div>';try{const r=await NexusAPI.executeCleanup(true);a.innerHTML=`<div class="admin-tool-result"><pre class="admin-json-pre">${this._esc(JSON.stringify(r, null, 2))}</pre></div>`;}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
            document.getElementById('adminExecuteCleanupBtn')?.addEventListener('click',async()=>{if(!confirm('Are you sure you want to execute cleanup?'))return;const a=document.getElementById('cleanupResultArea');a.innerHTML='<div class="admin-loading">Executing cleanup...</div>';try{const r=await NexusAPI.executeCleanup(false);a.innerHTML=`<div class="admin-tool-result"><pre class="admin-json-pre">${this._esc(JSON.stringify(r, null, 2))}</pre></div>`;setTimeout(()=>this.renderCleanup(),1500);}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
            document.getElementById('adminCleanupRefreshBtn')?.addEventListener('click',()=>this.renderCleanup());
        } catch(e){this._showError('Failed to load cleanup data: '+e.message);}
    }

    // ── Tools Tab ──
    renderTools() {
        this.container.innerHTML=`<div class="admin-section"><h3 class="admin-section-title">Tools</h3><div class="admin-tool-section"><div class="admin-tool-title">Schedule Parser</div><div class="admin-tool-desc">Parse natural language into a cron expression.</div><div class="u-flex u-gap-sm"><input type="text" class="form-input u-flex-1" id="scheduleParseInput" placeholder="e.g., every weekday at 9am"><button class="action-btn primary" id="scheduleParseBtn">Parse</button></div><div id="scheduleParseResult"></div></div><div class="admin-tool-section"><div class="admin-tool-title">Data Export</div><div class="admin-tool-desc">Export tasks or sessions data.</div><div class="u-row-wrap"><select class="form-input form-select u-w-160" id="exportType"><option value="tasks">Tasks</option><option value="sessions">Sessions</option></select><select class="form-input form-select u-w-120" id="exportFormat"><option value="json">JSON</option><option value="csv">CSV</option></select><button class="action-btn primary" id="exportBtn">Download</button></div><div id="exportResult"></div></div><div class="admin-tool-section"><div class="admin-tool-title">Standup Report</div><div class="admin-tool-desc">Generate a summary report of recent task activity.</div><button class="action-btn primary" id="standupBtn">Generate Report</button><div id="standupResult"></div></div></div>`;
        document.getElementById('scheduleParseBtn')?.addEventListener('click',async()=>{const i=document.getElementById('scheduleParseInput')?.value?.trim();if(!i)return;const a=document.getElementById('scheduleParseResult');a.innerHTML='<div class="admin-loading">Parsing...</div>';try{const d=await NexusAPI.parseSchedule(i);a.innerHTML=`<div class="admin-tool-result"><pre class="admin-json-pre">${this._esc(JSON.stringify(d, null, 2))}</pre></div>`;}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
        document.getElementById('scheduleParseInput')?.addEventListener('keydown',e=>{if(e.key==='Enter')document.getElementById('scheduleParseBtn')?.click();});
        document.getElementById('exportBtn')?.addEventListener('click',async()=>{const t=document.getElementById('exportType')?.value||'tasks';const f=document.getElementById('exportFormat')?.value||'json';const a=document.getElementById('exportResult');a.innerHTML='<div class="admin-loading">Exporting...</div>';try{const d=await NexusAPI.exportData(t,f);const blob=new Blob([f==='csv'?d:JSON.stringify(d,null,2)],{type:f==='csv'?'text/csv':'application/json'});const u=URL.createObjectURL(blob);const l=document.createElement('a');l.href=u;l.download=`${t}_export.${f}`;l.click();URL.revokeObjectURL(u);a.innerHTML=`<div class="admin-download-success">Downloaded ${f.toUpperCase()} file</div>`;}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
        document.getElementById('standupBtn')?.addEventListener('click',async()=>{const a=document.getElementById('standupResult');a.innerHTML='<div class="admin-loading">Generating report...</div>';try{const d=await NexusAPI.getStandup();a.innerHTML=`<div class="admin-tool-result"><pre class="admin-json-pre">${this._esc(JSON.stringify(d, null, 2))}</pre></div>`;}catch(e){a.innerHTML=`<div class="admin-error">${this._esc(e.message)}</div>`;}});
    }

    // ============================================================
    // New Tabs — Merged from Panel framework
    // ============================================================

    // ── Agents Tab ──
    async renderAgentsTab() {
        this._showLoading();
        try {
            const [agentsData, workload, statsData] = await Promise.all([
                NexusAPI.getAgents().catch(() => ({ agents: [] })),
                NexusAPI.getWorkload().catch(() => ({})),
                NexusAPI.getAgentStats().catch(() => ({})),
            ]);
            const agents = agentsData.agents || [];
            const queues = workload.agents || workload.queues || [];
            const stats = statsData.stats || statsData;

            // Agent Registry with API stats
            const online = agents.filter(a => a.available).length;
            const totalTasks = stats.total_tasks || stats.tasks_total || 0;
            const avgResponse = stats.avg_response_ms ?? stats.avg_response ?? '-';
            let registryHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Agent Registry</h3>
                    <button class="action-btn primary" id="registerAgentBtn">Register Agent</button>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value large">${agents.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Online</span><span class="admin-metric-value admin-metric-value-success">${online}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Offline</span><span class="admin-metric-value u-text-tertiary">${agents.length - online}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Avg Response</span><span class="admin-metric-value">${avgResponse}${typeof avgResponse === 'number' ? 'ms' : ''}</span></div>
                        </div></div>
                    </div>
                    ${agents.length === 0 ? '<div class="u-empty-state-lg">No agents found</div>' :
                      agents.map(a => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-icon ${a.available ? 'status-online' : 'status-offline'}">
                                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                            </div>
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(a.display_name || a.id)}</div>
                                <div class="panel-list-item-sub">${this._esc(a.agent_type || '')} &middot; ${this._esc(a.username || '')} ${a.last_active ? '&middot; Last: ' + new Date(a.last_active).toLocaleString() : ''}</div>
                            </div>
                            <span class="panel-badge ${a.available ? 'badge-ok' : 'badge-muted'}">${a.available ? 'Online' : 'Offline'}</span>
                            ${!a.available ? `<button class="action-btn compact u-ml-sm" data-agent-id="${this._esc(a.id)}" data-action="deregister-agent" title="Deregister agent">Remove</button>` : ''}
                        </div>
                    `).join('')}
                </div>`;

            // Agent Heartbeat with API data
            let heartbeatHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Agent Heartbeat</h3>
                    ${agents.length === 0 ? '<div class="u-empty-state-lg">No heartbeat data</div>' :
                      agents.slice(0, 10).map(a => `
                        <div class="panel-list-item">
                            <div class="timeline-dot ${a.available ? 'status-online' : 'status-offline'}"></div>
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(a.display_name || a.id)}</div>
                                <div class="panel-list-item-sub">${a.last_active ? new Date(a.last_active).toLocaleString() : 'Unknown'} &middot; ${a.available ? 'OK' : 'Offline'}</div>
                            </div>
                            ${a.available ? `<button class="action-btn compact" data-agent-id="${this._esc(a.id)}" data-action="agent-heartbeat" title="Send heartbeat">Ping</button>` : ''}
                        </div>
                    `).join('')}
                </div>`;

            // Agent Soul
            let soulHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Agent Soul Profiles</h3>
                    ${agents.length === 0 ? '<div class="u-empty-state-lg">No soul profiles</div>' :
                      agents.map(a => {
                        const soul = a.soul || a.identity;
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(a.display_name || a.id)}</div>
                                <div class="panel-list-item-sub">${this._esc(a.agent_type || '')}</div>
                                ${soul ? `<pre class="panel-code panel-code-top-xs">${this._esc(typeof soul === 'string' ? soul : JSON.stringify(soul, null, 2))}</pre>` : '<div class="u-text-tertiary u-text-xs">No soul profile configured</div>'}
                            </div>
                        </div>`;
                    }).join('')}
                </div>`;

            // Agent Queue
            const totalPending = queues.reduce((s, q) => s + (q.pending || q.queued || 0), 0);
            const totalRunning = queues.reduce((s, q) => s + (q.running || 0), 0);
            let queueHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Agent Queue</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Pending</span><span class="admin-metric-value large">${totalPending}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Running</span><span class="admin-metric-value admin-metric-value-success">${totalRunning}</span></div>
                        </div></div>
                    </div>
                    ${queues.length === 0 ? '<div class="u-empty-state-lg">No queue data</div>' :
                      queues.map(q => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(q.agent_id || q.name || 'Unknown')}</div>
                                <div class="panel-list-item-sub">Pending: ${q.pending || q.queued || 0} &middot; Running: ${q.running || 0}</div>
                            </div>
                            <div class="panel-queue-bar"><progress class="queue-bar-progress" max="100" value="${Math.min(100, ((q.running || 0) / Math.max(1, (q.capacity || 5))) * 100)}"></progress></div>
                        </div>
                    `).join('')}
                </div>`;

            // Agent Messaging
            let messagingHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Agent Messaging</h3>
                    <div id="agentMessagingContent"><div class="u-empty-state-lg">No messages yet</div></div>
                </div>`;

            // Swarm Teams
            let teamsHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Swarm Teams</h3>
                    <button class="action-btn primary u-mb-sm" id="createTeamBtn">Create Team</button>
                    <div id="teamsList"><div class="u-empty-state-lg">Loading teams...</div></div>
                </div>`;

            this.container.innerHTML = registryHtml + heartbeatHtml + soulHtml + queueHtml + messagingHtml + teamsHtml;

            // Load messaging data lazily
            try {
                const msgData = await NexusAPI.getAuditLog({ action: 'message', limit: 30 });
                const messages = msgData.entries || msgData.logs || [];
                const mc = document.getElementById('agentMessagingContent');
                if (mc && messages.length > 0) {
                    mc.innerHTML = messages.map(m => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(m.from || m.agent_id || 'System')}</div>
                                <div class="panel-list-item-sub">${m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : ''} &middot; ${this._esc(m.content || m.message || m.action || '')}</div>
                            </div>
                        </div>
                    `).join('');
                }
            } catch (e) { /* ignore */ }

            // Load teams
            try {
                const teamsList = document.getElementById('teamsList');
                const teamsData = await NexusAPI.getAgents().catch(() => ({}));
                const teamNames = (teamsData.teams || []);
                if (teamNames.length === 0) {
                    teamsList.innerHTML = '<div class="u-empty-state-lg">No teams</div>';
                } else {
                    teamsList.innerHTML = teamNames.map(t => {
                        const name = typeof t === 'string' ? t : (t.name || t.id);
                        return `<div class="panel-list-item">
                            <div class="panel-list-item-body"><div class="panel-list-item-title">${this._esc(name)}</div></div>
                            <button class="action-btn compact" data-team-name="${this._esc(name)}" data-action="team-status">Status</button>
                            <button class="action-btn compact" data-team-name="${this._esc(name)}" data-action="team-mailbox">Mailbox</button>
                            <button class="action-btn compact" data-team-name="${this._esc(name)}" data-action="team-claim-task">Claim Task</button>
                            <button class="action-btn danger compact" data-team-name="${this._esc(name)}" data-action="team-shutdown">Shutdown</button>
                        </div>`;
                    }).join('');
                }
            } catch (e) { /* ignore */ }

            // Bind agent lifecycle actions
            this.container.querySelectorAll('[data-action="deregister-agent"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Deregister this agent?')) return;
                    try { await NexusAPI.deregisterAgent(btn.dataset.agentId); this.renderAgentsTab(); }
                    catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="agent-heartbeat"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try { await NexusAPI.agentHeartbeat(btn.dataset.agentId); this.app?.showToast?.('Heartbeat sent', 'success'); }
                    catch (e) { this.app?.showToast?.(e.message, 'error'); }
                });
            });
            this.container.querySelectorAll('[data-action="team-shutdown"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Shutdown team ' + btn.dataset.teamName + '?')) return;
                    try { await NexusAPI.shutdownTeam(btn.dataset.teamName); this.renderAgentsTab(); }
                    catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="team-status"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        const status = await NexusAPI.getTeamStatus(btn.dataset.teamName);
                        alert(JSON.stringify(status, null, 2));
                    } catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="team-mailbox"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const agentId = prompt('Agent ID to view mailbox:');
                    if (!agentId) return;
                    try {
                        const mailbox = await NexusAPI.getAgentMailbox(btn.dataset.teamName, agentId);
                        alert(JSON.stringify(mailbox, null, 2));
                    } catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="team-claim-task"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Claim a task for team ' + btn.dataset.teamName + '?')) return;
                    try {
                        const result = await NexusAPI.claimTeamTask(btn.dataset.teamName);
                        this.app?.showToast?.('Task claimed', 'success');
                    } catch (e) { alert(e.message); }
                });
            });
            document.getElementById('registerAgentBtn')?.addEventListener('click', async () => {
                const id = prompt('Agent ID:');
                if (!id) return;
                const agentType = prompt('Agent type (optional):') || '';
                try { await NexusAPI.registerAgent({ id, agent_type: agentType }); this.renderAgentsTab(); }
                catch (e) { alert(e.message); }
            });
            document.getElementById('createTeamBtn')?.addEventListener('click', async () => {
                const name = prompt('Team name:');
                if (!name) return;
                try { await NexusAPI.createTeam({ name }); this.renderAgentsTab(); }
                catch (e) { alert(e.message); }
            });
        } catch (e) { this._showError('Failed to load agents: ' + e.message); }
    }

    // ── Activity Tab ──
    async renderActivityTab() {
        this._showLoading();
        try {
            const [auditData, diagData] = await Promise.all([
                NexusAPI.getAuditLog({ limit: 50 }).catch(() => ({ entries: [] })),
                NexusAPI.getDiagnostics().catch(() => ({})),
            ]);
            const entries = auditData.entries || auditData.logs || [];
            const tokenUsage = diagData.token_usage || diagData.usage || [];
            const costData = diagData.cost_analysis || diagData.billing || { total: 0, breakdown: [] };

            // Activity Feed
            let feedHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Activity Feed</h3>
                    ${entries.length === 0 ? '<div class="u-empty-state-lg">No activity recorded</div>' :
                      entries.map(e => {
                        const time = e.timestamp ? new Date(e.timestamp).toLocaleString() : '';
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(e.action || e.event_type || 'Activity')}</div>
                                <div class="panel-list-item-sub">${time} ${e.username ? '&middot; ' + this._esc(e.username) : ''}</div>
                            </div>
                        </div>`;
                    }).join('')}
                </div>`;

            // Notifications
            const notifications = entries.filter(e => e.action === 'notification');
            const unread = notifications.filter(n => !n.read).length;
            let notifyHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Notifications ${unread > 0 ? `<span class="admin-badge warn u-ml-sm">${unread} Unread</span>` : ''}</h3>
                    ${notifications.length === 0 ? '<div class="u-empty-state-lg">No notifications</div>' :
                      notifications.map(n => `
                        <div class="panel-list-item ${n.read ? '' : 'unread'}">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(n.action || n.title || 'Notification')}</div>
                                <div class="panel-list-item-sub">${this._esc(n.detail || n.message || '')}</div>
                            </div>
                            <span class="panel-badge ${n.level === 'error' ? 'badge-error' : n.level === 'warning' ? 'badge-warn' : 'badge-ok'}">${n.level || 'info'}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Token Usage
            const totalTokens = tokenUsage.reduce((s, u) => s + (u.total_tokens || u.tokens || 0), 0);
            const totalCost = tokenUsage.reduce((s, u) => s + (u.cost || 0), 0);
            let tokenHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Token Usage</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total Tokens</span><span class="admin-metric-value large">${(totalTokens / 1000).toFixed(1)}k</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Cost</span><span class="admin-metric-value">$${totalCost.toFixed(2)}</span></div>
                        </div></div>
                    </div>
                    ${tokenUsage.length === 0 ? '<div class="u-empty-state-lg">No token usage data</div>' :
                      tokenUsage.map(u => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(u.provider || u.model || 'Unknown')}</div>
                                <div class="panel-list-item-sub">Prompt: ${(u.prompt_tokens || 0).toLocaleString()} &middot; Completion: ${(u.completion_tokens || 0).toLocaleString()} &middot; Total: ${(u.total_tokens || u.tokens || 0).toLocaleString()}</div>
                            </div>
                            <span class="panel-badge">${u.cost != null ? '$' + u.cost.toFixed(4) : ''}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Cost Analysis
            const breakdown = costData.breakdown || [];
            const costTotal = costData.total || 0;
            let costHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Cost Analysis</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total Cost</span><span class="admin-metric-value large">$${costTotal.toFixed(2)}</span></div>
                        </div></div>
                    </div>
                    ${breakdown.length === 0 ? '<div class="u-empty-state-lg">No cost data available</div>' :
                      breakdown.map(b => {
                        const pct = costTotal > 0 ? ((b.cost / costTotal) * 100).toFixed(1) : 0;
                        return `
                        <div class="panel-bar-row">
                            <div class="panel-bar-label">${this._esc(b.provider || b.model || b.label)}</div>
                            <div class="panel-bar-track"><progress class="panel-bar-progress" max="100" value="${pct}"></progress></div>
                            <div class="panel-bar-value">$${(b.cost || 0).toFixed(2)} (${pct}%)</div>
                        </div>`;
                    }).join('')}
                </div>`;

            this.container.innerHTML = feedHtml + notifyHtml + tokenHtml + costHtml;
        } catch (e) { this._showError('Failed to load activity: ' + e.message); }
    }

    // ── Memory Tab ──
    async renderMemoryTab() {
        this._showLoading();
        try {
            const [data, memoryState] = await Promise.all([
                NexusAPI.getAgents().catch(() => ({ agents: [] })),
                NexusAPI.getMemoryState().catch(() => null),
            ]);
            const agents = data.agents || [];
            const memState = memoryState?.state || memoryState;

            // Memory Browser
            const memEntries = agents.map(a => ({
                id: a.id, agent: a.display_name || a.id,
                memory_count: a.memory_count || 0,
                last_updated: a.last_active || new Date().toISOString(),
            }));
            let browserHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Memory Browser</h3>
                    ${memEntries.length === 0 ? '<div class="u-empty-state-lg">No memory entries found</div>' :
                      memEntries.map(e => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(e.agent)}</div>
                                <div class="panel-list-item-sub">${e.memory_count} entries &middot; Updated ${new Date(e.last_updated).toLocaleString()}</div>
                            </div>
                        </div>
                    `).join('')}
                </div>`;

            // Memory Tree
            const tree = agents.map(a => ({
                id: a.id, name: a.display_name || a.id,
                children: [
                    { id: `${a.id}-short`, name: 'Short-term', count: 0 },
                    { id: `${a.id}-long`, name: 'Long-term', count: 0 },
                    { id: `${a.id}-episodic`, name: 'Episodic', count: 0 },
                ],
            }));
            let treeHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Memory Tree</h3>
                    ${tree.length === 0 ? '<div class="u-empty-state-lg">No memory tree data</div>' :
                      tree.map(n => `
                        <div class="u-mb-sm">
                            <div class="panel-group-title">${this._esc(n.name)}</div>
                            ${n.children.map(c => `
                                <div class="panel-tree-row">
                                    <span class="tree-leaf-dot"></span>
                                    <span class="tree-label">${this._esc(c.name)}</span>
                                    <span class="panel-badge">${c.count}</span>
                                </div>
                            `).join('')}
                        </div>
                    `).join('')}
                </div>`;

            // Memory Graph
            const nodes = agents.map(a => ({ id: a.id, label: a.display_name || a.id, available: a.available }));
            const edges = [];
            for (let i = 0; i < agents.length; i++) {
                for (let j = i + 1; j < agents.length; j++) {
                    if (agents[i].username === agents[j].username) {
                        edges.push({ from: agents[i].id, to: agents[j].id });
                    }
                }
            }
            let graphHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Memory Graph</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Nodes</span><span class="admin-metric-value">${nodes.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Edges</span><span class="admin-metric-value">${edges.length}</span></div>
                        </div></div>
                    </div>
                    <div class="panel-graph-container"><canvas class="panel-canvas" id="memoryGraphCanvas" width="600" height="400"></canvas></div>
                </div>`;

            // Memory State from API
            const memSessions = memState?.sessions || memState?.entries || [];
            const memContexts = memState?.contexts || [];
            let memStateHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Memory State</h3>
                    ${memState ? `
                        <div class="admin-cards">
                            <div class="admin-card"><div class="admin-card-body">
                                <div class="admin-metric"><span class="admin-metric-label">Sessions</span><span class="admin-metric-value">${memSessions.length}</span></div>
                                <div class="admin-metric"><span class="admin-metric-label">Contexts</span><span class="admin-metric-value">${memContexts.length}</span></div>
                            </div></div>
                        </div>
                        ${memSessions.length > 0 ? memSessions.slice(0, 10).map(s => `
                            <div class="panel-list-item">
                                <div class="panel-list-item-body">
                                    <div class="panel-list-item-title">${this._esc(s.session_id || s.id || 'Session')}</div>
                                    <div class="panel-list-item-sub">${s.updated_at ? new Date(s.updated_at).toLocaleString() : ''} ${s.message_count ? '&middot; ' + s.message_count + ' messages' : ''}</div>
                                </div>
                                <button class="action-btn compact" data-session-id="${this._esc(s.session_id || s.id)}" data-action="restore-memory">Restore</button>
                            </div>
                        `).join('') : '<div class="u-empty-state-lg">No memory sessions</div>'}
                    ` : '<div class="u-empty-state-lg">Memory state API unavailable</div>'}
                </div>`;

            this.container.innerHTML = browserHtml + treeHtml + memStateHtml + graphHtml;

            // Draw the memory graph
            const canvas = document.getElementById('memoryGraphCanvas');
            if (canvas && nodes.length > 0) {
                const ctx = canvas.getContext('2d');
                const w = canvas.width, h = canvas.height;
                ctx.clearRect(0, 0, w, h);
                const cx = w / 2, cy = h / 2, r = Math.min(w, h) * 0.35;
                const positions = {};
                nodes.forEach((node, i) => {
                    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2;
                    positions[node.id] = { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
                });
                ctx.strokeStyle = 'rgba(100, 160, 255, 0.3)'; ctx.lineWidth = 1;
                for (const edge of edges) {
                    const from = positions[edge.from], to = positions[edge.to];
                    if (from && to) { ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y); ctx.stroke(); }
                }
                const style = getComputedStyle(document.documentElement);
                for (const node of nodes) {
                    const pos = positions[node.id]; if (!pos) continue;
                    ctx.beginPath(); ctx.arc(pos.x, pos.y, 8, 0, 2 * Math.PI);
                    ctx.fillStyle = node.available ? (style.getPropertyValue('--success-500') || '#22c55e') : (style.getPropertyValue('--text-muted') || '#888');
                    ctx.fill(); ctx.strokeStyle = 'rgba(255,255,255,0.2)'; ctx.lineWidth = 1; ctx.stroke();
                    ctx.fillStyle = style.getPropertyValue('--text-primary') || '#fff'; ctx.font = '10px sans-serif'; ctx.textAlign = 'center';
                    ctx.fillText(node.label.split('/').pop(), pos.x, pos.y + 20);
                }
            }

            // Bind restore memory actions
            this.container.querySelectorAll('[data-action="restore-memory"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Restore memory context from this session?')) return;
                    try {
                        await NexusAPI.restoreMemoryContext(btn.dataset.sessionId);
                        this.app?.showToast?.('Memory context restored', 'success');
                    } catch (e) { this.app?.showToast?.(e.message, 'error'); }
                });
            });
        } catch (e) { this._showError('Failed to load memory: ' + e.message); }
    }

    // ── Integrations Tab ──
    async renderIntegrationsTab() {
        this._showLoading();
        try {
            const [diagData, projectsData, runtimeData, teleportSessions] = await Promise.all([
                NexusAPI.getDiagnostics().catch(() => ({})),
                NexusAPI.getProjects().catch(() => ({ projects: [] })),
                NexusAPI.getAgentRuntimes('claude').catch(() => ({ runtimes: {} })),
                NexusAPI.listTeleportSessions().catch(() => ({ sessions: [] })),
            ]);

            // Webhooks
            const webhooks = diagData.webhooks || [];
            let webhookHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Webhooks</h3>
                    ${webhooks.length === 0 ? '<div class="u-empty-state-lg">No webhooks configured</div>' :
                      webhooks.map(w => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(w.name || w.url || 'Webhook')}</div>
                                <div class="panel-list-item-sub">${this._esc(w.url || w.detail || '')} &middot; ${this._esc(w.events || 'all events')}</div>
                            </div>
                            <span class="panel-badge ${w.active !== false ? 'badge-ok' : 'badge-muted'}">${w.active !== false ? 'Active' : 'Inactive'}</span>
                        </div>
                    `).join('')}
                </div>`;

            // GitHub Sync
            const repos = (projectsData.projects || []).map(p => ({
                name: typeof p === 'string' ? p : p.name || p.path || 'Unknown',
                path: typeof p === 'string' ? p : p.path || '',
            }));
            let githubHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">GitHub Sync</h3>
                    ${repos.length === 0 ? '<div class="u-empty-state-lg">No repositories connected</div>' :
                      repos.map(r => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(r.name)}</div>
                                <div class="panel-list-item-sub">${this._esc(r.path)}</div>
                            </div>
                            <span class="panel-badge badge-ok">Connected</span>
                        </div>
                    `).join('')}
                </div>`;

            // Claude Code
            const runtime = runtimeData.runtimes?.claude || runtimeData.runtime || {};
            const sessions = runtime.sessions || runtime.processes || [];
            let claudeHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Claude Code</h3>
                    ${Object.keys(runtime).length > 0 ? `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">Runtime: ${this._esc(runtime.version || 'Unknown')}</div>
                                <div class="panel-list-item-sub">${this._esc(runtime.path || 'Not found')}</div>
                            </div>
                            <span class="panel-badge ${runtime.available ? 'badge-ok' : 'badge-error'}">${runtime.available ? 'Available' : 'Not Found'}</span>
                        </div>
                    ` : '<div class="u-empty-state-lg">No Claude Code runtime detected</div>'}
                    ${sessions.length > 0 ? sessions.map(s => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(s.id || s.session_id || 'Session')}</div>
                                <div class="panel-list-item-sub">${this._esc(s.project || s.cwd || '')}</div>
                            </div>
                            <span class="panel-badge badge-ok">Running</span>
                        </div>
                    `).join('') : ''}
                </div>`;

            // Teleport with API data
            const connections = diagData.teleport_connections || diagData.connections || [];
            const tpSessions = teleportSessions.sessions || teleportSessions || [];
            const activeConns = connections.filter(c => c.status === 'connected' || c.active).length;
            const activeTpSessions = tpSessions.filter(s => s.status === 'active' || s.connected).length;
            let teleportHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Teleport</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Active</span><span class="admin-metric-value admin-metric-value-success">${activeConns}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value">${connections.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Sessions</span><span class="admin-metric-value">${activeTpSessions}</span></div>
                        </div></div>
                    </div>
                    <div class="u-row-top">
                        <button class="action-btn primary u-text-sm" id="teleportConnectBtn">Connect</button>
                        <button class="action-btn u-text-sm" id="teleportSyncBtn">Sync</button>
                        <button class="action-btn danger u-text-sm" id="teleportDisconnectBtn">Disconnect</button>
                    </div>
                    ${connections.length === 0 ? '<div class="u-empty-state-lg">No teleport connections</div>' :
                      connections.map(c => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(c.name || c.host || 'Connection')}</div>
                                <div class="panel-list-item-sub">${this._esc(c.host || '')} ${c.port ? ':' + c.port : ''} &middot; Latency: ${c.latency_ms ?? '—'}ms</div>
                            </div>
                            <span class="panel-badge ${c.status === 'connected' || c.active ? 'badge-ok' : 'badge-muted'}">${c.status || (c.active ? 'Active' : 'Inactive')}</span>
                        </div>
                    `).join('')}
                    ${tpSessions.length > 0 ? `
                        <div class="panel-group-title-lg">Sessions</div>
                        ${tpSessions.slice(0, 10).map(s => `
                            <div class="panel-list-item">
                                <div class="panel-list-item-body">
                                    <div class="panel-list-item-title">${this._esc(s.id || s.session_id || 'Session')}</div>
                                    <div class="panel-list-item-sub">${this._esc(s.host || '')} ${s.username ? '&middot; ' + this._esc(s.username) : ''}</div>
                                </div>
                                <span class="panel-badge ${s.status === 'active' || s.connected ? 'badge-ok' : 'badge-muted'}">${s.status || 'Unknown'}</span>
                            </div>
                        `).join('')}
                    ` : ''}
                </div>`;

            this.container.innerHTML = webhookHtml + githubHtml + claudeHtml + teleportHtml;

            // Bind Teleport actions
            document.getElementById('teleportConnectBtn')?.addEventListener('click', async () => {
                try { await NexusAPI.connectTeleport(); this.app?.showToast?.('Teleport connected', 'success'); this.renderIntegrationsTab(); }
                catch (e) { this.app?.showToast?.(e.message, 'error'); }
            });
            document.getElementById('teleportDisconnectBtn')?.addEventListener('click', async () => {
                if (!confirm('Disconnect Teleport?')) return;
                try { await NexusAPI.disconnectTeleport(); this.app?.showToast?.('Teleport disconnected', 'success'); this.renderIntegrationsTab(); }
                catch (e) { this.app?.showToast?.(e.message, 'error'); }
            });
            document.getElementById('teleportSyncBtn')?.addEventListener('click', async () => {
                try { await NexusAPI.syncTeleport(); this.app?.showToast?.('Teleport synced', 'success'); }
                catch (e) { this.app?.showToast?.(e.message, 'error'); }
            });
        } catch (e) { this._showError('Failed to load integrations: ' + e.message); }
    }

    // ── Admin Tab ──
    async renderAdminTab() {
        this._showLoading();
        try {
            const [diagData, secData, featuresData] = await Promise.all([
                NexusAPI.getDiagnostics().catch(() => ({})),
                NexusAPI.getSecurityScan().catch(() => ({})),
                NexusAPI.getFeatures().catch(() => ({ flags: [] })),
            ]);

            // Feature Flags from API
            const flags = featuresData.flags || featuresData.features || diagData.feature_flags || diagData.flags || [];
            const enabled = flags.filter(f => f.enabled || f.value === true).length;
            let flagHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Feature Flags</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Enabled</span><span class="admin-metric-value admin-metric-value-success">${enabled}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Disabled</span><span class="admin-metric-value">${flags.length - enabled}</span></div>
                        </div></div>
                    </div>
                    ${flags.length === 0 ? '<div class="u-empty-state-lg">No feature flags configured</div>' :
                      flags.map(f => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(f.name || f.key)}</div>
                                <div class="panel-list-item-sub">${this._esc(f.description || '')}</div>
                            </div>
                            <label class="panel-toggle"><input type="checkbox" ${f.enabled ? 'checked' : ''} data-flag-key="${this._esc(f.name || f.key)}"><span class="toggle-slider"></span></label>
                        </div>
                    `).join('')}
                </div>`;

            // Standup Report
            let standupHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Standup Report</h3>
                    <button class="action-btn primary panel-group" id="adminStandupGenBtn">Generate Report</button>
                    <div id="adminStandupResult"></div>
                </div>`;

            // RBAC
            const roles = secData.rbac || secData.roles || [
                { name: 'admin', permissions: ['*'], users: [] },
                { name: 'operator', permissions: ['task:read', 'task:write', 'agent:read'], users: [] },
                { name: 'viewer', permissions: ['task:read', 'agent:read'], users: [] },
            ];
            let rbacHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">RBAC</h3>
                    ${roles.map(r => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(r.name)}</div>
                                <div class="panel-list-item-sub">${(r.permissions || []).length} permissions</div>
                            </div>
                        </div>
                    `).join('')}
                </div>`;

            this.container.innerHTML = flagHtml + standupHtml + rbacHtml;

            // Bind standup report generation
            document.getElementById('adminStandupGenBtn')?.addEventListener('click', async () => {
                const area = document.getElementById('adminStandupResult');
                area.innerHTML = '<div class="admin-loading">Generating report...</div>';
                try {
                    const report = await NexusAPI.getStandup();
                    area.innerHTML = `
                        <div class="admin-section">
                            <div class="admin-metric"><span class="admin-metric-label">Completed</span><span class="admin-metric-value">${report.tasks_completed ?? 0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">In Progress</span><span class="admin-metric-value">${report.tasks_in_progress ?? 0}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Agents Active</span><span class="admin-metric-value">${report.agents_active ?? 0}</span></div>
                        </div>
                        ${report.recent_completions?.length ? report.recent_completions.map(t => `<div class="panel-list-item"><div class="panel-list-item-body"><div class="panel-list-item-title">${this._esc(t.title || t.id)}</div><div class="panel-list-item-sub">${this._esc(t.agent_type || '')}</div></div></div>`).join('') : ''}
                    `;
                } catch (e) { area.innerHTML = `<div class="admin-error">${this._esc(e.message)}</div>`; }
            });

            // Bind feature flag toggles
            this.container.querySelectorAll('.panel-toggle input').forEach(input => {
                input.addEventListener('change', async (e) => {
                    const key = e.target.dataset.flagKey;
                    const newVal = e.target.checked;
                    try {
                        await NexusAPI.patchFlag(key, newVal);
                        this.app?.showToast?.(`Flag "${key}" ${newVal ? 'enabled' : 'disabled'}`, 'success');
                    } catch (err) {
                        e.target.checked = !newVal; // revert on error
                        this.app?.showToast?.(err.message, 'error');
                    }
                });
            });

            // Reload flags button
            const reloadBtn = document.createElement('button');
            reloadBtn.className = 'action-btn';
            reloadBtn.textContent = 'Reload Flags';
            reloadBtn.classList.add('u-mt-sm');
            reloadBtn.addEventListener('click', async () => {
                try { await NexusAPI.reloadFlags(); this.renderAdminTab(); this.app?.showToast?.('Flags reloaded', 'success'); }
                catch (e) { this.app?.showToast?.(e.message, 'error'); }
            });
            const flagSection = this.container.querySelector('.admin-section');
            flagSection?.appendChild(reloadBtn);
        } catch (e) { this._showError('Failed to load admin: ' + e.message); }
    }

    // ── Permissions Tab ──
    async renderPermissionsTab() {
        this._showLoading();
        try {
            const [permsData, permCache] = await Promise.all([
                NexusAPI.getPermissions().catch(() => ({ mode: 'unknown', permissions: [] })),
                NexusAPI.getPermissionCache().catch(() => ({ entries: [] })),
            ]);
            const mode = permsData.mode || 'unknown';
            const permissions = permsData.permissions || permsData.entries || [];
            const cacheEntries = permCache.entries || permCache.cache || [];

            let modeHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Permission Mode</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Current Mode</span><span class="admin-metric-value large">${this._esc(mode)}</span></div>
                        </div></div>
                    </div>
                    <div class="u-row-top">
                        <button class="action-btn ${mode === 'permissive' ? 'primary' : ''} u-text-sm" data-mode="permissive" data-action="set-perm-mode">Permissive</button>
                        <button class="action-btn ${mode === 'restrictive' ? 'primary' : ''} u-text-sm" data-mode="restrictive" data-action="set-perm-mode">Restrictive</button>
                        <button class="action-btn ${mode === 'auto' ? 'primary' : ''} u-text-sm" data-mode="auto" data-action="set-perm-mode">Auto</button>
                        <button class="action-btn danger u-text-sm" id="clearPermCacheBtn">Clear Cache</button>
                    </div>
                </div>`;

            let permsListHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Permissions</h3>
                    ${permissions.length === 0 ? '<div class="u-empty-state-lg">No permissions configured</div>' :
                      permissions.map(p => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(p.name || p.role || p.id || 'Permission')}</div>
                                <div class="panel-list-item-sub">${this._esc(p.description || p.scope || '')}</div>
                            </div>
                            <span class="panel-badge ${p.granted !== false ? 'badge-ok' : 'badge-error'}">${p.granted !== false ? 'Granted' : 'Denied'}</span>
                        </div>
                    `).join('')}
                </div>`;

            let cacheHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Permission Cache</h3>
                    ${cacheEntries.length === 0 ? '<div class="u-empty-state-lg">No cache entries</div>' :
                      cacheEntries.slice(0, 20).map(c => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(c.key || c.agent_id || 'Entry')}</div>
                                <div class="panel-list-item-sub">${this._esc(c.permission || c.action || '')}</div>
                            </div>
                        </div>
                    `).join('')}
                </div>`;

            this.container.innerHTML = modeHtml + permsListHtml + cacheHtml;

            // Bind mode switch
            this.container.querySelectorAll('[data-action="set-perm-mode"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        await NexusAPI.setPermissionMode(btn.dataset.mode);
                        this.app?.showToast?.(`Permission mode set to ${btn.dataset.mode}`, 'success');
                        this.renderPermissionsTab();
                    } catch (e) { this.app?.showToast?.(e.message, 'error'); }
                });
            });
            document.getElementById('clearPermCacheBtn')?.addEventListener('click', async () => {
                if (!confirm('Clear permission cache?')) return;
                try {
                    await NexusAPI.clearPermissionCache();
                    this.app?.showToast?.('Permission cache cleared', 'success');
                    this.renderPermissionsTab();
                } catch (e) { this.app?.showToast?.(e.message, 'error'); }
            });
        } catch (e) { this._showError('Failed to load permissions: ' + e.message); }
    }

    // ── Sessions Tab (Session Recovery) ──
    async renderSessionsTab() {
        this._showLoading();
        try {
            const sessionsData = await NexusAPI.getSessions({ pageSize: 50 }).catch(() => ({ sessions: [] }));
            const sessions = sessionsData.sessions || [];

            let listHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Session Recovery</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value large">${sessions.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Error</span><span class="admin-metric-value admin-metric-value-error">${sessions.filter(s => s.status === 'error').length}</span></div>
                        </div></div>
                    </div>
                    ${sessions.length === 0 ? '<div class="u-empty-state-lg">No sessions</div>' :
                      sessions.map(s => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(s.id || s.session_id || 'Session')}</div>
                                <div class="panel-list-item-sub">${this._esc(s.status || '')} ${s.username ? '&middot; ' + this._esc(s.username) : ''} ${s.created_at ? '&middot; ' + new Date(s.created_at).toLocaleString() : ''}</div>
                            </div>
                            ${s.status === 'error' ? `
                                <button class="action-btn compact" data-session-id="${this._esc(s.id || s.session_id)}" data-action="check-interrupted">Interrupted</button>
                                <button class="action-btn compact" data-session-id="${this._esc(s.id || s.session_id)}" data-action="find-orphans">Orphans</button>
                            ` : ''}
                        </div>
                    `).join('')}
                </div>`;

            this.container.innerHTML = listHtml;

            // Bind session recovery actions
            this.container.querySelectorAll('[data-action="check-interrupted"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        const result = await NexusAPI.getInterruptedTurns(btn.dataset.sessionId);
                        const turns = result.turns || result.interrupted || [];
                        if (turns.length === 0) { alert('No interrupted turns found'); return; }
                        const msgId = turns[0].message_id || turns[0].id;
                        if (confirm(`Found ${turns.length} interrupted turn(s). Recover first one?`)) {
                            await NexusAPI.recoverInterruptedTurn(btn.dataset.sessionId, msgId);
                            this.app?.showToast?.('Turn recovered', 'success');
                        }
                    } catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="find-orphans"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        const result = await NexusAPI.findOrphanToolResults(btn.dataset.sessionId);
                        const orphans = result.orphans || result.results || [];
                        alert(`Found ${orphans.length} orphan tool result(s)`);
                    } catch (e) { alert(e.message); }
                });
            });
        } catch (e) { this._showError('Failed to load sessions: ' + e.message); }
    }

    // ── Missions Tab ──
    async renderMissionsTab() {
        this._showLoading();
        try {
            const missionsData = await NexusAPI.listMissions().catch(() => ({ missions: [] }));
            const missions = missionsData.missions || missionsData.items || [];

            let listHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Missions</h3>
                    <button class="action-btn primary u-mb-sm" id="createMissionBtn">Create Mission</button>
                    ${missions.length === 0 ? '<div class="u-empty-state-lg">No missions</div>' :
                      missions.map(m => {
                        const status = m.status || 'unknown';
                        const statusClass = status === 'approved' ? 'badge-ok' : status === 'pending' ? 'badge-warn' : status === 'cancelled' ? 'badge-error' : 'badge-muted';
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(m.name || m.title || m.id)}</div>
                                <div class="panel-list-item-sub">${this._esc(m.description || '').substring(0, 80)} ${m.created_at ? '&middot; ' + new Date(m.created_at).toLocaleString() : ''}</div>
                            </div>
                            <span class="panel-badge ${statusClass}">${this._esc(status)}</span>
                            <div class="admin-action-row-tight">
                                ${status === 'pending' ? `<button class="action-btn compact btn-success" data-mission-id="${this._esc(m.id)}" data-action="approve-mission">Approve</button>` : ''}
                                ${status === 'approved' || status === 'in_progress' ? `<button class="action-btn compact" data-mission-id="${this._esc(m.id)}" data-action="pause-mission">Pause</button>` : ''}
                                ${status === 'paused' ? `<button class="action-btn compact" data-mission-id="${this._esc(m.id)}" data-action="resume-mission">Resume</button>` : ''}
                                <button class="action-btn compact" data-mission-id="${this._esc(m.id)}" data-action="mission-log">Log</button>
                                <button class="action-btn danger compact" data-mission-id="${this._esc(m.id)}" data-action="cancel-mission">Cancel</button>
                            </div>
                        </div>`;
                    }).join('')}
                </div>`;

            this.container.innerHTML = listHtml;

            // Bind mission actions
            this.container.querySelectorAll('[data-action="approve-mission"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try { await NexusAPI.approveMission(btn.dataset.missionId); this.app?.showToast?.('Mission approved', 'success'); this.renderMissionsTab(); }
                    catch (e) { this.app?.showToast?.(e.message, 'error'); }
                });
            });
            this.container.querySelectorAll('[data-action="pause-mission"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try { await NexusAPI.pauseMission(btn.dataset.missionId); this.renderMissionsTab(); }
                    catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="resume-mission"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try { await NexusAPI.resumeMission(btn.dataset.missionId); this.renderMissionsTab(); }
                    catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="cancel-mission"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Cancel this mission?')) return;
                    try { await NexusAPI.cancelMission(btn.dataset.missionId); this.renderMissionsTab(); }
                    catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="mission-log"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        const log = await NexusAPI.getMissionLog(btn.dataset.missionId);
                        alert(JSON.stringify(log, null, 2));
                    } catch (e) { alert(e.message); }
                });
            });
            document.getElementById('createMissionBtn')?.addEventListener('click', async () => {
                const name = prompt('Mission name:');
                if (!name) return;
                const desc = prompt('Description (optional):') || '';
                try { await NexusAPI.createMission({ name, description: desc }); this.renderMissionsTab(); }
                catch (e) { alert(e.message); }
            });
        } catch (e) { this._showError('Failed to load missions: ' + e.message); }
    }

    // ── Runs / Evals Tab ──
    async renderRunsTab() {
        this._showLoading();
        try {
            const [runsData, leaderboard] = await Promise.all([
                NexusAPI.listRuns().catch(() => ({ runs: [] })),
                NexusAPI.getEvalsLeaderboard().catch(() => ({ entries: [] })),
            ]);
            const runs = runsData.runs || runsData.items || [];
            const lbEntries = leaderboard.entries || leaderboard.leaderboard || [];

            let runsHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Runs</h3>
                    <button class="action-btn primary u-mb-sm" id="createRunBtn">Create Run</button>
                    ${runs.length === 0 ? '<div class="u-empty-state-lg">No runs</div>' :
                      runs.map(r => {
                        const status = r.status || 'unknown';
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(r.name || r.id)}</div>
                                <div class="panel-list-item-sub">${this._esc(status)} ${r.created_at ? '&middot; ' + new Date(r.created_at).toLocaleString() : ''} ${r.score != null ? '&middot; Score: ' + r.score : ''}</div>
                            </div>
                            <span class="panel-badge ${status === 'completed' ? 'badge-ok' : status === 'running' ? 'badge-warn' : 'badge-muted'}">${this._esc(status)}</span>
                            <div class="admin-action-row-tight">
                                <button class="action-btn compact" data-run-id="${this._esc(r.id)}" data-action="view-run">View</button>
                                ${status === 'completed' ? `<button class="action-btn compact" data-run-id="${this._esc(r.id)}" data-action="eval-run">Eval</button>` : ''}
                            </div>
                        </div>`;
                    }).join('')}
                </div>`;

            let leaderboardHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Evals Leaderboard</h3>
                    ${lbEntries.length === 0 ? '<div class="u-empty-state-lg">No eval entries</div>' :
                      lbEntries.slice(0, 20).map((e, i) => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">#${i + 1} ${this._esc(e.name || e.agent_id || 'Entry')}</div>
                                <div class="panel-list-item-sub">Score: ${e.score ?? '-'} ${e.model ? '&middot; ' + this._esc(e.model) : ''}</div>
                            </div>
                            <span class="panel-badge">${e.score ?? '-'}</span>
                        </div>
                    `).join('')}
                </div>`;

            this.container.innerHTML = runsHtml + leaderboardHtml;

            // Bind run actions
            document.getElementById('createRunBtn')?.addEventListener('click', async () => {
                const name = prompt('Run name:');
                if (!name) return;
                try { await NexusAPI.createRun({ name }); this.renderRunsTab(); }
                catch (e) { alert(e.message); }
            });
            this.container.querySelectorAll('[data-action="view-run"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        const run = await NexusAPI.getRun(btn.dataset.runId);
                        alert(JSON.stringify(run, null, 2));
                    } catch (e) { alert(e.message); }
                });
            });
            this.container.querySelectorAll('[data-action="eval-run"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const score = prompt('Evaluation score (0-100):');
                    if (score == null) return;
                    try {
                        await NexusAPI.evalRun(btn.dataset.runId, { score: parseFloat(score) });
                        this.app?.showToast?.('Run evaluated', 'success');
                        this.renderRunsTab();
                    } catch (e) { this.app?.showToast?.(e.message, 'error'); }
                });
            });
        } catch (e) { this._showError('Failed to load runs: ' + e.message); }
    }

    // ── Evolution Tab ──
    async renderEvolutionTab() {
        this._showLoading();
        try {
            const [status, memory] = await Promise.all([
                NexusAPI.getEvolutionStatus().catch(() => ({})),
                NexusAPI.getEvolutionMemory().catch(() => ({})),
            ]);

            const isRunning = status.running || status.in_progress || false;
            const phase = status.phase || status.current_phase || 'idle';
            const generations = status.generations || status.total_generations || 0;
            const memEntries = memory.entries || memory.generations || [];

            let statusHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Evolution</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Status</span><span class="admin-metric-value large ${isRunning ? 'admin-metric-value-success' : 'admin-metric-value-muted'}">${isRunning ? 'Running' : 'Idle'}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Phase</span><span class="admin-metric-value">${this._esc(phase)}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Generations</span><span class="admin-metric-value">${generations}</span></div>
                        </div></div>
                    </div>
                    <div class="u-row-top">
                        <button class="action-btn primary u-text-sm" id="triggerEvolutionBtn">Trigger Evolution</button>
                        <button class="action-btn u-text-sm" id="synthesisBtn">Run Synthesis</button>
                    </div>
                </div>`;

            let memoryHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Evolution Memory</h3>
                    ${memEntries.length === 0 ? '<div class="u-empty-state-lg">No evolution memory entries</div>' :
                      memEntries.slice(0, 20).map(e => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(e.phase || e.generation || 'Entry')}</div>
                                <div class="panel-list-item-sub">${this._esc(e.summary || e.result || '').substring(0, 100)} ${e.timestamp ? '&middot; ' + new Date(e.timestamp).toLocaleString() : ''}</div>
                            </div>
                            <span class="panel-badge ${e.success !== false ? 'badge-ok' : 'badge-error'}">${e.success !== false ? 'OK' : 'Failed'}</span>
                        </div>
                    `).join('')}
                </div>`;

            this.container.innerHTML = statusHtml + memoryHtml;

            document.getElementById('triggerEvolutionBtn')?.addEventListener('click', async () => {
                if (!confirm('Trigger evolution cycle?')) return;
                try {
                    await NexusAPI.triggerEvolution();
                    this.app?.showToast?.('Evolution triggered', 'success');
                    this.renderEvolutionTab();
                } catch (e) { this.app?.showToast?.(e.message, 'error'); }
            });
            document.getElementById('synthesisBtn')?.addEventListener('click', async () => {
                if (!confirm('Run evolution synthesis?')) return;
                try {
                    await NexusAPI.evolutionSynthesis();
                    this.app?.showToast?.('Synthesis started', 'success');
                    this.renderEvolutionTab();
                } catch (e) { this.app?.showToast?.(e.message, 'error'); }
            });
        } catch (e) { this._showError('Failed to load evolution: ' + e.message); }
    }

    // ── Scheduling Tab ──
    async renderSchedulingTab() {
        this._showLoading();
        try {
            const [schedData, taskData] = await Promise.all([
                NexusAPI.getSchedules({ pageSize: 50 }).catch(() => ({ schedules: [] })),
                NexusAPI.getTasks({ pageSize: 20 }).catch(() => ({ tasks: [] })),
            ]);
            const schedules = schedData.schedules || schedData.items || [];
            const doneTasks = (taskData.tasks || []).filter(t => t.status === 'done').slice(0, 20);

            // Cron Scheduler
            const activeSched = schedules.filter(s => s.status === 'active').length;
            const pausedSched = schedules.filter(s => s.status === 'paused').length;
            let cronHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Cron Scheduler</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Active</span><span class="admin-metric-value admin-metric-value-success">${activeSched}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Paused</span><span class="admin-metric-value admin-metric-value-warn">${pausedSched}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Total</span><span class="admin-metric-value">${schedules.length}</span></div>
                        </div></div>
                    </div>
                    ${schedules.length === 0 ? '<div class="u-empty-state-lg">No schedules configured</div>' :
                      schedules.map(s => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(s.name || s.id)}</div>
                                <div class="panel-list-item-sub">${this._esc(s.cron || s.schedule || '')} &middot; ${this._esc(s.task_type || '')}</div>
                            </div>
                            <span class="panel-badge ${s.status === 'active' ? 'badge-ok' : s.status === 'paused' ? 'badge-warn' : 'badge-muted'}">${s.status}</span>
                        </div>
                    `).join('')}
                </div>`;

            // NLP Parser
            let nlpHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Natural Language Scheduler</h3>
                    <div class="u-flex u-gap-sm">
                        <input type="text" class="form-input u-flex-1" id="schedulingNlpInput" placeholder='e.g. "every weekday at 9am"'>
                        <button class="action-btn primary" id="schedulingNlpBtn">Parse</button>
                    </div>
                    <div id="schedulingNlpResult" class="u-mt-sm"></div>
                </div>`;

            // Template Tasks
            let templateHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Template Tasks</h3>
                    ${doneTasks.length === 0 ? '<div class="u-empty-state-lg">No templates available</div>' :
                      '<div class="panel-grid">' + doneTasks.map(t => `
                        <div class="panel-card">
                            <div class="panel-card-title">${this._esc(t.title || t.id)}</div>
                            <div class="panel-card-meta">${this._esc(t.agent_type || 'any')} &middot; ${this._esc(t.priority || 'normal')}</div>
                        </div>
                    `).join('') + '</div>'}
                </div>`;

            this.container.innerHTML = cronHtml + nlpHtml + templateHtml;

            // Bind NLP parser
            document.getElementById('schedulingNlpBtn')?.addEventListener('click', async () => {
                const input = document.getElementById('schedulingNlpInput')?.value?.trim();
                if (!input) return;
                const area = document.getElementById('schedulingNlpResult');
                area.innerHTML = '<div class="admin-loading">Parsing...</div>';
                try {
                    const result = await NexusAPI.parseSchedule(input);
                    area.innerHTML = `
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Cron Expression</span><span class="admin-metric-value">${this._esc(result.cron || '')}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Human Readable</span><span class="admin-metric-value">${this._esc(result.human || result.description || '')}</span></div>
                        </div></div>
                        ${result.next_runs ? result.next_runs.map(r => `<div class="u-text-sm u-text-secondary">${this._esc(r)}</div>`).join('') : ''}
                    `;
                } catch (e) { area.innerHTML = `<div class="admin-error">${this._esc(e.message)}</div>`; }
            });
            document.getElementById('schedulingNlpInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('schedulingNlpBtn')?.click(); });
        } catch (e) { this._showError('Failed to load scheduling: ' + e.message); }
    }
}

class SettingsView {
    constructor(app) {
        this.app = app;
        this.tabCategories = {
            overview: 'workspace',
            onboarding: 'workspace',
            general: 'configuration',
            mcp: 'configuration',
            skills: 'configuration',
            runtimes: 'configuration',
            integrations: 'configuration',
            tools: 'operations',
            agents: 'operations',
            activity: 'operations',
            memory: 'operations',
            scheduling: 'operations',
            security: 'governance',
            audit: 'governance',
            cleanup: 'governance',
            admin: 'governance',
        };
        this.defaultTabByCategory = {
            workspace: 'overview',
            configuration: 'general',
            operations: 'agents',
            governance: 'security',
        };
        this.activeTab = localStorage.getItem('nexus-settings-tab') || 'overview';
        this.activeCategory = this.tabCategories[this.activeTab] || localStorage.getItem('nexus-settings-category') || 'workspace';
        this.configSection = document.getElementById('settingsConfigSection');
        this.adminSection = document.getElementById('settingsAdminSection');
        this.settingsContainer = document.querySelector('.settings-container');
        this._skillsPanelContainer = null;
        this.bindEvents();
    }

    bindEvents() {
        document.querySelectorAll('.settings-category-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.switchCategory(tab.dataset.settingsCategory);
            });
        });
        document.querySelectorAll('.settings-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                this.switchTab(tab.dataset.settingsTab);
            });
        });
    }

    switchTab(tabName) {
        this.activeTab = tabName;
        this.activeCategory = this.tabCategories[tabName] || this.activeCategory || 'workspace';
        localStorage.setItem('nexus-settings-tab', tabName);
        localStorage.setItem('nexus-settings-category', this.activeCategory);
        this.applyTab();
    }

    switchCategory(categoryName) {
        const nextCategory = String(categoryName || '').trim().toLowerCase();
        if (!nextCategory) return;
        this.activeCategory = nextCategory;
        localStorage.setItem('nexus-settings-category', this.activeCategory);

        if (this.tabCategories[this.activeTab] !== this.activeCategory) {
            this.activeTab = this.defaultTabByCategory[this.activeCategory] || 'overview';
            localStorage.setItem('nexus-settings-tab', this.activeTab);
        }

        this.applyTab();
    }

    applyTab() {
        const configTabMap = {
            general: 'parameters',
            mcp: 'mcp',
        };
        const stackedMode = this.activeTab === 'skills';
        this.settingsContainer?.classList.toggle('settings-stacked', stackedMode);

        // Tabs that show in admin section (with panel content merged)
        const adminTabs = [
            'overview', 'onboarding', 'security', 'runtimes', 'audit', 'cleanup', 'tools',
            'agents', 'activity', 'memory', 'integrations', 'admin', 'permissions',
            'sessions', 'missions', 'runs', 'evolution', 'scheduling',
        ];

        document.querySelectorAll('.settings-category-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.settingsCategory === this.activeCategory);
        });

        document.querySelectorAll('.settings-tab').forEach(tab => {
            const category = tab.dataset.settingsCategory || this.tabCategories[tab.dataset.settingsTab] || 'workspace';
            const visible = category === this.activeCategory;
            tab.hidden = !visible;
            tab.classList.toggle('active', visible && tab.dataset.settingsTab === this.activeTab);
        });

        const configTab = configTabMap[this.activeTab];
        if (configTab) {
            // Pure ConfigView tabs (general, mcp)
            if (this.configSection) this.configSection.hidden = false;
            if (this.adminSection) this.adminSection.hidden = true;
            this._removeSkillsPanelSection();
            this.app.configView.refresh();
            this.app.configView.switchTab(configTab);
            return;
        }

        if (this.activeTab === 'skills') {
            // Skills tab: show ConfigView skills AND panel content below
            if (this.configSection) this.configSection.hidden = false;
            this.app.configView.refresh();
            this.app.configView.switchTab('skills');
            // Render panel content below config section
            this._renderSkillsPanelSection();
            return;
        }

        // All other tabs go through AdminView
        if (this.configSection) this.configSection.hidden = true;
        this._removeSkillsPanelSection();
        if (this.adminSection) this.adminSection.hidden = false;
        this.app.adminView.switchTab(this.activeTab);
    }

    async _renderSkillsPanelSection() {
        this._removeSkillsPanelSection();

        const section = document.createElement('div');
        section.id = 'settingsSkillsPanelSection';
        section.className = 'settings-section';
        section.classList.add('u-mt-0');
        section.innerHTML = '<div class="admin-content" id="skillsPanelContent"><div class="admin-loading">Loading skills panels...</div></div>';

        // Insert after configSection
        this.configSection?.after(section);
        this._skillsPanelContainer = document.getElementById('skillsPanelContent');
        if (!this._skillsPanelContainer) return;

        try {
            const [skillsData, secData] = await Promise.all([
                NexusAPI.getSkills().catch(() => ({ providers: {} })),
                NexusAPI.getSecurityScan().catch(() => ({})),
            ]);

            const providers = Object.keys(skillsData.providers || {});
            const totalSkills = providers.reduce((s, p) => s + (skillsData.providers[p]?.length || 0), 0);

            // Skill Registry
            let registryHtml = `
                <div class="admin-section">
                    <h3 class="admin-section-title">Skill Registry</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Providers</span><span class="admin-metric-value">${providers.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Total Skills</span><span class="admin-metric-value">${totalSkills}</span></div>
                        </div></div>
                    </div>
                    ${providers.map(p => {
                        const skills = skillsData.providers[p] || [];
                        return `
                        <div class="panel-group">
                            <div class="panel-group-title">${this._esc(p)} <span class="panel-badge">${skills.length}</span></div>
                            ${skills.map(sk => `
                                <div class="panel-list-item">
                                    <div class="panel-list-item-body">
                                        <div class="panel-list-item-title">${this._esc(sk.skill_name || sk.name)}</div>
                                        <div class="panel-list-item-sub">${this._esc(sk.description || '')}</div>
                                    </div>
                                </div>
                            `).join('')}
                        </div>`;
                    }).join('')}
                </div>`;

            // Skill Security
            const pending = (secData.skills?.pending || []).map(s => ({ ...s, _status: 'pending' }));
            const approved = (secData.skills?.approved || []).map(s => ({ ...s, _status: 'approved' }));
            const allSkills = [...pending, ...approved];
            let secSkillsHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Skill Security</h3>
                    <div class="admin-cards">
                        <div class="admin-card"><div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Pending</span><span class="admin-metric-value admin-metric-value-warn">${pending.length}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Approved</span><span class="admin-metric-value admin-metric-value-success">${approved.length}</span></div>
                        </div></div>
                    </div>
                    ${allSkills.length === 0 ? '<div class="u-empty-state-lg">No skill security entries</div>' :
                      allSkills.map(s => `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(s.name || s.skill_name)}</div>
                                <div class="panel-list-item-sub">${this._esc(s.provider || '')} &middot; ${this._esc(s.risk_level || 'unknown risk')}</div>
                            </div>
                            <span class="panel-badge ${s._status === 'approved' ? 'badge-ok' : 'badge-warn'}">${s._status}</span>
                        </div>
                    `).join('')}
                </div>`;

            // Skill Sync
            let syncHtml = `
                <div class="admin-section u-mt-lg">
                    <h3 class="admin-section-title">Skill Sync</h3>
                    ${providers.length === 0 ? '<div class="u-empty-state-lg">No providers to sync</div>' :
                      providers.map(p => {
                        const count = (skillsData.providers[p] || []).length;
                        return `
                        <div class="panel-list-item">
                            <div class="panel-list-item-body">
                                <div class="panel-list-item-title">${this._esc(p)}</div>
                                <div class="panel-list-item-sub">${count} skills</div>
                            </div>
                            <span class="panel-badge badge-ok">In Sync</span>
                        </div>`;
                    }).join('')}
                </div>`;

            this._skillsPanelContainer.innerHTML = registryHtml + secSkillsHtml + syncHtml;
        } catch (e) {
            this._skillsPanelContainer.innerHTML = `<div class="admin-error">Failed to load skills: ${this._esc(e.message)}</div>`;
        }
    }

    _removeSkillsPanelSection() {
        const existing = document.getElementById('settingsSkillsPanelSection');
        if (existing) existing.remove();
        this._skillsPanelContainer = null;
    }

    _esc(str) { return String(str||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

    refresh() {
        this.applyTab();
    }
}

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

class PlanModeIndicator {
    /** Top-bar indicator showing plan mode status */
    constructor(app) {
        this.app = app;
        this.el = document.getElementById('planModeIndicator');
        this.statusEl = document.getElementById('planModeStatus');
        this.viewBtn = document.getElementById('planModeViewBtn');
        this.exitBtn = document.getElementById('planModeExitBtn');
        this._visible = false;
        this._bindEvents();
    }

    _bindEvents() {
        this.viewBtn?.addEventListener('click', () => this.app.planModePanel.toggle());
        this.exitBtn?.addEventListener('click', async () => {
            await this.app.planModeManager.exitPlanMode();
        });
    }

    show(status = 'Exploring') {
        this._visible = true;
        if (this.el) this.el.hidden = false;
        this.setStatus(status);
    }

    hide() {
        this._visible = false;
        if (this.el) this.el.hidden = true;
    }

    setStatus(status) {
        if (this.statusEl) this.statusEl.textContent = `— ${status}`;
    }

    get visible() { return this._visible; }
}

class PlanEditor {
    /** Plan content editor panel */
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('planEditorContainer');
        this.textarea = document.getElementById('planEditor');
        this.submitBtn = document.getElementById('planSubmitBtn');
        this._bindEvents();
    }

    _bindEvents() {
        this.submitBtn?.addEventListener('click', async () => {
            const content = this.textarea?.value?.trim();
            if (!content) return;
            await this.app.planModeManager.submitPlan(content);
        });
    }

    show() {
        if (this.container) this.container.hidden = false;
        if (this.textarea) this.textarea.focus();
    }

    hide() {
        if (this.container) this.container.hidden = true;
    }

    clear() {
        if (this.textarea) this.textarea.value = '';
    }
}

class PlanApprovalWidget {
    /** Approval/rejection buttons with plan content display */
    constructor(app) {
        this.app = app;
        this.container = document.getElementById('planApprovalContainer');
        this.contentDisplay = document.getElementById('planContentDisplay');
        this.approveBtn = document.getElementById('planApproveBtn');
        this.rejectBtn = document.getElementById('planRejectBtn');
        this._bindEvents();
    }

    _bindEvents() {
        this.approveBtn?.addEventListener('click', async () => {
            await this.app.planModeManager.approvePlan();
        });
        this.rejectBtn?.addEventListener('click', async () => {
            await this.app.planModeManager.rejectPlan();
        });
    }

    show(content) {
        if (this.container) this.container.hidden = false;
        if (this.contentDisplay) this.contentDisplay.textContent = content;
    }

    hide() {
        if (this.container) this.container.hidden = true;
    }
}

class PlanModePanel {
    /** Dropdown panel for plan editing/approval */
    constructor(app) {
        this.app = app;
        this.el = document.getElementById('planModePanel');
        this.closeBtn = document.getElementById('planPanelCloseBtn');
        this._visible = false;
        this._bindEvents();
    }

    _bindEvents() {
        this.closeBtn?.addEventListener('click', () => this.hide());
        // Close on click outside
        document.addEventListener('click', (e) => {
            if (this._visible && this.el && !this.el.contains(e.target) &&
                !document.getElementById('planModeViewBtn')?.contains(e.target)) {
                this.hide();
            }
        });
    }

    toggle() {
        this._visible ? this.hide() : this.show();
    }

    show() {
        this._visible = true;
        if (this.el) this.el.hidden = false;
    }

    hide() {
        this._visible = false;
        if (this.el) this.el.hidden = true;
    }

    get visible() { return this._visible; }
}

class PlanModeManager {
    /** Manages plan mode state and API interactions */
    constructor(app) {
        this.app = app;
        this.indicator = new PlanModeIndicator(app);
        this.editor = new PlanEditor(app);
        this.approval = new PlanApprovalWidget(app);
        this.panel = new PlanModePanel(app);
        this._planMode = false;
        this._planContent = null;
    }

    async enterPlanMode() {
        try {
            await NexusAPI.enterPlanMode();
            this._planMode = true;
            this._planContent = null;
            this.indicator.show('Exploring');
            this.editor.show();
            this.approval.hide();
            this.panel.show();
        } catch (e) {
            console.error('Enter plan mode failed:', e);
            alert(e.message);
        }
    }

    async submitPlan(content) {
        try {
            await NexusAPI.submitPlan(content);
            this._planContent = content;
            this.indicator.setStatus('Awaiting Approval');
            this.editor.hide();
            this.approval.show(content);
        } catch (e) {
            console.error('Submit plan failed:', e);
            alert(e.message);
        }
    }

    async approvePlan() {
        try {
            await NexusAPI.approvePlan();
            this._planMode = false;
            this._planContent = null;
            this.indicator.hide();
            this.panel.hide();
            this.editor.clear();
        } catch (e) {
            console.error('Approve plan failed:', e);
            alert(e.message);
        }
    }

    async rejectPlan() {
        try {
            await NexusAPI.rejectPlan();
            this._planContent = null;
            this.indicator.setStatus('Exploring');
            this.approval.hide();
            this.editor.clear();
            this.editor.show();
        } catch (e) {
            console.error('Reject plan failed:', e);
            alert(e.message);
        }
    }

    async exitPlanMode() {
        try {
            await NexusAPI.exitPlanMode();
            this._planMode = false;
            this._planContent = null;
            this.indicator.hide();
            this.panel.hide();
            this.editor.clear();
        } catch (e) {
            console.error('Exit plan mode failed:', e);
            alert(e.message);
        }
    }

    async refreshStatus() {
        try {
            const data = await NexusAPI.getPlanStatus();
            this._planMode = data.plan_mode;
            this._planContent = data.plan_content;
            if (this._planMode) {
                if (this._planContent) {
                    this.indicator.show('Awaiting Approval');
                    this.editor.hide();
                    this.approval.show(this._planContent);
                } else {
                    this.indicator.show('Exploring');
                    this.editor.show();
                    this.approval.hide();
                }
            } else {
                this.indicator.hide();
            }
        } catch (e) {
            console.debug('Plan status refresh failed:', e);
        }
    }

    get isPlanMode() { return this._planMode; }
}

    global.ConfigView = ConfigView;
    global.AdminView = AdminView;
    global.SettingsView = SettingsView;
    global.GlobalSearch = GlobalSearch;
    global.PlanModeIndicator = PlanModeIndicator;
    global.PlanEditor = PlanEditor;
    global.PlanApprovalWidget = PlanApprovalWidget;
    global.PlanModePanel = PlanModePanel;
    global.PlanModeManager = PlanModeManager;
    global.NexusShellViews = Object.freeze({
        ConfigView,
        AdminView,
        SettingsView,
        GlobalSearch,
        PlanModeIndicator,
        PlanEditor,
        PlanApprovalWidget,
        PlanModePanel,
        PlanModeManager,
    });
})(window);
