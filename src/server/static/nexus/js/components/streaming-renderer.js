/**
 * StreamingRenderer - 处理流式墓碑与可恢复错误扣留的前端组件
 *
 * 功能：
 * - 跟踪 tombstoned 块（已被标记为失效）
 * - 管理 withheld 块（因可恢复错误被扣留）
 * - 自动重试机制（指数退避）
 * - DOM 中墓碑样式标记
 */
class StreamingRenderer {
    /**
     * @param {Object} options
     * @param {Function} options.onRetryChunk - 发送重试请求的回调 (blockId) => void
     * @param {Function} options.onChunkUpdate - 块更新回调 (blockId, content) => void
     * @param {HTMLElement} options.container - 渲染容器
     */
    constructor(options = {}) {
        this.onRetryChunk = typeof options.onRetryChunk === 'function' ? options.onRetryChunk : null;
        this.onChunkUpdate = typeof options.onChunkUpdate === 'function' ? options.onChunkUpdate : null;
        this.container = options.container || null;

        // Tombstone tracking
        this.tombstonedBlocks = new Set();    // 已被标记 tombstone 的 block_id
        this.tombstoneRecords = new Map();    // tombstone 记录 map

        // Withheld blocks tracking
        this.withheldBlocks = new Map();      // block_id -> { reason, content, retryCount }
        this.maxRetries = 3;

        // Retry timers for exponential backoff
        this.retryTimers = new Map();          // block_id -> timer reference
        this.baseRetryDelay = 2000;            // 2 seconds
        this.maxRetryDelay = 30000;            // 30 seconds

        // Block content cache for incremental updates
        this.blockContents = new Map();        // block_id -> content string

        // Event handlers
        this._eventHandlers = new Map();
    }

    /**
     * 注册事件处理器
     * @param {string} eventType
     * @param {Function} handler
     */
    on(eventType, handler) {
        if (!this._eventHandlers.has(eventType)) {
            this._eventHandlers.set(eventType, []);
        }
        this._eventHandlers.get(eventType).push(handler);
    }

    /**
     * 触发事件
     * @param {string} eventType
     * @param {Object} data
     */
    _emit(eventType, data) {
        const handlers = this._eventHandlers.get(eventType);
        if (handlers) {
            for (const handler of handlers) {
                try {
                    handler(data);
                } catch (e) {
                    console.error(`StreamingRenderer event handler error (${eventType}):`, e);
                }
            }
        }
    }

    // ----------------------------------------------------------
    // Tombstone 处理
    // ----------------------------------------------------------

    /**
     * 处理 tombstone 事件
     * @param {Object} data { block_id, sequence, reason, new_block_id }
     */
    onTombstone(data) {
        const { block_id, sequence, reason, new_block_id } = data;

        // 记录 tombstone
        this.tombstonedBlocks.add(block_id);
        this.tombstoneRecords.set(block_id, {
            sequence,
            reason,
            newBlockId: new_block_id,
            timestamp: Date.now()
        });

        // 在 DOM 中标记
        this._markTombstoneInDOM(block_id);

        // 清除相关的重试定时器
        if (this.retryTimers.has(block_id)) {
            clearTimeout(this.retryTimers.get(block_id));
            this.retryTimers.delete(block_id);
        }

        // 清除 withheld 状态（如果有）
        if (this.withheldBlocks.has(block_id)) {
            this.withheldBlocks.delete(block_id);
        }

        // 触发事件
        this._emit('tombstone', data);

        console.debug(`[StreamingRenderer] Tombstone marked: ${block_id} (reason: ${reason})`);
    }

    /**
     * 在 DOM 中标记 tombstone 样式
     * @param {string} blockId
     */
    _markTombstoneInDOM(blockId) {
        if (!this.container) return;

        const element = this._findBlockElement(blockId);
        if (!element) return;

        // 添加 tombstone 样式类
        element.classList.add('chunk-tombstone');

        // 添加 data 属性标记
        element.dataset.tombstoneReason = this.tombstoneRecords.get(blockId)?.reason || 'unknown';

        // 触发事件让外部可以自定义处理
        this._emit('tombstone-dom', { blockId, element });
    }

    /**
     * 查找块对应的 DOM 元素
     * @param {string} blockId
     * @returns {HTMLElement|null}
     */
    _findBlockElement(blockId) {
        if (!this.container) return null;
        return this.container.querySelector(`[data-block-id="${blockId}"]`) ||
               this.container.querySelector(`[data-streaming-block="${blockId}"]`);
    }

    // ----------------------------------------------------------
    // Withheld/Chunk Hold 处理
    // ----------------------------------------------------------

    /**
     * 处理块扣留事件
     * @param {Object} data { block_id, reason }
     */
    onChunkHold(data) {
        const { block_id, reason } = data;

        // 如果块已有内容，保存它
        const existingContent = this.blockContents.get(block_id) || '';

        this.withheldBlocks.set(block_id, {
            reason,
            content: existingContent,
            retryCount: 0,
            timestamp: Date.now()
        });

        // 在 DOM 中标记 withheld 状态
        this._markWithheldInDOM(block_id, reason);

        // 触发事件
        this._emit('chunk-hold', data);

        console.debug(`[StreamingRenderer] Chunk held: ${block_id} (reason: ${reason})`);
    }

    /**
     * 在 DOM 中标记 withheld 样式
     * @param {string} blockId
     * @param {string} reason
     */
    _markWithheldInDOM(blockId, reason) {
        if (!this.container) return;

        const element = this._findBlockElement(blockId);
        if (!element) return;

        // 添加 withheld 样式类
        element.classList.add('chunk-withheld');

        // 添加 data 属性
        element.dataset.withheldReason = reason;
        element.classList.add('chunk-recovering');

        // 触发事件
        this._emit('withheld-dom', { blockId, element, reason });
    }

    /**
     * 处理块释放事件
     * @param {Object} data { block_id, content }
     */
    onChunkRelease(data) {
        const { block_id, content } = data;

        const withheld = this.withheldBlocks.get(block_id);
        if (withheld) {
            // 更新内容
            this.blockContents.set(block_id, content);
            this.withheldBlocks.delete(block_id);

            // 替换 DOM 中的块内容
            this.replaceBlock(block_id, content);

            // 移除 withheld 样式
            this._clearWithheldStyle(block_id);

            // 触发事件
            this._emit('chunk-release', data);
        }

        console.debug(`[StreamingRenderer] Chunk released: ${block_id}`);
    }

    /**
     * 清除 withheld 样式
     * @param {string} blockId
     */
    _clearWithheldStyle(blockId) {
        if (!this.container) return;

        const element = this._findBlockElement(blockId);
        if (!element) return;

        element.classList.remove('chunk-withheld', 'chunk-recovering');
        delete element.dataset.withheldReason;
    }

    // ----------------------------------------------------------
    // 块替换处理
    // ----------------------------------------------------------

    /**
     * 处理块替换事件
     * @param {Object} data { old_block_id, new_block_id, content }
     */
    onChunkReplace(data) {
        const { old_block_id, new_block_id, content } = data;

        // 标记旧块为 tombstone
        if (!this.tombstonedBlocks.has(old_block_id)) {
            this.onTombstone({
                block_id: old_block_id,
                sequence: 0,
                reason: 'replaced',
                new_block_id
            });
        }

        // 更新内容缓存
        if (content) {
            this.blockContents.set(new_block_id, content);
        }

        // 触发事件
        this._emit('chunk-replace', data);

        console.debug(`[StreamingRenderer] Chunk replaced: ${old_block_id} -> ${new_block_id}`);
    }

    /**
     * 替换块内容
     * @param {string} blockId
     * @param {string} newContent
     */
    replaceBlock(blockId, newContent) {
        this.blockContents.set(blockId, newContent);

        if (!this.container) return;

        const element = this._findBlockElement(blockId);
        if (element) {
            // 更新元素内容
            element.textContent = newContent;
            element.classList.remove('chunk-tombstone', 'chunk-withheld', 'chunk-recovering');
        }

        // 触发更新回调
        if (this.onChunkUpdate) {
            this.onChunkUpdate(blockId, newContent);
        }

        this._emit('block-updated', { blockId, content: newContent });
    }

    // ----------------------------------------------------------
    // 自动重试（TEMPORARY/RATE_LIMIT）
    // ----------------------------------------------------------

    /**
     * 调度重试（指数退避）
     * @param {string} blockId
     * @param {number} delay 延迟毫秒
     */
    _scheduleRetry(blockId, delay = null) {
        // 清除已有的定时器
        if (this.retryTimers.has(blockId)) {
            clearTimeout(this.retryTimers.get(blockId));
        }

        const withheld = this.withheldBlocks.get(blockId);
        if (!withheld) return;

        const retryCount = withheld.retryCount || 0;
        const actualDelay = delay || Math.min(this.baseRetryDelay * Math.pow(2, retryCount), this.maxRetryDelay);

        console.debug(`[StreamingRenderer] Scheduling retry for ${blockId} in ${actualDelay}ms (attempt ${retryCount + 1})`);

        const timer = setTimeout(() => {
            this.retryTimers.delete(blockId);
            this._executeRetry(blockId);
        }, actualDelay);

        this.retryTimers.set(blockId, timer);
    }

    /**
     * 执行重试
     * @param {string} blockId
     */
    _executeRetry(blockId) {
        const withheld = this.withheldBlocks.get(blockId);
        if (!withheld) return;

        if (!this.withholdingQueue || !this.withholdingQueue.should_retry(blockId)) {
            console.debug(`[StreamingRenderer] Max retries reached for ${blockId}, giving up`);
            this._emit('retry-failed', { blockId });
            return;
        }

        // 更新重试计数
        withheld.retryCount = (withheld.retryCount || 0) + 1;

        // 发送重试事件
        if (this.onRetryChunk) {
            this.onRetryChunk(blockId);
        }

        this._emit('retry', { blockId, attempt: withheld.retryCount });
    }

    /**
     * 取消重试
     * @param {string} blockId
     */
    cancelRetry(blockId) {
        if (this.retryTimers.has(blockId)) {
            clearTimeout(this.retryTimers.get(blockId));
            this.retryTimers.delete(blockId);
        }
    }

    /**
     * 取消所有重试
     */
    cancelAllRetries() {
        for (const [blockId, timer] of this.retryTimers) {
            clearTimeout(timer);
        }
        this.retryTimers.clear();
    }

    // ----------------------------------------------------------
    // SSE 事件处理（与 SSEHandler 配合使用）
    // ----------------------------------------------------------

    /**
     * 处理 SSE 事件
     * @param {string} eventType
     * @param {Object} payload
     */
    handleSSEEvent(eventType, payload) {
        switch (eventType) {
            case 'BLOCK_TOMBSTONE':
                this.onTombstone(payload);
                break;

            case 'CHUNK_REPLACE':
                this.onChunkReplace(payload);
                break;

            case 'CHUNK_HOLD':
                this.onChunkHold(payload);
                // 自动调度重试
                if (payload.reason === 'temporary' || payload.reason === 'rate_limit') {
                    this._scheduleRetry(payload.block_id);
                }
                break;

            case 'CHUNK_RELEASE':
                this.onChunkRelease(payload);
                break;

            case 'BLOCK_TOMBSTONE':
                // 兼容大小写
                this.onTombstone(payload);
                break;

            default:
                // 未知事件类型
                this._emit('unknown-event', { eventType, payload });
        }
    }

    /**
     * 注册 SSEHandler 事件监听
     * @param {SSEHandler} sseHandler
     */
    attachToSSEHandler(sseHandler) {
        const eventTypes = ['BLOCK_TOMBSTONE', 'CHUNK_REPLACE', 'CHUNK_HOLD', 'CHUNK_RELEASE', 'block.tombstone', 'chunk.replace', 'chunk.hold', 'chunk.release'];

        for (const type of eventTypes) {
            sseHandler.on(type, (payload) => {
                this.handleSSEEvent(type, payload);
            });
        }
    }

    // ----------------------------------------------------------
    // 内容更新
    // ----------------------------------------------------------

    /**
     * 更新块内容（增量）
     * @param {string} blockId
     * @param {string} deltaContent
     */
    appendToBlock(blockId, deltaContent) {
        const current = this.blockContents.get(blockId) || '';
        const newContent = current + deltaContent;
        this.blockContents.set(blockId, newContent);

        if (this.container) {
            const element = this._findBlockElement(blockId);
            if (element) {
                element.textContent = newContent;
            }
        }

        this._emit('block-updated', { blockId, content: newContent, delta: deltaContent });
    }

    /**
     * 获取块内容
     * @param {string} blockId
     * @returns {string}
     */
    getBlockContent(blockId) {
        return this.blockContents.get(blockId) || '';
    }

    // ----------------------------------------------------------
    // 状态查询
    // ----------------------------------------------------------

    /**
     * 检查块是否已被标记为 tombstone
     * @param {string} blockId
     * @returns {boolean}
     */
    isTombstoned(blockId) {
        return this.tombstonedBlocks.has(blockId);
    }

    /**
     * 检查块是否被扣留
     * @param {string} blockId
     * @returns {boolean}
     */
    isWithheld(blockId) {
        return this.withheldBlocks.has(blockId);
    }

    /**
     * 获取所有 tombstone 块 ID
     * @returns {string[]}
     */
    getTombstonedBlocks() {
        return Array.from(this.tombstonedBlocks);
    }

    /**
     * 获取所有 withheld 块 ID
     * @returns {string[]}
     */
    getWithheldBlocks() {
        return Array.from(this.withheldBlocks.keys());
    }

    // ----------------------------------------------------------
    // 清理
    // ----------------------------------------------------------

    /**
     * 重置所有状态
     */
    reset() {
        this.tombstonedBlocks.clear();
        this.tombstoneRecords.clear();
        this.withheldBlocks.clear();
        this.blockContents.clear();
        this.cancelAllRetries();
        this._eventHandlers.clear();
    }

    /**
     * 销毁组件
     */
    destroy() {
        this.reset();
        this.container = null;
        this.onRetryChunk = null;
        this.onChunkUpdate = null;
    }
}

// 兼容暴露到全局
window.StreamingRenderer = StreamingRenderer;
