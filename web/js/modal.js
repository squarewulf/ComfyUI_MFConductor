/**
 * MF Conductor - Modal Manager
 * Handles modal dialogs (confirm, prompt, custom modals)
 */

import { escapeHtml, generateId } from './utils.js';

class ModalManager {
    constructor() {
        this.activeModals = new Map();
        this.overlay = null;
        this.init();
    }

    init() {
        // Create overlay if it doesn't exist
        this.overlay = document.getElementById('modal-overlay');
        if (!this.overlay) {
            this.overlay = document.createElement('div');
            this.overlay.id = 'modal-overlay';
            this.overlay.className = 'modal-overlay hidden';
            this.overlay.addEventListener('click', (e) => {
                if (e.target === this.overlay) {
                    this.closeTopModal();
                }
            });
            document.body.appendChild(this.overlay);
        }

        // Handle escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeTopModal();
            }
        });
    }

    /**
     * Show a confirmation dialog
     * @param {Object} options - Dialog options
     * @returns {Promise<boolean>} User's choice
     */
    confirm(options = {}) {
        const {
            title = 'Confirm',
            message = 'Are you sure?',
            confirmText = 'Confirm',
            cancelText = 'Cancel',
            type = 'info' // 'info', 'warning', 'danger'
        } = options;

        return new Promise((resolve) => {
            const id = generateId();
            
            const typeClasses = {
                info: 'btn-primary',
                warning: 'btn-warning',
                danger: 'btn-danger'
            };

            const modal = document.createElement('div');
            modal.className = 'modal confirm-modal';
            modal.id = `modal-${id}`;
            modal.innerHTML = `
                <div class="modal-header">
                    <h3 class="modal-title">${escapeHtml(title)}</h3>
                    <button class="modal-close" data-action="cancel">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>
                <div class="modal-body">
                    <p>${escapeHtml(message)}</p>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" data-action="cancel">${escapeHtml(cancelText)}</button>
                    <button class="btn ${typeClasses[type] || typeClasses.info}" data-action="confirm">${escapeHtml(confirmText)}</button>
                </div>
            `;

            const handleAction = (action) => {
                this.close(id);
                resolve(action === 'confirm');
            };

            modal.querySelectorAll('[data-action]').forEach(btn => {
                btn.addEventListener('click', () => handleAction(btn.dataset.action));
            });

            this.show(id, modal);
        });
    }

    /**
     * Show a prompt dialog
     * @param {Object} options - Dialog options
     * @returns {Promise<string|null>} User's input or null if cancelled
     */
    prompt(options = {}) {
        const {
            title = 'Input',
            message = '',
            placeholder = '',
            defaultValue = '',
            confirmText = 'OK',
            cancelText = 'Cancel',
            inputType = 'text',
            validate = null
        } = options;

        return new Promise((resolve) => {
            const id = generateId();

            const modal = document.createElement('div');
            modal.className = 'modal prompt-modal';
            modal.id = `modal-${id}`;
            modal.innerHTML = `
                <div class="modal-header">
                    <h3 class="modal-title">${escapeHtml(title)}</h3>
                    <button class="modal-close" data-action="cancel">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>
                <div class="modal-body">
                    ${message ? `<p class="mb-3">${escapeHtml(message)}</p>` : ''}
                    <input type="${inputType}" class="modal-input" placeholder="${escapeHtml(placeholder)}" value="${escapeHtml(defaultValue)}">
                    <p class="modal-error hidden text-red-500 text-sm mt-1"></p>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-secondary" data-action="cancel">${escapeHtml(cancelText)}</button>
                    <button class="btn btn-primary" data-action="confirm">${escapeHtml(confirmText)}</button>
                </div>
            `;

            const input = modal.querySelector('.modal-input');
            const errorEl = modal.querySelector('.modal-error');

            const handleAction = (action) => {
                if (action === 'confirm') {
                    const value = input.value.trim();
                    
                    if (validate) {
                        const error = validate(value);
                        if (error) {
                            errorEl.textContent = error;
                            errorEl.classList.remove('hidden');
                            input.focus();
                            return;
                        }
                    }
                    
                    this.close(id);
                    resolve(value);
                } else {
                    this.close(id);
                    resolve(null);
                }
            };

            modal.querySelectorAll('[data-action]').forEach(btn => {
                btn.addEventListener('click', () => handleAction(btn.dataset.action));
            });

            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    handleAction('confirm');
                }
            });

            this.show(id, modal);
            setTimeout(() => input.focus(), 100);
        });
    }

    /**
     * Show a custom modal
     * @param {string} id - Modal ID
     * @param {HTMLElement|string} content - Modal content
     */
    show(id, content) {
        let modal;
        
        if (typeof content === 'string') {
            modal = document.createElement('div');
            modal.className = 'modal';
            modal.id = `modal-${id}`;
            modal.innerHTML = content;
        } else {
            modal = content;
        }

        this.overlay.appendChild(modal);
        this.overlay.classList.remove('hidden');
        document.body.classList.add('modal-open');
        
        this.activeModals.set(id, modal);

        // Trigger enter animation
        requestAnimationFrame(() => {
            modal.classList.add('modal-enter');
        });

        return modal;
    }

    /**
     * Close a specific modal
     * @param {string} id - Modal ID
     */
    close(id) {
        const modal = this.activeModals.get(id);
        if (!modal) return;

        modal.classList.remove('modal-enter');
        modal.classList.add('modal-exit');

        setTimeout(() => {
            modal.remove();
            this.activeModals.delete(id);

            if (this.activeModals.size === 0) {
                this.overlay.classList.add('hidden');
                document.body.classList.remove('modal-open');
            }
        }, 200);
    }

    /**
     * Close the topmost modal
     */
    closeTopModal() {
        const ids = Array.from(this.activeModals.keys());
        if (ids.length > 0) {
            this.close(ids[ids.length - 1]);
        }
    }

    /**
     * Close all modals
     */
    closeAll() {
        for (const id of this.activeModals.keys()) {
            this.close(id);
        }
    }

    /**
     * Get a modal by ID
     * @param {string} id - Modal ID
     * @returns {HTMLElement|null}
     */
    get(id) {
        return this.activeModals.get(id) || null;
    }

    /**
     * Check if any modal is open
     * @returns {boolean}
     */
    isOpen() {
        return this.activeModals.size > 0;
    }
}

// Export singleton instance
export const modal = new ModalManager();
export default modal;







