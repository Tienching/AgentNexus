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
            this.securityPanel = document.getElementById('settingsSafetySecurityPanel');
            this.auditPanel = document.getElementById('settingsSafetyAuditPanel');
            this.cleanupPanel = document.getElementById('settingsSafetyCleanupPanel');
            this.adminPanel = document.getElementById('settingsSafetyAdminPanel');
        }

        async refresh() {
            if (!this.root) return;
            this.renderSummary();
            await this._renderAdminPanel('renderSecurity', this.securityPanel);
            await this._renderAdminPanel('renderAudit', this.auditPanel);
            await this._renderAdminPanel('renderCleanup', this.cleanupPanel);
            await this._renderAdminPanel('renderAdminTab', this.adminPanel);
        }

        renderSummary() {
            if (!this.summary) return;

            const agents = Array.isArray(this.app.availableAgents) ? this.app.availableAgents.length : 0;
            const online = Array.isArray(this.app.availableAgents)
                ? this.app.availableAgents.filter(agent => agent?.available).length
                : 0;

            this.summary.innerHTML = `
                <div class="admin-cards">
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Agents in Scope</span><span class="admin-metric-value">${agents}</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Online Now</span><span class="admin-metric-value">${online}</span></div>
                        </div>
                    </div>
                    <div class="admin-card">
                        <div class="admin-card-body">
                            <div class="admin-metric"><span class="admin-metric-label">Safety Surface</span><span class="admin-metric-value">Security · Audit · Cleanup</span></div>
                            <div class="admin-metric"><span class="admin-metric-label">Governance</span><span class="admin-metric-value">Flags · RBAC · Standup</span></div>
                        </div>
                    </div>
                </div>
            `;
        }

        async _renderAdminPanel(methodName, container) {
            if (!container || !this.app.adminView || typeof this.app.adminView[methodName] !== 'function') {
                return;
            }

            // Clear any stale content so partial renders from a previous pass don't
            // visually leak into this section (prevents the "safety tab showing basic
            // tab's content" bug caused by overlapping async renders).
            container.innerHTML = '';

            const previousContainer = this.app.adminView.container;
            this.app.adminView.container = container;
            try {
                await this.app.adminView[methodName]();
            } catch (error) {
                container.innerHTML = `<div class="admin-error">${escapeHtml(error.message || 'Failed to load section')}</div>`;
            } finally {
                // Only restore if nothing else swapped it out meanwhile.
                if (this.app.adminView.container === container) {
                    this.app.adminView.container = previousContainer;
                }
            }
        }
    }

    global.SettingsSafetySection = SettingsSafetySection;
    global.NexusSettingsSections = global.NexusSettingsSections || {};
    global.NexusSettingsSections.SettingsSafetySection = SettingsSafetySection;
})(window);
