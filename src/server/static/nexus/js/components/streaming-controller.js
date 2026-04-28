/**
 * NexusStreamingController
 *
 * Shared streaming reducer/controller for chat, task, and channel flows.
 * Normalizes SSE/fetch stream events and keeps the text/tool-call state
 * transitions in one place so view-specific code only worries about DOM
 * rendering.
 */
class NexusStreamingController {
    constructor(handlers = {}) {
        this.handlers = { ...handlers };
        this.toolCalls = new Map();
        this.currentTextContent = '';
        this.currentTextSegmentIndex = 0;
        this._finished = false;
    }

    static create(handlers = {}) {
        return new NexusStreamingController(handlers);
    }

    static _stringifyText(value) {
        if (value === undefined || value === null) return '';
        return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    }

    static parseSSEEvent(rawEvent) {
        if (!rawEvent || !String(rawEvent).trim()) return null;

        const lines = String(rawEvent).split('\n');
        let eventType = '';
        const dataLines = [];

        for (let line of lines) {
            if (line.endsWith('\r')) line = line.slice(0, -1);
            if (line.startsWith('event:')) {
                eventType = line.slice(6).trim();
            } else if (line.startsWith('data:')) {
                let payloadLine = line.slice(5);
                if (payloadLine.startsWith(' ')) payloadLine = payloadLine.slice(1);
                dataLines.push(payloadLine);
            }
        }

        const eventData = dataLines.join('\n').trim();
        if (!eventData || eventData === '[DONE]') return null;
        return { eventType, eventData };
    }

    static parseJSONEvent(eventData) {
        try {
            return JSON.parse(eventData);
        } catch (_) {
            return { type: 'RUN_ERROR', message: eventData };
        }
    }

    static async consumeReadableStream(response, session) {
        const reader = response?.body?.getReader?.() || null;
        if (!reader) {
            throw new Error('No response body');
        }

        const decoder = new TextDecoder();
        let buffer = '';

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value, { stream: true });
                buffer += chunk;
                const events = buffer.split(/\r?\n\r?\n/);
                buffer = events.pop() || '';
                for (const event of events) {
                    session.processRawSSEEvent(event);
                }
            }

            if (buffer.trim()) {
                session.processRawSSEEvent(buffer);
            }
        } finally {
            try {
                reader.releaseLock();
            } catch (_) {
                // Ignore releaseLock failures from partially consumed streams.
            }
        }
    }

    static bindEventSource(eventSource, session, options = {}) {
        if (!eventSource || !session) return eventSource || null;

        const normalizedOptions = typeof options === 'function' ? { ignoreWhen: options } : (options || {});
        const ignoreWhen = typeof normalizedOptions.ignoreWhen === 'function' ? normalizedOptions.ignoreWhen : null;
        const onParseError = typeof normalizedOptions.onParseError === 'function' ? normalizedOptions.onParseError : null;

        eventSource.onmessage = (event) => {
            if (ignoreWhen && ignoreWhen(event)) return;
            if (!event?.data) return;
            try {
                session.processEvent(JSON.parse(event.data));
            } catch (error) {
                if (onParseError) {
                    onParseError(error, event);
                }
            }
        };

        return eventSource;
    }

    static setElementVisibility(element, visible) {
        if (!element) return;
        element.classList.toggle('is-hidden', !visible);
    }

    static setToolCallStatus(statusEl, isError) {
        if (!statusEl) return;
        const statusWrapper = statusEl.closest('.tool-call-status');
        if (statusWrapper) {
            statusWrapper.classList.remove('status-pending', 'status-executing', 'status-completed', 'status-failed');
            statusWrapper.classList.add(isError ? 'status-failed' : 'status-completed');
        }
        statusEl.textContent = isError ? '✗' : '✓';
    }

    _emit(name, ...args) {
        const handler = this.handlers?.[name];
        if (typeof handler === 'function') {
            return handler(...args, this);
        }
        return undefined;
    }

    _appendText(value) {
        const text = NexusStreamingController._stringifyText(value);
        if (!text) return '';
        this.currentTextContent += text;
        return this.currentTextContent;
    }

    _finishTextSegment() {
        const snapshot = this.currentTextContent;
        this.currentTextContent = '';
        this.currentTextSegmentIndex += 1;
        return snapshot;
    }

    _upsertToolCall(data) {
        const toolCallId = data.toolCallId || `tool-${Date.now()}`;
        const toolName = data.toolCallName || data.tool_name || 'Tool';
        const toolCall = this.toolCalls.get(toolCallId) || {
            id: toolCallId,
            name: toolName,
            args: '',
            status: 'executing',
            result: '',
            error: '',
        };
        this.toolCalls.set(toolCallId, toolCall);
        return toolCall;
    }

    processRawSSEEvent(rawEvent) {
        const parsed = NexusStreamingController.parseSSEEvent(rawEvent);
        if (!parsed) return false;

        const eventData = NexusStreamingController.parseJSONEvent(parsed.eventData);
        return this.processEvent(eventData, parsed.eventType);
    }

    processEvent(data, eventType = '') {
        if (!data) return false;

        const type = String(data.type || '').trim();
        const sseDelta = data.response ?? data.delta;
        const textValue = data.delta ?? data.content ?? data.text ?? data.response;

        if (eventType === 'delta' && sseDelta !== undefined) {
            this._appendText(sseDelta);
            this._emit('onDelta', sseDelta, data, eventType);
            if (data.finished === true) {
                this._finishTextSegment();
                this._emit('onTextEnd', data);
            }
            return true;
        }

        switch (type) {
            case 'RUN_STARTED':
                this._emit('onRunStarted', data);
                return true;
            case 'TEXT_MESSAGE_START':
                this._emit('onTextStart', data);
                return true;
            case 'TEXT_MESSAGE_CONTENT': {
                if (textValue !== undefined && textValue !== null && textValue !== '') {
                    this._appendText(textValue);
                    this._emit('onTextContent', this.currentTextContent, data);
                }
                return true;
            }
            case 'TEXT_MESSAGE_END':
                this._emit('onTextEnd', data);
                this._finishTextSegment();
                return true;
            case 'TOOL_CALL_START': {
                const toolCall = this._upsertToolCall(data);
                this._finishTextSegment();
                this._emit('onToolCallStart', toolCall, data);
                return true;
            }
            case 'TOOL_CALL_ARGS': {
                const toolCall = this._upsertToolCall(data);
                toolCall.args += String(data.delta || '');
                this._emit('onToolCallArgs', toolCall, data);
                return true;
            }
            case 'TOOL_CALL_END': {
                const toolCall = this._upsertToolCall(data);
                toolCall.status = data.error ? 'failed' : 'completed';
                toolCall.result = data.result || '';
                toolCall.error = data.error || '';
                this._emit('onToolCallEnd', toolCall, data);
                return true;
            }
            case 'TOOL_CALL_RESULT': {
                const toolCall = this._upsertToolCall(data);
                toolCall.result = data.result || data.content || '';
                this._emit('onToolCallResult', toolCall, data);
                return true;
            }
            case 'RUN_FINISHED':
                this._finished = true;
                this._emit('onRunFinished', data);
                return true;
            case 'RUN_ERROR':
                this._finished = true;
                this._emit('onRunError', data);
                return true;
            case 'result':
                if (textValue !== undefined && textValue !== null && textValue !== '') {
                    this._appendText(textValue);
                    this._emit('onTextContent', this.currentTextContent, data);
                }
                return true;
            default:
                if (data.delta && !type) {
                    this._appendText(data.delta);
                    this._emit('onDelta', data.delta, data, eventType);
                    return true;
                }
                if (data.error) {
                    this._finished = true;
                    this._emit('onRunError', data);
                    return true;
                }
                this._emit('onUnknown', data, eventType);
                return false;
        }
    }
}

class NexusStreamSessionView {
    constructor(options = {}) {
        this.container = options.container || null;
        this.replaceElement = options.replaceElement || null;
        this.clearContainerOnFirstBubble = !!options.clearContainerOnFirstBubble;
        this.messageHtmlFactory = typeof options.messageHtmlFactory === 'function'
            ? options.messageHtmlFactory
            : this._defaultMessageHtmlFactory.bind(this);
        this.renderMessageContent = typeof options.renderMessageContent === 'function'
            ? options.renderMessageContent
            : ((value) => NexusStreamingController._stringifyText(value));
        this.renderStreamingToolCall = typeof options.renderStreamingToolCall === 'function'
            ? options.renderStreamingToolCall
            : (() => '');
        this.formatToolCallTitle = typeof options.formatToolCallTitle === 'function'
            ? options.formatToolCallTitle
            : ((toolName) => toolName || 'Tool');
        this.escapeHtml = typeof options.escapeHtml === 'function'
            ? options.escapeHtml
            : ((value) => String(value ?? ''));
        this.scrollContainer = options.scrollContainer || this.container || this.replaceElement || null;
        this.bubbleIdPrefix = options.bubbleIdPrefix || 'stream-session-bubble';
        this.textIdPrefix = options.textIdPrefix || 'stream-session-text';
        this.currentTextEl = null;
        this.bubbleEl = null;
        this.initialized = false;
        this.hasRenderedContent = false;
        // Once finalize() is called we refuse to create new bubbles. This
        // prevents a race where a late stream event (fired after the
        // post-stream snapshot sync rewrote chatDetail.innerHTML) would
        // otherwise `_ensureBubble()` → fail the document.body.contains()
        // check → append a fresh duplicate bubble to the messages container.
        // That race is exactly what caused "reply duplicated N times after
        // refresh" in the chat pane.
        this.finalized = false;
    }

    _defaultMessageHtmlFactory(messageId, bubbleId) {
        return `
            <div class="message assistant" id="${messageId}">
                <div class="message-avatar assistant">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="18" height="18">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
                    </svg>
                </div>
                <div class="message-content">
                    <div class="message-bubble streaming-bubble" id="${bubbleId}"></div>
                </div>
            </div>
        `;
    }

    _resolveBubbleElement(bubbleId) {
        return document.getElementById(bubbleId)
            || this.replaceElement?.querySelector?.(`#${bubbleId}`)
            || this.container?.querySelector?.(`#${bubbleId}`)
            || null;
    }

    _ensureBubble() {
        // Hard guard: after finalize() we never materialise a new bubble,
        // even if a late onDelta / onTextContent / onToolCall* arrives.
        // Without this the caller can accidentally append duplicate
        // assistant bubbles to the messages container whenever some other
        // code path (e.g. post-stream snapshot sync) has already replaced
        // the chat detail DOM out from under us.
        if (this.finalized) return null;

        if (this.bubbleEl && document.body.contains(this.bubbleEl)) {
            return this.bubbleEl;
        }

        const uniqueId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        const messageId = `${this.bubbleIdPrefix}-msg-${uniqueId}`;
        const bubbleId = `${this.bubbleIdPrefix}-${uniqueId}`;
        const markup = this.messageHtmlFactory(messageId, bubbleId);

        if (this.replaceElement) {
            this.replaceElement.innerHTML = markup;
            this.initialized = true;
        } else if (this.container) {
            if (this.clearContainerOnFirstBubble && !this.initialized) {
                this.container.innerHTML = '';
            }
            this.container.insertAdjacentHTML('beforeend', markup);
            this.initialized = true;
        }

        this.bubbleEl = this._resolveBubbleElement(bubbleId);
        return this.bubbleEl;
    }

    _ensureTextElement(session) {
        if (!this.currentTextEl) {
            const bubble = this._ensureBubble();
            if (bubble) {
                const segmentIndex = session?.currentTextSegmentIndex || 0;
                const textId = `${this.textIdPrefix}-${segmentIndex}-${Date.now()}`;
                bubble.insertAdjacentHTML('beforeend', `<div class="message-text streaming" id="${textId}"></div>`);
                this.currentTextEl = bubble.querySelector(`#${textId}`) || document.getElementById(textId);
            }
        }
        return this.currentTextEl;
    }

    _scrollToBottom() {
        const el = this.scrollContainer || this.container || this.replaceElement;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    setTextContent(text, session) {
        const textEl = this._ensureTextElement(session);
        if (!textEl) return;
        textEl.innerHTML = this.renderMessageContent(text || '');
        this.hasRenderedContent = this.hasRenderedContent || !!String(text || '').trim();
        this._scrollToBottom();
    }

    endTextSegment() {
        if (this.currentTextEl) {
            this.currentTextEl.classList.remove('streaming');
        }
        this.currentTextEl = null;
    }

    renderToolCall(toolCall, data = {}) {
        const bubble = this._ensureBubble();
        if (!bubble) return;
        this.endTextSegment();
        const title = data.toolCallDisplayName || this.formatToolCallTitle(toolCall.name, {}, toolCall.args || '');
        bubble.insertAdjacentHTML('beforeend', this.renderStreamingToolCall(toolCall.id, title, toolCall.status || 'executing'));
        this.hasRenderedContent = true;
        this._scrollToBottom();
    }

    updateToolCallArgs(toolCall) {
        const argsEl = document.getElementById(`streaming-tool-args-${toolCall.id}`);
        if (argsEl) {
            argsEl.textContent = toolCall.args || '';
        }
        const titleEl = document.querySelector(`[data-streaming-tool-id="${toolCall.id}"] .tool-call-name`);
        if (titleEl) {
            titleEl.textContent = this.formatToolCallTitle(toolCall.name, {}, toolCall.args || '');
        }
    }

    updateToolCallResult(toolCall, data = {}) {
        const titleEl = document.querySelector(`[data-streaming-tool-id="${toolCall.id}"] .tool-call-name`);
        if (titleEl) {
            titleEl.textContent = data.toolCallDisplayName || this.formatToolCallTitle(toolCall.name, {}, toolCall.args || '');
        }

        const statusEl = document.querySelector(`[data-streaming-tool-id="${toolCall.id}"] .tool-call-status-icon`);
        if (statusEl && (data.type === 'TOOL_CALL_END' || toolCall.error || data.error)) {
            NexusStreamingController.setToolCallStatus(statusEl, !!(toolCall.error || data.error));
        }

        const resultValue = toolCall.result || data.result || data.content || '';
        const resultSection = document.getElementById(`streaming-tool-result-section-${toolCall.id}`);
        const resultEl = document.getElementById(`streaming-tool-result-${toolCall.id}`);
        if (resultSection && resultEl && resultValue) {
            NexusStreamingController.setElementVisibility(resultSection, true);
            resultEl.textContent = typeof resultValue === 'string' ? resultValue : JSON.stringify(resultValue, null, 2);
        }

        const errorValue = toolCall.error || data.error || '';
        const errorSection = document.getElementById(`streaming-tool-error-section-${toolCall.id}`);
        const errorEl = document.getElementById(`streaming-tool-error-${toolCall.id}`);
        if (errorSection && errorEl && errorValue) {
            NexusStreamingController.setElementVisibility(errorSection, true);
            errorEl.textContent = errorValue;
        }

        this.hasRenderedContent = this.hasRenderedContent || !!String(resultValue || errorValue || '').trim();
        this._scrollToBottom();
    }

    renderError(errorMessage) {
        const message = String(errorMessage || 'Stream error').trim();
        if (!message) return;
        const bubble = this._ensureBubble();
        if (!bubble) return;
        this.endTextSegment();
        bubble.insertAdjacentHTML('beforeend', `
            <div class="message-error with-top-gap">
                <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="16" height="16">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <span>${this.escapeHtml(message)}</span>
            </div>
        `);
        this.hasRenderedContent = true;
        this._scrollToBottom();
    }

    finalize() {
        this.endTextSegment();
        if (this.bubbleEl) {
            this.bubbleEl.querySelectorAll('.message-text:empty').forEach((element) => element.remove());
        }
        // Latch finalized so subsequent _ensureBubble() calls return null
        // instead of spawning duplicate bubbles (see class docstring).
        this.finalized = true;
    }

    hasVisibleContent() {
        const bubbleText = this.bubbleEl?.textContent?.trim?.() || '';
        return this.hasRenderedContent || bubbleText.length > 0;
    }

    createController(extraHandlers = {}) {
        const invoke = (name, ...args) => {
            const handler = extraHandlers?.[name];
            if (typeof handler === 'function') {
                handler(...args);
            }
        };

        return NexusStreamingController.create({
            onRunStarted: (data, session) => invoke('onRunStarted', data, session),
            onTextStart: (data, session) => {
                this._ensureBubble();
                invoke('onTextStart', data, session);
            },
            onTextContent: (text, data, session) => {
                this.setTextContent(text, session);
                invoke('onTextContent', text, data, session);
            },
            onTextEnd: (data, session) => {
                this.endTextSegment();
                invoke('onTextEnd', data, session);
            },
            onToolCallStart: (toolCall, data, session) => {
                this.renderToolCall(toolCall, data);
                invoke('onToolCallStart', toolCall, data, session);
            },
            onToolCallArgs: (toolCall, data, session) => {
                this.updateToolCallArgs(toolCall, data);
                invoke('onToolCallArgs', toolCall, data, session);
            },
            onToolCallEnd: (toolCall, data, session) => {
                this.updateToolCallResult(toolCall, { ...data, type: 'TOOL_CALL_END' });
                invoke('onToolCallEnd', toolCall, data, session);
            },
            onToolCallResult: (toolCall, data, session) => {
                this.updateToolCallResult(toolCall, { ...data, type: 'TOOL_CALL_RESULT' });
                invoke('onToolCallResult', toolCall, data, session);
            },
            onRunFinished: (data, session) => {
                this.finalize();
                invoke('onRunFinished', data, session);
            },
            onRunError: (data, session) => {
                this.renderError(data?.message || data?.error || 'Stream error');
                this.finalize();
                invoke('onRunError', data, session);
            },
            onDelta: (delta, data, session) => {
                this.setTextContent(session?.currentTextContent || delta, session);
                if (data?.finished === true) {
                    this.endTextSegment();
                }
                invoke('onDelta', delta, data, session);
            },
            onUnknown: (data, eventType, session) => invoke('onUnknown', data, eventType, session),
        });
    }
}

window.NexusStreamingController = NexusStreamingController;
window.NexusStreamSessionView = NexusStreamSessionView;
