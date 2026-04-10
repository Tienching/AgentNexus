/**
 * TaskCommentsPanel - View and add comments on tasks.
 */

class TaskCommentsPanel extends BasePanel {
    constructor(id, def, opts) {
        super(id, def, opts);
        this._taskId = opts.taskId || null;
        this._comments = [];
    }

    setTaskId(taskId) {
        this._taskId = taskId;
        this.refresh();
    }

    async refresh() {
        if (!this._taskId) { this.showEmpty('Select a task to view comments'); return; }
        try {
            const data = await this.api.getTaskComments(this._taskId);
            this._comments = data.comments || [];
            this.render(this.container);
        } catch (e) {
            this.showError(e.message);
        }
    }

    render(container) {
        this.container = container;
        if (!this._taskId) { this.showEmpty('Select a task to view comments'); return; }

        container.innerHTML = `
            ${this._headerHtml()}
            <div class="panel-body">
                <div class="panel-comment-list">
                    ${this._comments.map(c => `
                        <div class="panel-comment">
                            <div class="panel-comment-header">
                                <span class="panel-comment-author">${this._escapeHtml(c.author || c.username || 'Unknown')}</span>
                                <span class="panel-comment-time">${c.created_at ? new Date(c.created_at).toLocaleString() : ''}</span>
                            </div>
                            <div class="panel-comment-body">${this._escapeHtml(c.content || c.text || '')}</div>
                        </div>
                    `).join('')}
                </div>
                <div class="panel-comment-input">
                    <textarea class="panel-input" rows="2" placeholder="Add a comment…" data-role="comment-input"></textarea>
                    <button class="panel-btn primary" data-action="submit-comment">Send</button>
                </div>
            </div>
        `;

        this._bindRefreshBtn();
        const submitBtn = container.querySelector('[data-action="submit-comment"]');
        const input = container.querySelector('[data-role="comment-input"]');
        if (submitBtn && input) {
            submitBtn.addEventListener('click', async () => {
                const text = input.value.trim();
                if (!text) return;
                try {
                    await this.api.createTaskComment(this._taskId, { content: text });
                    input.value = '';
                    this.refresh();
                } catch (e) {
                    this.showError(e.message);
                }
            });
        }
    }
}

export { TaskCommentsPanel };
