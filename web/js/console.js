/**
 * MF Conductor - Console Manager
 * Handles console output display and backend log polling
 */

import { escapeHtml, isStandaloneMode } from './utils.js';
import api from './api.js';

class ConsoleManager {
    constructor() {
        this.container = null;
        this.contentEl = null;
        this.badgeEl = null;
        this.logCount = 0;
        this.autoScroll = true;
        this.backendLogIndex = 0;
        this.pollingInterval = null;
        this.consoleOutput = [];
        this.maxLines = 1000;
    }

    /**
     * Initialize the console manager
     * @param {Object} options - Configuration options
     */
    init(options = {}) {
        this.container = options.container || document.getElementById('console-panel');
        this.contentEl = options.content || document.getElementById('console-content');
        this.badgeEl = options.badge || document.getElementById('console-badge');
        
        if (options.maxLines) {
            this.maxLines = options.maxLines;
        }

        // Bind scroll event for auto-scroll detection
        if (this.contentEl) {
            this.contentEl.addEventListener('scroll', () => {
                const { scrollTop, scrollHeight, clientHeight } = this.contentEl;
                this.autoScroll = scrollTop + clientHeight >= scrollHeight - 50;
            });
        }
    }

    /**
     * Add a log entry to the console
     * @param {string} message - Log message
     * @param {string} type - Log type: 'info', 'success', 'warning', 'error'
     */
    log(message, type = 'info') {
        // Fallback to browser console if not initialized
        if (!this.contentEl) {
            console.log(`[MF Conductor] ${message}`);
            return;
        }

        const timestamp = new Date().toLocaleTimeString();
        const entry = document.createElement('div');
        entry.className = `console-entry ${type}`;
        entry.innerHTML = `
            <span class="console-timestamp">[${timestamp}]</span>
            <span class="console-message">${escapeHtml(message)}</span>
        `;

        // Remove welcome message if present
        const welcome = this.contentEl.querySelector('.console-welcome');
        if (welcome) welcome.remove();

        this.contentEl.appendChild(entry);
        this.consoleOutput.push({ message, type, timestamp });

        // Trim old entries
        while (this.consoleOutput.length > this.maxLines) {
            this.consoleOutput.shift();
            const firstChild = this.contentEl.firstElementChild;
            if (firstChild && !firstChild.classList.contains('console-welcome')) {
                firstChild.remove();
            }
        }

        // Auto-scroll to bottom
        if (this.autoScroll) {
            this.contentEl.scrollTop = this.contentEl.scrollHeight;
        }

        // Update badge
        this.logCount++;
        this.updateBadge();

        return entry;
    }

    /**
     * Append ComfyUI process output to console
     * @param {string} text - Output text
     * @param {string} type - Output type
     */
    appendOutput(text, type = 'info') {
        if (!this.contentEl) return;

        const entry = document.createElement('div');
        entry.className = `console-entry console-comfy-output ${type}`;
        entry.innerHTML = `<span class="console-message">${escapeHtml(text)}</span>`;

        this.contentEl.appendChild(entry);

        if (this.autoScroll) {
            this.contentEl.scrollTop = this.contentEl.scrollHeight;
        }
    }

    /**
     * Clear the console
     */
    clear() {
        if (this.contentEl) {
            this.contentEl.innerHTML = '';
        }
        this.consoleOutput = [];
        this.logCount = 0;
        this.updateBadge();
    }

    /**
     * Update the console badge count
     */
    updateBadge() {
        if (!this.badgeEl) return;

        if (this.logCount > 0) {
            this.badgeEl.textContent = this.logCount > 99 ? '99+' : this.logCount;
            this.badgeEl.classList.remove('hidden');
        } else {
            this.badgeEl.classList.add('hidden');
        }
    }

    /**
     * Reset the badge count
     */
    resetBadge() {
        this.logCount = 0;
        this.updateBadge();
    }

    /**
     * Start polling for backend logs
     * @param {number} interval - Polling interval in milliseconds
     */
    startPolling(interval = 1000) {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
        }

        this.pollingInterval = setInterval(() => this.pollBackendLogs(), interval);
        this.log('Console polling started', 'info');
    }

    /**
     * Stop polling for backend logs
     */
    stopPolling() {
        if (this.pollingInterval) {
            clearInterval(this.pollingInterval);
            this.pollingInterval = null;
        }
    }

    /**
     * Poll backend for new logs
     */
    async pollBackendLogs() {
        try {
            const response = await api.getBackendLogs(this.backendLogIndex);
            
            if (response.logs && response.logs.length > 0) {
                for (const log of response.logs) {
                    this.log(log.message, log.type || 'info');
                }
                this.backendLogIndex += response.logs.length;
            }
        } catch (error) {
            // Silently fail - network errors are expected during server restart
        }
    }

    /**
     * Show a placeholder message when stopped
     * @param {string} message - Placeholder message
     * @param {string} hint - Hint text
     */
    showPlaceholder(message, hint = '') {
        if (!this.contentEl) return;
        
        // Only show if console is empty
        if (this.contentEl.children.length === 0) {
            this.contentEl.innerHTML = `
                <div class="console-welcome">
                    <i class="fa-solid fa-terminal text-4xl text-slate-600 mb-4"></i>
                    <p class="console-placeholder-text">${escapeHtml(message)}</p>
                    ${hint ? `<p class="console-placeholder-hint">${escapeHtml(hint)}</p>` : ''}
                </div>
            `;
        }
    }

    /**
     * Export console history
     * @returns {Array} Console output array
     */
    export() {
        return [...this.consoleOutput];
    }

    /**
     * Save console history to localStorage
     */
    save() {
        try {
            localStorage.setItem('mf_conductor_console', JSON.stringify(this.consoleOutput.slice(-100)));
        } catch (e) {
            console.warn('Failed to save console history:', e);
        }
    }

    /**
     * Load console history from localStorage
     */
    load() {
        try {
            const saved = localStorage.getItem('mf_conductor_console');
            if (saved) {
                const history = JSON.parse(saved);
                history.forEach(entry => {
                    this.log(entry.message, entry.type);
                });
            }
        } catch (e) {
            console.warn('Failed to load console history:', e);
        }
    }
}

// Export singleton instance
export const console_manager = new ConsoleManager();
export default console_manager;







