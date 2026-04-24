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

function _tcCommentDepthClass(depth) {
    const normalizedDepth = Math.max(0, Math.min(Number(depth) || 0, 3));
    return `task-comment-card depth-${normalizedDepth}`;
}

function _tcTimelineStatusClass(action) {
    const value = String(action || '').toLowerCase();
    if (value.includes('fail')) return 'is-error';
    if (value.includes('complet')) return 'is-success';
    return 'is-warning';
}

/* ------------------------------------------------------------------ */
/* Comments                                                            */
/* ------------------------------------------------------------------ */

function _renderCommentNode(comment, depth, ctx) {
    const replies = Array.isArray(comment?.replies) ? comment.replies : [];
    const rawCommentId = String(comment?.id || '');
    const domCommentId = rawCommentId.replace(/[^A-Za-z0-9_-]/g, '_');
    const mentions = Array.isArray(comment?.mentions) && comment.mentions.length
        ? `<div class="task-comment-mentions">Mentions: ${_tcEsc(comment.mentions.map((m) => `@${m}`).join(' '))}</div>`
        : '';
    const app = _tcGetApp();
    const contentHtml = app?.chatView?.formatMessageContent
        ? app.chatView.formatMessageContent(comment.content || '')
        : _tcEsc(comment.content || '');

    return `
        <div class="${_tcCommentDepthClass(depth)}">
            <div class="task-comment-header">
                <span class="task-comment-author">${_tcEsc(comment.author || 'user')}</span>
                <span class="task-comment-time">${_tcFormatTime((comment.created_at || 0) * 1000)}</span>
            </div>
            <div class="message-text task-comment-body">${contentHtml}</div>
            ${mentions}
            <div class="task-comment-actions">
                <button class="action-btn task-comment-reply-btn" data-action="reply-comment" data-comment-id="${_tcEsc(rawCommentId)}" data-comment-dom-id="${domCommentId}">Reply</button>
            </div>
            <div id="replyForm-${domCommentId}" class="task-comment-reply-form" hidden>
                <textarea id="replyInput-${domCommentId}" class="form-input" rows="2" placeholder="Write a reply... use @name for mentions"></textarea>
                <button class="action-btn primary task-comment-submit-btn" data-action="submit-reply" data-comment-id="${_tcEsc(rawCommentId)}" data-comment-dom-id="${domCommentId}">Post Reply</button>
            </div>
            ${replies.length ? `<div class="task-comment-replies">${replies.map((r) => _renderCommentNode(r, depth + 1, ctx)).join('')}</div>` : ''}
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
            <div class="task-pane-header">
                <strong class="task-pane-title">Comments</strong>
                <span class="task-pane-count">${comments.length}</span>
            </div>
            <div class="task-comment-list">
                ${comments.length ? comments.map((c) => _renderCommentNode(c, 0, ctx)).join('') : '<div class="task-pane-empty">No comments yet.</div>'}
            </div>
            <div class="task-pane-form">
                <label class="task-pane-label">New comment</label>
                <textarea id="taskCommentInput-${paneId}" class="form-input" rows="3" placeholder="Write a comment... use @name for mentions"></textarea>
                <div class="task-pane-actions">
                    <button class="action-btn primary task-comment-submit-btn" data-action="submit-comment">Post</button>
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
                form.hidden = !form.hidden;
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
        commentsRoot.innerHTML = '<div class="task-pane-error">Failed to load comments</div>';
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
            <div class="task-pane-header">
                <strong class="task-pane-title">Aegis Quality</strong>
                <span class="task-quality-state ${data?.gate_allowed ? 'is-passed' : 'is-blocked'}">
                    ${data?.gate_allowed ? 'Gate Passed' : 'Gate Blocked'}
                </span>
            </div>
            <div class="task-pane-caption">
                ${_tcEsc(data?.gate_reason || '')}
            </div>
            ${latest ? `
                <div class="task-pane-note">
                    Latest: <strong>${_tcEsc(String(latest.status || ''))}</strong>
                    by ${_tcEsc(String(latest.reviewer || 'unknown'))}
                    · ${_tcFormatTime((latest.created_at || 0) * 1000)}
                </div>
            ` : '<div class="task-pane-empty is-compact">No reviews yet.</div>'}
            <div class="task-quality-history">
                ${reviews.length ? reviews.map((review) => `
                    <div class="task-quality-review-card">
                        <div class="task-quality-review-header">
                            <span class="task-quality-review-status">${_tcEsc(String(review.status || ''))}</span>
                            <span class="task-quality-review-time">${_tcFormatTime((review.created_at || 0) * 1000)}</span>
                        </div>
                        <div class="task-quality-reviewer">Reviewer: ${_tcEsc(String(review.reviewer || 'unknown'))}</div>
                        ${review.notes ? `<div class="message-text task-quality-review-notes">${app?.chatView?.formatMessageContent ? app.chatView.formatMessageContent(String(review.notes)) : _tcEsc(String(review.notes))}</div>` : ''}
                    </div>
                `).join('') : '<div class="task-pane-empty is-compact">No history entries.</div>'}
            </div>
            <div class="task-pane-form task-pane-form-lg">
                <label class="task-pane-label">Reviewer</label>
                <input id="qualityReviewer-${paneId}" type="text" class="form-input" value="aegis" placeholder="reviewer">
                <label class="task-pane-label">Status</label>
                <select id="qualityStatus-${paneId}" class="form-input form-select">
                    <option value="approved">approved</option>
                    <option value="needs_changes">needs_changes</option>
                    <option value="rejected">rejected</option>
                </select>
                <label class="task-pane-label">Notes (Markdown)</label>
                <textarea id="qualityNotes-${paneId}" class="form-input" rows="3" placeholder="Review notes"></textarea>
                <div class="task-pane-actions">
                    <button class="action-btn task-quality-preview-btn" type="button" data-action="toggle-quality-preview" data-task-id="${taskId}">Preview</button>
                    <button class="action-btn primary task-quality-submit-btn" data-action="submit-quality-review" data-task-id="${taskId}">Submit Review</button>
                </div>
                <div id="qualityPreview-${paneId}" class="task-quality-preview" hidden>
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
                const shouldShow = preview.hidden;
                preview.hidden = !preview.hidden;
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
        qualityRoot.innerHTML = '<div class="task-pane-error">Failed to load quality reviews</div>';
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
            <div class="task-pane-header">
                <strong class="task-pane-title">Timeline</strong>
                <span class="task-pane-count">${events.length} events</span>
            </div>
            ${events.length === 0 ? '<div class="task-pane-empty is-compact">No task events recorded</div>' : `
            <div class="task-timeline-list">
                ${events.map(ev => {
                    const time = ev.timestamp ? new Date(ev.timestamp).toLocaleString() : '';
                    const statusClass = _tcTimelineStatusClass(ev.action || ev.event_type);
                    return `
                    <div class="task-timeline-row">
                        <div class="task-timeline-dot ${statusClass}"></div>
                        <div class="task-timeline-body">
                            <div class="task-timeline-title">${_tcEsc(ev.action || ev.event_type || 'Event')}</div>
                            <div class="task-timeline-meta">${time}${ev.task_id ? ' · ' + _tcEsc(ev.task_id.slice(0,8)) : ''}</div>
                            ${ev.detail ? `<div class="task-timeline-detail">${_tcEsc(ev.detail)}</div>` : ''}
                        </div>
                    </div>`;
                }).join('')}
            </div>`}
        `;
    } catch (error) {
        console.error('Failed to load task timeline:', error);
        timelineRoot.innerHTML = '<div class="task-pane-error">Failed to load timeline</div>';
    }
}

// Export globally
window.TaskComponents = {
    renderTaskComments,
    renderQualityGate,
    renderTaskTimeline,
};
