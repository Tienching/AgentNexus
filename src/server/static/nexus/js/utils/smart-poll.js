/**
 * SmartPoll - Visibility-aware polling utility
 *
 * Automatically pauses polling when the page/tab is hidden and resumes
 * when it becomes visible again. If the page was hidden for longer than
 * the poll interval, the callback fires immediately on visibility return
 * so the UI refreshes without waiting for the next scheduled tick.
 *
 * Usage:
 *   const poll = new SmartPoll(callback, { intervalMs: 10000 });
 *   poll.start();   // Begin polling
 *   poll.stop();    // Pause polling (can be resumed with start())
 *   poll.destroy(); // Tear down listeners & timers permanently
 */

class SmartPoll {

    /**
     * Create a new SmartPoll instance.
     * @param {Function} callback - Function to call on each poll tick
     * @param {Object} [options]
     * @param {number} [options.intervalMs=10000] - Polling interval in milliseconds
     */
    constructor(callback, options = {}) {
        if (typeof callback !== 'function') {
            throw new Error('SmartPoll: callback must be a function');
        }

        /** @private */
        this._callback = callback;

        /** @private */
        this._intervalMs = options.intervalMs || 10000;

        /** @private */
        this._timerId = null;

        /** @private */
        this._lastPollTs = 0;

        /** @private */
        this._running = false;

        /** @private */
        this._destroyed = false;

        // Bound handler so we can remove the exact same reference on destroy
        /** @private */
        this._onVisibilityChange = this._handleVisibilityChange.bind(this);
    }

    // ----------------------------------------------------------
    // Public API
    // ----------------------------------------------------------

    /**
     * Start polling. If already running this is a no-op.
     * Fires the callback immediately, then sets up the interval.
     */
    start() {
        if (this._destroyed) {
            console.warn('SmartPoll: cannot start a destroyed instance');
            return;
        }
        if (this._running) return;

        this._running = true;
        document.addEventListener('visibilitychange', this._onVisibilityChange);

        // If the page is visible right now, fire immediately and start the timer
        if (!document.hidden) {
            this._fire();
            this._scheduleInterval();
        }
        // If the page is hidden, we'll kick off when it becomes visible
    }

    /**
     * Stop (pause) polling. Can be resumed with start().
     */
    stop() {
        if (!this._running) return;

        this._clearInterval();
        document.removeEventListener('visibilitychange', this._onVisibilityChange);
        this._running = false;
    }

    /**
     * Permanently tear down this instance — clears timers, removes
     * listeners and marks the instance as destroyed so it can't restart.
     */
    destroy() {
        this.stop();
        this._destroyed = true;
        this._callback = null;
    }

    // ----------------------------------------------------------
    // Private helpers
    // ----------------------------------------------------------

    /**
     * Handle document visibility changes.
     * @private
     */
    _handleVisibilityChange() {
        if (document.hidden) {
            // Page just became hidden — pause the timer to avoid waste
            this._clearInterval();
        } else {
            // Page became visible — check if we missed a poll
            const elapsed = Date.now() - this._lastPollTs;
            if (elapsed >= this._intervalMs) {
                this._fire();
            }
            this._scheduleInterval();
        }
    }

    /**
     * Invoke the callback and record the timestamp.
     * @private
     */
    _fire() {
        this._lastPollTs = Date.now();
        this._callback();
    }

    /**
     * Start the periodic interval timer.
     * @private
     */
    _scheduleInterval() {
        this._clearInterval();
        this._timerId = setInterval(() => {
            this._fire();
        }, this._intervalMs);
    }

    /**
     * Clear the current interval timer, if any.
     * @private
     */
    _clearInterval() {
        if (this._timerId !== null) {
            clearInterval(this._timerId);
            this._timerId = null;
        }
    }
}

// Export for use in other scripts
window.SmartPoll = SmartPoll;
