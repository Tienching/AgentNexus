/**
 * Panel Definitions - All 32 Nexus panels registered here.
 *
 * Loaded early (after panel-registry.js) so the registry is populated
 * before the UI tries to create panels.
 */

(function registerAllPanels() {
    const registry = window.PanelRegistry;

    // Icon SVG path data (24×24 viewbox)
    const ICONS = {
        agent:    'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z',
        heartbeat:'M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z',
        soul:     'M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z',
        queue:    'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10',
        message:  'M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z',
        task:     'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4',
        comment:  'M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z',
        quality:  'M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z',
        timeline: 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
        skill:    'M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4',
        security: 'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z',
        sync:     'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
        cron:     'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
        nlp:      'M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129',
        template: 'M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6z',
        activity: 'M13 10V3L4 14h7v7l9-11h-7z',
        notify:   'M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9',
        token:    'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
        cost:     'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z',
        memory:   'M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4',
        tree:     'M4 6h16M4 10h16M4 14h16M4 18h16',
        graph:    'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1',
        audit:    'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01',
        trust:    'M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z',
        hook:     'M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4',
        perm:     'M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z',
        webhook:  'M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1',
        github:   'M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z',
        claude:   'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z',
        teleport: 'M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4',
        flag:     'M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2z',
        standup:  'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z',
        rbac:     'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z',
    };

    registry.registerAll([
        // ---- Agent ----
        { id: 'agent-registry',   title: 'Agent Registry',     icon: ICONS.agent,    category: 'agent',   module: 'agent/agent-registry-panel.js',   refreshMs: 15000 },
        { id: 'agent-heartbeat',  title: 'Agent Heartbeat',    icon: ICONS.heartbeat,category: 'agent',   module: 'agent/agent-heartbeat-panel.js',  refreshMs: 5000 },
        { id: 'agent-soul',       title: 'Agent Soul',         icon: ICONS.soul,     category: 'agent',   module: 'agent/agent-soul-panel.js',       refreshMs: 0 },
        { id: 'agent-queue',      title: 'Agent Queue',        icon: ICONS.queue,    category: 'agent',   module: 'agent/agent-queue-panel.js',      refreshMs: 5000 },
        { id: 'agent-messaging',  title: 'Agent Messaging',    icon: ICONS.message,  category: 'agent',   module: 'agent/agent-messaging-panel.js',  refreshMs: 0 },

        // ---- Task ----
        { id: 'task-board',       title: 'Task Board',         icon: ICONS.task,     category: 'task',    module: 'task/task-board-panel.js',         refreshMs: 10000 },
        { id: 'task-comments',    title: 'Task Comments',      icon: ICONS.comment,  category: 'task',    module: 'task/task-comments-panel.js',      refreshMs: 0 },
        { id: 'quality-gate',     title: 'Quality Gate',       icon: ICONS.quality,  category: 'task',    module: 'task/quality-gate-panel.js',       refreshMs: 0 },
        { id: 'task-timeline',    title: 'Task Timeline',      icon: ICONS.timeline, category: 'task',    module: 'task/task-timeline-panel.js',      refreshMs: 15000 },

        // ---- Skill ----
        { id: 'skill-registry',   title: 'Skill Registry',     icon: ICONS.skill,    category: 'skill',   module: 'skill/skill-registry-panel.js',    refreshMs: 30000 },
        { id: 'skill-security',   title: 'Skill Security',     icon: ICONS.security, category: 'skill',   module: 'skill/skill-security-panel.js',    refreshMs: 0 },
        { id: 'skill-sync',       title: 'Skill Sync',         icon: ICONS.sync,     category: 'skill',   module: 'skill/skill-sync-panel.js',        refreshMs: 0 },

        // ---- Scheduler ----
        { id: 'cron-scheduler',   title: 'Cron Scheduler',     icon: ICONS.cron,     category: 'scheduler',module: 'scheduler/cron-scheduler-panel.js', refreshMs: 15000 },
        { id: 'nlp-parser',       title: 'NLP Parser',         icon: ICONS.nlp,      category: 'scheduler',module: 'scheduler/nlp-parser-panel.js',     refreshMs: 0 },
        { id: 'template-tasks',   title: 'Template Tasks',     icon: ICONS.template, category: 'scheduler',module: 'scheduler/template-tasks-panel.js', refreshMs: 30000 },

        // ---- Activity ----
        { id: 'activity-feed',    title: 'Activity Feed',      icon: ICONS.activity, category: 'activity',module: 'activity/activity-feed-panel.js',   refreshMs: 10000 },
        { id: 'notification',     title: 'Notifications',      icon: ICONS.notify,   category: 'activity',module: 'activity/notification-panel.js',    refreshMs: 15000 },
        { id: 'token-usage',      title: 'Token Usage',        icon: ICONS.token,    category: 'activity',module: 'activity/token-usage-panel.js',     refreshMs: 30000 },
        { id: 'cost-analysis',    title: 'Cost Analysis',      icon: ICONS.cost,     category: 'activity',module: 'activity/cost-analysis-panel.js',   refreshMs: 60000 },

        // ---- Memory ----
        { id: 'memory-browser',   title: 'Memory Browser',     icon: ICONS.memory,   category: 'memory',  module: 'memory/memory-browser-panel.js',   refreshMs: 0 },
        { id: 'memory-tree',      title: 'Memory Tree',        icon: ICONS.tree,     category: 'memory',  module: 'memory/memory-tree-panel.js',      refreshMs: 0 },
        { id: 'memory-graph',     title: 'Memory Graph',       icon: ICONS.graph,    category: 'memory',  module: 'memory/memory-graph-panel.js',     refreshMs: 0 },

        // ---- Security ----
        { id: 'security-audit',   title: 'Security Audit',     icon: ICONS.audit,    category: 'security',module: 'security/security-audit-panel.js',  refreshMs: 30000 },
        { id: 'trust-score',      title: 'Trust Score',        icon: ICONS.trust,    category: 'security',module: 'security/trust-score-panel.js',     refreshMs: 30000 },
        { id: 'hook-profiles',    title: 'Hook Profiles',      icon: ICONS.hook,     category: 'security',module: 'security/hook-profiles-panel.js',   refreshMs: 0 },
        { id: 'permission',       title: 'Permissions',        icon: ICONS.perm,     category: 'security',module: 'security/permission-panel.js',      refreshMs: 0 },

        // ---- Integration ----
        { id: 'webhook',          title: 'Webhooks',           icon: ICONS.webhook,  category: 'integration',module: 'integration/webhook-panel.js',  refreshMs: 0 },
        { id: 'github-sync',      title: 'GitHub Sync',        icon: ICONS.github,   category: 'integration',module: 'integration/github-sync-panel.js', refreshMs: 0 },
        { id: 'claude-code',      title: 'Claude Code',        icon: ICONS.claude,   category: 'integration',module: 'integration/claude-code-panel.js', refreshMs: 0 },
        { id: 'teleport',         title: 'Teleport',           icon: ICONS.teleport, category: 'integration',module: 'integration/teleport-panel.js',  refreshMs: 0 },

        // ---- Admin ----
        { id: 'feature-flag',     title: 'Feature Flags',      icon: ICONS.flag,     category: 'admin',   module: 'admin/feature-flag-panel.js',      refreshMs: 0 },
        { id: 'standup-report',   title: 'Standup Report',     icon: ICONS.standup,  category: 'admin',   module: 'admin/standup-report-panel.js',    refreshMs: 0 },
        { id: 'rbac',             title: 'RBAC',               icon: ICONS.rbac,     category: 'admin',   module: 'admin/rbac-panel.js',              refreshMs: 0 },
    ]);
})();
