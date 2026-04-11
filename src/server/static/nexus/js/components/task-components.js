/**
 * Task detail tab rendering functions — standalone, no BasePanel dependency.
 *
 * Each function receives a container element, task ID, and a context object
 * with helpers for API calls, HTML escaping, time formatting, etc.
 *
 * Usage:
 *   renderTaskComments(container, taskId, ctx)
 *   renderQualityGate(container, taskId, ctx)
 *   renderTaskTimeline(container, taskId, ctx)
 */

/* ------------------------------------------------------------------ */
/* Helpers (private)                                                   */
/* ------------------------------------------------------------------ */

function _tcEsc(str) {
    const d = document.createElement('div');
    d.textContent = str || '';
    return d.innerHTML;
}

function _tcFormatTime(timestamp) {
    if (!timestamp) return '';
    const d = new Date(timestamp);
    const diff = Date.now() - d;
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return d.toLocaleDateString();
}

function _tcGetExecUser() {
    return document.getElementById('globalUserFilter')?.value || NexusAPI.getDefaultExecUser();
}

function _tcGetApp() {
    return window.nexusApp || window.app;
}

/* ------------------------------------------------------------------ */
/* Comments                                                            */
/* ------------------------------------------------------------------ */

function _renderCommentNode(comment, depth, ctx) {
    const replies = Array.isArray(comment?.replies) ? comment.replies : [];
    const margin = Math.min(depth * 14, 42);
    const rawCommentId = String(comment?.id || '');
    const domCommentId = rawCommentId.replace(/[^A-Za-z0-9_-]/g, '_');
    const mentions = Array.isArray(comment?.mentions) && comment.mentions.length
        ? `<div style="font-size:10px;color:var(--text-muted);margin-top:3px;">Mentions: ${_tcEsc(comment.mentions.map((m) => `@${m}`).join(' '))}</div>`
        : '';
    const app = _tcGetApp();
    const contentHtml = app?.chatView?.formatMessageContent
        ? app.chatView.formatMessageContent(comment.content || '')
        : _tcEsc(comment.content || '');

    return `
        <div style="margin-left:${margin}px;border:1px solid var(--border);border-radius:6px;padding:8px;background:var(--bg-secondary);display:flex;flex-direction:column;gap:6px;">
            <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">
                <span style="font-size:11px;font-weight:600;color:var(--text-primary);">${_tcEsc(comment.author || 'user')}</span>
                <span style="font-size:10px;color:var(--text-muted);">${_tcFormatTime((comment.created_at || 0) * 1000)}</span>
            </div>
            <div class="message-text" style="font-size:12px;">${contentHtml}</div>
            ${mentions}
            <div style="display:flex;gap:6px;">
                <button class="action-btn" data-action="reply-comment" data-comment-id="${_tcEsc(rawCommentId)}" data-comment-dom-id="${domCommentId}" style="padding:2px 8px;font-size:11px;">Reply</button>
            </div>
            <div id="replyForm-${domCommentId}" style="display:none;gap:6px;">
                <textarea id="replyInput-${domCommentId}" class="form-input" rows="2" placeholder="Write a reply... use @name for mentions"></textarea>
                <button class="action-btn primary" data-action="submit-reply" data-comment-id="${_tcEsc(rawCommentId)}" data-comment-dom-id="${domCommentId}" style="padding:4px 10px;font-size:11px;">Post Reply</button>
            </div>
            ${replies.length ? `<div style="display:flex;flex-direction:column;gap:6px;">${replies.map((r) => _renderCommentNode(r, depth + 1, ctx)).join('')}</div>` : ''}
        </div>
    `;
}

function _getMentionCandidates() {
    const app = _tcGetApp();
    const candidates = [];
    const agents = app?.chatView?.getAvailableAgents ? app.chatView.getAvailableAgents('') : [];
    const usernames = [...new Set((agents || []).map((a) => String(a?.username || '').trim()).filter(Boolean))];
    const agentNames = [...new Set((agents || []).map((a) => String(a?.agent_type || '').trim()).filter(Boolean))];

    usernames.forEach((username) => {
        candidates.push({ id: `user:${username}`, label: username, type: 'user' });
    });
    agentNames.forEach((agent) => {
        candidates.push({ id: `agent:${agent}`, label: agent, type: 'agent' });
    });

    if (typeof window.MentionTextarea === 'function' && typeof window.MentionTextarea.normalizeCandidates === 'function') {
        return window.MentionTextarea.normalizeCandidates(candidates);
    }
    return candidates;
}

/**
 * Render the Comments tab content.
 *
 * @param {HTMLElement} container  The tab pane element
 * @param {string} taskId         Task ID
 * @param {Object}   ctx          Context with .mentionInputsByPane, .paneId
 */
async function renderTaskComments(container, taskId, ctx) {
    const paneId = ctx.paneId;
    const rootId = `taskComments-${paneId}`;

    // Destroy old MentionTextarea instances
    const oldMentions = ctx.mentionInputsByPane?.[paneId] || [];
    oldMentions.forEach((instance) => { try { instance.destroy(); } catch {} });
    if (ctx.mentionInputsByPane) ctx.mentionInputsByPane[paneId] = [];

    let commentsRoot = document.getElementById(rootId);
    if (!commentsRoot) {
        commentsRoot = container;
    }

    const execUser = _tcGetExecUser();

    try {
        const data = await NexusAPI.getTaskComments(taskId, { execUser });
        const comments = Array.isArray(data?.comments) ? data.comments : [];

        commentsRoot.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                <strong style="font-size:12px;color:var(--text-primary);">Comments</strong>
                <span style="font-size:11px;color:var(--text-muted);">${comments.length}</span>
            </div>
            <div style="display:flex;flex-direction:column;gap:6px;max-height:220px;overflow-y:auto;margin-bottom:10px;">
                ${comments.length ? comments.map((c) => _renderCommentNode(c, 0, ctx)).join('') : '<div style="font-size:11px;color:var(--text-muted);">No comments yet.</div>'}
            </div>
            <div style="border-top:1px solid var(--border);padding-top:8px;display:grid;gap:6px;">
                <label style="font-size:11px;color:var(--text-muted);">New comment</label>
                <textarea id="taskCommentInput-${paneId}" class="form-input" rows="3" placeholder="Write a comment... use @name for mentions"></textarea>
                <div style="display:flex;gap:6px;justify-content:flex-end;">
                    <button class="action-btn primary" data-action="submit-comment" style="padding:4px 12px;">Post</button>
                </div>
            </div>
        `;

        const submitBtn = commentsRoot.querySelector('[data-action="submit-comment"]');
        if (submitBtn) {
            submitBtn.addEventListener('click', async () => {
                const input = document.getElementById(`taskCommentInput-${paneId}`);
                const content = input?.value?.trim() || '';
                if (!content) {
                    _tcGetApp()?.showToast?.('Comment content is required', 'warning');
                    return;
                }
                await NexusAPI.createTaskComment(taskId, { content, author: 'user' }, { execUser });
                if (input) input.value = '';
                await renderTaskComments(container, taskId, ctx);
            });
        }

        commentsRoot.querySelectorAll('[data-action="reply-comment"]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const domId = btn.getAttribute('data-comment-dom-id') || '';
                const form = document.getElementById(`replyForm-${domId}`);
                if (!form) return;
                form.style.display = form.style.display === 'none' ? 'grid' : 'none';
            });
        });

        commentsRoot.querySelectorAll('[data-action="submit-reply"]').forEach((btn) => {
            btn.addEventListener('click', async () => {
                const commentId = btn.getAttribute('data-comment-id') || '';
                const domId = btn.getAttribute('data-comment-dom-id') || '';
                const input = document.getElementById(`replyInput-${domId}`);
                const content = input?.value?.trim() || '';
                if (!content) {
                    _tcGetApp()?.showToast?.('Reply content is required', 'warning');
                    return;
                }
                await NexusAPI.createTaskComment(taskId, { content, author: 'user', parent_id: commentId }, { execUser });
                await renderTaskComments(container, taskId, ctx);
            });
        });

        if (typeof window.MentionTextarea === 'function') {
            const mentionCandidates = _getMentionCandidates();
            const instances = [];
            const mainInput = document.getElementById(`taskCommentInput-${paneId}`);
            if (mainInput) {
                instances.push(new window.MentionTextarea(mainInput, { candidates: mentionCandidates, maxItems: 8 }));
            }
            commentsRoot.querySelectorAll('textarea[id^="replyInput-"]').forEach((textarea) => {
                instances.push(new window.MentionTextarea(textarea, { candidates: mentionCandidates, maxItems: 8 }));
            });
            if (ctx.mentionInputsByPane) ctx.mentionInputsByPane[paneId] = instances;
        }
    } catch (error) {
        console.error('Failed to load task comments:', error);
        commentsRoot.innerHTML = `<div style="font-size:12px;color:var(--error);">Failed to load comments</div>`;
    }
}

/* ------------------------------------------------------------------ */
/* Quality Gate                                                        */
/* ------------------------------------------------------------------ */

/**
 * Render the Quality tab content.
 *
 * @param {HTMLElement} container  The tab pane element
 * @param {string} taskId         Task ID
 * @param {Object}   ctx          Context with .paneId, .onRefresh(callback)
 */
async function renderQualityGate(container, taskId, ctx) {
    const paneId = ctx.paneId;
    const rootId = `taskQuality-${paneId}`;

    let qualityRoot = document.getElementById(rootId);
    if (!qualityRoot) {
        qualityRoot = container;
    }

    const execUser = _tcGetExecUser();
    const app = _tcGetApp();

    try {
        const data = await NexusAPI.getTaskQualityReviews(taskId, { execUser });
        const latest = data?.latest_review;
        const reviews = Array.isArray(data?.reviews) ? data.reviews : [];
        qualityRoot.innerHTML = `
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
                <strong style="font-size: 12px; color: var(--text-primary);">Aegis Quality</strong>
                <span style="font-size: 11px; color: ${data?.gate_allowed ? 'var(--success)' : 'var(--warning)'};">
                    ${data?.gate_allowed ? 'Gate Passed' : 'Gate Blocked'}
                </span>
            </div>
            <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 10px;">
                ${_tcEsc(data?.gate_reason || '')}
            </div>
            ${latest ? `
                <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 10px;">
                    Latest: <strong>${_tcEsc(String(latest.status || ''))}</strong>
                    by ${_tcEsc(String(latest.reviewer || 'unknown'))}
                    · ${_tcFormatTime((latest.created_at || 0) * 1000)}
                </div>
            ` : '<div style="font-size: 11px; color: var(--text-muted); margin-bottom: 10px;">No reviews yet.</div>'}
            <div style="display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; max-height: 180px; overflow-y: auto;">
                ${reviews.length ? reviews.map((review) => `
                    <div style="border: 1px solid var(--border); border-radius: 6px; padding: 8px; background: var(--bg-secondary);">
                        <div style="display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-bottom: 4px;">
                            <span style="font-size: 11px; font-weight: 600; color: var(--text-primary);">${_tcEsc(String(review.status || ''))}</span>
                            <span style="font-size: 10px; color: var(--text-muted);">${_tcFormatTime((review.created_at || 0) * 1000)}</span>
                        </div>
                        <div style="font-size: 11px; color: var(--text-secondary); margin-bottom: 4px;">Reviewer: ${_tcEsc(String(review.reviewer || 'unknown'))}</div>
                        ${review.notes ? `<div class="message-text" style="font-size: 11px; color: var(--text-secondary);">${app?.chatView?.formatMessageContent ? app.chatView.formatMessageContent(String(review.notes)) : _tcEsc(String(review.notes))}</div>` : ''}
                    </div>
                `).join('') : '<div style="font-size: 11px; color: var(--text-muted);">No history entries.</div>'}
            </div>
            <div style="border-top: 1px solid var(--border); padding-top: 10px; display: grid; gap: 6px;">
                <label style="font-size: 11px; color: var(--text-muted);">Reviewer</label>
                <input id="qualityReviewer-${paneId}" type="text" class="form-input" value="aegis" placeholder="reviewer">
                <label style="font-size: 11px; color: var(--text-muted);">Status</label>
                <select id="qualityStatus-${paneId}" class="form-input form-select">
                    <option value="approved">approved</option>
                    <option value="needs_changes">needs_changes</option>
                    <option value="rejected">rejected</option>
                </select>
                <label style="font-size: 11px; color: var(--text-muted);">Notes (Markdown)</label>
                <textarea id="qualityNotes-${paneId}" class="form-input" rows="3" placeholder="Review notes"></textarea>
                <div style="display:flex;gap:6px;justify-content:flex-end;">
                    <button class="action-btn" type="button" data-action="toggle-quality-preview" data-task-id="${taskId}" style="padding:4px 10px;">Preview</button>
                    <button class="action-btn primary" data-action="submit-quality-review" data-task-id="${taskId}" style="justify-content: center;">Submit Review</button>
                </div>
                <div id="qualityPreview-${paneId}" style="display:none;border:1px solid var(--border);border-radius:6px;padding:8px;background:var(--bg-secondary);">
                    <div class="message-empty">Nothing to preview</div>
                </div>
            </div>
        `;

        const submitBtn = qualityRoot.querySelector('[data-action="submit-quality-review"]');
        if (submitBtn) {
            submitBtn.addEventListener('click', async () => {
                const reviewer = document.getElementById(`qualityReviewer-${paneId}`)?.value?.trim() || 'aegis';
                const status = document.getElementById(`qualityStatus-${paneId}`)?.value || 'approved';
                const notes = document.getElementById(`qualityNotes-${paneId}`)?.value?.trim() || '';
                try {
                    await NexusAPI.submitTaskQualityReview(taskId, { reviewer, status, notes }, { execUser });
                    app?.showToast?.('Quality review submitted', 'success');
                    if (ctx.onRefresh) await ctx.onRefresh(taskId);
                } catch (error) {
                    console.error('Failed to submit quality review:', error);
                    app?.showToast?.(error.message || 'Failed to submit quality review', 'error');
                }
            });
        }

        const previewBtn = qualityRoot.querySelector('[data-action="toggle-quality-preview"]');
        if (previewBtn) {
            previewBtn.addEventListener('click', () => {
                const preview = document.getElementById(`qualityPreview-${paneId}`);
                const notesValue = document.getElementById(`qualityNotes-${paneId}`)?.value || '';
                if (!preview) return;
                const shouldShow = preview.style.display === 'none';
                preview.style.display = shouldShow ? '' : 'none';
                if (!shouldShow) return;
                const renderer = app?.chatView?.markdownRenderer;
                if (renderer && typeof renderer.renderPreview === 'function') {
                    renderer.renderPreview(notesValue, preview);
                } else {
                    preview.innerHTML = `<div class="message-text">${app?.chatView?.formatMessageContent ? app.chatView.formatMessageContent(notesValue) : _tcEsc(notesValue)}</div>`;
                }
            });
        }
    } catch (error) {
        console.error('Failed to load quality reviews:', error);
        qualityRoot.innerHTML = `<div style="font-size: 12px; color: var(--error);">Failed to load quality reviews</div>`;
    }
}

/* ------------------------------------------------------------------ */
/* Timeline                                                            */
/* ------------------------------------------------------------------ */

/**
 * Render the Timeline tab content.
 *
 * @param {HTMLElement} container  The tab pane element
 * @param {string} taskId         Task ID
 * @param {Object}   ctx          Context with .paneId
 */
async function renderTaskTimeline(container, taskId, ctx) {
    const paneId = ctx.paneId;
    const rootId = `taskTimeline-${paneId}`;

    let timelineRoot = document.getElementById(rootId);
    if (!timelineRoot) {
        timelineRoot = container;
    }

    const execUser = _tcGetExecUser();

    try {
        const data = await NexusAPI.getAuditLog({ action: 'task', task_id: taskId, limit: 50 });
        const events = Array.isArray(data?.entries || data?.logs) ? (data.entries || data.logs) : [];

        timelineRoot.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                <strong style="font-size:12px;color:var(--text-primary);">Timeline</strong>
                <span style="font-size:11px;color:var(--text-muted);">${events.length} events</span>
            </div>
            ${events.length === 0 ? '<div style="font-size:11px;color:var(--text-muted);">No task events recorded</div>' : `
            <div style="display:flex;flex-direction:column;gap:2px;max-height:320px;overflow-y:auto;">
                ${events.map(ev => {
                    const time = ev.timestamp ? new Date(ev.timestamp).toLocaleString() : '';
                    const statusClass = ev.action?.includes('fail') ? 'status-offline' :
                                       ev.action?.includes('complet') ? 'status-online' : 'status-warn';
                    return `
                    <div style="display:flex;gap:8px;align-items:flex-start;padding:4px 0;">
                        <div style="width:8px;height:8px;border-radius:50%;margin-top:4px;flex-shrink:0;background:${statusClass === 'status-online' ? 'var(--success, #22c55e)' : statusClass === 'status-offline' ? 'var(--error, #ef4444)' : 'var(--warning, #f59e0b)'};"></div>
                        <div style="flex:1;min-width:0;">
                            <div style="font-size:11px;font-weight:600;color:var(--text-primary);">${_tcEsc(ev.action || ev.event_type || 'Event')}</div>
                            <div style="font-size:10px;color:var(--text-muted);">${time}${ev.task_id ? ' · ' + _tcEsc(ev.task_id.slice(0,8)) : ''}</div>
                            ${ev.detail ? `<div style="font-size:11px;color:var(--text-secondary);margin-top:2px;">${_tcEsc(ev.detail)}</div>` : ''}
                        </div>
                    </div>`;
                }).join('')}
            </div>`}
        `;
    } catch (error) {
        console.error('Failed to load task timeline:', error);
        timelineRoot.innerHTML = `<div style="font-size:12px;color:var(--error);">Failed to load timeline</div>`;
    }
}

// Export globally
window.TaskComponents = {
    renderTaskComments,
    renderQualityGate,
    renderTaskTimeline,
};
