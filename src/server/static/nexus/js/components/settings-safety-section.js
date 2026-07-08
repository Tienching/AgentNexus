(function initSettingsSafetySection(global) {
    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    class SettingsSafetySection {
        constructor(app, options = {}) {
            this.app = app;
            this.root = options.root || document.querySelector('[data-settings-section="safety"]');
            this.summary = document.getElementById('settingsSafetySummary');
        }

        async refresh() {
            if (!this.root) return;
            this.renderSummary();
        }

        renderSummary() {
            if (!this.summary) return;

            const execUser = this.app.getDefaultExecUser?.() || 'ubuntu';
            const cliCommand = this.app.serverDefaults?.cli_command || 'codebuddy';
            const workdir = this.app.serverDefaults?.current_workdir || '—';

            this.summary.innerHTML = `
                <div class="admin-cards">
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Exec User</span><span class="admin-metric-value">${escapeHtml(execUser)}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">CLI</span><span class="admin-metric-value">${escapeHtml(cliCommand)}</span></div>
                        </div>
                    </div>
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Runtime Focus</span><span class="admin-metric-value">Terminal · Workspace</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Current Workdir</span><span class="admin-metric-value">${escapeHtml(workdir)}</span></div>
                        </div>
                    </div>
                </div>
                <div class="u-text-secondary u-text-sm u-mt-sm">这里仅保留运行相关信息；原先的安全、审计、治理等后台控制面已从主设置流里移除。</div>
            `;
        }
    }

    global.SettingsSafetySection = SettingsSafetySection;
    global.NexusSettingsSections = global.NexusSettingsSections || {};
    global.NexusSettingsSections.SettingsSafetySection = SettingsSafetySection;
})(window);
