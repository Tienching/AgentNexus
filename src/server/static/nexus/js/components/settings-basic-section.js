(function initSettingsBasicSection(global) {
    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    class SettingsBasicSection {
        constructor(app, options = {}) {
            this.app = app;
            this.root = options.root || document.querySelector('[data-settings-section="basic"]');
            this.summary = document.getElementById('settingsBasicSummary');
        }

        async refresh() {
            if (!this.root) return;
            this.renderSummary();
            this.app.configView?.renderParameters?.();
        }

        renderSummary() {
            if (!this.summary) return;

            const defaultProvider = this.app.getDefaultProvider?.() || 'claude';
            const aliases = Array.isArray(this.app.customProviders) ? this.app.customProviders.length : 0;
            const execUser = this.app.getDefaultExecUser?.() || 'ubuntu';
            const workdir = this.app.serverDefaults?.current_workdir || '—';
            const users = Array.isArray(this.app.availableUsers) ? this.app.availableUsers.length : 0;

            this.summary.innerHTML = `
                <div class="admin-cards">
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Default Provider</span><span class="admin-metric-value">${escapeHtml(defaultProvider)}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Aliases</span><span class="admin-metric-value">${aliases}</span></div>
                        </div>
                    </div>
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Exec User</span><span class="admin-metric-value">${escapeHtml(execUser)}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Known Users</span><span class="admin-metric-value">${users}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Workspace</span><span class="admin-metric-value">${escapeHtml(workdir)}</span></div>
                        </div>
                    </div>
                </div>
            `;
        }
    }

    global.SettingsBasicSection = SettingsBasicSection;
    global.NexusSettingsSections = global.NexusSettingsSections || {};
    global.NexusSettingsSections.SettingsBasicSection = SettingsBasicSection;
})(window);
