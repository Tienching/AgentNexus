/**
 * Kanban drag-and-drop helper.
 *
 * Enhanced HTML5 DnD wrapper for Nexus task board.
 * Supports cross-column status changes AND within-column reordering
 * using float-based position calculation.
 *
 * Features:
 * - Custom ghost drag preview (replaces browser default thumbnail)
 * - Drop indicator insertion line with pulse animation
 * - Center-distance column collision detection
 * - Card midpoint insertion index calculation
 * - Drag lifecycle body class & user-select suppression
 *
 * Expects:
 * - board element containing .kanban-column[data-status]
 * - cards with .task-card[data-task-id][draggable="true"]
 */
class KanbanDragDrop {
    static POSITION_GAP = 65536;

    static mount(board, options = {}) {
        if (!board) return null;
        const instance = new KanbanDragDrop(board, options);
        instance.bind();
        return instance;
    }

    constructor(board, options = {}) {
        this.board = board;
        this.onMove = options.onMove || (async () => {});
        this.onReorder = options.onReorder || (async () => {});
        this.onDragStart = options.onDragStart || (() => {});
        this.onDragEnd = options.onDragEnd || (() => {});
        this.getTaskStatus = options.getTaskStatus || (() => null);
        this.getTaskPosition = options.getTaskPosition || (() => 0);
        this.dragState = null;
        this._dropIndicator = null;
        this._ghostEl = null;
        this._columnEls = [];
    }

    bind() {
        this._columnEls = Array.from(this.board.querySelectorAll('.kanban-column'));

        this.board.querySelectorAll('.task-card[draggable="true"]').forEach((card) => {
            if (card.dataset.kanbanBound === '1') return;
            card.dataset.kanbanBound = '1';
            card.addEventListener('dragstart', (event) => this.handleDragStart(event, card));
            card.addEventListener('dragend', () => this.handleDragEnd());
        });

        this._columnEls.forEach((column) => {
            const items = column.querySelector('.kanban-column-items');
            if (!items || items.dataset.kanbanBound === '1') return;
            items.dataset.kanbanBound = '1';
            items.addEventListener('dragover', (event) => this.handleDragOver(event, items, column));
            items.addEventListener('dragenter', (event) => this.handleDragEnter(event, column));
            items.addEventListener('dragleave', (event) => this.handleDragLeave(event, items, column));
            items.addEventListener('drop', (event) => this.handleDrop(event, items, column));
        });
    }

    handleDragStart(event, card) {
        const taskId = card.dataset.taskId;
        const fromStatus = this.getTaskStatus(taskId) || card.closest('.kanban-column')?.dataset.status || '';
        this.dragState = { taskId, fromStatus };

        // Mark original card as being dragged
        card.classList.add('task-card-dragging');

        // Create custom ghost preview element
        const ghost = card.cloneNode(true);
        ghost.classList.add('task-card-ghost');
        ghost.style.width = card.offsetWidth + 'px';
        ghost.style.position = 'absolute';
        ghost.style.top = '-1000px';
        document.body.appendChild(ghost);
        if (event.dataTransfer) {
            event.dataTransfer.setDragImage(ghost, 20, 20);
        }
        this._ghostEl = ghost;

        // Drag lifecycle: suppress text selection and add body class
        document.body.classList.add('kanban-dragging-active');
        document.body.style.userSelect = 'none';
        document.body.style.webkitUserSelect = 'none';

        this.onDragStart(taskId, fromStatus);
        if (event.dataTransfer) {
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', JSON.stringify(this.dragState));
        }
    }

    handleDragEnd() {
        // Remove drag lifecycle state
        document.body.classList.remove('kanban-dragging-active');
        document.body.style.userSelect = '';
        document.body.style.webkitUserSelect = '';

        // Clean up visual indicators
        this._removeDropIndicator();
        this.board.querySelectorAll('.task-card-dragging').forEach((el) => el.classList.remove('task-card-dragging'));
        this.board.querySelectorAll('.kanban-drop-target').forEach((el) => el.classList.remove('kanban-drop-target'));

        // Remove ghost element
        if (this._ghostEl) {
            this._ghostEl.remove();
            this._ghostEl = null;
        }

        const wasState = this.dragState;
        this.dragState = null;
        this.onDragEnd(wasState?.taskId, wasState?.fromStatus);
    }

    handleDragOver(event, items, column) {
        if (!this.dragState) return;
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        column.classList.add('kanban-drop-target');
        this._showDropIndicator(event, items);
    }

    handleDragEnter(event, column) {
        if (!this.dragState) return;
        event.preventDefault();
        column.classList.add('kanban-drop-target');
    }

    handleDragLeave(event, items, column) {
        const related = event.relatedTarget;
        if (related && (column.contains(related) || items.contains(related))) return;
        column.classList.remove('kanban-drop-target');
        this._removeDropIndicator();
    }

    async handleDrop(event, items, column) {
        event.preventDefault();
        const toStatus = column.dataset.status;
        const payload = this.dragState || this.readTransfer(event);
        column.classList.remove('kanban-drop-target');
        this._removeDropIndicator();
        if (!payload || !payload.taskId || !toStatus) return;

        const dropIndex = this._getDropIndex(event, items);
        const cards = Array.from(items.querySelectorAll('.task-card:not(.task-card-dragging)'));
        const cardIds = cards.map(c => c.dataset.taskId);

        const newPosition = this._computePosition(cardIds, dropIndex);

        if (payload.fromStatus === toStatus) {
            // Within-column reorder
            await this.onReorder(payload.taskId, toStatus, newPosition);
        } else {
            // Cross-column move
            await this.onMove(payload.taskId, toStatus, payload.fromStatus, newPosition);
        }
    }

    /**
     * Compute float position for insertion at dropIndex among existing cards.
     * @param {string[]} cardIds - IDs of cards in target column (excluding dragged)
     * @param {number} dropIndex - insertion index (0 = before first card)
     * @returns {number} new position value
     */
    _computePosition(cardIds, dropIndex) {
        const GAP = KanbanDragDrop.POSITION_GAP;

        if (cardIds.length === 0) {
            return GAP;
        }

        if (dropIndex <= 0) {
            // Insert before first card
            const firstPos = this.getTaskPosition(cardIds[0]);
            return firstPos / 2;
        }

        if (dropIndex >= cardIds.length) {
            // Insert after last card
            const lastPos = this.getTaskPosition(cardIds[cardIds.length - 1]);
            return lastPos + GAP;
        }

        // Insert between two cards
        const prevPos = this.getTaskPosition(cardIds[dropIndex - 1]);
        const nextPos = this.getTaskPosition(cardIds[dropIndex]);
        return (prevPos + nextPos) / 2;
    }

    /**
     * Determine insertion index based on mouse Y position relative to cards.
     * Uses card midpoint for natural feeling insertion.
     */
    _getDropIndex(event, items) {
        const cards = Array.from(items.querySelectorAll('.task-card:not(.task-card-dragging)'));
        if (cards.length === 0) return 0;

        const y = event.clientY;
        for (let i = 0; i < cards.length; i++) {
            const rect = cards[i].getBoundingClientRect();
            const midY = rect.top + rect.height / 2;
            if (y < midY) return i;
        }
        return cards.length;
    }

    /**
     * Find the closest column based on center-distance collision detection.
     * Returns { column, items } or null if no column is close enough.
     */
    _getClosestColumn(event) {
        let closestColumn = null;
        let minDist = Infinity;

        for (const col of this._columnEls) {
            const rect = col.getBoundingClientRect();
            const centerX = rect.left + rect.width / 2;
            const centerY = rect.top + rect.height / 2;
            const dx = Math.abs(event.clientX - centerX);
            const dy = Math.abs(event.clientY - centerY);
            // Weight horizontal distance more heavily since columns are side-by-side
            const dist = dx * 1.5 + dy * 0.5;
            if (dist < minDist) {
                minDist = dist;
                closestColumn = col;
            }
        }

        if (!closestColumn) return null;
        const items = closestColumn.querySelector('.kanban-column-items');
        return items ? { column: closestColumn, items } : null;
    }

    /**
     * Show a visual drop indicator line between cards.
     * Uses CSS class for styling instead of inline styles.
     */
    _showDropIndicator(event, items) {
        this._removeDropIndicator();
        const cards = Array.from(items.querySelectorAll('.task-card:not(.task-card-dragging)'));

        const y = event.clientY;
        let insertBefore = null;
        for (const card of cards) {
            const rect = card.getBoundingClientRect();
            if (y < rect.top + rect.height / 2) {
                insertBefore = card;
                break;
            }
        }

        const indicator = document.createElement('div');
        indicator.className = 'kanban-drop-indicator';
        this._dropIndicator = indicator;

        if (insertBefore) {
            items.insertBefore(indicator, insertBefore);
        } else {
            items.appendChild(indicator);
        }
    }

    _removeDropIndicator() {
        if (this._dropIndicator) {
            this._dropIndicator.remove();
            this._dropIndicator = null;
        }
    }

    readTransfer(event) {
        try {
            const raw = event.dataTransfer?.getData('text/plain');
            return raw ? JSON.parse(raw) : null;
        } catch {
            return null;
        }
    }
}

window.KanbanDragDrop = KanbanDragDrop;
