/**
 * MF Conductor - Toast Notification System
 * Provides user feedback through toast notifications
 */

import { escapeHtml } from './utils.js';

class ToastManager {
    constructor() {
        this.container = null;
        this.init();
    }

    init() {
        // Create container if it doesn't exist
        this.container = document.getElementById('toast-container');
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.id = 'toast-container';
            this.container.className = 'fixed bottom-4 right-4 z-50 flex flex-col gap-2';
            document.body.appendChild(this.container);
        }
    }

    /**
     * Show a toast notification
     * @param {string} type - Toast type: 'success', 'error', 'warning', 'info'
     * @param {string} message - Toast message
     * @param {number} duration - Duration in milliseconds (default: 3000)
     */
    show(type, message, duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        const icons = {
            success: 'fa-check-circle',
            error: 'fa-exclamation-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
        };

        toast.innerHTML = `
            <i class="fa-solid ${icons[type] || icons.info}"></i>
            <span>${escapeHtml(message)}</span>
            <button class="toast-close" onclick="this.parentElement.remove()">
                <i class="fa-solid fa-times"></i>
            </button>
        `;

        this.container.appendChild(toast);

        // Auto-remove after duration
        setTimeout(() => {
            toast.classList.add('toast-exit');
            setTimeout(() => toast.remove(), 300);
        }, duration);

        return toast;
    }

    success(message, duration) {
        return this.show('success', message, duration);
    }

    error(message, duration = 5000) {
        return this.show('error', message, duration);
    }

    warning(message, duration = 4000) {
        return this.show('warning', message, duration);
    }

    info(message, duration) {
        return this.show('info', message, duration);
    }
}

// Export singleton instance
export const toast = new ToastManager();
export default toast;







