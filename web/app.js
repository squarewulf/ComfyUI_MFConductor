/**
 * MF Conductor - Custom Node Manager
 * Frontend Application
 * 
 * @version 1.3.0
 * @author squarewulf
 */

// ==================== UTILITY FUNCTIONS ====================

/**
 * Debounce function to limit how often a function can fire
 * @param {Function} func - Function to debounce
 * @param {number} wait - Milliseconds to wait
 * @returns {Function} Debounced function
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Throttle function to limit function calls to once per interval
 * @param {Function} func - Function to throttle
 * @param {number} limit - Milliseconds between calls
 * @returns {Function} Throttled function
 */
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// ==================== MAIN APPLICATION CLASS ====================

class MFConductor {
    constructor() {
        // Node management
        this.nodes = [];
        this.filteredNodes = [];
        this.sortField = 'name';
        this.sortDirection = 'asc';
        this.selectedNode = null;
        this.viewMode = 'grid'; // 'grid' or 'list'
        this.currentTab = 'profiles'; // 'profiles', 'nodes', 'packages', 'community'
        
        // User data & features
        this.userData = { favorites: [], tags: {}, notes: {}, usage: {} };
        this.selectedNodes = new Set(); // For bulk selection
        this.browseMode = false;
        this.browseNodes = [];
        this.browseCategories = [];
        this.updateStatus = {}; // Cache update check results
        this.diskUsage = {}; // Cache disk usage
        this.filterTag = '';
        this.showFavoritesOnly = false;
        this.nodesWithUpdates = 0; // For update badge
        
        // Profile management
        this.profiles = {};
        this.editingProfile = null;
        this.profileSelectedNodes = new Set();
        this.profileCustomFlags = [];
        this.profileExcludedPackages = new Set();
        this.installedPackages = [];
        
        // File browser
        this.filesData = [];
        this.filesFolder = 'output';
        this.filesRecursive = false;
        this.filesSubfolder = '';
        this.filesSortBy = 'date';
        this.filesSortDir = 'desc';
        this.filesTypeFilter = '';
        this.filesSearch = '';
        this.filesViewMode = 'grid';
        this.selectedFile = null;
        
        // Required nodes/packages - these are essential for ComfyUI to function
        this.requiredNodes = new Set([
            'ComfyUI-Manager',       // Highly recommended for node management
            'ComfyUI_MFConductor'    // Required - this is the manager itself
        ]);
        
        this.requiredPackages = new Set([
            // Core Python packages required by ComfyUI
            'torch', 'torchvision', 'torchaudio',
            'numpy', 'Pillow', 'PIL',
            'safetensors', 'transformers',
            'aiohttp', 'yarl', 'requests',
            'tqdm', 'psutil', 'scipy',
            'einops', 'kornia',
            'comfy', 'comfyui'
        ]);
        
        // ComfyUI Process Management
        this.comfyStatus = 'stopped'; // 'stopped', 'starting', 'running', 'error'
        this.comfyManaged = true;
        this.comfyPort = null;
        this.comfyProcess = null;
        this.comfyServerReady = false; // True only when HTTP server responds
        this.consoleOutput = [];
        this.consoleAutoScroll = true;
        this.consolePolling = null;
        this.backendLogPolling = null;
        this.backendLogIndex = 0;
        this.serverReadyCheckInterval = null;
        this.defaultProfile = null;
        
        // Undo system
        this.undoStack = [];
        this.maxUndoSize = 10;
        
        // Settings
        this.settings = {
            theme: 'dark',
            accent: 'moss',
            customAccentColor: '#8a9a5b',
            btnColorSuccess: null,
            btnColorWarning: null,
            btnColorDanger: null,
            useCustomBtnColors: false,
            animations: true,
            uiScale: 1,  // 0=compact, 1=normal, 2=old person
            autoRefresh: true,
            showDisabled: true,
            consoleAutoscroll: true,
            confirmRemove: true,
            defaultSort: 'name',
            consoleBuffer: 1000,
            consoleTimestamps: false,
            systemThemeSync: false // Sync with OS theme
        };
        
        // Color picker state
        this.colorPicker = {
            isOpen: false,
            target: null,
            hue: 0,
            saturation: 100,
            brightness: 100,
            originalColor: '#ffffff',
            currentColor: '#ffffff'
        };
        
        // Debounced search functions for performance
        this.debouncedFilterNodes = debounce(() => this.filterNodes(), 150);
        this.debouncedFilterBrowse = debounce(() => this.filterBrowseNodes(), 150);
        this.debouncedFilterPackages = debounce(() => this.renderPackagesTab(), 150);
        
        // API base URL - auto-detect standalone vs integrated mode
        this.apiBase = this.detectApiBase();
        
        // Setup system theme listener
        this.setupSystemThemeListener();
        
        this.init();
    }
    
    detectApiBase() {
        const path = window.location.pathname || '';
        if (path.startsWith('/mf_conductor')) {
            return '/mf_conductor';
        }
        
        // Standalone mode (including reverse proxies/default ports)
        return '';
    }
    
    // ==================== SYSTEM THEME SYNC ====================
    
    setupSystemThemeListener() {
        // Listen for OS theme changes
        if (window.matchMedia) {
            const darkModeQuery = window.matchMedia('(prefers-color-scheme: dark)');
            darkModeQuery.addEventListener('change', (e) => {
                if (this.settings.systemThemeSync) {
                    this.setTheme(e.matches ? 'dark' : 'light');
                }
            });
        }
    }
    
    applySystemTheme() {
        if (window.matchMedia && this.settings.systemThemeSync) {
            const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            this.setTheme(isDark ? 'dark' : 'light');
        }
    }
    
    // ==================== UNDO SYSTEM ====================
    
    /**
     * Push an action to the undo stack
     * @param {Object} action - { type, data, undo: async function }
     */
    pushUndo(action) {
        this.undoStack.push({
            ...action,
            timestamp: Date.now()
        });
        
        // Limit stack size
        if (this.undoStack.length > this.maxUndoSize) {
            this.undoStack.shift();
        }
        
        // Show undo toast
        this.showUndoToast(action.message || 'Action completed', action);
    }
    
    showUndoToast(message, action) {
        const toast = document.createElement('div');
        toast.className = 'toast toast-undo';
        toast.innerHTML = `
            <span>${this.escapeHtml(message)}</span>
            <button class="undo-btn" onclick="app.performUndo()">Undo</button>
            <button class="toast-close" onclick="this.parentElement.remove()">×</button>
        `;
        
        const container = this.toastContainer || document.getElementById('toast-container');
        if (container) {
            container.appendChild(toast);
            
            // Auto-remove after 8 seconds (longer for undo)
            setTimeout(() => {
                if (toast.parentElement) {
                    toast.classList.add('toast-fade-out');
                    setTimeout(() => toast.remove(), 300);
                }
            }, 8000);
        }
    }
    
    async performUndo() {
        if (this.undoStack.length === 0) {
            this.showToast('info', 'Nothing to undo');
            return;
        }
        
        const action = this.undoStack.pop();
        
        try {
            if (action.undo && typeof action.undo === 'function') {
                await action.undo();
                this.showToast('success', `Undone: ${action.message || action.type}`);
            }
        } catch (error) {
            console.error('Undo failed:', error);
            this.showToast('error', `Failed to undo: ${error.message}`);
        }
    }
    
    // ==================== ERROR HANDLING ====================
    
    /**
     * Parse error response and return user-friendly message
     * @param {Error|Response|Object} error 
     * @param {string} defaultMessage 
     * @returns {string}
     */
    parseError(error, defaultMessage = 'An error occurred') {
        if (typeof error === 'string') return error;
        
        // Network errors
        if (error.message?.includes('Failed to fetch') || error.message?.includes('NetworkError')) {
            return 'Network error: Unable to connect to server. Check your connection.';
        }
        
        // Git errors
        if (error.message?.includes('Authentication failed') || error.message?.includes('403')) {
            return 'Authentication failed: Repository may be private or require login.';
        }
        if (error.message?.includes('not found') || error.message?.includes('404')) {
            return 'Repository not found: Check the URL is correct.';
        }
        if (error.message?.includes('rate limit') || error.message?.includes('429')) {
            return 'Rate limited: Too many requests. Please wait a moment.';
        }
        
        // Git specific
        if (error.message?.includes('not a git repository')) {
            return 'Not a Git repository: This folder was not cloned from Git.';
        }
        if (error.message?.includes('merge conflict')) {
            return 'Merge conflict: Manual intervention required in the node folder.';
        }
        
        // Pip errors
        if (error.message?.includes('No matching distribution')) {
            return 'Package not found: Check the package name is correct.';
        }
        if (error.message?.includes('permission denied') || error.message?.includes('Access is denied')) {
            return 'Permission denied: Try running as administrator.';
        }
        
        // Timeout
        if (error.message?.includes('timeout') || error.message?.includes('Timeout')) {
            return 'Operation timed out: The server took too long to respond.';
        }
        
        return error.message || defaultMessage;
    }
    
    /**
     * Wrapper for API calls with retry capability
     * @param {Function} apiCall - Async function to call
     * @param {Object} options - { retries, retryDelay, onRetry }
     */
    async withRetry(apiCall, options = {}) {
        const { retries = 2, retryDelay = 1000, onRetry = null } = options;
        let lastError;
        
        for (let attempt = 0; attempt <= retries; attempt++) {
            try {
                return await apiCall();
            } catch (error) {
                lastError = error;
                
                if (attempt < retries) {
                    if (onRetry) onRetry(attempt + 1, retries);
                    await new Promise(r => setTimeout(r, retryDelay * (attempt + 1)));
                }
            }
        }
        
        throw lastError;
    }
    
    /**
     * Show error toast with retry button
     * @param {string} message 
     * @param {Function} retryFn 
     */
    showErrorWithRetry(message, retryFn) {
        const toast = document.createElement('div');
        toast.className = 'toast toast-error toast-with-retry';
        toast.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="15" y1="9" x2="9" y2="15"/>
                <line x1="9" y1="9" x2="15" y2="15"/>
            </svg>
            <span>${this.escapeHtml(message)}</span>
            <button class="retry-btn">Retry</button>
            <button class="toast-close" onclick="this.parentElement.remove()">×</button>
        `;
        
        toast.querySelector('.retry-btn').addEventListener('click', () => {
            toast.remove();
            if (retryFn) retryFn();
        });
        
        const container = this.toastContainer || document.getElementById('toast-container');
        if (container) {
            container.appendChild(toast);
            
            // Longer timeout for error toasts with retry
            setTimeout(() => {
                if (toast.parentElement) {
                    toast.classList.add('toast-fade-out');
                    setTimeout(() => toast.remove(), 300);
                }
            }, 15000);
        }
    }
    
    async init() {
        this.loadSettings(); // Load settings first to apply theme
        this.bindElements(); // Must be called before any logging
        this.log('MF Conductor initializing...', 'info');
        this.bindEvents();
        this.bindMainTabs();
        this.bindComfyControls();
        this.bindSettingsEvents();
        this.loadUserPreferences();
        this.setupKeyboardShortcuts();
        this.log('Loading user data...', 'info');
        await this.loadUserData();
        await this.loadProfiles();
        this.renderProfilesGrid();
        this.updateComfyControls();
        this.restoreConsoleFromStorage(); // Restore terminal history
        this.checkComfyStatus();
        this.startBackendLogPolling(); // Start polling for backend logs
        this.setupCleanupHandler(); // Clean up on page unload
        this.setupHashNavigation(); // Handle URL hash for tab persistence
        this.log('MF Conductor ready', 'success');
        // Don't load nodes immediately - wait until Nodes tab is clicked
    }
    
    setupHashNavigation() {
        const isIntegrated = this.apiBase === '/mf_conductor';
        
        // In integrated mode, hide Files tab and Profiles features that don't work
        if (isIntegrated) {
            const filesNav = document.getElementById('nav-files');
            if (filesNav) filesNav.style.display = 'none';
            
            // Also hide console nav since it's not useful in integrated mode
            const consoleNav = document.getElementById('nav-console');
            if (consoleNav) consoleNav.style.display = 'none';
        }
        
        // Valid tab names (exclude files and console in integrated mode)
        const validTabs = isIntegrated 
            ? ['profiles', 'nodes', 'packages', 'community']
            : ['profiles', 'files', 'nodes', 'packages', 'console', 'community'];
        
        // Check URL hash on load and switch to that tab
        const hash = window.location.hash.slice(1); // Remove '#'
        if (hash && validTabs.includes(hash)) {
            this.switchMainTab(hash, false); // Don't update hash again
        } else if (isIntegrated) {
            // Default to Nodes tab in integrated mode (Profiles less useful)
            this.switchMainTab('nodes', false);
        }
        
        // Listen for hash changes (browser back/forward)
        window.addEventListener('hashchange', () => {
            const newHash = window.location.hash.slice(1);
            if (newHash && validTabs.includes(newHash) && newHash !== this.currentTab) {
                this.switchMainTab(newHash, false);
            }
        });
    }
    
    setupCleanupHandler() {
        window.addEventListener('beforeunload', () => {
            this.stopConsolePolling();
            this.stopBackendLogPolling();
            if (this.serverReadyCheckInterval) {
                clearInterval(this.serverReadyCheckInterval);
                this.serverReadyCheckInterval = null;
            }
        });
    }
    
    // Main Tab Navigation (Sidebar)
    bindMainTabs() {
        // Sidebar navigation links are bound via onclick in HTML
        // This method is kept for compatibility
    }
    
    async switchMainTab(tabName, updateHash = true) {
        // Update sidebar links
        document.querySelectorAll('.sidebar-link').forEach(link => link.classList.remove('active'));
        document.getElementById(`nav-${tabName}`)?.classList.add('active');
        
        // Update tab content - hide all, show selected
        document.querySelectorAll('.tab-content').forEach(c => {
            c.classList.add('hidden');
            c.classList.remove('active');
        });
        const tabContent = document.getElementById(`tab-${tabName}`);
        if (tabContent) {
            tabContent.classList.remove('hidden');
            tabContent.classList.add('active');
        }
        
        this.currentTab = tabName;
        
        // Update URL hash for persistence across refreshes
        if (updateHash && window.location.hash !== `#${tabName}`) {
            history.replaceState(null, '', `#${tabName}`);
        }
        
        // Load content for tab if needed
        if (tabName === 'nodes' && this.nodes.length === 0) {
            await this.loadNodes();
        } else if (tabName === 'packages') {
            await this.loadPackagesTab();
        } else if (tabName === 'profiles') {
            this.renderProfilesGrid();
        } else if (tabName === 'console') {
            // Update console placeholder if running externally/integrated
            if (this.comfyStatus === 'running' && !this.comfyManaged) {
                this.showExternalComfyMessage(this.comfyPort);
            }
            this.scrollConsoleToBottom();
        } else if (tabName === 'files') {
            await this.loadFilesTab();
        }
    }
    
    // Profiles Grid
    async loadProfiles() {
        this.log('Loading profiles...', 'info');
        try {
            const response = await fetch(`${this.apiBase}/api/profiles`);
            const data = await response.json();
            this.profiles = data.success ? data.profiles : {};
            const count = Object.keys(this.profiles).length;
            this.log(`Loaded ${count} profile${count !== 1 ? 's' : ''}`, 'success');
        } catch (error) {
            this.log(`Error loading profiles: ${error.message}`, 'error');
            console.error('Error loading profiles:', error);
            this.profiles = {};
        }
    }
    
    renderProfilesGrid() {
        const grid = document.getElementById('profiles-grid');
        if (!grid) return;
        
        // Get filter/sort options
        const searchInput = document.getElementById('profiles-search');
        const sortSelect = document.getElementById('profiles-sort');
        const searchTerm = (searchInput?.value || '').toLowerCase();
        const sortBy = sortSelect?.value || 'name';
        
        // Filter profiles
        let profileEntries = Object.entries(this.profiles).filter(([name, profile]) => {
            if (searchTerm && !name.toLowerCase().includes(searchTerm)) {
                return false;
            }
            return true;
        });
        
        // Sort profiles
        const sortDir = this.profilesSortDir || 'asc';
        profileEntries.sort((a, b) => {
            let cmp = 0;
            if (sortBy === 'name') {
                cmp = a[0].localeCompare(b[0]);
            } else if (sortBy === 'nodes') {
                const aNodes = (a[1].enabled || []).length || 999; // All = 999 (high)
                const bNodes = (b[1].enabled || []).length || 999;
                cmp = aNodes - bNodes;
            } else if (sortBy === 'default') {
                const aDefault = a[1].is_default ? 0 : 1;
                const bDefault = b[1].is_default ? 0 : 1;
                cmp = aDefault - bDefault;
            }
            return sortDir === 'desc' ? -cmp : cmp;
        });
        
        // Update profile count
        const countEl = document.getElementById('profiles-count');
        const totalProfiles = Object.keys(this.profiles).length;
        if (countEl) {
            if (searchTerm) {
                countEl.textContent = `${profileEntries.length} of ${totalProfiles} profiles`;
            } else {
                countEl.textContent = `${totalProfiles} profile${totalProfiles !== 1 ? 's' : ''}`;
            }
        }
        
        // Bind buttons (once)
        this.bindProfilesToolbar();
        
        // Get view mode
        const viewMode = this.profilesViewMode || 'grid';
        grid.className = viewMode === 'list' ? 'profiles-list' : 'profiles-grid';
        
        let html = '';
        
        // Render existing profiles
        for (const [name, profile] of profileEntries) {
            const isDefault = profile.is_default || false;
            const avatar = profile.avatar || 'default.svg';
            const enabledList = profile.enabled || [];
            const nodeCountText = enabledList.length > 0 ? `${enabledList.length} nodes` : 'All nodes';
            
            if (viewMode === 'list') {
                // List view row
                html += `
                    <div class="profile-row ${isDefault ? 'default' : ''}" data-profile="${this.escapeHtml(name)}">
                        <div class="profile-row-avatar">
                            <img src="${this.escapeHtml(avatar)}" alt="${this.escapeHtml(name)}" onerror="this.src='default.svg'">
                        </div>
                        <div class="profile-row-name">
                            <span class="name">${this.escapeHtml(name)}</span>
                            ${isDefault ? '<span class="default-badge">Default</span>' : ''}
                        </div>
                        <div class="profile-row-nodes">${nodeCountText}</div>
                        <div class="profile-row-actions">
                            <button class="btn-glass btn-sm btn-success" onclick="event.stopPropagation(); app.handleProfileAction('launch', '${this.escapeHtml(name)}')" title="Launch">
                                <i class="fa-solid fa-play"></i>
                            </button>
                            <button class="btn-glass btn-sm" onclick="event.stopPropagation(); app.handleProfileAction('edit', '${this.escapeHtml(name)}')" title="Edit">
                                <i class="fa-solid fa-pen"></i>
                            </button>
                            <button class="btn-glass btn-sm" onclick="event.stopPropagation(); app.exportProfile('${this.escapeHtml(name)}')" title="Export">
                                <i class="fa-solid fa-download"></i>
                            </button>
                            <button class="btn-glass btn-sm ${isDefault ? 'btn-warning' : ''}" onclick="event.stopPropagation(); app.toggleDefaultProfile('${this.escapeHtml(name)}')" title="${isDefault ? 'Remove default' : 'Set as default'}">
                                <i class="fa-solid fa-star"></i>
                            </button>
                        </div>
                    </div>
                `;
            } else {
                // Grid view tile
                html += `
                    <div class="profile-tile ${isDefault ? 'default' : ''}" data-profile="${this.escapeHtml(name)}">
                        <div class="profile-tile-content">
                            <div class="profile-tile-avatar">
                                <img src="${this.escapeHtml(avatar)}" alt="${this.escapeHtml(name)}" onerror="this.src='default.svg'">
                            </div>
                            <div class="profile-tile-info">
                                <div class="profile-tile-name">
                                    ${this.escapeHtml(name)}
                                    <button class="profile-star ${isDefault ? 'active' : ''}" 
                                            onclick="event.stopPropagation(); app.toggleDefaultProfile('${this.escapeHtml(name)}')"
                                            title="${isDefault ? 'Remove as default' : 'Set as default'}">
                                        <svg viewBox="0 0 24 24" fill="${isDefault ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2">
                                            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
                                        </svg>
                                    </button>
                                </div>
                                <div class="profile-tile-meta">${nodeCountText}</div>
                            </div>
                        </div>
                        <div class="profile-tile-actions">
                            <button class="profile-action-btn launch" onclick="event.stopPropagation(); app.handleProfileAction('launch', '${this.escapeHtml(name)}')" title="Launch">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <polygon points="5 3 19 12 5 21 5 3"/>
                                </svg>
                                <span>Launch</span>
                            </button>
                            <button class="profile-action-btn edit" onclick="event.stopPropagation(); app.handleProfileAction('edit', '${this.escapeHtml(name)}')" title="Edit">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/>
                                    <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/>
                                </svg>
                                <span>Edit</span>
                            </button>
                        </div>
                    </div>
                `;
            }
        }
        
        // Add "Create Profile" tile/row (only if not searching)
        if (!searchTerm) {
            if (viewMode === 'list') {
                html += `
                    <div class="profile-row profile-row-add" onclick="app.createNewProfile()">
                        <div class="profile-row-avatar">
                            <i class="fa-solid fa-plus"></i>
                        </div>
                        <div class="profile-row-name">
                            <span class="name">Create New Profile</span>
                        </div>
                        <div class="profile-row-nodes"></div>
                        <div class="profile-row-actions"></div>
                    </div>
                `;
            } else {
                html += `
                    <div class="profile-tile profile-tile-add" onclick="app.createNewProfile()">
                        <div class="profile-tile-content">
                            <div class="profile-tile-avatar">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <line x1="12" y1="5" x2="12" y2="19"/>
                                    <line x1="5" y1="12" x2="19" y2="12"/>
                                </svg>
                            </div>
                            <div class="profile-tile-info">
                                <div class="profile-tile-name">Add Profile</div>
                            </div>
                        </div>
                    </div>
                `;
            }
        }
        
        grid.innerHTML = html;
        
        // Use event delegation for context menu (bind once on grid, not each tile)
        if (!grid.dataset.contextMenuBound) {
            grid.dataset.contextMenuBound = 'true';
            grid.addEventListener('contextmenu', (e) => {
                const tile = e.target.closest('.profile-tile:not(.profile-tile-add), .profile-row:not(.profile-row-add)');
                if (tile) {
                    this.showProfileContextMenu(e, tile.dataset.profile);
                }
            });
        }
    }
    
    bindProfilesToolbar() {
        // Only bind once
        if (this._profilesToolbarBound) return;
        this._profilesToolbarBound = true;
        
        // Import button
        const importBtn = document.getElementById('import-profile-btn');
        if (importBtn) {
            importBtn.addEventListener('click', () => this.importProfile());
        }
        
        // Create button
        const createBtn = document.getElementById('create-profile-btn');
        if (createBtn) {
            createBtn.addEventListener('click', () => this.createNewProfile());
        }
        
        // Search
        const searchInput = document.getElementById('profiles-search');
        if (searchInput) {
            searchInput.addEventListener('input', () => this.renderProfilesGrid());
        }
        
        // Sort select
        const sortSelect = document.getElementById('profiles-sort');
        if (sortSelect) {
            sortSelect.addEventListener('change', () => this.renderProfilesGrid());
        }
        
        // Sort direction
        const sortDirBtn = document.getElementById('profiles-sort-dir');
        if (sortDirBtn) {
            sortDirBtn.addEventListener('click', () => {
                this.profilesSortDir = this.profilesSortDir === 'asc' ? 'desc' : 'asc';
                const icon = sortDirBtn.querySelector('i');
                if (icon) {
                    icon.className = this.profilesSortDir === 'asc' 
                        ? 'fa-solid fa-arrow-down-short-wide' 
                        : 'fa-solid fa-arrow-up-short-wide';
                }
                this.renderProfilesGrid();
            });
        }
        
        // View toggle
        const viewGridBtn = document.getElementById('profiles-view-grid');
        const viewListBtn = document.getElementById('profiles-view-list');
        
        // Apply loaded preferences
        if (viewGridBtn && viewListBtn) {
            viewGridBtn.classList.toggle('active', this.profilesViewMode !== 'list');
            viewListBtn.classList.toggle('active', this.profilesViewMode === 'list');
        }
        
        if (viewGridBtn) {
            viewGridBtn.addEventListener('click', () => {
                this.profilesViewMode = 'grid';
                viewGridBtn.classList.add('active');
                viewListBtn?.classList.remove('active');
                this.renderProfilesGrid();
                this.saveUserPreferences();
            });
        }
        if (viewListBtn) {
            viewListBtn.addEventListener('click', () => {
                this.profilesViewMode = 'list';
                viewListBtn.classList.add('active');
                viewGridBtn?.classList.remove('active');
                this.renderProfilesGrid();
                this.saveUserPreferences();
            });
        }
    }
    
    // ==================== PROFILE CONTEXT MENU ====================
    
    showProfileContextMenu(e, profileName) {
        e.preventDefault();
        e.stopPropagation();
        
        const menu = document.getElementById('profile-context-menu');
        if (!menu) return;
        
        // Store which profile the menu is for
        menu.dataset.profile = profileName;
        
        // Update "Set as Default" text based on current state
        const profile = this.profiles[profileName];
        const setDefaultItem = menu.querySelector('[data-action="set-default"]');
        if (setDefaultItem && profile) {
            const isDefault = profile.is_default;
            setDefaultItem.innerHTML = `
                <i class="fa-${isDefault ? 'solid' : 'regular'} fa-star w-4 text-center"></i>
                ${isDefault ? 'Remove Default' : 'Set as Default'}
            `;
        }
        
        // Position the menu at cursor
        menu.style.display = 'block';
        
        // Calculate position to keep menu on screen
        const menuRect = menu.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        
        let x = e.clientX;
        let y = e.clientY;
        
        // Adjust if menu would go off right edge
        if (x + menuRect.width > viewportWidth) {
            x = viewportWidth - menuRect.width - 10;
        }
        
        // Adjust if menu would go off bottom edge
        if (y + menuRect.height > viewportHeight) {
            y = viewportHeight - menuRect.height - 10;
        }
        
        menu.style.left = `${x}px`;
        menu.style.top = `${y}px`;
        
        // Add click-outside listener
        setTimeout(() => {
            document.addEventListener('click', this.hideProfileContextMenu);
            document.addEventListener('contextmenu', this.hideProfileContextMenu);
        }, 0);
    }
    
    hideProfileContextMenu = () => {
        const menu = document.getElementById('profile-context-menu');
        if (menu) {
            menu.style.display = 'none';
        }
        document.removeEventListener('click', this.hideProfileContextMenu);
        document.removeEventListener('contextmenu', this.hideProfileContextMenu);
    }
    
    handleContextMenuAction(action) {
        const menu = document.getElementById('profile-context-menu');
        const profileName = menu?.dataset.profile;
        if (!profileName) return;
        
        this.hideProfileContextMenu();
        
        switch (action) {
            case 'launch':
                this.launchProfile(profileName);
                break;
            case 'edit':
                this.editProfile(profileName);
                break;
            case 'duplicate':
                this.duplicateProfile(profileName);
                break;
            case 'set-default':
                this.toggleDefaultProfile(profileName);
                break;
            case 'export':
                this.exportProfile(profileName);
                break;
            case 'quick-launch':
                this.createProfileShortcut(profileName);
                break;
            case 'delete':
                this.confirmDeleteProfile(profileName);
                break;
        }
    }
    
    async duplicateProfile(profileName) {
        const profile = this.profiles[profileName];
        if (!profile) return;
        
        // Generate a unique name
        let newName = `${profileName} (Copy)`;
        let counter = 2;
        while (this.profiles[newName]) {
            newName = `${profileName} (Copy ${counter})`;
            counter++;
        }
        
        try {
            const payload = {
                name: newName,
                description: profile.description || '',
                avatar: profile.avatar || 'default.svg',
                enabled: profile.enabled || [],
                disabled: profile.disabled || [],
                flags: profile.flags || {},
                custom_flags: profile.custom_flags || '',
                custom_flags_list: profile.custom_flags_list || [],
                excluded_packages: profile.excluded_packages || []
            };
            
            const response = await fetch(`${this.apiBase}/api/profiles/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const data = await response.json();
            if (data.success) {
                this.showToast('success', `Profile duplicated as "${newName}"`);
                await this.loadProfiles();
                this.renderProfilesGrid();
            } else {
                this.showToast('error', data.message || 'Failed to duplicate profile');
            }
        } catch (error) {
            this.showToast('error', this.parseError(error, 'Failed to duplicate profile'));
        }
    }
    
    async createConductorShortcut() {
        // Use native file save dialog
        const savePath = await this.showSaveFileDialog('MF Conductor.lnk');
        if (!savePath) return; // User cancelled
        
        this.log(`Creating MF Conductor shortcut: ${savePath}`, 'info');
        try {
            this.showToast('info', 'Creating shortcut...');
            
            const response = await fetch(`${this.apiBase}/api/shortcuts/conductor`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ save_path: savePath })
            });
            
            const data = await response.json();
            if (data.success) {
                this.log(`MF Conductor shortcut created successfully: ${savePath}`, 'success');
                this.showToast('success', data.message || 'Shortcut created');
            } else {
                this.log(`Failed to create shortcut: ${data.message}`, 'error');
                this.showToast('error', data.message || 'Failed to create shortcut');
            }
        } catch (error) {
            this.log(`Error creating shortcut: ${error.message}`, 'error');
            this.showToast('error', this.parseError(error, 'Failed to create shortcut'));
        }
    }
    
    async createProfileShortcut(profileName) {
        const profile = this.profiles[profileName];
        if (!profile) {
            this.showToast('error', 'Profile not found');
            return;
        }
        
        // Use native file save dialog
        const safeName = profileName.replace(/[^a-zA-Z0-9 _-]/g, '').trim();
        const savePath = await this.showSaveFileDialog(`ComfyUI - ${safeName}.lnk`);
        if (!savePath) return; // User cancelled
        
        this.log(`Creating profile shortcut: ${profileName} → ${savePath}`, 'info');
        try {
            this.showToast('info', `Creating shortcut for "${profileName}"...`);
            
            const response = await fetch(`${this.apiBase}/api/shortcuts/profile`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    profile_name: profileName,
                    save_path: savePath
                })
            });
            
            const data = await response.json();
            if (data.success) {
                this.log(`Profile shortcut created successfully: ${savePath}`, 'success');
                this.showToast('success', data.message || `Shortcut created for "${profileName}"`);
            } else {
                this.log(`Failed to create profile shortcut: ${data.message}`, 'error');
                this.showToast('error', data.message || 'Failed to create shortcut');
            }
        } catch (error) {
            this.log(`Error creating profile shortcut: ${error.message}`, 'error');
            this.showToast('error', this.parseError(error, 'Failed to create shortcut'));
        }
    }
    
    async showSaveFileDialog(suggestedName) {
        // Ask backend to show a native Windows save dialog
        try {
            const response = await fetch(`${this.apiBase}/api/system/save-dialog`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ suggested_name: suggestedName })
            });
            const data = await response.json();
            
            if (data.success && data.path) {
                return data.path;
            } else if (data.cancelled) {
                return null;
            }
        } catch (e) {
            console.error('Save dialog error:', e);
        }
        
        // Fallback: use prompt dialog if native dialog fails
        try {
            const response = await fetch(`${this.apiBase}/api/system/desktop-path`);
            const data = await response.json();
            const isWindows = /windows/i.test(navigator.userAgent || '');
            const separator = isWindows ? '\\' : '/';
            const defaultPath = data.success ? `${data.path}${separator}${suggestedName}` : `Desktop${separator}${suggestedName}`;
            
            return await this.showPrompt({
                title: 'Save Shortcut',
                message: 'Enter the full path where you want to save the shortcut:',
                placeholder: defaultPath,
                defaultValue: defaultPath,
                confirmText: 'Create'
            });
        } catch (e) {
            const isWindows = /windows/i.test(navigator.userAgent || '');
            const separator = isWindows ? '\\' : '/';
            return await this.showPrompt({
                title: 'Save Shortcut',
                message: 'Enter the full path where you want to save the shortcut:',
                placeholder: `Desktop${separator}${suggestedName}`,
                defaultValue: `Desktop${separator}${suggestedName}`,
                confirmText: 'Create'
            });
        }
    }
    
    async confirmDeleteProfile(profileName) {
        const confirmed = await this.showConfirm({
            title: 'Delete Profile',
            message: `Are you sure you want to delete "${profileName}"? This cannot be undone.`,
            confirmText: 'Delete',
            confirmClass: 'btn-danger'
        });
        
        if (confirmed) {
            this.deleteProfileConfirmed(profileName);
        }
    }
    
    
    async deleteProfileConfirmed(profileName) {
        this.log(`Deleting profile: ${profileName}`, 'warning');
        try {
            const response = await fetch(`${this.apiBase}/api/profiles/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: profileName })
            });
            const data = await response.json();
            if (data.success) {
                this.log(`Profile "${profileName}" deleted successfully`, 'success');
                this.showToast('success', `Profile "${profileName}" deleted`);
                await this.loadProfiles();
                this.renderProfilesGrid();
                this.updateComfyControls();
            } else {
                this.log(`Failed to delete profile: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.showToast('error', this.parseError(error, 'Failed to delete profile'));
        }
    }
    
    async toggleDefaultProfile(profileName) {
        const profile = this.profiles[profileName];
        if (!profile) return;
        
        const isCurrentlyDefault = profile.is_default;
        
        if (isCurrentlyDefault) {
            // Remove default status
            try {
                const response = await fetch(`${this.apiBase}/api/profiles/clear-default`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await response.json();
                if (data.success) {
                    await this.loadProfiles();
                    this.renderProfilesGrid();
                    this.updateComfyControls();
                    this.showToast('success', 'Default profile cleared');
                }
            } catch (error) {
                this.showToast('error', this.parseError(error, 'Failed to clear default'));
            }
        } else {
            // Set as default (this will automatically clear any existing default)
            try {
                const response = await fetch(`${this.apiBase}/api/profiles/set-default`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: profileName })
                });
                const data = await response.json();
                if (data.success) {
                    await this.loadProfiles();
                    this.renderProfilesGrid();
                    this.updateComfyControls();
                    this.showToast('success', `${profileName} set as default`);
                } else {
                    this.showToast('error', data.message);
                }
            } catch (error) {
                this.showToast('error', this.parseError(error, 'Failed to set default'));
            }
        }
    }
    
    async handleProfileAction(action, profileName) {
        switch (action) {
            case 'launch':
                await this.launchProfile(profileName);
                break;
            case 'edit':
                this.editProfile(profileName);
                break;
        }
    }
    
    async launchProfile(profileName) {
        // Check if already running
        if (this.comfyStatus === 'running' || this.comfyStatus === 'starting') {
            this.log('ComfyUI is already running', 'warning');
            this.showToast('warning', 'ComfyUI is already running');
            return;
        }
        
        // Switch to terminal page immediately and show splash
        this.switchMainTab('console');
        this.clearConsoleOutput();
        this.showSplashScreen(); // Non-blocking
        
        this.log(`Launching ComfyUI with profile "${profileName}"...`, 'info');
        this.updateComfyStatus('starting');
        this.appendToConsole(`Launching ComfyUI with profile "${profileName}"...`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/comfy/launch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile: profileName })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log('ComfyUI process started', 'success');
                this.showToast('success', `Launching ${profileName}...`);
                this.appendToConsole('ComfyUI process started', 'success');
                this.startConsolePolling();
                // Start checking if server is ready
                this.checkComfyServerReady();
            } else {
                this.log(`Failed to launch ComfyUI: ${data.message}`, 'error');
                this.updateComfyStatus('error');
                this.appendToConsole(`Failed to launch: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.updateComfyStatus('error');
            this.appendToConsole(`Error launching ComfyUI: ${error.message}`, 'error');
            console.error('Error launching profile:', error);
            this.showErrorWithRetry(
                this.parseError(error, 'Failed to launch profile'),
                () => this.launchProfile(profileName)
            );
        }
    }
    
    async promptEnableInProfiles(nodeFolderName) {
        // Get list of profiles
        const profileNames = Object.keys(this.profiles);
        
        if (profileNames.length === 0) {
            return; // No profiles to enable in
        }
        
        // Create modal content with checkboxes
        const checkboxes = profileNames.map((name, idx) => {
            const profile = this.profiles[name];
            const isDefault = profile.is_default ? ' (default)' : '';
            return `
                <label class="profile-checkbox-item">
                    <input type="checkbox" name="profile" value="${this.escapeHtml(name)}" ${idx === 0 ? 'checked' : ''}>
                    <span>${this.escapeHtml(name)}${isDefault}</span>
                </label>
            `;
        }).join('');
        
        // Create and show modal
        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 400px;">
                <div class="modal-header">
                    <h3>Enable Node in Profiles?</h3>
                    <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>
                <div class="modal-body">
                    <p class="text-slate-400 mb-4">Would you like to enable <strong class="text-white">${this.escapeHtml(nodeFolderName)}</strong> in any profiles?</p>
                    
                    <div class="mb-4">
                        <label class="profile-checkbox-item select-all">
                            <input type="checkbox" id="enable-all-profiles">
                            <span class="font-semibold">Select All</span>
                        </label>
                    </div>
                    
                    <div class="profile-checkbox-list">
                        ${checkboxes}
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-glass" onclick="this.closest('.modal-overlay').remove()">Skip</button>
                    <button class="btn btn-primary" id="enable-profiles-confirm">Enable Selected</button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Add show class after a frame to trigger animation
        requestAnimationFrame(() => {
            modal.classList.add('show');
        });
        
        // Handle select all
        const selectAllCheckbox = modal.querySelector('#enable-all-profiles');
        const profileCheckboxes = modal.querySelectorAll('input[name="profile"]');
        
        selectAllCheckbox.addEventListener('change', () => {
            profileCheckboxes.forEach(cb => cb.checked = selectAllCheckbox.checked);
        });
        
        // Handle confirm
        return new Promise((resolve) => {
            modal.querySelector('#enable-profiles-confirm').addEventListener('click', async () => {
                const selectedProfiles = Array.from(profileCheckboxes)
                    .filter(cb => cb.checked)
                    .map(cb => cb.value);
                
                if (selectedProfiles.length > 0) {
                    // Enable node in selected profiles
                    for (const profileName of selectedProfiles) {
                        const profile = this.profiles[profileName];
                        if (profile) {
                            if (!profile.enabled) profile.enabled = [];
                            if (!profile.enabled.includes(nodeFolderName)) {
                                profile.enabled.push(nodeFolderName);
                            }
                            // Remove from disabled if present
                            if (profile.disabled) {
                                profile.disabled = profile.disabled.filter(n => n !== nodeFolderName);
                            }
                        }
                    }
                    
                    // Save profiles
                    try {
                        for (const profileName of selectedProfiles) {
                            await fetch(`${this.apiBase}/api/profiles/save`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    name: profileName,
                                    profile: this.profiles[profileName]
                                })
                            });
                        }
                        this.showToast('success', `Enabled in ${selectedProfiles.length} profile(s)`);
                        this.log(`Enabled ${nodeFolderName} in: ${selectedProfiles.join(', ')}`, 'success');
                    } catch (error) {
                        this.showToast('error', 'Failed to update profiles');
                    }
                }
                
                modal.remove();
                resolve();
            });
            
            // Handle close/skip
            modal.querySelector('.modal-close')?.addEventListener('click', () => {
                modal.remove();
                resolve();
            });
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.remove();
                    resolve();
                }
            });
        });
    }
    
    async launchDefaultProfile() {
        // Find the default profile
        const defaultProfile = Object.entries(this.profiles).find(([name, profile]) => profile.is_default);
        
        if (defaultProfile) {
            await this.launchProfile(defaultProfile[0]);
        } else {
            // No default profile, just launch with first profile or no profile
            const firstProfile = Object.keys(this.profiles)[0];
            if (firstProfile) {
                await this.launchProfile(firstProfile);
            } else {
                this.showToast('error', 'No profiles available to launch');
            }
        }
    }
    
    async setDefaultProfile(profileName) {
        this.log(`Setting default profile: ${profileName}`, 'info');
        try {
            const response = await fetch(`${this.apiBase}/api/profiles/set-default`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: profileName })
            });
            const data = await response.json();
            
            if (data.success) {
                this.log(`Default profile set to: ${profileName}`, 'success');
                this.showToast('success', `${profileName} set as default`);
                await this.loadProfiles();
                this.renderProfilesGrid();
            } else {
                this.log(`Failed to set default profile: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.log(`Error setting default profile: ${error.message}`, 'error');
            this.showToast('error', 'Failed to set default profile');
        }
    }
    
    // Profile Editor
    createNewProfile() {
        this.editingProfile = null;
        this.profileSelectedNodes = new Set();
        this.profileCustomFlags = [];
        this.profileExcludedPackages = new Set();
        this.openProfileEditor('Create Profile');
    }
    
    editProfile(profileName) {
        const profile = this.profiles[profileName];
        if (!profile) return;
        
        this.editingProfile = profileName;
        // If enabled list is empty, treat as "all nodes" (select all)
        if (profile.enabled && profile.enabled.length > 0) {
            this.profileSelectedNodes = new Set(profile.enabled);
        } else {
            // Empty enabled = all nodes selected
            this.profileSelectedNodes = new Set(this.nodes.map(n => n.folder_name));
        }
        this.profileCustomFlags = (profile.custom_flags_list || []).map(f => 
            typeof f === 'string' ? { value: f, enabled: true } : f
        );
        this.profileExcludedPackages = new Set(profile.excluded_packages || []);
        
        this.openProfileEditor('Edit Profile', profile);
    }
    
    async openProfileEditor(title, profile = null) {
        const editor = document.getElementById('profile-editor');
        if (!editor) return;
        
        // Load nodes if not already loaded
        if (this.nodes.length === 0) {
            await this.loadNodes();
        }
        
        // Load packages
        await this.loadPackagesList();
        
        document.getElementById('profile-editor-title').textContent = title;
        document.getElementById('profile-name-input').value = profile ? this.editingProfile : '';
        document.getElementById('profile-desc-input').value = profile?.description || '';
        document.getElementById('profile-avatar-preview').src = profile?.avatar || 'default.svg';
        document.getElementById('profile-delete-btn').style.display = profile ? 'inline-flex' : 'none';
        
        // Initialize nodes - only if not already set by editProfile()
        // Profile saves 'enabled' array, not 'nodes'
        // Empty enabled list = all nodes (preset profiles use this)
        if (profile?.enabled && profile.enabled.length > 0) {
            // Editing existing profile with specific nodes
            this.profileSelectedNodes = new Set(profile.enabled);
        } else {
            // New profile OR profile with empty enabled list: select all nodes
            this.profileSelectedNodes = new Set(this.nodes.map(n => n.folder_name));
        }
        
        // Always ensure required nodes are included
        this.requiredNodes.forEach(folder => this.profileSelectedNodes.add(folder));
        
        // Initialize packages - all included by default (excluded_packages is what's NOT included)
        if (profile?.excluded_packages) {
            this.profileExcludedPackages = new Set(profile.excluded_packages);
        } else if (!profile) {
            // New profile: include all packages (empty excluded set)
            this.profileExcludedPackages = new Set();
        }
        
        // Initialize custom flags from custom_flags_list (the array of objects)
        if (profile?.custom_flags_list) {
            this.profileCustomFlags = profile.custom_flags_list.map(f => 
                typeof f === 'string' ? { value: f, enabled: true } : f
            );
        } else if (!profile) {
            this.profileCustomFlags = [];
        }
        
        // Load flags
        if (profile?.flags) {
            this.loadProfileEditorFlags(profile.flags);
        } else {
            this.clearProfileEditorFlags();
        }
        
        // Render nodes and packages
        this.renderProfileEditorNodes();
        this.renderProfileEditorPackages();
        this.renderProfileEditorCustomFlags();
        
        // Bind tab switching
        this.bindProfileEditorTabs();
        
        // Bind events
        this.bindProfileEditorEvents();
        
        editor.classList.add('show');
    }
    
    closeProfileEditor() {
        const editor = document.getElementById('profile-editor');
        if (editor) {
            editor.classList.remove('show');
        }
        this.editingProfile = null;
    }
    
    bindProfileEditorTabs() {
        document.querySelectorAll('.profile-editor-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.profile-editor-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.profile-editor-tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const tabId = 'pe-tab-' + tab.dataset.tab;
                document.getElementById(tabId)?.classList.add('active');
            });
        });
    }
    
    bindProfileEditorEvents() {
        // Close on overlay click
        const editor = document.getElementById('profile-editor');
        editor?.addEventListener('click', (e) => {
            if (e.target === editor) {
                this.closeProfileEditor();
            }
        });
        
        // Avatar picker
        const avatarInput = document.getElementById('profile-avatar-input');
        avatarInput?.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    document.getElementById('profile-avatar-preview').src = e.target.result;
                };
                reader.readAsDataURL(file);
            }
        });
        
        // Node transfers
        document.getElementById('pe-add-all-nodes')?.addEventListener('click', () => {
            this.nodes.forEach(n => this.profileSelectedNodes.add(n.folder_name));
            this.renderProfileEditorNodes();
        });
        
        document.getElementById('pe-remove-all-nodes')?.addEventListener('click', () => {
            // Keep required nodes, remove the rest
            const toKeep = new Set();
            this.profileSelectedNodes.forEach(folder => {
                if (this.requiredNodes.has(folder)) toKeep.add(folder);
            });
            this.profileSelectedNodes = toKeep;
            this.renderProfileEditorNodes();
            if (toKeep.size > 0) {
                this.showToast('info', `Kept ${toKeep.size} required node${toKeep.size > 1 ? 's' : ''}`);
            }
        });
        
        document.getElementById('pe-add-selected-nodes')?.addEventListener('click', () => {
            document.querySelectorAll('#pe-available-nodes-list .profile-node-item.selected').forEach(item => {
                this.profileSelectedNodes.add(item.dataset.folder);
            });
            this.renderProfileEditorNodes();
        });
        
        document.getElementById('pe-remove-selected-nodes')?.addEventListener('click', () => {
            let skipped = 0;
            document.querySelectorAll('#pe-selected-nodes-list .profile-node-item.selected').forEach(item => {
                if (this.requiredNodes.has(item.dataset.folder)) {
                    skipped++;
                } else {
                    this.profileSelectedNodes.delete(item.dataset.folder);
                }
            });
            if (skipped > 0) {
                this.showToast('warning', `Cannot remove ${skipped} required node${skipped > 1 ? 's' : ''}`);
            }
            this.renderProfileEditorNodes();
        });
        
        // Search filters for nodes
        document.getElementById('pe-available-search')?.addEventListener('input', (e) => {
            this.renderProfileEditorNodes(e.target.value, '');
        });
        
        document.getElementById('pe-selected-search')?.addEventListener('input', (e) => {
            this.renderProfileEditorNodes('', e.target.value);
        });
        
        // Package transfers
        document.getElementById('pe-include-all-pkg')?.addEventListener('click', () => {
            this.profileExcludedPackages.clear();
            this.renderProfileEditorPackages(
                document.getElementById('pe-excluded-pkg-search')?.value || '',
                document.getElementById('pe-included-pkg-search')?.value || ''
            );
        });
        
        document.getElementById('pe-exclude-all-pkg')?.addEventListener('click', () => {
            if (this.installedPackages) {
                let skipped = 0;
                this.installedPackages.forEach(p => {
                    // Check if package is required (case-insensitive)
                    const lower = p.name.toLowerCase();
                    let isRequired = false;
                    for (const req of this.requiredPackages) {
                        if (req.toLowerCase() === lower) {
                            isRequired = true;
                            break;
                        }
                    }
                    if (isRequired) {
                        skipped++;
                    } else {
                        this.profileExcludedPackages.add(p.name);
                    }
                });
                if (skipped > 0) {
                    this.showToast('info', `Kept ${skipped} required package${skipped > 1 ? 's' : ''}`);
                }
            }
            this.renderProfileEditorPackages(
                document.getElementById('pe-excluded-pkg-search')?.value || '',
                document.getElementById('pe-included-pkg-search')?.value || ''
            );
        });
        
        document.getElementById('pe-include-selected-pkg')?.addEventListener('click', () => {
            const selected = document.querySelectorAll('#pe-excluded-pkg-list .profile-node-item.selected');
            if (selected.length === 0) {
                this.showToast('info', 'No packages selected');
                return;
            }
            selected.forEach(item => {
                this.profileExcludedPackages.delete(item.dataset.pkg);
            });
            this.renderProfileEditorPackages(
                document.getElementById('pe-excluded-pkg-search')?.value || '',
                document.getElementById('pe-included-pkg-search')?.value || ''
            );
        });
        
        document.getElementById('pe-exclude-selected-pkg')?.addEventListener('click', () => {
            const selected = document.querySelectorAll('#pe-included-pkg-list .profile-node-item.selected');
            if (selected.length === 0) {
                this.showToast('info', 'No packages selected');
                return;
            }
            let skipped = 0;
            selected.forEach(item => {
                const pkgName = item.dataset.pkg;
                const lower = pkgName.toLowerCase();
                let isRequired = false;
                for (const req of this.requiredPackages) {
                    if (req.toLowerCase() === lower) {
                        isRequired = true;
                        break;
                    }
                }
                if (isRequired) {
                    skipped++;
                } else {
                    this.profileExcludedPackages.add(pkgName);
                }
            });
            if (skipped > 0) {
                this.showToast('warning', `Cannot exclude ${skipped} required package${skipped > 1 ? 's' : ''}`);
            }
            this.renderProfileEditorPackages(
                document.getElementById('pe-excluded-pkg-search')?.value || '',
                document.getElementById('pe-included-pkg-search')?.value || ''
            );
        });
        
        // Search filters for packages
        document.getElementById('pe-excluded-pkg-search')?.addEventListener('input', (e) => {
            this.renderProfileEditorPackages(e.target.value, '');
        });
        
        document.getElementById('pe-included-pkg-search')?.addEventListener('input', (e) => {
            this.renderProfileEditorPackages('', e.target.value);
        });
        
        // Custom flags
        const addCustomFlag = () => {
            const input = document.getElementById('pe-custom-flag-input');
            const flag = input?.value.trim();
            if (flag && !this.profileCustomFlags.find(f => f.value === flag)) {
                this.profileCustomFlags.push({ value: flag, enabled: true });
                input.value = '';
                this.renderProfileEditorCustomFlags();
            }
        };
        
        document.getElementById('pe-add-custom-flag')?.addEventListener('click', addCustomFlag);
        document.getElementById('pe-custom-flag-input')?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') addCustomFlag();
        });
    }
    
    pickProfileAvatar() {
        document.getElementById('profile-avatar-input')?.click();
    }
    
    renderProfileEditorNodes(availFilter = '', selectedFilter = '') {
        const availContainer = document.getElementById('pe-available-nodes-list');
        const selectedContainer = document.getElementById('pe-selected-nodes-list');
        const availCount = document.getElementById('pe-available-count');
        const selectedCount = document.getElementById('pe-selected-count');
        
        if (!availContainer || !selectedContainer) return;
        
        const availFilterLower = availFilter.toLowerCase();
        const selectedFilterLower = selectedFilter.toLowerCase();
        
        // Excluded nodes (not in profile)
        const available = this.nodes.filter(n => 
            !this.profileSelectedNodes.has(n.folder_name) &&
            (!availFilter || n.display_name.toLowerCase().includes(availFilterLower) || n.folder_name.toLowerCase().includes(availFilterLower))
        );
        
        availContainer.innerHTML = available.map(n => {
            const isRequired = this.requiredNodes.has(n.folder_name);
            return `
                <div class="profile-node-item ${isRequired ? 'required-item' : ''}" data-folder="${this.escapeHtml(n.folder_name)}" 
                     onclick="this.classList.toggle('selected')" ondblclick="app.peAddNode('${this.escapeHtml(n.folder_name)}')">
                    <span class="node-name">${this.escapeHtml(n.display_name)}</span>
                    ${isRequired ? '<span class="required-badge" title="Required for ComfyUI">Required</span>' : ''}
                </div>
            `;
        }).join('') || '<div style="padding:20px;color:var(--text-muted);font-size:11px;text-align:center;">All nodes in profile</div>';
        
        if (availCount) availCount.textContent = available.length;
        
        // Selected nodes (in profile)
        const selectedArray = Array.from(this.profileSelectedNodes);
        const filtered = selectedArray.filter(folder => {
            if (!selectedFilter) return true;
            const node = this.nodes.find(n => n.folder_name === folder);
            return node && (node.display_name.toLowerCase().includes(selectedFilterLower) || folder.toLowerCase().includes(selectedFilterLower));
        });
        
        // Sort: required items first
        filtered.sort((a, b) => {
            const aReq = this.requiredNodes.has(a) ? 0 : 1;
            const bReq = this.requiredNodes.has(b) ? 0 : 1;
            return aReq - bReq;
        });
        
        selectedContainer.innerHTML = filtered.map(folder => {
            const node = this.nodes.find(n => n.folder_name === folder);
            const displayName = node?.display_name || folder;
            const isRequired = this.requiredNodes.has(folder);
            const escapedFolder = this.escapeHtml(folder);
            const onDblClick = isRequired 
                ? "app.showToast('warning', 'This node is required for ComfyUI')" 
                : `app.peRemoveNode('${escapedFolder}')`;
            const onClick = isRequired ? '' : "this.classList.toggle('selected')";
            return `
                <div class="profile-node-item ${isRequired ? 'required-item locked' : ''}" 
                     data-folder="${escapedFolder}" 
                     onclick="${onClick}" 
                     ondblclick="${onDblClick}"
                     ${isRequired ? 'title="Required - cannot be removed"' : ''}>
                    <span class="node-name">${this.escapeHtml(displayName)}</span>
                    ${isRequired ? '<span class="required-badge locked" title="Required for ComfyUI">Required</span>' : ''}
                </div>
            `;
        }).join('') || '<div style="padding:20px;color:var(--text-muted);font-size:11px;text-align:center;">No nodes selected</div>';
        
        if (selectedCount) selectedCount.textContent = this.profileSelectedNodes.size;
    }
    
    peAddNode(folder) {
        this.profileSelectedNodes.add(folder);
        this.renderProfileEditorNodes(
            document.getElementById('pe-available-search')?.value || '',
            document.getElementById('pe-selected-search')?.value || ''
        );
    }
    
    peRemoveNode(folder) {
        // Prevent removing required nodes
        if (this.requiredNodes.has(folder)) {
            this.showToast('warning', 'This node is required for ComfyUI to function');
            return;
        }
        this.profileSelectedNodes.delete(folder);
        this.renderProfileEditorNodes(
            document.getElementById('pe-available-search')?.value || '',
            document.getElementById('pe-selected-search')?.value || ''
        );
    }
    
    renderProfileEditorPackages(excludedFilter = '', includedFilter = '') {
        const excludedContainer = document.getElementById('pe-excluded-pkg-list');
        const includedContainer = document.getElementById('pe-included-pkg-list');
        const excludedCount = document.getElementById('pe-excluded-pkg-count');
        const includedCount = document.getElementById('pe-included-pkg-count');
        
        if (!excludedContainer || !includedContainer) return;
        
        if (!this.installedPackages || this.installedPackages.length === 0) {
            excludedContainer.innerHTML = '<div style="padding:20px;color:var(--text-muted);font-size:11px;text-align:center;">No packages loaded</div>';
            includedContainer.innerHTML = '<div style="padding:20px;color:var(--text-muted);font-size:11px;text-align:center;">No packages loaded</div>';
            return;
        }
        
        const excludedFilterLower = excludedFilter.toLowerCase();
        const includedFilterLower = includedFilter.toLowerCase();
        
        // Helper to check if package is required (case-insensitive)
        const isPackageRequired = (name) => {
            const lower = name.toLowerCase();
            for (const req of this.requiredPackages) {
                if (req.toLowerCase() === lower) return true;
            }
            return false;
        };
        
        // Excluded packages (left side)
        const excluded = this.installedPackages.filter(pkg => 
            this.profileExcludedPackages.has(pkg.name) &&
            (!excludedFilter || pkg.name.toLowerCase().includes(excludedFilterLower))
        );
        
        // Included packages (right side - not in excluded set)
        const included = this.installedPackages.filter(pkg => 
            !this.profileExcludedPackages.has(pkg.name) &&
            (!includedFilter || pkg.name.toLowerCase().includes(includedFilterLower))
        );
        
        // Sort included: required items first
        included.sort((a, b) => {
            const aReq = isPackageRequired(a.name) ? 0 : 1;
            const bReq = isPackageRequired(b.name) ? 0 : 1;
            if (aReq !== bReq) return aReq - bReq;
            return a.name.localeCompare(b.name);
        });
        
        excludedContainer.innerHTML = excluded.map(pkg => {
            const isRequired = isPackageRequired(pkg.name);
            const escapedName = this.escapeHtml(pkg.name);
            return `
                <div class="profile-node-item ${isRequired ? 'required-item' : ''}" 
                     data-pkg="${escapedName}" 
                     onclick="this.classList.toggle('selected')" 
                     ondblclick="app.peIncludePackage('${escapedName}')">
                    <span class="node-name">${escapedName}</span>
                    <span class="node-version">${this.escapeHtml(pkg.version || '')}</span>
                    ${isRequired ? '<span class="required-badge warning" title="Required for ComfyUI - should be included!">Required</span>' : ''}
                </div>
            `;
        }).join('') || '<div style="padding:20px;color:var(--text-muted);font-size:11px;text-align:center;">No excluded packages</div>';
        
        includedContainer.innerHTML = included.map(pkg => {
            const isRequired = isPackageRequired(pkg.name);
            const escapedName = this.escapeHtml(pkg.name);
            const onDblClick = isRequired 
                ? "app.showToast('warning', 'This package is required for ComfyUI')" 
                : `app.peExcludePackage('${escapedName}')`;
            const onClick = isRequired ? '' : "this.classList.toggle('selected')";
            return `
                <div class="profile-node-item ${isRequired ? 'required-item locked' : ''}" 
                     data-pkg="${escapedName}" 
                     onclick="${onClick}" 
                     ondblclick="${onDblClick}"
                     ${isRequired ? 'title="Required - cannot be excluded"' : ''}>
                    <span class="node-name">${escapedName}</span>
                    <span class="node-version">${this.escapeHtml(pkg.version || '')}</span>
                    ${isRequired ? '<span class="required-badge locked" title="Required for ComfyUI">Required</span>' : ''}
                </div>
            `;
        }).join('') || '<div style="padding:20px;color:var(--text-muted);font-size:11px;text-align:center;">All packages excluded</div>';
        
        if (excludedCount) excludedCount.textContent = this.profileExcludedPackages.size;
        if (includedCount) includedCount.textContent = this.installedPackages.length - this.profileExcludedPackages.size;
    }
    
    peIncludePackage(name) {
        this.profileExcludedPackages.delete(name);
        this.renderProfileEditorPackages(
            document.getElementById('pe-excluded-pkg-search')?.value || '',
            document.getElementById('pe-included-pkg-search')?.value || ''
        );
    }
    
    peExcludePackage(name) {
        // Check if package is required (case-insensitive)
        const lower = name.toLowerCase();
        for (const req of this.requiredPackages) {
            if (req.toLowerCase() === lower) {
                this.showToast('warning', 'This package is required for ComfyUI to function');
                return;
            }
        }
        this.profileExcludedPackages.add(name);
        this.renderProfileEditorPackages(
            document.getElementById('pe-excluded-pkg-search')?.value || '',
            document.getElementById('pe-included-pkg-search')?.value || ''
        );
    }
    
    renderProfileEditorCustomFlags() {
        const container = document.getElementById('pe-custom-flags-list');
        if (!container) return;
        
        container.innerHTML = this.profileCustomFlags.map((flag, index) => `
            <div class="custom-flag-item">
                <input type="checkbox" ${flag.enabled ? 'checked' : ''} 
                    onchange="app.peToggleCustomFlag(${index}, this.checked)">
                <span class="flag-text">${this.escapeHtml(flag.value)}</span>
                <button class="flag-remove" onclick="app.peRemoveCustomFlag(${index})" title="Remove">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12">
                        <path d="M18 6L6 18M6 6l12 12"/>
                    </svg>
                </button>
            </div>
        `).join('');
    }
    
    peToggleCustomFlag(index, enabled) {
        if (this.profileCustomFlags[index]) {
            this.profileCustomFlags[index].enabled = enabled;
        }
    }
    
    peRemoveCustomFlag(index) {
        this.profileCustomFlags.splice(index, 1);
        this.renderProfileEditorCustomFlags();
    }
    
    loadProfileEditorFlags(flags) {
        this.clearProfileEditorFlags();
        
        ['vram', 'attention', 'precision', 'vae', 'cache'].forEach(group => {
            if (flags[group]) {
                const input = document.querySelector(`#pe-tab-flags input[name="pe-${group}"][value="${flags[group]}"]`);
                if (input) input.checked = true;
            }
        });
        
        document.querySelectorAll('#pe-tab-flags .flag-option input[type="checkbox"]').forEach(cb => {
            const baseName = cb.name.replace('pe-', '');
            cb.checked = flags[baseName] === cb.value;
        });
    }
    
    clearProfileEditorFlags() {
        ['vram', 'attention', 'precision', 'vae', 'cache'].forEach(group => {
            const defaultInput = document.querySelector(`#pe-tab-flags input[name="pe-${group}"][value=""]`);
            if (defaultInput) defaultInput.checked = true;
        });
        
        document.querySelectorAll('#pe-tab-flags .flag-option input[type="checkbox"]').forEach(cb => {
            cb.checked = false;
        });
    }
    
    getProfileEditorFlags() {
        const flags = {};
        
        ['vram', 'attention', 'precision', 'vae', 'cache'].forEach(group => {
            const checked = document.querySelector(`#pe-tab-flags input[name="pe-${group}"]:checked`);
            if (checked && checked.value) {
                flags[group] = checked.value;
            }
        });
        
        document.querySelectorAll('#pe-tab-flags .flag-option input[type="checkbox"]:checked').forEach(cb => {
            const baseName = cb.name.replace('pe-', '');
            flags[baseName] = cb.value;
        });
        
        return flags;
    }
    
    async saveProfile() {
        const nameInput = document.getElementById('profile-name-input');
        const name = nameInput?.value?.trim();
        if (!name) {
            this.showToast('error', 'Please enter a profile name');
            return;
        }
        
        const description = document.getElementById('profile-desc-input')?.value.trim() || '';
        const avatarImg = document.getElementById('profile-avatar-preview');
        const avatar = avatarImg?.src || 'default.svg';
        
        // Ensure required nodes are always enabled (MF_Conductor, ComfyUI-Manager, etc.)
        this.requiredNodes.forEach(folder => this.profileSelectedNodes.add(folder));
        
        const enabled = Array.from(this.profileSelectedNodes);
        const disabled = this.nodes
            .filter(n => !this.profileSelectedNodes.has(n.folder_name) && !this.requiredNodes.has(n.folder_name))
            .map(n => n.folder_name);
        
        const flags = this.getProfileEditorFlags();
        const customFlagsList = this.profileCustomFlags;
        const customFlagsString = this.profileCustomFlags.filter(f => f.enabled).map(f => f.value).join(' ');
        const excludedPackages = Array.from(this.profileExcludedPackages);
        
        // Check if we're editing an existing profile
        // This ensures we update/rename the existing profile, not create a duplicate
        const isEditing = this.editingProfile !== null;
        
        try {
            const payload = {
                name,
                description,
                avatar,
                enabled,
                disabled,
                flags,
                custom_flags: customFlagsString,
                custom_flags_list: customFlagsList,
                excluded_packages: excludedPackages
            };
            
            // If editing an existing profile, always include the old name
            // This handles both rename (old deleted, new created) and update (same name overwritten)
            if (isEditing) {
                payload.old_name = this.editingProfile;
            }
            
            const response = await fetch(`${this.apiBase}/api/profiles/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await response.json();
            
            if (data.success) {
                const action = isEditing ? 'Updated' : 'Created';
                this.log(`${action} profile: "${name}" (${enabled.length} enabled, ${disabled.length} disabled)`, 'success');
                this.showToast('success', `Profile "${name}" saved`);
                this.closeProfileEditor();
                await this.loadProfiles();
                this.renderProfilesGrid();
            } else {
                this.log(`Failed to save profile: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            console.error('Error saving profile:', error);
            this.showToast('error', this.parseError(error, 'Failed to save profile'));
        }
    }
    
    async deleteCurrentProfile() {
        if (!this.editingProfile) return;
        
        const confirmed = await this.showConfirm({
            title: `Delete profile "${this.editingProfile}"?`,
            message: `This profile will be permanently deleted.`,
            type: 'danger',
            confirmText: 'Delete',
            confirmClass: 'btn-danger'
        });
        if (!confirmed) return;
        
        try {
            const response = await fetch(`${this.apiBase}/api/profiles/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: this.editingProfile })
            });
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', 'Profile deleted');
                this.closeProfileEditor();
                await this.loadProfiles();
                this.renderProfilesGrid();
            } else {
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.showToast('error', 'Failed to delete profile');
        }
    }
    
    // ==================== FILE BROWSER ====================
    
    async loadFilesTab() {
        const container = document.getElementById('files-grid');
        const countEl = document.getElementById('files-count');
        const sizeEl = document.getElementById('files-size');
        const pathEl = document.getElementById('files-current-path');
        
        if (!container) return;
        
        // Show loading state
        container.innerHTML = `
            <div class="loading-state flex flex-col items-center justify-center py-20 col-span-full">
                <div class="loader mb-4"></div>
                <p class="text-slate-400">Loading files...</p>
            </div>
        `;
        
        try {
            // Only request workflow data when in workflow view mode (for performance)
            const needWorkflow = this.filesViewMode === 'workflow' && this.filesFolder === 'output';
            const params = new URLSearchParams({
                folder: this.filesFolder,
                subfolder: this.filesSubfolder,
                sort: this.filesSortBy,
                dir: this.filesSortDir,
                type: this.filesTypeFilter,
                search: this.filesSearch,
                recursive: this.filesRecursive,
                with_workflow: needWorkflow ? 'true' : 'false'
            });
            
            const response = await fetch(`${this.apiBase}/api/files?${params}`);
            const data = await response.json();
            
            if (!data.success) {
                throw new Error(data.message);
            }
            
            this.filesData = data.files || [];
            
            // Update stats
            if (countEl) countEl.textContent = `${data.total} files`;
            if (sizeEl) sizeEl.textContent = this.formatBytes(data.total_size);
            if (pathEl) {
                let folderName;
                if (this.filesFolder === 'both') {
                    folderName = 'All Files';
                } else {
                    folderName = this.filesFolder.charAt(0).toUpperCase() + this.filesFolder.slice(1);
                }
                
                if (this.filesSubfolder && !this.filesRecursive) {
                    pathEl.textContent = `${folderName} / ${this.filesSubfolder}`;
                } else {
                    pathEl.textContent = folderName;
                }
            }
            
            // Handle workflow view visibility
            const workflowBtn = document.getElementById('files-view-workflow');
            if (workflowBtn) {
                if (this.filesFolder === 'output') {
                    workflowBtn.style.display = 'flex';
                } else {
                    workflowBtn.style.display = 'none';
                    // Force switch out of workflow mode if not in output
                    if (this.filesViewMode === 'workflow') {
                        this.filesViewMode = 'grid';
                        this.saveUserPreferences();
                        this.updateViewToggleButtons();
                    }
                }
            }
            
            this.renderFilesGrid();
            
        } catch (error) {
            console.error('Error loading files:', error);
            container.innerHTML = `
                <div class="files-empty col-span-full">
                    <i class="fa-solid fa-exclamation-triangle text-amber-500"></i>
                    <h3>Error Loading Files</h3>
                    <p>${this.escapeHtml(error.message)}</p>
                </div>
            `;
        }
    }
    
    renderFilesGrid() {
        const container = document.getElementById('files-grid');
        if (!container) return;
        
        if (this.filesData.length === 0 && !this.filesSubfolder) {
            container.innerHTML = `
                <div class="files-empty col-span-full">
                    <i class="fa-solid fa-folder-open"></i>
                    <h3>No Files Found</h3>
                    <p>This folder is empty or no files match your filters.</p>
                </div>
            `;
            return;
        }
        
        // Handle workflow grouping view
        if (this.filesViewMode === 'workflow') {
            this.renderWorkflowGroups(container);
            return;
        }
        
        // Apply view mode
        container.className = this.filesViewMode === 'list' ? 'files-grid list-view' : 'files-grid';
        
        let html = '';
        
        // Add column headers for list view
        if (this.filesViewMode === 'list') {
            const sortIcon = (field) => {
                if (this.filesSortBy !== field) return '';
                return this.filesSortDir === 'desc' 
                    ? '<i class="fa-solid fa-caret-down sort-icon"></i>' 
                    : '<i class="fa-solid fa-caret-up sort-icon"></i>';
            };
            const activeClass = (field) => this.filesSortBy === field ? 'active' : '';
            
            html += `
                <div class="files-header">
                    <span class="header-thumb"></span>
                    <span class="header-name sortable ${activeClass('name')}" data-sort="name">Name ${sortIcon('name')}</span>
                    <span class="header-date sortable ${activeClass('date')}" data-sort="date">Date ${sortIcon('date')}</span>
                    <span class="header-size sortable ${activeClass('size')}" data-sort="size">Size ${sortIcon('size')}</span>
                    <span class="header-workflow sortable ${activeClass('workflow')}" data-sort="workflow">Workflow ${sortIcon('workflow')}</span>
                    <span class="header-actions"></span>
                </div>
            `;
        }
        
        // Add back button if in subfolder (not in recursive mode)
        if (this.filesSubfolder && !this.filesRecursive) {
            html += `
                <div class="file-tile back-button" data-path=".." data-is-dir="true">
                    <div class="file-thumbnail">
                        <i class="fa-solid fa-arrow-left file-icon"></i>
                    </div>
                    <div class="file-info">
                        <div class="file-name">.. (Back)</div>
                        <div class="file-meta">
                            <span class="file-date">-</span>
                            <span class="file-size">-</span>
                            <span class="file-workflow">-</span>
                        </div>
                    </div>
                    <div class="file-actions"></div>
                </div>
            `;
        }
        
        html += this.filesData.map(file => this.buildFileTile(file)).join('');
        container.innerHTML = html;
        
        // Bind click handlers
        container.querySelectorAll('.file-tile').forEach(tile => {
            tile.addEventListener('click', (e) => {
                // Ignore if clicking on action buttons
                if (e.target.closest('.file-action-btn')) return;
                
                const filePath = tile.dataset.path;
                const isDir = tile.dataset.isDir === 'true';
                
                if (isDir && !this.filesRecursive) {
                    this.navigateToFolder(filePath);
                } else if (!isDir) {
                    this.previewFile(filePath);
                }
            });
            
            tile.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                this.showFileContextMenu(e, tile.dataset.path, tile.dataset.name);
            });
        });
        
        // Bind load workflow buttons
        container.querySelectorAll('.load-workflow-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                
                // Check if ComfyUI is running
                if (btn.dataset.comfyReady !== 'true') {
                    const shouldLaunch = await this.showConfirm({
                        title: 'ComfyUI Not Running',
                        message: 'Loading a workflow requires ComfyUI to be running. Would you like to launch ComfyUI with your default profile?',
                        type: 'info',
                        confirmText: 'Launch ComfyUI',
                        cancelText: 'Cancel'
                    });
                    
                    if (shouldLaunch) {
                        // Store the workflow path to load after ComfyUI starts
                        this.pendingWorkflowPath = btn.dataset.path;
                        await this.launchDefaultProfile();
                    }
                    return;
                }
                
                this.loadWorkflowFromFile(btn.dataset.path);
            });
        });
        
        // Bind sortable headers
        container.querySelectorAll('.files-header .sortable').forEach(header => {
            header.addEventListener('click', () => {
                const sortField = header.dataset.sort;
                if (this.filesSortBy === sortField) {
                    // Toggle direction
                    this.filesSortDir = this.filesSortDir === 'desc' ? 'asc' : 'desc';
                } else {
                    // New sort field, default to desc
                    this.filesSortBy = sortField;
                    this.filesSortDir = 'desc';
                }
                // Update sort select if it exists
                const sortSelect = document.getElementById('files-sort');
                if (sortSelect) sortSelect.value = sortField;
                
                this.loadFilesTab();
                this.saveUserPreferences();
            });
        });
    }
    
    renderWorkflowGroups(container) {
        container.className = 'workflow-view-container';
        
        // Group files by workflow
        const workflowGroups = {};
        const filesOnly = this.filesData.filter(f => !f.is_dir);
        
        filesOnly.forEach(file => {
            const workflowName = file.workflow || 'No Workflow';
            if (!workflowGroups[workflowName]) {
                workflowGroups[workflowName] = [];
            }
            workflowGroups[workflowName].push(file);
        });
        
        // Sort workflow names
        const sortedWorkflows = Object.keys(workflowGroups).sort((a, b) => {
            if (a === 'No Workflow') return 1;
            if (b === 'No Workflow') return -1;
            return a.localeCompare(b);
        });
        
        if (sortedWorkflows.length === 0) {
            container.innerHTML = `
                <div class="files-empty col-span-full">
                    <i class="fa-solid fa-sitemap"></i>
                    <h3>No Files Found</h3>
                    <p>No files with workflow metadata found.</p>
                </div>
            `;
            return;
        }
        
        let html = '<div class="workflow-list">';
        
        sortedWorkflows.forEach(workflowName => {
            const files = workflowGroups[workflowName];
            const fileCount = files.length;
            
            html += `
                <div class="workflow-group">
                    <div class="workflow-header">
                        <i class="fa-solid fa-chevron-right toggle-icon"></i>
                        <div class="workflow-name">${this.escapeHtml(workflowName)}</div>
                        <div class="workflow-count">${fileCount} file${fileCount !== 1 ? 's' : ''}</div>
                    </div>
                    <div class="workflow-content">
                        <div class="files-grid">
                            ${files.map(file => this.buildFileTile(file)).join('')}
                        </div>
                    </div>
                </div>
            `;
        });
        
        html += '</div>';
        
        container.innerHTML = html;
        
        // Bind toggle handlers
        container.querySelectorAll('.workflow-header').forEach(header => {
            header.addEventListener('click', () => {
                const group = header.closest('.workflow-group');
                group.classList.toggle('expanded');
            });
        });
        
        // Bind click handlers for file tiles
        container.querySelectorAll('.file-tile').forEach(tile => {
            tile.addEventListener('click', (e) => {
                // Ignore if clicking on action buttons
                if (e.target.closest('.file-action-btn')) return;
                
                const filePath = tile.dataset.path;
                const isDir = tile.dataset.isDir === 'true';
                
                if (isDir && !this.filesRecursive) {
                    this.navigateToFolder(filePath);
                } else if (!isDir) {
                    this.previewFile(filePath);
                }
            });
            
            tile.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                this.showFileContextMenu(e, tile.dataset.path, tile.dataset.name);
            });
        });
        
        // Bind load workflow buttons
        container.querySelectorAll('.load-workflow-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                
                // Check if ComfyUI is running
                if (btn.dataset.comfyReady !== 'true') {
                    const shouldLaunch = await this.showConfirm({
                        title: 'ComfyUI Not Running',
                        message: 'Loading a workflow requires ComfyUI to be running. Would you like to launch ComfyUI with your default profile?',
                        type: 'info',
                        confirmText: 'Launch ComfyUI',
                        cancelText: 'Cancel'
                    });
                    
                    if (shouldLaunch) {
                        // Store the workflow path to load after ComfyUI starts
                        this.pendingWorkflowPath = btn.dataset.path;
                        await this.launchDefaultProfile();
                    }
                    return;
                }
                
                this.loadWorkflowFromFile(btn.dataset.path);
            });
        });
    }
    
    buildFileTile(file) {
        const isImage = file.type === 'image';
        const isVideo = file.type === 'video';
        const isAudio = file.type === 'audio';
        const isFolder = file.is_dir;
        const hasWorkflow = !isFolder && file.workflow && file.workflow !== 'none' && file.workflow !== 'No Workflow';
        
        let thumbnailContent = '';
        
        if (isFolder) {
            thumbnailContent = `<i class="fa-solid fa-folder file-icon folder-icon"></i>`;
        } else if (isImage) {
            const thumbUrl = `${this.apiBase}/api/files/thumbnail/${this.filesFolder}/${file.path}`;
            thumbnailContent = `<img src="${thumbUrl}" alt="${this.escapeHtml(file.name)}" loading="lazy" onerror="this.style.display='none'; this.parentElement.innerHTML='<i class=\\'fa-solid fa-image file-icon\\'></i>';">`;
        } else if (isVideo) {
            thumbnailContent = `
                <i class="fa-solid fa-film file-icon video-icon"></i>
                <span class="file-type-badge">${file.extension?.substring(1) || 'vid'}</span>
            `;
        } else if (isAudio) {
            thumbnailContent = `
                <i class="fa-solid fa-music file-icon audio-icon"></i>
                <span class="file-type-badge">${file.extension?.substring(1) || 'aud'}</span>
            `;
        } else {
            const iconMap = {
                '.json': 'fa-solid fa-code json-icon',
                '.txt': 'fa-solid fa-file-lines text-icon',
                '.py': 'fa-brands fa-python python-icon',
                '.js': 'fa-brands fa-js js-icon',
                '.safetensors': 'fa-solid fa-cube model-icon',
                '.ckpt': 'fa-solid fa-cube model-icon',
                '.pt': 'fa-solid fa-cube model-icon',
            };
            const iconClass = iconMap[file.extension] || 'fa-solid fa-file';
            thumbnailContent = `<i class="${iconClass} file-icon"></i>`;
        }
        
        const dateStr = file.modified ? new Date(file.modified * 1000).toLocaleDateString() : '-';
        const sizeStr = isFolder ? '-' : this.formatBytes(file.size || 0);
        const workflowStr = isFolder ? '-' : (file.workflow || '-');
        
        // Load workflow button for PNG files (they can all have workflows)
        const isPng = file.extension?.toLowerCase() === '.png';
        const canHaveWorkflow = isPng && !isFolder;
        const isComfyRunning = this.comfyServerReady;
        const loadWorkflowBtn = canHaveWorkflow ? `
            <button class="file-action-btn load-workflow-btn ${!isComfyRunning ? 'disabled' : ''} ${hasWorkflow ? 'has-workflow' : ''}" 
                    data-path="${this.escapeHtml(file.path)}" 
                    data-comfy-ready="${isComfyRunning}"
                    title="${hasWorkflow ? (isComfyRunning ? 'Load Workflow in ComfyUI' : 'ComfyUI not running') : 'Try to load workflow'}">
                <i class="fa-solid fa-diagram-project"></i>
            </button>
        ` : '';
        
        return `
            <div class="file-tile ${isFolder ? 'is-folder' : ''}" data-path="${this.escapeHtml(file.path)}" data-name="${this.escapeHtml(file.name)}" data-is-dir="${file.is_dir}" data-workflow="${hasWorkflow}">
                <div class="file-thumbnail">
                    ${thumbnailContent}
                </div>
                <div class="file-info">
                    <div class="file-name" title="${this.escapeHtml(file.name)}">${this.escapeHtml(file.name)}</div>
                    <div class="file-meta">
                        <span class="file-date">${dateStr}</span>
                        <span class="file-size">${sizeStr}</span>
                        <span class="file-workflow ${hasWorkflow ? 'has-workflow' : ''}">${this.escapeHtml(workflowStr)}</span>
                    </div>
                </div>
                <div class="file-actions">
                    ${loadWorkflowBtn}
                </div>
            </div>
        `;
    }
    
    navigateToFolder(folderPath) {
        if (folderPath === '..') {
            // Go up one level
            const parts = this.filesSubfolder.split('/').filter(p => p);
            parts.pop();
            this.filesSubfolder = parts.join('/');
        } else {
            this.filesSubfolder = folderPath;
        }
        this.loadFilesTab();
    }
    
    async handlePreviewWorkflowClick(filePath) {
        // Close the preview modal
        document.querySelector('.file-preview-modal')?.remove();
        
        // Check if ComfyUI is running
        if (!this.comfyServerReady) {
            const shouldLaunch = await this.showConfirm({
                title: 'ComfyUI Not Running',
                message: 'Loading a workflow requires ComfyUI to be running. Would you like to launch ComfyUI with your default profile?',
                type: 'info',
                confirmText: 'Launch ComfyUI',
                cancelText: 'Cancel'
            });
            
            if (shouldLaunch) {
                this.pendingWorkflowPath = filePath;
                await this.launchDefaultProfile();
            }
            return;
        }
        
        this.loadWorkflowFromFile(filePath);
    }
    
    async loadWorkflowFromFile(filePath) {
        try {
            this.log(`Loading workflow from ${filePath}...`, 'info');
            
            // Get workflow data from the image
            const response = await fetch(`${this.apiBase}/api/files/workflow/${this.filesFolder}/${filePath}`);
            const data = await response.json();
            
            if (!data.success) {
                this.showToast('error', data.message || 'Failed to load workflow');
                this.log(`Failed to load workflow: ${data.message}`, 'error');
                return;
            }
            
            // Check if ComfyUI is running
            if (!this.comfyServerReady) {
                this.showToast('warning', 'ComfyUI is not running. Start it first to load workflows.');
                return;
            }
            
            // Load workflow into ComfyUI via its API
            const comfyUrl = this.settings.comfyUrl || 'http://127.0.0.1:8188';
            
            // ComfyUI expects workflow to be loaded via the graph API
            // We'll open ComfyUI with the workflow in localStorage, then redirect
            localStorage.setItem('mfconductor_pending_workflow', JSON.stringify(data.workflow));
            
            // Open ComfyUI
            window.open(comfyUrl, '_blank');
            
            this.showToast('success', 'Workflow loaded! Opening ComfyUI...');
            this.log('Workflow loaded and ComfyUI opened', 'success');
            
            // Note: To fully integrate, ComfyUI would need to check for this localStorage item
            // Alternative: Use ComfyUI's /api endpoint if available
        } catch (error) {
            this.showToast('error', 'Failed to load workflow');
            this.log(`Error loading workflow: ${error.message}`, 'error');
        }
    }
    
    async previewFile(filePath) {
        const file = this.filesData.find(f => f.path === filePath);
        if (!file) return;
        
        if (file.type !== 'image' && file.type !== 'video') {
            // Open in explorer for non-previewable files
            this.openFileLocation(filePath);
            return;
        }
        
        // Get navigable files (images and videos only)
        const mediaFiles = this.filesData.filter(f => !f.is_dir && (f.type === 'image' || f.type === 'video'));
        const currentIndex = mediaFiles.findIndex(f => f.path === filePath);
        
        // Store for navigation
        this.previewMediaFiles = mediaFiles;
        this.previewCurrentIndex = currentIndex;
        
        this.showPreviewModal(file);
    }
    
    showPreviewModal(file) {
        // Remove existing modal
        document.querySelector('.file-preview-modal')?.remove();
        
        const filePath = file.path;
        const isPng = file.extension?.toLowerCase() === '.png';
        const hasDetectedWorkflow = file.workflow && file.workflow !== '-' && file.workflow !== 'No Workflow';
        
        // All PNGs can potentially have workflows
        const canHaveWorkflow = isPng;
        
        const hasPrev = this.previewCurrentIndex > 0;
        const hasNext = this.previewCurrentIndex < this.previewMediaFiles.length - 1;
        
        const modal = document.createElement('div');
        modal.className = 'file-preview-modal';
        modal.innerHTML = `
            ${hasPrev ? `
                <button class="file-preview-nav prev" title="Previous (←)">
                    <i class="fa-solid fa-chevron-left"></i>
                </button>
            ` : ''}
            ${hasNext ? `
                <button class="file-preview-nav next" title="Next (→)">
                    <i class="fa-solid fa-chevron-right"></i>
                </button>
            ` : ''}
            <button class="file-preview-close" title="Close (Esc)">
                <i class="fa-solid fa-times"></i>
            </button>
            <div class="file-preview-content">
                ${file.type === 'image' 
                    ? `<img src="${this.apiBase}/api/files/thumbnail/${this.filesFolder}/${filePath}" alt="${this.escapeHtml(file.name)}">`
                    : `<video src="${this.apiBase}/api/files/serve/${this.filesFolder}/${filePath}" controls autoplay></video>`
                }
                <div class="file-preview-info">
                    <span class="preview-filename">${this.escapeHtml(file.name)}</span>
                    <span class="preview-meta">
                        <span>${this.formatBytes(file.size)}</span>
                        <span class="preview-counter">${this.previewCurrentIndex + 1} / ${this.previewMediaFiles.length}</span>
                        ${hasDetectedWorkflow ? `<span class="preview-workflow">${this.escapeHtml(file.workflow)}</span>` : ''}
                    </span>
                    <div class="file-preview-actions">
                        ${canHaveWorkflow ? `
                            <button class="btn btn-sm ${this.comfyServerReady ? 'btn-success' : 'btn-glass'}" 
                                    id="preview-open-workflow"
                                    data-path="${this.escapeHtml(filePath)}"
                                    title="${this.comfyServerReady ? 'Load workflow in ComfyUI' : 'ComfyUI not running'}">
                                <i class="fa-solid fa-diagram-project"></i> Open Workflow
                            </button>
                        ` : ''}
                        <button class="btn btn-sm btn-glass" id="preview-open-location" data-path="${this.escapeHtml(filePath)}">
                            <i class="fa-solid fa-folder-open"></i> Open Location
                        </button>
                        <button class="btn btn-sm btn-danger" id="preview-delete" data-path="${this.escapeHtml(filePath)}" data-name="${this.escapeHtml(file.name)}">
                            <i class="fa-solid fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Bind navigation
        const prevBtn = modal.querySelector('.file-preview-nav.prev');
        const nextBtn = modal.querySelector('.file-preview-nav.next');
        
        if (prevBtn) {
            prevBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.navigatePreview(-1);
            });
        }
        
        if (nextBtn) {
            nextBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.navigatePreview(1);
            });
        }
        
        // Bind action buttons
        const workflowBtn = modal.querySelector('#preview-open-workflow');
        if (workflowBtn) {
            workflowBtn.addEventListener('click', () => {
                this.handlePreviewWorkflowClick(workflowBtn.dataset.path);
            });
        }
        
        const openLocationBtn = modal.querySelector('#preview-open-location');
        if (openLocationBtn) {
            openLocationBtn.addEventListener('click', () => {
                this.openFileLocation(openLocationBtn.dataset.path);
            });
        }
        
        const deleteBtn = modal.querySelector('#preview-delete');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', () => {
                this.deleteFileWithConfirm(deleteBtn.dataset.path, deleteBtn.dataset.name);
            });
        }
        
        // Close handlers
        modal.querySelector('.file-preview-close').addEventListener('click', () => this.closePreviewModal());
        modal.addEventListener('click', (e) => {
            if (e.target === modal) this.closePreviewModal();
        });
        
        // Keyboard handler
        this.previewKeyHandler = (e) => {
            if (e.key === 'Escape') {
                this.closePreviewModal();
            } else if (e.key === 'ArrowLeft' && hasPrev) {
                this.navigatePreview(-1);
            } else if (e.key === 'ArrowRight' && hasNext) {
                this.navigatePreview(1);
            }
        };
        document.addEventListener('keydown', this.previewKeyHandler);
    }
    
    navigatePreview(direction) {
        const newIndex = this.previewCurrentIndex + direction;
        if (newIndex >= 0 && newIndex < this.previewMediaFiles.length) {
            this.previewCurrentIndex = newIndex;
            const newFile = this.previewMediaFiles[newIndex];
            this.showPreviewModal(newFile);
        }
    }
    
    closePreviewModal() {
        document.querySelector('.file-preview-modal')?.remove();
        if (this.previewKeyHandler) {
            document.removeEventListener('keydown', this.previewKeyHandler);
            this.previewKeyHandler = null;
        }
    }
    
    showFileContextMenu(event, filePath, fileName) {
        // Remove any existing context menu
        document.querySelectorAll('.file-context-menu').forEach(m => m.remove());
        
        const menu = document.createElement('div');
        menu.className = 'file-context-menu absolute bg-card border border-border-subtle rounded-lg shadow-xl py-1 z-50';
        menu.style.left = `${event.clientX}px`;
        menu.style.top = `${event.clientY}px`;
        menu.innerHTML = `
            <button class="w-full px-4 py-2 text-left text-sm text-slate-300 hover:bg-white/10 flex items-center gap-2" data-action="open">
                <i class="fa-solid fa-folder-open w-4"></i> Open Location
            </button>
            <button class="w-full px-4 py-2 text-left text-sm text-red-400 hover:bg-white/10 flex items-center gap-2" data-action="delete">
                <i class="fa-solid fa-trash w-4"></i> Delete
            </button>
        `;
        
        document.body.appendChild(menu);
        
        menu.querySelector('[data-action="open"]').addEventListener('click', () => {
            this.openFileLocation(filePath);
            menu.remove();
        });
        
        menu.querySelector('[data-action="delete"]').addEventListener('click', () => {
            this.deleteFileWithConfirm(filePath, fileName);
            menu.remove();
        });
        
        // Close on click outside
        setTimeout(() => {
            document.addEventListener('click', function closeMenu(e) {
                if (!menu.contains(e.target)) {
                    menu.remove();
                    document.removeEventListener('click', closeMenu);
                }
            });
        }, 0);
    }
    
    async openFileLocation(filePath = '') {
        try {
            const response = await fetch(`${this.apiBase}/api/files/open-location`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder: this.filesFolder,
                    path: filePath
                })
            });
            const data = await response.json();
            if (!data.success) {
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.showToast('error', 'Failed to open folder');
        }
    }
    
    async deleteFileWithConfirm(filePath, fileName) {
        // Close preview modal if open
        document.querySelectorAll('.file-preview-modal').forEach(m => m.remove());
        
        const confirmed = await this.showConfirm({
            title: 'Delete File?',
            message: `Are you sure you want to delete "${fileName}"? This cannot be undone.`,
            type: 'danger',
            confirmText: 'Delete'
        });
        
        if (!confirmed) return;
        
        try {
            const response = await fetch(`${this.apiBase}/api/files/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder: this.filesFolder,
                    path: filePath
                })
            });
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', `Deleted: ${fileName}`);
                this.log(`Deleted file: ${fileName}`, 'success');
                await this.loadFilesTab();
            } else {
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.showToast('error', 'Failed to delete file');
        }
    }
    
    applyFilesPreferences() {
        // Apply folder button state
        document.querySelectorAll('.folder-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.folder === this.filesFolder);
        });
        
        // Apply recursive button state
        const recursiveBtn = document.getElementById('files-recursive-btn');
        if (recursiveBtn) {
            recursiveBtn.classList.toggle('active', this.filesRecursive);
        }
        
        // Apply view mode
        this.updateViewToggleButtons();
        
        // Apply sort select
        const sortSelect = document.getElementById('files-sort');
        if (sortSelect) {
            sortSelect.value = this.filesSortBy;
        }
        
        // Apply sort direction icon
        const sortDirBtn = document.getElementById('files-sort-dir');
        if (sortDirBtn) {
            const icon = sortDirBtn.querySelector('i');
            if (icon) {
                icon.className = this.filesSortDir === 'desc' 
                    ? 'fa-solid fa-arrow-down-short-wide' 
                    : 'fa-solid fa-arrow-up-short-wide';
            }
        }
    }
    
    updateViewToggleButtons() {
        const gridViewBtn = document.getElementById('files-view-grid');
        const listViewBtn = document.getElementById('files-view-list');
        const workflowViewBtn = document.getElementById('files-view-workflow');
        
        [gridViewBtn, listViewBtn, workflowViewBtn].forEach(btn => {
            if (btn) {
                 btn.classList.remove('active', 'bg-accent-primary', 'text-white');
            }
        });
        
        if (this.filesViewMode === 'grid' && gridViewBtn) gridViewBtn.classList.add('active', 'bg-accent-primary', 'text-white');
        if (this.filesViewMode === 'list' && listViewBtn) listViewBtn.classList.add('active', 'bg-accent-primary', 'text-white');
        if (this.filesViewMode === 'workflow' && workflowViewBtn) workflowViewBtn.classList.add('active', 'bg-accent-primary', 'text-white');
    }

    bindFilesEvents() {
        // Apply loaded preferences to UI
        this.applyFilesPreferences();
        
        // Folder selector buttons
        document.querySelectorAll('.folder-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.folder-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                this.filesFolder = btn.dataset.folder;
                this.filesSubfolder = '';
                this.loadFilesTab();
                this.saveUserPreferences();
            });
        });
        
        // Recursive toggle
        const recursiveBtn = document.getElementById('files-recursive-btn');
        if (recursiveBtn) {
            recursiveBtn.addEventListener('click', () => {
                this.filesRecursive = !this.filesRecursive;
                recursiveBtn.classList.toggle('active', this.filesRecursive);
                this.filesSubfolder = ''; // Reset subfolder when toggling
                this.loadFilesTab();
                this.saveUserPreferences();
            });
        }
        
        // Search
        const searchInput = document.getElementById('files-search');
        if (searchInput) {
            searchInput.addEventListener('input', debounce(() => {
                this.filesSearch = searchInput.value;
                this.loadFilesTab();
            }, 300));
        }
        
        // Sort
        const sortSelect = document.getElementById('files-sort');
        if (sortSelect) {
            sortSelect.addEventListener('change', () => {
                this.filesSortBy = sortSelect.value;
                this.loadFilesTab();
                this.saveUserPreferences();
            });
        }
        
        // Sort direction
        const sortDirBtn = document.getElementById('files-sort-dir');
        if (sortDirBtn) {
            sortDirBtn.addEventListener('click', () => {
                this.filesSortDir = this.filesSortDir === 'desc' ? 'asc' : 'desc';
                const icon = sortDirBtn.querySelector('i');
                if (icon) {
                    icon.className = this.filesSortDir === 'desc' 
                        ? 'fa-solid fa-arrow-down-short-wide' 
                        : 'fa-solid fa-arrow-up-short-wide';
                }
                this.loadFilesTab();
                this.saveUserPreferences();
            });
        }
        
        // Type filter
        const typeFilter = document.getElementById('files-type-filter');
        if (typeFilter) {
            typeFilter.addEventListener('change', () => {
                this.filesTypeFilter = typeFilter.value;
                this.loadFilesTab();
            });
        }
        
        // View toggle
        const gridViewBtn = document.getElementById('files-view-grid');
        const listViewBtn = document.getElementById('files-view-list');
        const workflowViewBtn = document.getElementById('files-view-workflow');
        
        if (gridViewBtn) {
            gridViewBtn.addEventListener('click', () => {
                this.filesViewMode = 'grid';
                this.updateViewToggleButtons();
                this.renderFilesGrid();
                this.saveUserPreferences();
            });
        }
        
        if (listViewBtn) {
            listViewBtn.addEventListener('click', () => {
                this.filesViewMode = 'list';
                this.updateViewToggleButtons();
                this.renderFilesGrid();
                this.saveUserPreferences();
            });
        }
        
        if (workflowViewBtn) {
            workflowViewBtn.addEventListener('click', () => {
                this.filesViewMode = this.filesViewMode === 'workflow' ? 'grid' : 'workflow';
                this.updateViewToggleButtons();
                this.renderFilesGrid();
                this.saveUserPreferences();
            });
        }
        
        // Refresh
        const refreshBtn = document.getElementById('files-refresh-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => this.loadFilesTab());
        }
        
        // Open folder
        const openFolderBtn = document.getElementById('files-open-folder-btn');
        if (openFolderBtn) {
            openFolderBtn.addEventListener('click', () => this.openFileLocation());
        }
    }
    
    // Packages Tab
    async loadPackagesTab() {
        const container = document.getElementById('packages-tab-list');
        const statsEl = document.getElementById('packages-tab-stats');
        if (!container) return;
        
        this.log('Loading installed packages...', 'info');
        container.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div><p>Loading packages...</p></div>';
        
        try {
            const response = await fetch(`${this.apiBase}/api/packages`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            
            const data = await response.json();
            
            if (data.success && data.packages) {
                this.installedPackages = data.packages.map(pkg => ({
                    ...pkg,
                    hasUpdate: false,
                    latestVersion: null
                }));
                this.packagesSort = 'name';
                this.packagesShowOutdated = false;
                this.renderPackagesTab();
                this.updatePackagesStats();
                this.log(`Loaded ${this.installedPackages.length} installed package${this.installedPackages.length !== 1 ? 's' : ''}`, 'success');
            } else {
                this.log('Could not load packages', 'error');
                container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted);">Could not load packages</div>';
            }
        } catch (error) {
            this.log(`Error loading packages: ${error.message}`, 'error');
            console.error('Error loading packages:', error);
            container.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text-muted);">Error: ${this.escapeHtml(error.message)}</div>`;
        }
    }
    
    updatePackagesStats() {
        const statsEl = document.getElementById('packages-tab-stats');
        const upgradeAllBtn = document.getElementById('packages-upgrade-all-btn');
        if (!this.installedPackages) return;
        
        const total = this.installedPackages.length;
        const outdated = this.installedPackages.filter(p => p.hasUpdate).length;
        
        if (statsEl) {
            statsEl.innerHTML = `
                <span class="packages-stat-badge">${total} packages</span>
                ${outdated > 0 ? `<span class="packages-stat-badge outdated">${outdated} outdated</span>` : ''}
            `;
        }
        
        // Show/hide upgrade all button
        if (upgradeAllBtn) {
            upgradeAllBtn.style.display = outdated > 0 ? 'inline-flex' : 'none';
        }
    }
    
    renderPackagesTab() {
        const container = document.getElementById('packages-tab-list');
        const searchInput = document.getElementById('packages-tab-search');
        if (!container || !this.installedPackages) return;
        
        const filter = searchInput?.value?.toLowerCase() || '';
        const showOutdated = document.getElementById('packages-show-outdated')?.checked || false;
        const sortBy = document.getElementById('packages-sort')?.value || 'name';
        const viewMode = this.packagesViewMode || 'list';
        
        let filtered = this.installedPackages.filter(pkg => {
            if (filter && !pkg.name.toLowerCase().includes(filter)) return false;
            if (showOutdated && !pkg.hasUpdate) return false;
            return true;
        });
        
        // Sort
        filtered.sort((a, b) => {
            if (sortBy === 'name') return a.name.localeCompare(b.name);
            if (sortBy === 'version') return (a.version || '').localeCompare(b.version || '');
            return 0;
        });
        
        // Set view mode class
        container.className = `packages-tab-list ${viewMode}-view`;
        
        if (filtered.length === 0) {
            container.innerHTML = `<div style="padding:40px;text-align:center;color:var(--text-muted);">
                ${showOutdated ? 'No outdated packages found' : 'No packages found'}
            </div>`;
            return;
        }
        
        container.innerHTML = filtered.map(pkg => {
            const isOutdated = pkg.hasUpdate;
            const pypiUrl = `https://pypi.org/project/${encodeURIComponent(pkg.name)}/`;
            const hasDesc = pkg.summary && pkg.summary.trim();
            return `
                <div class="package-item ${isOutdated ? 'outdated' : ''} ${hasDesc ? '' : 'no-desc'}" data-package="${this.escapeHtml(pkg.name)}">
                    <div class="package-info" onclick="app.togglePackageDetails('${this.escapeHtml(pkg.name)}')">
                        <div class="package-header">
                            <span class="package-name">${this.escapeHtml(pkg.name)}</span>
                            <span class="package-version ${isOutdated ? 'outdated' : ''}">${this.escapeHtml(pkg.version || 'unknown')}</span>
                            ${isOutdated ? `<span class="package-latest">Latest: ${this.escapeHtml(pkg.latestVersion)}</span>` : ''}
                            <span class="package-expand-icon">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                    <polyline points="6 9 12 15 18 9"/>
                                </svg>
                            </span>
                        </div>
                        <div class="package-summary">${hasDesc ? this.escapeHtml(pkg.summary) : '<span class="loading-desc">Click to load description...</span>'}</div>
                        <div class="package-meta">
                            <a href="${pypiUrl}" target="_blank" class="package-meta-item package-pypi-link" title="View on PyPI" onclick="event.stopPropagation()">
                                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                                    <polyline points="15 3 21 3 21 9"/>
                                    <line x1="10" y1="14" x2="21" y2="3"/>
                                </svg>
                                PyPI
                            </a>
                            ${pkg.location ? `
                                <span class="package-meta-item" title="${this.escapeHtml(pkg.location)}">
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
                                    </svg>
                                    ${this.escapeHtml(pkg.location.split(/[/\\]/).slice(-2).join('/'))}
                                </span>
                            ` : ''}
                        </div>
                    </div>
                    <div class="package-actions">
                        <button class="btn ${isOutdated ? 'btn-success' : 'btn-primary'} btn-sm package-upgrade-btn" onclick="app.checkAndUpgradePackage('${this.escapeHtml(pkg.name)}')" title="${isOutdated ? `Update available: ${pkg.latestVersion}` : 'Check for updates & upgrade'}">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                <path d="M12 19V5M5 12l7-7 7 7"/>
                            </svg>
                            ${isOutdated ? 'Update' : 'Upgrade'}
                        </button>
                        <button class="btn btn-secondary btn-sm" onclick="app.reinstallPackage('${this.escapeHtml(pkg.name)}')" title="Reinstall current version">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                <path d="M23 4v6h-6"/>
                                <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/>
                            </svg>
                        </button>
                        <button class="btn btn-danger btn-sm" onclick="app.uninstallPackage('${this.escapeHtml(pkg.name)}')" title="Uninstall">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                            </svg>
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    }
    
    async checkPackageUpdates() {
        const btn = document.getElementById('packages-check-updates-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<div class="loading-spinner" style="width:14px;height:14px;margin:0;"></div> Checking...';
        }
        
        this.showToast('info', 'Checking for package updates... (this may take a while)');
        this.log('Checking for package updates... (this may take a while)', 'info');
        
        try {
            const applyUpdates = (updates = []) => {
                const updateMap = new Map(
                    updates.map(update => [String(update.name || '').toLowerCase(), update])
                );
                
                this.installedPackages.forEach(pkg => {
                    const key = String(pkg.name || '').toLowerCase();
                    const update = updateMap.get(key);
                    if (update) {
                        pkg.hasUpdate = true;
                        pkg.latestVersion = update.latest_version;
                    } else {
                        pkg.hasUpdate = false;
                        pkg.latestVersion = null;
                    }
                });
                
                this.renderPackagesTab();
                this.updatePackagesStats();
                
                const count = updates.length;
                if (count > 0) {
                    this.log(`Update check complete: ${count} package${count > 1 ? 's' : ''} can be updated`, 'warning');
                    this.showToast('warning', `${count} package${count > 1 ? 's' : ''} can be updated`);
                } else {
                    this.log('Update check complete: All packages are up to date', 'success');
                    this.showToast('success', 'All packages are up to date');
                }
            };
            
            // Start the check (returns immediately with job_id)
            const startResponse = await fetch(`${this.apiBase}/api/packages/check-updates`, {
                method: 'POST'
            });
            
            const startData = await startResponse.json();
            
            if (!startData.success) {
                this.log(`Failed to start update check: ${startData.message || 'Unknown error'}`, 'error');
                this.showToast('error', startData.message || 'Failed to start update check');
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Check Updates';
                }
                return;
            }
            
            // Integrated mode returns results immediately (no job_id)
            if (!startData.job_id) {
                applyUpdates(startData.updates || []);
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Check Updates';
                }
                return;
            }
            
            const jobId = startData.job_id;
            this.log('Update check started (running in background)...', 'info');
            
            let pollCount = 0;
            
            // Poll for results
            const pollInterval = setInterval(async () => {
                try {
                    pollCount++;
                    if (pollCount % 5 === 0) { // Log progress every 10 seconds (5 polls * 2 seconds)
                        this.log('Still checking for updates...', 'info');
                    }
                    
                    const statusResponse = await fetch(`${this.apiBase}/api/packages/check-updates-status?job_id=${jobId}`);
                    const statusData = await statusResponse.json();
                    
                    if (statusData.status === 'running') {
                        // Still running, continue polling
                        return;
                    }
                    
                    // Done or error
                    clearInterval(pollInterval);
                    
                    if (statusData.success && statusData.updates) {
                        applyUpdates(statusData.updates);
                    } else {
                        this.log(`Update check failed: ${statusData.message || 'Unknown error'}`, 'error');
                        this.showToast('error', statusData.message || 'Failed to check updates');
                    }
                    
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Check Updates';
                    }
                } catch (error) {
                    clearInterval(pollInterval);
                    console.error('Error polling update status:', error);
                    this.log(`Error checking update status: ${error.message}`, 'error');
                    this.showToast('error', 'Error checking update status');
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Check Updates';
                    }
                }
            }, 2000); // Poll every 2 seconds
            
            // Timeout after 3 minutes
            setTimeout(() => {
                clearInterval(pollInterval);
                if (btn && btn.disabled) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Check Updates';
                }
                this.log('Update check timed out. Try checking individual packages instead.', 'warning');
                this.showToast('warning', 'Update check is taking longer than expected. Try checking individual packages.');
            }, 180000);
            
        } catch (error) {
            console.error('Error checking updates:', error);
            this.log(`Failed to check updates: ${error.message}`, 'error');
            this.showToast('error', `Failed to check updates: ${error.message}`);
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="fa-solid fa-rotate"></i> Check Updates';
            }
        }
    }
    
    async checkAndUpgradePackage(packageName) {
        const item = document.querySelector(`.package-item[data-package="${packageName}"]`);
        const upgradeBtn = item?.querySelector('.package-upgrade-btn');
        
        if (upgradeBtn) {
            upgradeBtn.disabled = true;
            upgradeBtn.innerHTML = '<div class="loading-spinner" style="width:12px;height:12px;margin:0;"></div> Checking...';
        }
        
        this.showToast('info', `Checking ${packageName} for updates...`);
        this.log(`Checking for updates: ${packageName}...`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/packages/check-single`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: packageName })
            });
            
            const data = await response.json();
            console.log('Package check response:', data);
            
            if (data.success) {
                const pkg = this.installedPackages.find(p => p.name === packageName);
                
                if (data.has_update) {
                    const versions = data.available_versions || [data.latest_version];
                    this.log(`${packageName}: ${data.current_version} → ${data.latest_version} (${versions.length} versions available)`, 'warning');
                    this.showToast('success', `Update found! ${data.current_version} → ${data.latest_version}`);
                    
                    if (pkg) {
                        pkg.hasUpdate = true;
                        pkg.latestVersion = data.latest_version;
                        pkg.availableVersions = versions;
                    }
                    
                    // Restore button before showing modal
                    if (upgradeBtn) {
                        upgradeBtn.disabled = false;
                        upgradeBtn.classList.remove('btn-primary');
                        upgradeBtn.classList.add('btn-success');
                        upgradeBtn.innerHTML = `
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                <path d="M12 19V5M5 12l7-7 7 7"/>
                            </svg>
                            Update
                        `;
                    }
                    
                    // Prompt for version selection
                    await this.promptUpgradeVersion(packageName, data.current_version, versions);
                    this.renderPackagesTab();
                    this.updatePackagesStats();
                } else {
                    if (pkg) pkg.hasUpdate = false;
                    this.log(`${packageName} is already at the latest version (${data.current_version})`, 'success');
                    this.showToast('success', `${packageName} is already at the latest version`);
                    this.renderPackagesTab();
                    this.updatePackagesStats();
                }
            } else {
                this.log(`Failed to check ${packageName}: ${data.message || 'Unknown error'}`, 'error');
                this.showToast('error', data.message || `Failed to check ${packageName}`);
                // Restore button on error
                if (upgradeBtn) {
                    upgradeBtn.disabled = false;
                    upgradeBtn.innerHTML = `
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M12 19V5M5 12l7-7 7 7"/>
                        </svg>
                        Upgrade
                    `;
                }
            }
        } catch (error) {
            console.error('Error checking package:', error);
            this.log(`Error checking ${packageName}: ${error.message}`, 'error');
            this.showToast('error', `Failed to check ${packageName}: ${error.message}`);
            // Restore button on error
            if (upgradeBtn) {
                upgradeBtn.disabled = false;
                upgradeBtn.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path d="M12 19V5M5 12l7-7 7 7"/>
                    </svg>
                    Upgrade
                `;
            }
        }
    }
    
    async checkSinglePackageUpdate(packageName) {
        const item = document.querySelector(`.package-item[data-package="${packageName}"]`);
        const checkBtn = item?.querySelector('.package-check-btn');
        
        if (checkBtn) {
            checkBtn.disabled = true;
            checkBtn.innerHTML = '<div class="loading-spinner" style="width:12px;height:12px;margin:0;"></div>';
        }
        
        this.log(`Checking for updates: ${packageName}...`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/packages/check-single`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: packageName })
            });
            
            const data = await response.json();
            
            if (data.success) {
                const pkg = this.installedPackages.find(p => p.name === packageName);
                if (pkg) {
                    if (data.has_update) {
                        pkg.hasUpdate = true;
                        pkg.latestVersion = data.latest_version;
                        pkg.availableVersions = data.available_versions || [data.latest_version];
                        this.log(`${packageName} has update available: ${data.current_version} → ${data.latest_version}`, 'warning');
                        this.showToast('info', `Update available for ${packageName}`);
                        
                        // Restore button before showing modal
                        if (checkBtn) {
                            checkBtn.disabled = false;
                            checkBtn.innerHTML = '<i class="fa-solid fa-clock-rotate-left"></i>';
                        }
                        
                        // Prompt for version selection
                        await this.promptUpgradeVersion(packageName, data.current_version, pkg.availableVersions);
                    } else {
                        pkg.hasUpdate = false;
                        this.log(`${packageName} is up to date (${data.current_version})`, 'success');
                        this.showToast('success', `${packageName} is up to date`);
                    }
                    this.renderPackagesTab();
                    this.updatePackagesStats();
                }
            } else {
                this.log(`Failed to check ${packageName}: ${data.message || 'Unknown error'}`, 'error');
                this.showToast('error', data.message || `Failed to check ${packageName}`);
            }
        } catch (error) {
            console.error('Error checking package:', error);
            this.log(`Error checking ${packageName}: ${error.message}`, 'error');
            this.showToast('error', `Failed to check ${packageName}`);
        } finally {
            if (checkBtn) {
                checkBtn.disabled = false;
                checkBtn.innerHTML = '<i class="fa-solid fa-clock-rotate-left"></i>';
            }
        }
    }
    
    async jumpToPackage(packageName) {
        // Switch to the packages tab
        await this.switchMainTab('packages');
        
        // Set the search input to the package name
        const searchInput = document.getElementById('packages-tab-search');
        if (searchInput) {
            searchInput.value = packageName;
        }
        
        // Re-render to filter
        this.renderPackagesTab();
        
        // Find and highlight the package row
        setTimeout(() => {
            const packageRow = document.querySelector(`.package-item[data-package="${packageName}"]`);
            if (packageRow) {
                // Scroll into view
                packageRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
                
                // Add highlight animation
                packageRow.classList.add('package-highlight');
                setTimeout(() => {
                    packageRow.classList.remove('package-highlight');
                }, 2000);
            } else {
                this.showToast('info', `Package "${packageName}" not found in installed packages`);
            }
        }, 100);
    }
    
    openPackageInstallModal() {
        const modal = document.getElementById('package-install-modal');
        const input = document.getElementById('package-name-input');
        if (modal) {
            modal.classList.add('show');
            if (input) {
                input.value = '';
                input.focus();
            }
        }
    }
    
    closePackageInstallModal() {
        const modal = document.getElementById('package-install-modal');
        if (modal) modal.classList.remove('show');
    }
    
    async installPackageFromModal() {
        const input = document.getElementById('package-name-input');
        const packageName = input?.value?.trim();
        
        if (!packageName) {
            this.showToast('error', 'Please enter a package name');
            return;
        }
        
        this.closePackageInstallModal();
        await this.installPackage(packageName);
    }
    
    async installPackage(packageName) {
        this.showToast('info', `Installing ${packageName}...`);
        this.log(`pip install ${packageName}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/packages/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: packageName })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', `Successfully installed ${packageName}`);
                this.log(data.message || `Installed ${packageName}`, 'success');
                await this.loadPackagesTab();
            } else {
                this.showToast('error', data.message || `Failed to install ${packageName}`);
                this.log(data.message || 'Installation failed', 'error');
            }
        } catch (error) {
            console.error('Error installing package:', error);
            this.showToast('error', `Failed to install ${packageName}`);
            this.log(`Error: ${error.message}`, 'error');
        }
    }
    
    async uninstallPackage(packageName) {
        const confirmed = await this.showConfirm({
            title: `Uninstall "${packageName}"?`,
            message: `This may break nodes that depend on this package.`,
            type: 'warning',
            confirmText: 'Uninstall',
            confirmClass: 'btn-danger'
        });
        if (!confirmed) return;
        
        const item = document.querySelector(`.package-item[data-package="${packageName}"]`);
        if (item) item.classList.add('updating');
        
        this.showToast('info', `Uninstalling ${packageName}...`);
        this.log(`pip uninstall ${packageName}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/packages/uninstall`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: packageName })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', `Successfully uninstalled ${packageName}`);
                this.log(data.message || `Uninstalled ${packageName}`, 'success');
                await this.loadPackagesTab();
            } else {
                this.showToast('error', data.message || `Failed to uninstall ${packageName}`);
                this.log(data.message || 'Uninstall failed', 'error');
                if (item) item.classList.remove('updating');
            }
        } catch (error) {
            console.error('Error uninstalling package:', error);
            this.showToast('error', `Failed to uninstall ${packageName}`);
            this.log(`Error: ${error.message}`, 'error');
            if (item) item.classList.remove('updating');
        }
    }
    
    async promptUpgradeVersion(packageName, currentVersion, availableVersions) {
        // If no versions available, show a simple upgrade confirmation
        if (!availableVersions || availableVersions.length === 0) {
            const pkg = this.installedPackages.find(p => p.name === packageName);
            if (pkg && pkg.latestVersion && pkg.latestVersion !== currentVersion) {
                // There's a latest version but no version list - offer to upgrade to latest
                const confirmed = await this.showConfirm({
                    title: `Upgrade ${packageName}?`,
                    message: `Upgrade from ${currentVersion} to ${pkg.latestVersion}?`,
                    type: 'info',
                    confirmText: 'Upgrade',
                    confirmClass: 'btn-success'
                });
                if (confirmed) {
                    await this.upgradePackage(packageName, pkg.latestVersion);
                }
            } else {
                this.showToast('info', `${packageName} is up to date`);
            }
            return;
        }
        
        // Create version options
        const versionOptions = availableVersions.map((ver, idx) => {
            const isLatest = idx === 0 ? ' (latest)' : '';
            return `
                <label class="version-radio-item">
                    <input type="radio" name="version" value="${this.escapeHtml(ver)}" ${idx === 0 ? 'checked' : ''}>
                    <span>${this.escapeHtml(ver)}${isLatest}</span>
                </label>
            `;
        }).join('');
        
        // Create and show modal
        const modal = document.createElement('div');
        modal.className = 'modal-overlay';
        modal.innerHTML = `
            <div class="modal-content" style="max-width: 400px;">
                <div class="modal-header">
                    <h3>Upgrade ${this.escapeHtml(packageName)}</h3>
                    <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">
                        <i class="fa-solid fa-times"></i>
                    </button>
                </div>
                <div class="modal-body">
                    <p class="text-slate-400 mb-2">Current version: <strong class="text-white">${this.escapeHtml(currentVersion)}</strong></p>
                    <p class="text-slate-400 mb-4">Select a version to upgrade to:</p>
                    
                    <div class="version-radio-list">
                        ${versionOptions}
                    </div>
                </div>
                <div class="modal-footer">
                    <button class="btn btn-glass" onclick="this.closest('.modal-overlay').remove()">Cancel</button>
                    <button class="btn btn-success" id="upgrade-version-confirm">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M12 19V5M5 12l7-7 7 7"/>
                        </svg>
                        Upgrade
                    </button>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Add show class after a frame to trigger animation
        requestAnimationFrame(() => {
            modal.classList.add('show');
        });
        
        // Handle confirm
        return new Promise((resolve) => {
            modal.querySelector('#upgrade-version-confirm').addEventListener('click', async () => {
                const selectedVersion = modal.querySelector('input[name="version"]:checked')?.value;
                modal.remove();
                
                if (selectedVersion) {
                    await this.upgradePackage(packageName, selectedVersion);
                }
                resolve();
            });
            
            // Handle close
            modal.querySelector('.modal-close')?.addEventListener('click', () => {
                modal.remove();
                resolve();
            });
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    modal.remove();
                    resolve();
                }
            });
        });
    }
    
    async upgradePackage(packageName, version = null) {
        const item = document.querySelector(`.package-item[data-package="${packageName}"]`);
        if (item) item.classList.add('updating');
        
        const versionText = version ? ` to ${version}` : '';
        this.showToast('info', `Upgrading ${packageName}${versionText}...`);
        this.log(`pip install --upgrade ${packageName}${version ? `==${version}` : ''}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/packages/upgrade`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: packageName, version: version })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', data.message || `Successfully upgraded ${packageName}`);
                this.log(data.message || `Upgraded ${packageName}`, 'success');
                await this.loadPackagesTab();
            } else {
                this.showToast('error', data.message || `Failed to upgrade ${packageName}`);
                this.log(data.message || 'Upgrade failed', 'error');
                if (item) item.classList.remove('updating');
            }
        } catch (error) {
            console.error('Error upgrading package:', error);
            this.showToast('error', `Failed to upgrade ${packageName}`);
            this.log(`Error: ${error.message}`, 'error');
            if (item) item.classList.remove('updating');
        }
    }
    
    async reinstallPackage(packageName) {
        const confirmed = await this.showConfirm({
            title: `Reinstall "${packageName}"?`,
            message: `This will force reinstall the package.`,
            type: 'info',
            confirmText: 'Reinstall'
        });
        if (!confirmed) return;
        
        const item = document.querySelector(`.package-item[data-package="${packageName}"]`);
        if (item) item.classList.add('updating');
        
        this.showToast('info', `Reinstalling ${packageName}...`);
        this.log(`pip install --force-reinstall ${packageName}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/packages/reinstall`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: packageName })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', `Successfully reinstalled ${packageName}`);
                this.log(data.message || `Reinstalled ${packageName}`, 'success');
                await this.loadPackagesTab();
            } else {
                this.showToast('error', data.message || `Failed to reinstall ${packageName}`);
                this.log(data.message || 'Reinstall failed', 'error');
                if (item) item.classList.remove('updating');
            }
        } catch (error) {
            console.error('Error reinstalling package:', error);
            this.showToast('error', `Failed to reinstall ${packageName}`);
            this.log(`Error: ${error.message}`, 'error');
            if (item) item.classList.remove('updating');
        }
    }
    
    async togglePackageDetails(packageName) {
        const item = document.querySelector(`.package-item[data-package="${packageName}"]`);
        if (!item) return;
        
        // Find the package in our data
        const pkg = this.installedPackages?.find(p => p.name === packageName);
        if (!pkg) return;
        
        // If we already have the summary, just toggle expanded state
        if (pkg.summary) {
            item.classList.toggle('expanded');
            return;
        }
        
        // Fetch package info from PyPI
        const summaryEl = item.querySelector('.package-summary');
        if (summaryEl) {
            summaryEl.innerHTML = '<span class="loading-desc">Loading description...</span>';
        }
        
        try {
            const response = await fetch(`https://pypi.org/pypi/${encodeURIComponent(packageName)}/json`);
            if (response.ok) {
                const data = await response.json();
                pkg.summary = data.info?.summary || 'No description available';
                pkg.homepage = data.info?.home_page || data.info?.project_url || '';
                pkg.author = data.info?.author || '';
                pkg.license = data.info?.license || '';
                
                if (summaryEl) {
                    summaryEl.textContent = pkg.summary;
                }
            } else {
                pkg.summary = 'Description not available';
                if (summaryEl) {
                    summaryEl.textContent = pkg.summary;
                }
            }
        } catch (error) {
            console.error('Error fetching package info:', error);
            pkg.summary = 'Could not load description';
            if (summaryEl) {
                summaryEl.textContent = pkg.summary;
            }
        }
        
        item.classList.toggle('expanded');
        item.classList.remove('no-desc');
    }
    
    async upgradeAllPackages() {
        const outdatedPackages = this.installedPackages?.filter(p => p.hasUpdate) || [];
        
        if (outdatedPackages.length === 0) {
            this.showToast('info', 'No packages to upgrade');
            return;
        }
        
        const confirmed = await this.showConfirm({
            title: `Upgrade ${outdatedPackages.length} package${outdatedPackages.length > 1 ? 's' : ''}?`,
            message: `This may take several minutes.`,
            type: 'info',
            confirmText: 'Upgrade All'
        });
        if (!confirmed) return;
        
        const btn = document.getElementById('packages-upgrade-all-btn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<div class="loading-spinner" style="width:14px;height:14px;margin:0;"></div> Upgrading...';
        }
        
        this.showToast('info', `Upgrading ${outdatedPackages.length} packages...`);
        this.log(`Upgrading ${outdatedPackages.length} packages...`, 'info');
        
        let successCount = 0;
        let failCount = 0;
        
        for (const pkg of outdatedPackages) {
            const item = document.querySelector(`.package-item[data-package="${pkg.name}"]`);
            if (item) item.classList.add('updating');
            
            try {
                this.log(`Upgrading ${pkg.name}...`, 'info');
                const response = await fetch(`${this.apiBase}/api/packages/upgrade`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ package_name: pkg.name })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    successCount++;
                    this.log(`Upgraded ${pkg.name}`, 'success');
                } else {
                    failCount++;
                    this.log(`Failed to upgrade ${pkg.name}: ${data.message}`, 'error');
                }
            } catch (error) {
                failCount++;
                this.log(`Error upgrading ${pkg.name}: ${error.message}`, 'error');
            }
        }
        
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                    <path d="M12 19V5M5 12l7-7 7 7"/>
                </svg>
                Upgrade All
            `;
        }
        
        if (failCount === 0) {
            this.showToast('success', `Successfully upgraded ${successCount} packages`);
        } else {
            this.showToast('warning', `Upgraded ${successCount}, failed ${failCount}`);
        }
        
        await this.loadPackagesTab();
    }
    
    // ==================== COMFYUI PROCESS MANAGEMENT ====================
    
    bindComfyControls() {
        // Launch button (transforms to "Go To Comfy" when running)
        const launchBtn = document.getElementById('launch-comfy-btn');
        if (launchBtn) {
            launchBtn.addEventListener('click', () => {
                if (this.comfyStatus === 'running') {
                    this.openComfyUI();
                } else {
                    this.launchComfyUI();
                }
            });
        }
        
        // Restart button
        const restartBtn = document.getElementById('restart-comfy-btn');
        if (restartBtn) {
            restartBtn.addEventListener('click', () => this.restartComfyUI());
        }
        
        // Stop button
        const stopBtn = document.getElementById('stop-comfy-btn');
        if (stopBtn) {
            stopBtn.addEventListener('click', () => this.stopComfyUI());
        }
        
        // Console controls
        const clearBtn = document.getElementById('console-clear-btn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => this.clearConsole());
        }
        
        const scrollCheckbox = document.getElementById('console-autoscroll-checkbox');
        if (scrollCheckbox) {
            // Sync initial state
            scrollCheckbox.checked = this.consoleAutoScroll;
            scrollCheckbox.addEventListener('change', () => {
                this.consoleAutoScroll = scrollCheckbox.checked;
                if (this.consoleAutoScroll) {
                    this.scrollConsoleToBottom();
                }
                this.saveUserPreferences();
            });
        }
        
        const copyBtn = document.getElementById('console-copy-btn');
        if (copyBtn) {
            copyBtn.addEventListener('click', () => this.copyConsoleOutput());
        }
        
        const exportBtn = document.getElementById('console-export-btn');
        if (exportBtn) {
            exportBtn.addEventListener('click', () => this.exportConsoleOutput());
        }
        
        // Command input
        const commandInput = document.getElementById('console-command-input');
        if (commandInput) {
            commandInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    this.runPythonCommand();
                }
            });
        }
        
        const runBtn = document.getElementById('console-run-btn');
        if (runBtn) {
            runBtn.addEventListener('click', () => this.runPythonCommand());
        }
    }
    
    updateComfyControls() {
        const launchBtn = document.getElementById('launch-comfy-btn');
        const restartBtn = document.getElementById('restart-comfy-btn');
        const stopBtn = document.getElementById('stop-comfy-btn');
        const statusEl = document.getElementById('comfy-status');
        
        // Find default profile
        this.defaultProfile = null;
        for (const [name, profile] of Object.entries(this.profiles)) {
            if (profile.is_default) {
                this.defaultProfile = name;
                break;
            }
        }
        
        const isRunning = this.comfyStatus === 'running';
        const isStarting = this.comfyStatus === 'starting';
        const isManaged = this.comfyManaged !== false;
        const serverReady = this.comfyServerReady;
        const isIntegrated = this.apiBase === '/mf_conductor';
        
        // In integrated mode, hide launch button and status indicator
        if (isIntegrated) {
            if (launchBtn) launchBtn.style.display = 'none';
            if (statusEl) statusEl.style.display = 'none';
            if (restartBtn) restartBtn.style.display = 'none';
            if (stopBtn) stopBtn.style.display = 'none';
            return;
        }
        
        // Standalone mode - show all controls
        if (launchBtn) launchBtn.style.display = '';
        if (statusEl) statusEl.style.display = '';
        if (restartBtn) restartBtn.style.display = '';
        if (stopBtn) stopBtn.style.display = '';
        
        // Update launch button - transforms to "Go To Comfy" only when server is actually ready
        if (launchBtn) {
            const port = this.comfyPort || 8188;
            if (isRunning && serverReady) {
                // Transform to "Go To Comfy" mode - server is confirmed ready
                launchBtn.disabled = false;
                launchBtn.classList.remove('btn-success');
                launchBtn.classList.add('btn-primary', 'comfy-ready', 'comfy-ready-blink');
                launchBtn.title = `ComfyUI is ready! Click to open at localhost:${port}`;
                launchBtn.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                        <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                        <polyline points="15 3 21 3 21 9"/>
                        <line x1="10" y1="14" x2="21" y2="3"/>
                    </svg>
                    Go To Comfy
                `;
            } else {
                // Normal "Launch ComfyUI" mode or "Launching..." mode
                launchBtn.classList.remove('btn-primary', 'comfy-ready');
                launchBtn.classList.add('btn-success');
                launchBtn.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                        <polygon points="5 3 19 12 5 21 5 3"/>
                    </svg>
                    ${isStarting ? 'Launching...' : 'Launch ComfyUI'}
                `;
                
                if (this.defaultProfile) {
                    launchBtn.disabled = isStarting;
                    launchBtn.title = isStarting 
                        ? 'ComfyUI is launching...' 
                        : `Launch ComfyUI with "${this.defaultProfile}" profile`;
                } else {
                    launchBtn.disabled = true;
                    launchBtn.title = 'Set a default profile first';
                }
            }
        }
        
        // Update restart/stop buttons - only enabled for managed processes
        if (restartBtn) {
            restartBtn.disabled = !(isRunning || isStarting) || !isManaged;
            if ((isRunning || isStarting) && !isManaged) {
                restartBtn.title = 'Cannot restart externally launched ComfyUI';
            } else {
                restartBtn.title = 'Restart ComfyUI';
            }
        }
        
        if (stopBtn) {
            stopBtn.disabled = !(isRunning || isStarting) || !isManaged;
            if ((isRunning || isStarting) && !isManaged) {
                stopBtn.title = 'Cannot stop externally launched ComfyUI';
            } else {
                stopBtn.title = 'Stop ComfyUI';
            }
        }
    }
    
    updateComfyStatus(status, message = null, managed = true, port = null) {
        const previousStatus = this.comfyStatus;
        this.comfyStatus = status;
        this.comfyManaged = managed;
        
        // Reset server ready flag when status changes away from running
        if (status !== 'running') {
            this.comfyServerReady = false;
        }
        
        // Preserve existing port if not provided, default to 8188 when running
        if (port !== null) {
            this.comfyPort = port;
        } else if (status === 'running' && !this.comfyPort) {
            this.comfyPort = 8188; // Default port
        } else if (status === 'stopped') {
            this.comfyPort = null;
        }
        
        const statusEl = document.getElementById('comfy-status');
        if (!statusEl) return;
        
        const indicator = statusEl.querySelector('.status-indicator');
        const text = statusEl.querySelector('.status-text');
        
        if (indicator) {
            indicator.className = 'status-indicator ' + status;
        }
        
        let statusText = message;
        if (!statusText) {
            if (status === 'stopped') {
                statusText = 'Stopped';
            } else if (status === 'starting') {
                statusText = 'Starting...';
            } else if (status === 'running') {
                if (this.comfyServerReady) {
                    // Server is confirmed ready
                    statusText = port ? `Ready :${port}` : 'Ready';
                } else {
                    // Process running but server not yet responding
                    statusText = 'Starting...';
                }
                if (!managed) {
                    statusText += ' (external)';
                }
            } else if (status === 'error') {
                statusText = 'Error';
            } else {
                statusText = status;
            }
        }
        
        if (text) {
            text.textContent = statusText;
        }
        
        this.updateComfyControls();
    }
    
    async checkComfyStatus() {
        try {
            const response = await fetch(`${this.apiBase}/api/comfy/status`);
            const data = await response.json();
            
            if (data.success) {
                this.updateComfyStatus(data.status, null, data.managed !== false, data.port);
                
                // Start polling if running and managed by us
                if ((data.status === 'running' || data.status === 'starting') && data.managed !== false) {
                    this.startConsolePolling();
                }
                
                // Check if server is actually ready (for both managed and external)
                if (data.status === 'running' && !this.comfyServerReady) {
                    this.checkComfyServerReady();
                }
                
                // Update console placeholder based on status
                if (data.status === 'running' && data.managed === false) {
                    this.showExternalComfyMessage(data.port);
                } else if (data.status === 'stopped') {
                    this.showStoppedMessage();
                }
            }
        } catch (error) {
            console.error('Error checking ComfyUI status:', error);
            // Show stopped message on error (couldn't reach API)
            this.showStoppedMessage();
        }
    }
    
    showStoppedMessage() {
        const output = document.getElementById('console-output');
        if (!output) return;
        
        // Only show placeholder if console is empty (no messages)
        const hasMessages = output.querySelectorAll('.console-line').length > 0;
        if (hasMessages) {
            return; // Don't clear existing messages
        }
        
        let placeholder = output.querySelector('.console-placeholder');
        if (!placeholder) {
            placeholder = document.createElement('div');
            placeholder.className = 'console-placeholder flex flex-col items-center justify-center h-full text-slate-500';
            output.appendChild(placeholder);
        }
        
        placeholder.innerHTML = `
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">
                <polyline points="4 17 10 11 4 5"/>
                <line x1="12" y1="19" x2="20" y2="19"/>
            </svg>
            <p>ComfyUI is not running</p>
            <p class="console-placeholder-hint">Click "Launch ComfyUI" to start</p>
        `;
    }
    
    showExternalComfyMessage(port) {
        const output = document.getElementById('console-output');
        if (!output) return;
        
        // Only show placeholder if console is empty (no messages)
        const hasMessages = output.querySelectorAll('.console-line').length > 0;
        if (hasMessages) {
            return; // Don't clear existing messages
        }
        
        // Check if we're in integrated mode (running inside ComfyUI)
        const isIntegratedMode = this.apiBase === '/mf_conductor';
        
        let placeholder = output.querySelector('.console-placeholder');
        
        // Create placeholder if it doesn't exist
        if (!placeholder) {
            placeholder = document.createElement('div');
            placeholder.className = 'console-placeholder flex flex-col items-center justify-center h-full text-slate-500';
            output.appendChild(placeholder);
        }
        
        if (isIntegratedMode) {
            placeholder.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                </svg>
                <p>Running in Integrated Mode</p>
                <p class="console-placeholder-hint">Console output is only available when using Standalone Mode.<br>
                To use console features, close ComfyUI and run <code>Launch_MFConductor.bat</code></p>
                <p class="console-placeholder-hint" style="margin-top: 12px;">
                    <strong>Command input below still works</strong> - you can run pip commands in the ComfyUI environment.
                </p>
            `;
        } else {
            placeholder.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">
                    <polyline points="4 17 10 11 4 5"/>
                    <line x1="12" y1="19" x2="20" y2="19"/>
                </svg>
                <p>ComfyUI is running externally on port ${port || 8188}</p>
                <p class="console-placeholder-hint">Console output is only available when launched from MF Conductor</p>
                <a href="http://127.0.0.1:${port || 8188}" target="_blank" class="btn btn-primary" style="margin-top: 16px;">
                    Open ComfyUI
                </a>
            `;
        }
    }
    
    async launchComfyUI() {
        if (!this.defaultProfile) {
            this.log('Cannot launch: No default profile set', 'error');
            this.showToast('error', 'Please set a default profile first');
            return;
        }
        
        // Check if already running
        if (this.comfyStatus === 'running' || this.comfyStatus === 'starting') {
            this.log('ComfyUI is already running', 'warning');
            this.showToast('warning', 'ComfyUI is already running');
            return;
        }
        
        // Switch to terminal page immediately
        this.switchMainTab('console');
        
        // Clear console and show splash screen (don't await - load in background)
        this.clearConsoleOutput();
        this.showSplashScreen(); // Non-blocking
        
        // Update button to "Launching..." immediately
        this.updateComfyStatus('starting');
        this.log(`Launching ComfyUI with profile "${this.defaultProfile}"...`, 'info');
        this.appendToConsole(`Launching ComfyUI with profile "${this.defaultProfile}"...`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/comfy/launch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ profile: this.defaultProfile })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', `Launching ${this.defaultProfile}...`);
                this.appendToConsole('ComfyUI process started', 'success');
                this.startConsolePolling();
                // Start checking if server is ready
                this.checkComfyServerReady();
            } else {
                this.updateComfyStatus('error');
                this.appendToConsole(`Failed to launch: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.updateComfyStatus('error');
            this.appendToConsole(`Error launching ComfyUI: ${error.message}`, 'error');
            this.showToast('error', 'Failed to launch ComfyUI');
        }
    }
    
    async stopComfyUI() {
        const confirmed = await this.showConfirm({
            title: 'Stop ComfyUI?',
            message: 'Are you sure you want to stop ComfyUI?',
            type: 'warning',
            confirmText: 'Stop'
        });
        if (!confirmed) return;
        
        this.log('Stopping ComfyUI...', 'info');
        this.appendToConsole('Stopping ComfyUI...', 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/comfy/stop`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log('ComfyUI stopped', 'success');
                this.updateComfyStatus('stopped');
                this.appendToConsole('ComfyUI stopped', 'success');
                this.stopConsolePolling();
                // Clear server ready check interval
                if (this.serverReadyCheckInterval) {
                    clearInterval(this.serverReadyCheckInterval);
                    this.serverReadyCheckInterval = null;
                }
                this.comfyServerReady = false;
            } else {
                this.log(`Failed to stop ComfyUI: ${data.message}`, 'error');
                this.appendToConsole(`Failed to stop: ${data.message}`, 'error');
            }
        } catch (error) {
            this.log(`Error stopping ComfyUI: ${error.message}`, 'error');
            this.appendToConsole(`Error stopping ComfyUI: ${error.message}`, 'error');
        }
    }
    
    async restartComfyUI() {
        this.log('Restarting ComfyUI...', 'info');
        this.appendToConsole('Restarting ComfyUI...', 'info');
        this.updateComfyStatus('starting');
        
        try {
            const response = await fetch(`${this.apiBase}/api/comfy/restart`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log('ComfyUI restart initiated', 'success');
                this.appendToConsole('ComfyUI restart initiated', 'success');
            } else {
                this.log(`Failed to restart ComfyUI: ${data.message}`, 'error');
                this.updateComfyStatus('error');
                this.appendToConsole(`Failed to restart: ${data.message}`, 'error');
            }
        } catch (error) {
            this.log(`Error restarting ComfyUI: ${error.message}`, 'error');
            this.updateComfyStatus('error');
            this.appendToConsole(`Error restarting ComfyUI: ${error.message}`, 'error');
        }
    }
    
    openComfyUI() {
        // Open immediately - don't wait for toast
        const port = this.comfyPort || 8188;
        const url = `http://localhost:${port}`;
        
        // Open in new tab immediately
        window.open(url, '_blank');
        
        // Show toast after (non-blocking)
        if (this.comfyServerReady) {
            this.showToast('success', `Opening ComfyUI at ${url}`);
        } else {
            this.showToast('warning', 'ComfyUI may still be loading...');
        }
    }
    
    // Console output management
    startConsolePolling() {
        if (this.consolePolling) return;
        
        this.consolePolling = setInterval(() => this.pollConsoleOutput(), 2000);
    }
    
    stopConsolePolling() {
        if (this.consolePolling) {
            clearInterval(this.consolePolling);
            this.consolePolling = null;
        }
    }
    
    async pollConsoleOutput() {
        try {
            const response = await fetch(`${this.apiBase}/api/comfy/output`);
            const data = await response.json();
            
            if (data.success) {
                // Update status
                if (data.status && data.status !== this.comfyStatus) {
                    this.updateComfyStatus(data.status);
                    
                    if (data.status === 'stopped') {
                        this.stopConsolePolling();
                    }
                }
                
                // Check if server is actually ready (only when running but not yet confirmed ready)
                if (data.status === 'running' && !this.comfyServerReady) {
                    // Poll more frequently when starting to detect when ready
                    this.checkComfyServerReady();
                    // Keep checking every 500ms until ready for fast detection
                    if (!this.serverReadyCheckInterval) {
                        this.serverReadyCheckInterval = setInterval(() => {
                            if (this.comfyStatus === 'running' && !this.comfyServerReady) {
                                this.checkComfyServerReady();
                            } else {
                                clearInterval(this.serverReadyCheckInterval);
                                this.serverReadyCheckInterval = null;
                            }
                        }, 500);
                    }
                }
                
                // Append new output
                if (data.output && data.output.length > 0) {
                    for (const line of data.output) {
                        this.appendToConsole(line.text, line.type || 'normal');
                    }
                }
            }
        } catch (error) {
            // Only log non-network errors (network errors are expected when server is down)
            if (error.name !== 'TypeError' || !error.message.includes('fetch')) {
                console.error('Console polling error:', error);
            }
        }
    }
    
    startBackendLogPolling() {
        // Only poll in standalone mode (port 8199)
        if (window.location.port === '8199') {
            this.backendLogFailureCount = 0;
            this.pollBackendLogs();
            this.backendLogPolling = setInterval(() => this.pollBackendLogs(), 2000);
        }
    }
    
    stopBackendLogPolling() {
        if (this.backendLogPolling) {
            clearInterval(this.backendLogPolling);
            this.backendLogPolling = null;
        }
    }
    
    async pollBackendLogs() {
        try {
            const response = await fetch(`${this.apiBase}/api/backend-logs?since=${this.backendLogIndex}`);
            if (!response.ok) return;
            
            const data = await response.json();
            if (data.success && data.logs && data.logs.length > 0) {
                for (const logEntry of data.logs) {
                    // Remove [MF Conductor] prefix since we're already in MF Conductor console
                    let message = logEntry.message || '';
                    if (message.startsWith('[MF Conductor] ')) {
                        message = message.substring(16); // Remove '[MF Conductor] ' prefix
                    }
                    this.log(message, logEntry.type || 'info');
                }
                this.backendLogIndex = data.next_index || this.backendLogIndex + data.logs.length;
            }
            // Reset failure count on any successful response cycle
            this.backendLogFailureCount = 0;
        } catch (error) {
            // Network errors are common if the server is down; stop polling to avoid hammering the browser.
            this.backendLogFailureCount = (this.backendLogFailureCount || 0) + 1;
            if (this.backendLogFailureCount >= 5) {
                this.stopBackendLogPolling();
                this.log('Backend log polling stopped (server unreachable). Restart MF Conductor and refresh this page.', 'warning');
            }
        }
    }
    
    async checkComfyServerReady() {
        const port = this.comfyPort || 8188;
        try {
            // Try to reach ComfyUI with a short timeout (500ms for faster detection)
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 500);
            
            // Try a simple fetch - any response (even 403) means server is up
            const response = await fetch(`http://127.0.0.1:${port}/`, {
                signal: controller.signal,
                method: 'HEAD',
                mode: 'no-cors' // Avoid CORS issues - we just need to know if server responds
            });
            
            clearTimeout(timeoutId);
            
            // In no-cors mode, response.type will be 'opaque' if successful
            // Any response at all means the server is ready
            if (!this.comfyServerReady) {
                this.comfyServerReady = true;
                // Clear the polling interval since we're ready
                if (this.serverReadyCheckInterval) {
                    clearInterval(this.serverReadyCheckInterval);
                    this.serverReadyCheckInterval = null;
                }
                this.log(`ComfyUI server ready at http://127.0.0.1:${port}`, 'success');
                this.appendToConsole(`✓ ComfyUI server ready at http://127.0.0.1:${port}`, 'success');
                this.updateComfyControls();
            }
        } catch (error) {
            // Network error or timeout - server not ready yet
            // Will retry on next poll
        }
    }
    
    appendToConsole(text, type = 'normal', skipSave = false) {
        const output = document.getElementById('console-output');
        if (!output) {
            console.warn('Console output element not found!');
            return;
        }
        
        // Remove placeholder if present
        const placeholder = output.querySelector('.console-placeholder');
        if (placeholder) {
            placeholder.remove();
        }
        
        // Create new line element
        const line = document.createElement('div');
        line.className = `console-line ${type}`;
        line.textContent = text;
        
        output.appendChild(line);
        
        // Store in memory array
        if (!this.consoleOutput) {
            this.consoleOutput = [];
        }
        this.consoleOutput.push({ text, type, time: Date.now() });
        
        // Limit console lines to prevent memory issues (check periodically, not every append)
        if (this.consoleOutput.length > 2100) {
            const maxLines = 2000;
            while (this.consoleOutput.length > maxLines) {
                output.firstElementChild?.remove();
                this.consoleOutput.shift();
            }
        }
        
        // Save to localStorage (debounced)
        if (!skipSave) {
            this.saveConsoleDebounced();
        }
        
        // Debounced auto-scroll for better performance
        if (this.consoleAutoScroll && !this._scrollPending) {
            this._scrollPending = true;
            requestAnimationFrame(() => {
                this.scrollConsoleToBottom();
                this._scrollPending = false;
            });
        }
    }
    
    clearConsoleOutput() {
        const output = document.getElementById('console-output');
        if (output) {
            output.innerHTML = '';
        }
        this.consoleOutput = [];
    }
    
    async showSplashScreen() {
        try {
            // Fetch the splash screen content (served from web/ directory)
            const response = await fetch(`${this.apiBase}/assets/splash.txt`);
            if (!response.ok) return;
            
            const splashText = await response.text();
            const output = document.getElementById('console-output');
            if (!output) return;
            
            // Create splash container with special styling
            const splashDiv = document.createElement('div');
            splashDiv.className = 'console-splash';
            splashDiv.innerHTML = `<pre class="splash-art">${this.escapeHtml(splashText)}</pre>`;
            output.appendChild(splashDiv);
            
            // Add empty line after splash
            this.appendToConsole('', 'normal', true);
        } catch (e) {
            // Splash screen is optional - continue without it
            console.log('Could not load splash screen:', e);
        }
    }
    
    saveConsoleDebounced() {
        // Debounce saving to avoid excessive writes
        if (this._saveConsoleTimeout) {
            clearTimeout(this._saveConsoleTimeout);
        }
        this._saveConsoleTimeout = setTimeout(() => {
            this.saveConsoleToStorage();
        }, 500);
    }
    
    saveConsoleToStorage() {
        try {
            // Only save last 500 lines to localStorage
            const toSave = this.consoleOutput.slice(-500);
            localStorage.setItem('mfc_console_history', JSON.stringify(toSave));
        } catch (e) {
            // Storage full or unavailable - ignore
        }
    }
    
    restoreConsoleFromStorage() {
        const output = document.getElementById('console-output');
        if (!output) return;
        
        try {
            const saved = localStorage.getItem('mfc_console_history');
            if (saved) {
                const lines = JSON.parse(saved);
                if (Array.isArray(lines) && lines.length > 0) {
                    // Remove placeholder
                    const placeholder = output.querySelector('.console-placeholder');
                    if (placeholder) {
                        placeholder.remove();
                    }
                    
                    // Restore lines
                    for (const item of lines) {
                        this.appendToConsole(item.text, item.type || 'normal', true);
                    }
                    
                    // Add separator
                    this.appendToConsole('--- Session restored ---', 'info', true);
                    
                    this.log(`Restored ${lines.length} console lines from previous session`, 'info');
                }
            }
        } catch (e) {
            // Ignore restore errors
        }
    }
    
    scrollConsoleToBottom() {
        const output = document.getElementById('console-output');
        if (output) {
            output.scrollTop = output.scrollHeight;
        }
    }
    
    toggleConsoleAutoScroll() {
        this.consoleAutoScroll = !this.consoleAutoScroll;
        
        const btn = document.getElementById('console-scroll-btn');
        if (btn) {
            btn.classList.toggle('active', this.consoleAutoScroll);
            btn.title = this.consoleAutoScroll ? 'Auto-scroll (enabled)' : 'Auto-scroll (disabled)';
        }
        
        if (this.consoleAutoScroll) {
            this.scrollConsoleToBottom();
        }
    }
    
    clearConsole() {
        // Clear terminal page output
        const terminalOutput = document.getElementById('console-output');
        if (terminalOutput) {
            terminalOutput.innerHTML = `
                <div class="console-placeholder">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">
                        <polyline points="4 17 10 11 4 5"/>
                        <line x1="12" y1="19" x2="20" y2="19"/>
                    </svg>
                    <p>Console cleared</p>
                </div>
            `;
        }
        
        // Clear bottom console panel
        if (this.consoleContent) {
            this.consoleContent.innerHTML = `
                <div class="console-welcome">
                    <span class="console-timestamp">[System]</span>
                    <span class="console-message">Console cleared.</span>
                </div>
            `;
        }
        
        this.consoleOutput = [];
        this.logCount = 0;
        this.updateConsoleBadge();
        
        // Also clear localStorage
        try {
            localStorage.removeItem('mfc_console_history');
        } catch (e) {}
    }
    
    async copyConsoleOutput() {
        const output = document.getElementById('console-output');
        if (!output) return;
        
        const lines = output.querySelectorAll('.console-line');
        const text = Array.from(lines).map(l => l.textContent).join('\n');
        
        try {
            await navigator.clipboard.writeText(text);
            this.showToast('success', 'Console output copied to clipboard');
        } catch (error) {
            this.showToast('error', 'Failed to copy to clipboard');
        }
    }
    
    exportConsoleOutput() {
        const output = document.getElementById('console-output');
        if (!output) return;
        
        const lines = output.querySelectorAll('.console-line');
        const text = Array.from(lines).map(l => l.textContent).join('\n');
        
        if (!text.trim()) {
            this.showToast('warning', 'Console is empty');
            return;
        }
        
        // Create blob and download
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        
        // Generate filename with timestamp
        const now = new Date();
        const timestamp = now.toISOString().replace(/[:.]/g, '-').slice(0, 19);
        a.download = `mf-conductor-terminal-${timestamp}.txt`;
        
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        this.showToast('success', 'Terminal output exported');
    }
    
    async runPythonCommand() {
        const input = document.getElementById('console-command-input');
        if (!input) return;
        
        const command = input.value.trim();
        if (!command) return;
        
        // Clear input
        input.value = '';
        
        // Show command in console
        this.appendToConsole(`> python.exe -m ${command}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/comfy/run-command`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command })
            });
            
            const data = await response.json();
            
            if (data.success) {
                if (data.output) {
                    this.appendToConsole(data.output, 'normal');
                }
                if (data.error) {
                    this.appendToConsole(data.error, 'error');
                }
            } else {
                this.appendToConsole(`Command failed: ${data.message}`, 'error');
            }
        } catch (error) {
            this.appendToConsole(`Error running command: ${error.message}`, 'error');
        }
    }
    
    bindElements() {
        // Search and filter
        this.searchInput = document.getElementById('search-input');
        this.sortSelect = document.getElementById('sort-select');
        this.sortDirectionBtn = document.getElementById('sort-direction');
        
        // Stats
        this.totalNodesEl = document.getElementById('total-nodes');
        this.shownNodesEl = document.getElementById('shown-nodes');
        
        // List containers
        this.nodeList = document.getElementById('node-list');
        this.loadingState = document.getElementById('loading-state');
        this.emptyState = document.getElementById('empty-state');
        
        // Buttons
        this.refreshBtn = document.getElementById('refresh-btn');
        this.installBtn = document.getElementById('install-btn');
        this.browseBtn = document.getElementById('browse-btn');
        this.checkUpdatesBtn = document.getElementById('check-updates-btn');
        this.batchUpdateBtn = document.getElementById('batch-update-btn');
        
        // Filter buttons
        this.filterFavoritesBtn = document.getElementById('filter-favorites');
        this.filterTagSelect = document.getElementById('filter-tag');
        
        // Install modal
        this.installModal = document.getElementById('install-modal');
        this.modalClose = document.getElementById('modal-close');
        this.modalCancel = document.getElementById('modal-cancel');
        this.modalInstall = document.getElementById('modal-install');
        this.gitUrlInput = document.getElementById('git-url');
        this.folderNameInput = document.getElementById('folder-name');
        this.installDepsCheckbox = document.getElementById('install-deps');
        
        // View toggle
        this.viewGridBtn = document.getElementById('view-grid');
        this.viewListBtn = document.getElementById('view-list');
        
        // Detail panel
        this.detailPanel = document.getElementById('detail-panel');
        this.detailClose = document.getElementById('detail-close');
        this.detailName = document.getElementById('detail-name');
        this.detailMeta = document.getElementById('detail-meta');
        this.detailDescription = document.getElementById('detail-description');
        this.detailRequirements = document.getElementById('detail-requirements');
        this.requirementsList = document.getElementById('requirements-list');
        this.requirementsCount = document.getElementById('requirements-count');
        this.detailUpdate = document.getElementById('detail-update');
        this.detailGithub = document.getElementById('detail-github');
        this.detailFolder = document.getElementById('detail-folder');
        this.detailDeactivate = document.getElementById('detail-deactivate');
        this.detailRemove = document.getElementById('detail-remove');
        
        // Toast container
        this.toastContainer = document.getElementById('toast-container');
        
        // Console panel (bottom)
        this.consolePanel = document.getElementById('console-panel');
        this.consoleHeader = document.getElementById('console-header');
        this.consoleToggle = document.getElementById('console-toggle');
        this.consoleClear = document.getElementById('console-clear');
        this.consoleBody = document.getElementById('console-body');
        this.consoleContent = document.getElementById('console-content');
        this.consoleBadge = document.getElementById('console-badge');
        this.consoleResizeHandle = document.getElementById('console-resize-handle');
        this.logCount = 0;
        this.consoleHeight = parseInt(localStorage.getItem('mfc_console_height')) || 300;
        
        // Footer
        this.scanTimeEl = document.getElementById('scan-time');
    }
    
    bindEvents() {
        // Search with debounce (using utility function)
        this.searchInput.addEventListener('input', () => this.debouncedFilterNodes());
        
        // Keyboard shortcut for search
        document.addEventListener('keydown', (e) => {
            if (e.key === '/' && document.activeElement !== this.searchInput) {
                e.preventDefault();
                this.searchInput.focus();
            }
            if (e.key === 'Escape') {
                this.closeDetailPanel();
                this.closeInstallModal();
                this.hideProfileContextMenu();
            }
        });
        
        // Sort controls
        this.sortSelect.addEventListener('change', () => {
            this.sortField = this.sortSelect.value;
            this.saveUserPreferences();
            this.filterNodes();
        });
        
        this.sortDirectionBtn.addEventListener('click', () => {
            this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            this.sortDirectionBtn.classList.toggle('asc', this.sortDirection === 'asc');
            this.saveUserPreferences();
            this.filterNodes();
        });
        
        // Refresh button
        this.refreshBtn.addEventListener('click', () => this.refreshNodes());
        
        // New feature buttons
        if (this.browseBtn) {
            this.browseBtn.addEventListener('click', () => this.openBrowseModal());
        }
        if (this.checkUpdatesBtn) {
            this.checkUpdatesBtn.addEventListener('click', () => this.checkAllUpdates());
        }
        if (this.batchUpdateBtn) {
            this.batchUpdateBtn.addEventListener('click', () => this.batchUpdateAll());
        }
        
        // Filter buttons
        if (this.filterFavoritesBtn) {
            this.filterFavoritesBtn.addEventListener('click', () => {
                this.showFavoritesOnly = !this.showFavoritesOnly;
                this.filterFavoritesBtn.classList.toggle('active', this.showFavoritesOnly);
                this.filterNodes();
            });
        }
        if (this.filterTagSelect) {
            this.filterTagSelect.addEventListener('change', () => {
                this.filterTag = this.filterTagSelect.value;
                this.filterNodes();
            });
        }
        
        // Batch tag buttons
        const batchAddTagBtn = document.getElementById('batch-add-tag');
        const batchRemoveTagBtn = document.getElementById('batch-remove-tag');
        if (batchAddTagBtn) {
            batchAddTagBtn.addEventListener('click', () => this.batchAddTag());
        }
        if (batchRemoveTagBtn) {
            batchRemoveTagBtn.addEventListener('click', () => this.batchRemoveTag());
        }
        
        // View toggle
        if (this.viewGridBtn) {
            this.viewGridBtn.addEventListener('click', () => {
                this.setViewMode('grid');
                this.saveUserPreferences();
            });
        }
        if (this.viewListBtn) {
            this.viewListBtn.addEventListener('click', () => {
                this.setViewMode('list');
                this.saveUserPreferences();
            });
        }
        
        // Install modal
        this.installBtn.addEventListener('click', () => this.openInstallModal());
        this.modalClose.addEventListener('click', () => this.closeInstallModal());
        this.modalCancel.addEventListener('click', () => this.closeInstallModal());
        this.modalInstall.addEventListener('click', () => this.installFromUrl());
        
        // Close modal on overlay click
        this.installModal.addEventListener('click', (e) => {
            if (e.target === this.installModal) {
                this.closeInstallModal();
            }
        });
        
        // Detail panel (only bind if elements exist - may not in tabbed interface)
        if (this.detailClose) {
            this.detailClose.addEventListener('click', () => this.closeDetailPanel());
        }
        if (this.detailUpdate) {
            this.detailUpdate.addEventListener('click', () => this.updateSelectedNode());
        }
        if (this.detailFolder) {
            this.detailFolder.addEventListener('click', () => this.openNodeFolder());
        }
        if (this.detailDeactivate) {
            this.detailDeactivate.addEventListener('click', () => this.deactivateSelectedNode());
        }
        if (this.detailRemove) {
            this.detailRemove.addEventListener('click', () => this.removeSelectedNode());
        }
        
        // Console panel (bottom)
        this.consoleHeader.addEventListener('click', (e) => {
            // Don't toggle if clicking on action buttons
            if (e.target.closest('.console-actions')) return;
            this.toggleConsole();
        });
        this.consoleToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggleConsole();
        });
        this.consoleClear.addEventListener('click', (e) => {
            e.stopPropagation();
            this.clearConsole();
        });
        
        // Console panel resize handle
        this.initConsoleResizer();
        
        // Resizer for expanded detail grid - using event delegation
        this.initDetailResizer();
        
        // Packages tab search and refresh
        // Packages tab events
        const packagesTabSearch = document.getElementById('packages-tab-search');
        if (packagesTabSearch) {
            packagesTabSearch.addEventListener('input', () => this.renderPackagesTab());
        }
        const packagesRefreshBtn = document.getElementById('packages-refresh-btn');
        if (packagesRefreshBtn) {
            packagesRefreshBtn.addEventListener('click', () => this.loadPackagesTab());
        }
        
        // Bind file browser events
        this.bindFilesEvents();
        const packagesInstallBtn = document.getElementById('packages-install-btn');
        if (packagesInstallBtn) {
            packagesInstallBtn.addEventListener('click', () => this.openPackageInstallModal());
        }
        const packagesCheckUpdatesBtn = document.getElementById('packages-check-updates-btn');
        if (packagesCheckUpdatesBtn) {
            packagesCheckUpdatesBtn.addEventListener('click', () => this.checkPackageUpdates());
        }
        const packagesUpgradeAllBtn = document.getElementById('packages-upgrade-all-btn');
        if (packagesUpgradeAllBtn) {
            packagesUpgradeAllBtn.addEventListener('click', () => this.upgradeAllPackages());
        }
        const packagesSortSelect = document.getElementById('packages-sort');
        if (packagesSortSelect) {
            packagesSortSelect.addEventListener('change', () => this.renderPackagesTab());
        }
        const packagesShowOutdated = document.getElementById('packages-show-outdated');
        if (packagesShowOutdated) {
            packagesShowOutdated.addEventListener('change', () => this.renderPackagesTab());
        }
        
        // Packages view toggle
        const packagesViewGrid = document.getElementById('packages-view-grid');
        const packagesViewList = document.getElementById('packages-view-list');
        if (packagesViewGrid) {
            packagesViewGrid.addEventListener('click', () => {
                this.packagesViewMode = 'grid';
                packagesViewGrid.classList.add('active');
                packagesViewList?.classList.remove('active');
                this.saveUserPreferences();
                this.renderPackagesTab();
            });
        }
        if (packagesViewList) {
            packagesViewList.addEventListener('click', () => {
                this.packagesViewMode = 'list';
                packagesViewList.classList.add('active');
                packagesViewGrid?.classList.remove('active');
                this.saveUserPreferences();
                this.renderPackagesTab();
            });
        }
        // Restore saved view mode for packages
        if (this.packagesViewMode === 'grid') {
            packagesViewGrid?.classList.add('active');
            packagesViewList?.classList.remove('active');
        } else {
            packagesViewList?.classList.add('active');
            packagesViewGrid?.classList.remove('active');
        }
        // Package install modal enter key
        const packageNameInput = document.getElementById('package-name-input');
        if (packageNameInput) {
            packageNameInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.installPackageFromModal();
                }
            });
        }
        
        // Profile context menu
        const contextMenu = document.getElementById('profile-context-menu');
        if (contextMenu) {
            contextMenu.querySelectorAll('.context-menu-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    const action = item.dataset.action;
                    if (action) this.handleContextMenuAction(action);
                });
            });
        }
    }
    
    initDetailResizer() {
        let isResizing = false;
        let currentGrid = null;
        let startX = 0;
        let startMainWidth = 0;
        let startReqWidth = 0;
        
        document.addEventListener('mousedown', (e) => {
            const resizer = e.target.closest('.expanded-detail-resizer');
            if (!resizer) return;
            
            const gridId = resizer.dataset.gridId;
            currentGrid = document.getElementById(gridId);
            if (!currentGrid) return;
            
            isResizing = true;
            resizer.classList.add('dragging');
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
            
            startX = e.clientX;
            const mainCol = currentGrid.querySelector('.expanded-detail-main');
            const reqCol = currentGrid.querySelector('.expanded-detail-requirements');
            startMainWidth = mainCol.offsetWidth;
            startReqWidth = reqCol.offsetWidth;
            
            e.preventDefault();
        });
        
        document.addEventListener('mousemove', (e) => {
            if (!isResizing || !currentGrid) return;
            
            const deltaX = e.clientX - startX;
            const gridWidth = currentGrid.offsetWidth;
            const newMainWidth = startMainWidth + deltaX;
            const newReqWidth = startReqWidth - deltaX;
            
            // Enforce minimum widths
            if (newMainWidth < 200 || newReqWidth < 150) return;
            
            // Calculate percentages based on available space (minus resizer width)
            const availableWidth = gridWidth - 6;
            const mainPercent = (newMainWidth / availableWidth) * 100;
            const reqPercent = (newReqWidth / availableWidth) * 100;
            
            currentGrid.style.gridTemplateColumns = `${mainPercent}% 6px ${reqPercent}%`;
        });
        
        document.addEventListener('mouseup', () => {
            if (isResizing) {
                isResizing = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
                document.querySelectorAll('.expanded-detail-resizer').forEach(r => r.classList.remove('dragging'));
                currentGrid = null;
            }
        });
    }
    
    async loadNodes() {
        this.showLoading(true);
        this.log('Loading custom nodes...', 'info');
        
        try {
            if (window.location.protocol === 'file:') {
                throw new Error('This page must be opened via the MF Conductor server (not file://)');
            }
            
            const parseJsonSafe = async (resp) => {
                try {
                    return await resp.json();
                } catch (e) {
                    return null;
                }
            };
            
            const tryFetch = async (base, query = '') => {
                const response = await fetch(`${base}/api/nodes${query}`);
                const data = await parseJsonSafe(response);
                return { response, data, base };
            };
            
            let { response, data, base } = await tryFetch(this.apiBase, '?fast=1');
            
            if (!response.ok) {
                const preferAlt = this.apiBase === '/mf_conductor' ? '' : '/mf_conductor';
                if (this.apiBase !== preferAlt) {
                    const alt = await tryFetch(preferAlt, '?fast=1');
                    if (alt.response.ok) {
                        this.apiBase = alt.base;
                        response = alt.response;
                        data = alt.data;
                        base = alt.base;
                    }
                }
            }
            
            if (!response.ok) {
                const message = (data && data.message) ? data.message : `HTTP ${response.status}`;
                throw new Error(message);
            }
            
            this.nodes = data.nodes || [];
            
            if (this.totalNodesEl) this.totalNodesEl.textContent = this.nodes.length;
            if (this.scanTimeEl) this.scanTimeEl.textContent = `Last scan: ${this.formatDate(data.scanned_at)}`;
            
            this.log(`Loaded ${this.nodes.length} custom nodes successfully`, 'success');
            this.filterNodes();
        } catch (error) {
            console.error('Error loading nodes:', error);
            this.log(`Error loading nodes: ${error.message}`, 'error');
            this.showToast('error', 'Failed to load custom nodes');
        } finally {
            this.showLoading(false);
        }
    }
    
    async refreshNodes() {
        this.refreshBtn.disabled = true;
        this.refreshBtn.querySelector('svg').style.animation = 'spin 1s linear infinite';
        this.log('Rescanning custom_nodes directory...', 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/refresh`, {
                method: 'POST'
            });
            if (!response.ok) throw new Error('Failed to refresh nodes');
            
            const data = await response.json();
            this.nodes = data.nodes || [];
            
            if (this.totalNodesEl) this.totalNodesEl.textContent = this.nodes.length;
            if (this.scanTimeEl) this.scanTimeEl.textContent = `Last scan: ${this.formatDate(data.scanned_at)}`;
            
            this.filterNodes();
            this.log(`Scan complete. Found ${this.nodes.length} custom nodes`, 'success');
            this.showToast('success', `Found ${this.nodes.length} custom nodes`);
        } catch (error) {
            console.error('Error refreshing nodes:', error);
            this.log(`Refresh failed: ${error.message}`, 'error');
            this.showToast('error', 'Failed to refresh node list');
        } finally {
            this.refreshBtn.disabled = false;
            this.refreshBtn.querySelector('svg').style.animation = '';
        }
    }
    
    filterNodes() {
        const searchTerm = this.searchInput.value.toLowerCase().trim();
        
        // Filter
        this.filteredNodes = this.nodes.filter(node => {
            // Disabled nodes filter
            if (!this.settings.showDisabled && node.is_disabled) {
                return false;
            }
            
            // Search filter
            if (searchTerm) {
                const searchableFields = [
                    node.display_name,
                    node.folder_name,
                    node.author,
                    node.description,
                    ...this.getTags(node.folder_name) // Also search tags
                ].filter(Boolean).map(f => f.toLowerCase());
                
                if (!searchableFields.some(field => field.includes(searchTerm))) {
                    return false;
                }
            }
            
            // Favorites filter
            if (this.showFavoritesOnly && !this.isFavorite(node.folder_name)) {
                return false;
            }
            
            // Tag filter
            if (this.filterTag) {
                const nodeTags = this.getTags(node.folder_name);
                if (!nodeTags.includes(this.filterTag)) {
                    return false;
                }
            }
            
            return true;
        });
        
        // Sort (favorites first if enabled)
        this.sortNodes();
        
        this.shownNodesEl.textContent = this.filteredNodes.length;
        this.updateTagsDropdown();
        this.renderNodes();
    }
    
    sortNodes() {
        this.filteredNodes.sort((a, b) => {
            // Always put favorites first
            const aFav = this.isFavorite(a.folder_name);
            const bFav = this.isFavorite(b.folder_name);
            if (aFav && !bFav) return -1;
            if (!aFav && bFav) return 1;
            
            // Then sort by selected field
            let aVal, bVal;
            
            switch (this.sortField) {
                case 'name':
                    aVal = (a.display_name || '').toLowerCase();
                    bVal = (b.display_name || '').toLowerCase();
                    break;
                case 'date_added':
                    aVal = a.date_added ? new Date(a.date_added).getTime() : 0;
                    bVal = b.date_added ? new Date(b.date_added).getTime() : 0;
                    break;
                case 'last_updated':
                    aVal = a.last_updated ? new Date(a.last_updated).getTime() : 0;
                    bVal = b.last_updated ? new Date(b.last_updated).getTime() : 0;
                    break;
                case 'author':
                    aVal = (a.author || 'zzz').toLowerCase();
                    bVal = (b.author || 'zzz').toLowerCase();
                    break;
                case 'stars':
                    aVal = a.stars || 0;
                    bVal = b.stars || 0;
                    break;
                default:
                    aVal = (a.display_name || '').toLowerCase();
                    bVal = (b.display_name || '').toLowerCase();
            }
            
            let result;
            if (typeof aVal === 'string') {
                result = aVal.localeCompare(bVal);
            } else {
                result = aVal - bVal;
            }
            
            return this.sortDirection === 'desc' ? -result : result;
        });
        
        // Update sort indicator visual
        this.updateSortIndicator();
    }
    
    updateSortIndicator() {
        // Update the sort direction button appearance
        const icon = this.sortDirectionBtn.querySelector('svg');
        if (icon) {
            icon.style.transform = this.sortDirection === 'asc' ? 'rotate(180deg)' : 'rotate(0deg)';
        }
        
        // Add visual feedback to show current sort
        const sortLabel = {
            'name': 'Name',
            'date_added': 'Date Added',
            'last_updated': 'Last Updated',
            'author': 'Author',
            'stars': 'GitHub Stars'
        };
        
        const dirLabel = this.sortDirection === 'asc' ? '(A-Z / Oldest)' : '(Z-A / Newest)';
        this.sortDirectionBtn.title = `Sort: ${sortLabel[this.sortField]} ${dirLabel}`;
        
        // Update list view header if in list mode
        if (this.viewMode === 'list') {
            this.updateListHeaderSort();
        }
    }
    
    setViewMode(mode, skipRender = false) {
        this.viewMode = mode;
        
        // Save preference to localStorage
        try {
            localStorage.setItem('mf_conductor_view', mode);
        } catch (e) {}
        
        // Update button states
        if (this.viewGridBtn) this.viewGridBtn.classList.toggle('active', mode === 'grid');
        if (this.viewListBtn) this.viewListBtn.classList.toggle('active', mode === 'list');
        
        // Update list class
        if (this.nodeList) this.nodeList.classList.toggle('list-view', mode === 'list');
        
        // Re-render (unless skipped during init)
        if (!skipRender) {
            this.renderNodes();
        }
    }
    
    loadUserPreferences() {
        try {
            // Load view mode
            const savedView = localStorage.getItem('mf_conductor_view');
            if (savedView === 'grid' || savedView === 'list') {
                this.setViewMode(savedView, true);
            }
            
            // Load sort preferences
            const savedSort = localStorage.getItem('mf_conductor_sort');
            if (savedSort) {
                this.sortField = savedSort;
                this.sortSelect.value = savedSort;
            }
            
            const savedDirection = localStorage.getItem('mf_conductor_sort_dir');
            if (savedDirection === 'asc' || savedDirection === 'desc') {
                this.sortDirection = savedDirection;
                this.sortDirectionBtn.classList.toggle('asc', savedDirection === 'asc');
            }
            
            // Load browse view mode
            const savedBrowseView = localStorage.getItem('mf_conductor_browse_view');
            if (savedBrowseView === 'grid' || savedBrowseView === 'list') {
                this.browseViewMode = savedBrowseView;
            }
            
            // Load packages view mode
            const savedPackagesView = localStorage.getItem('mf_conductor_packages_view');
            if (savedPackagesView === 'grid' || savedPackagesView === 'list') {
                this.packagesViewMode = savedPackagesView;
            } else {
                this.packagesViewMode = 'list'; // Default to list for packages
            }
            
            // Load files tab preferences
            const savedFilesView = localStorage.getItem('mf_conductor_files_view');
            if (savedFilesView === 'grid' || savedFilesView === 'list' || savedFilesView === 'workflow') {
                this.filesViewMode = savedFilesView;
            } else {
                this.filesViewMode = 'grid';
            }
            
            const savedFilesFolder = localStorage.getItem('mf_conductor_files_folder');
            if (savedFilesFolder) {
                this.filesFolder = savedFilesFolder;
            }
            
            // Enforce workflow view only for output folder
            if (this.filesViewMode === 'workflow' && this.filesFolder !== 'output') {
                this.filesViewMode = 'grid';
            }
            const savedFilesSort = localStorage.getItem('mf_conductor_files_sort');
            if (savedFilesSort) {
                this.filesSortBy = savedFilesSort;
            }
            const savedFilesSortDir = localStorage.getItem('mf_conductor_files_sort_dir');
            if (savedFilesSortDir === 'asc' || savedFilesSortDir === 'desc') {
                this.filesSortDir = savedFilesSortDir;
            }
            const savedFilesRecursive = localStorage.getItem('mf_conductor_files_recursive');
            if (savedFilesRecursive !== null) {
                this.filesRecursive = savedFilesRecursive === 'true';
            }
            
            // Load profiles view mode
            const savedProfilesView = localStorage.getItem('mf_conductor_profiles_view');
            if (savedProfilesView === 'grid' || savedProfilesView === 'list') {
                this.profilesViewMode = savedProfilesView;
            }
            
            // Load console preferences
            const savedConsoleAutoScroll = localStorage.getItem('mf_conductor_console_autoscroll');
            if (savedConsoleAutoScroll !== null) {
                this.consoleAutoScroll = savedConsoleAutoScroll === 'true';
                const checkbox = document.getElementById('console-autoscroll-checkbox');
                if (checkbox) checkbox.checked = this.consoleAutoScroll;
            }
            
            const savedConsoleExpanded = localStorage.getItem('mf_conductor_console_expanded');
            if (savedConsoleExpanded === 'true' && this.consolePanel) {
                this.consolePanel.classList.remove('collapsed');
                if (this.consoleBody) {
                    this.consoleBody.style.height = `${this.consoleHeight}px`;
                }
                this.updateMainContentPadding();
            }
        } catch (e) {}
    }
    
    saveUserPreferences() {
        try {
            localStorage.setItem('mf_conductor_view', this.viewMode);
            localStorage.setItem('mf_conductor_sort', this.sortField);
            localStorage.setItem('mf_conductor_sort_dir', this.sortDirection);
            localStorage.setItem('mf_conductor_browse_view', this.browseViewMode || 'grid');
            localStorage.setItem('mf_conductor_packages_view', this.packagesViewMode || 'list');
            
            // Files tab preferences
            localStorage.setItem('mf_conductor_files_view', this.filesViewMode || 'grid');
            localStorage.setItem('mf_conductor_files_folder', this.filesFolder || 'output');
            localStorage.setItem('mf_conductor_files_sort', this.filesSortBy || 'date');
            localStorage.setItem('mf_conductor_files_sort_dir', this.filesSortDir || 'desc');
            localStorage.setItem('mf_conductor_files_recursive', this.filesRecursive ? 'true' : 'false');
            
            // Profiles tab preferences
            localStorage.setItem('mf_conductor_profiles_view', this.profilesViewMode || 'grid');
            
            // Console preferences
            localStorage.setItem('mf_conductor_console_autoscroll', this.consoleAutoScroll ? 'true' : 'false');
            const consoleExpanded = this.consolePanel && !this.consolePanel.classList.contains('collapsed');
            localStorage.setItem('mf_conductor_console_expanded', consoleExpanded ? 'true' : 'false');
        } catch (e) {}
    }
    
    updateListHeaderSort() {
        const headers = this.nodeList.querySelectorAll('.list-header-col');
        headers.forEach(header => {
            const field = header.dataset.sort;
            header.classList.toggle('active', field === this.sortField);
            header.classList.toggle('desc', field === this.sortField && this.sortDirection === 'desc');
        });
    }
    
    handleListHeaderClick(field) {
        if (this.sortField === field) {
            // Toggle direction
            this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            // New field, default to asc (or desc for dates/stars)
            this.sortField = field;
            this.sortDirection = (field === 'date_added' || field === 'last_updated' || field === 'stars') ? 'desc' : 'asc';
        }
        
        // Update dropdown to match
        this.sortSelect.value = field;
        this.sortDirectionBtn.classList.toggle('asc', this.sortDirection === 'asc');
        
        // Save preferences
        this.saveUserPreferences();
        
        this.filterNodes();
    }
    
    renderNodes() {
        this.nodeList.innerHTML = '';
        
        if (this.filteredNodes.length === 0) {
            this.emptyState.style.display = 'flex';
            return;
        }
        
        this.emptyState.style.display = 'none';
        
        if (this.viewMode === 'list') {
            this.renderListView();
        } else {
            this.renderGridView();
        }
    }
    
    renderGridView() {
        this.filteredNodes.forEach(node => {
            const card = this.createNodeCard(node);
            this.nodeList.appendChild(card);
        });
    }
    
    renderListView() {
        // Create header
        const header = document.createElement('div');
        header.className = 'list-header';
        header.innerHTML = `
            <div class="list-header-col ${this.sortField === 'name' ? 'active' : ''} ${this.sortField === 'name' && this.sortDirection === 'desc' ? 'desc' : ''}" data-sort="name">
                Name
                <svg class="sort-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 5v14M5 12l7-7 7 7"/>
                </svg>
            </div>
            <div class="list-header-col ${this.sortField === 'author' ? 'active' : ''} ${this.sortField === 'author' && this.sortDirection === 'desc' ? 'desc' : ''}" data-sort="author">
                Author
                <svg class="sort-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 5v14M5 12l7-7 7 7"/>
                </svg>
            </div>
            <div class="list-header-col ${this.sortField === 'last_updated' ? 'active' : ''} ${this.sortField === 'last_updated' && this.sortDirection === 'desc' ? 'desc' : ''}" data-sort="last_updated">
                Updated
                <svg class="sort-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 5v14M5 12l7-7 7 7"/>
                </svg>
            </div>
            <div class="list-header-col ${this.sortField === 'stars' ? 'active' : ''} ${this.sortField === 'stars' && this.sortDirection === 'desc' ? 'desc' : ''}" data-sort="stars">
                Stars
                <svg class="sort-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 5v14M5 12l7-7 7 7"/>
                </svg>
            </div>
            <div class="list-header-col">Actions</div>
        `;
        
        // Add click handlers to sortable columns
        header.querySelectorAll('.list-header-col[data-sort]').forEach(col => {
            col.addEventListener('click', () => this.handleListHeaderClick(col.dataset.sort));
        });
        
        this.nodeList.appendChild(header);
        
        // Create rows
        this.filteredNodes.forEach(node => {
            const row = this.createNodeRow(node);
            this.nodeList.appendChild(row);
        });
    }
    
    createNodeRow(node) {
        const row = document.createElement('div');
        row.className = 'node-row';
        row.dataset.folder = node.folder_name;
        
        row.innerHTML = `
            <div class="node-row-name">
                <span class="name">${this.escapeHtml(node.display_name)}</span>
                <span class="folder">${this.escapeHtml(node.folder_name)}</span>
            </div>
            <div class="node-row-author">${this.escapeHtml(node.author || 'Unknown')}</div>
            <div class="node-row-date">${node.last_updated ? this.formatRelativeDate(node.last_updated) : '-'}</div>
            <div class="node-row-date">${node.stars > 0 ? this.formatNumber(node.stars) : '-'}</div>
            <div class="node-row-actions">
                ${node.git_url ? `
                    <a href="${this.escapeHtml(node.git_url)}" 
                       target="_blank" 
                       class="btn btn-secondary"
                       onclick="event.stopPropagation()"
                       title="Open GitHub">
                        <svg viewBox="0 0 24 24" fill="currentColor">
                            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                        </svg>
                    </a>
                ` : ''}
                <button class="btn btn-secondary" onclick="event.stopPropagation(); app.openNodeDetails('${this.escapeHtml(node.folder_name)}')" title="Details">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="1"/>
                        <circle cx="19" cy="12" r="1"/>
                        <circle cx="5" cy="12" r="1"/>
                    </svg>
                </button>
            </div>
        `;
        
        row.addEventListener('click', () => this.openNodeDetails(node.folder_name));
        
        return row;
    }
    
    createNodeCard(node) {
        const card = document.createElement('div');
        card.className = 'node-card';
        if (this.selectedNodes.has(node.folder_name)) {
            card.classList.add('selected');
        }
        card.dataset.folder = node.folder_name;
        
        const isFav = this.isFavorite(node.folder_name);
        const hasUpdate = this.updateStatus[node.folder_name]?.has_updates;
        const tags = this.getTags(node.folder_name);
        
        // Build badges HTML
        let badgesHtml = '';
        if (hasUpdate) {
            badgesHtml += '<span class="badge badge-update" title="Update available">Update</span>';
        }
        if (node.is_git_repo) {
            badgesHtml += '<span class="badge badge-git">Git</span>';
        }
        if (node.stars > 0) {
            badgesHtml += `
                <span class="badge badge-stars">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
                    </svg>
                    ${this.formatNumber(node.stars)}
                </span>`;
        }
        
        // Build meta HTML
        let metaHtml = '';
        if (node.author && node.author !== 'Unknown') {
            metaHtml += `
                <span class="node-meta-item">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/>
                        <circle cx="12" cy="7" r="4"/>
                    </svg>
                    ${this.escapeHtml(node.author)}
                </span>`;
        }
        if (node.last_updated) {
            metaHtml += `
                <span class="node-meta-item">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"/>
                        <polyline points="12 6 12 12 16 14"/>
                    </svg>
                    ${this.formatRelativeDate(node.last_updated)}
                </span>`;
        }
        
        // Tags HTML
        const tagsHtml = tags.length > 0 
            ? `<div class="node-tags">${tags.map(t => `<span class="node-tag">${this.escapeHtml(t)}</span>`).join('')}</div>` 
            : '';
        
        card.innerHTML = `
            <div class="node-card-header">
                <div>
                    <div class="node-name">${this.escapeHtml(node.display_name)}</div>
                    <div class="node-folder">${this.escapeHtml(node.folder_name)}</div>
                </div>
                <div class="node-header-actions">
                    <button class="favorite-btn ${isFav ? 'active' : ''}" onclick="event.stopPropagation(); app.toggleFavorite('${this.escapeHtml(node.folder_name)}')" title="${isFav ? 'Remove from favorites' : 'Add to favorites'}">
                        <svg viewBox="0 0 24 24" fill="${isFav ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2">
                            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
                        </svg>
                    </button>
                    <div class="node-badges">${badgesHtml}</div>
                </div>
            </div>
            ${node.description ? `<div class="node-description">${this.escapeHtml(node.description)}</div>` : ''}
            ${tagsHtml}
            <div class="node-meta">${metaHtml}</div>
            <div class="node-actions">
                ${node.git_url ? `
                    <a href="${this.escapeHtml(node.git_url)}" 
                       target="_blank" 
                       class="btn btn-secondary node-action-btn"
                       onclick="event.stopPropagation()">
                        <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
                            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                        </svg>
                        GitHub
                    </a>
                ` : ''}
                <button class="btn btn-secondary node-action-btn" onclick="event.stopPropagation(); app.openNodeDetails('${this.escapeHtml(node.folder_name)}')">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <circle cx="12" cy="12" r="3"/>
                        <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>
                    </svg>
                    Details
                </button>
            </div>
        `;
        
        card.addEventListener('click', () => this.openNodeDetails(node.folder_name));
        
        return card;
    }
    
    openNodeDetails(folderName) {
        const node = this.nodes.find(n => n.folder_name === folderName);
        if (!node) return;
        
        // Check if this node is already expanded - if so, collapse it
        if (this.selectedNode && this.selectedNode.folder_name === folderName) {
            this.closeNodeDetails(folderName);
            return;
        }
        
        // Collapse any previously expanded node
        if (this.selectedNode) {
            this.closeNodeDetails(this.selectedNode.folder_name);
        }
        
        this.selectedNode = node;
        
        // Find the row/card element and add expanded details below it
        const nodeElement = document.querySelector(`[data-folder="${folderName}"]`);
        if (!nodeElement) return;
        
        // Create the expanded detail section
        const detailSection = document.createElement('div');
        detailSection.className = 'node-detail-expanded';
        detailSection.id = `detail-${folderName}`;
        
        detailSection.innerHTML = this.buildExpandedDetailHTML(node);
        
        // Insert after the node element
        nodeElement.classList.add('expanded');
        nodeElement.after(detailSection);
        
        // Load requirements
        this.loadRequirementsInline(node.folder_name);
        
        // Smooth scroll to show the expanded content
        setTimeout(() => {
            detailSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }, 50);
    }
    
    closeNodeDetails(folderName) {
        const detailSection = document.getElementById(`detail-${folderName}`);
        if (detailSection) {
            detailSection.remove();
        }
        
        const nodeElement = document.querySelector(`[data-folder="${folderName}"]`);
        if (nodeElement) {
            nodeElement.classList.remove('expanded');
        }
        
        if (this.selectedNode && this.selectedNode.folder_name === folderName) {
            this.selectedNode = null;
        }
    }
    
    buildExpandedDetailHTML(node) {
        const tags = this.getTags(node.folder_name);
        const note = this.getNote(node.folder_name);
        const isFav = this.isFavorite(node.folder_name);
        
        return `
            <div class="expanded-detail-content">
                <div class="expanded-meta-bar">
                    <span class="meta-item"><span class="meta-label">Folder:</span> ${this.escapeHtml(node.folder_name)}</span>
                    <span class="meta-sep">|</span>
                    <span class="meta-item"><span class="meta-label">Author:</span> ${this.escapeHtml(node.author || 'Unknown')}</span>
                    <span class="meta-sep">|</span>
                    <span class="meta-item"><span class="meta-label">Added:</span> ${node.date_added ? this.formatRelativeDate(node.date_added) : 'Unknown'}</span>
                    <span class="meta-sep">|</span>
                    <span class="meta-item"><span class="meta-label">Updated:</span> ${node.last_updated ? this.formatRelativeDate(node.last_updated) : 'Unknown'}</span>
                    ${node.stars > 0 ? `<span class="meta-sep">|</span><span class="meta-item meta-stars"><svg viewBox="0 0 24 24" fill="currentColor" width="12" height="12"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg> ${this.formatNumber(node.stars)}</span>` : ''}
                </div>
                
                <div class="expanded-detail-grid" id="detail-grid-${node.folder_name}">
                    <div class="expanded-detail-main">
                        ${node.description ? `
                        <div class="expanded-detail-desc">
                            <p>${this.escapeHtml(node.description)}</p>
                        </div>
                        ` : ''}
                        
                        ${node.provided_nodes && node.provided_nodes.length > 0 ? `
                        <div class="expanded-detail-nodes">
                            <div class="nodes-toggle" onclick="this.parentElement.classList.toggle('expanded')">
                                <svg class="nodes-toggle-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12">
                                    <polyline points="9 18 15 12 9 6"/>
                                </svg>
                                <span class="nodes-count">${node.provided_nodes.length} node${node.provided_nodes.length !== 1 ? 's' : ''}</span>
                                <span class="nodes-preview-hint">${node.provided_nodes.slice(0, 3).join(', ')}${node.provided_nodes.length > 3 ? '...' : ''}</span>
                            </div>
                            <div class="nodes-list-container">
                                <div class="nodes-list">
                                    ${node.provided_nodes.map(n => `<span class="node-name-item">${this.escapeHtml(n)}</span>`).join('')}
                                </div>
                            </div>
                        </div>
                        ` : ''}
                        
                        <div class="expanded-detail-row">
                            <div class="expanded-detail-note">
                                <div class="detail-section-label">Note</div>
                                <textarea class="note-input" 
                                          placeholder="Add a note..."
                                          onchange="app.setNote('${this.escapeHtml(node.folder_name)}', this.value)">${this.escapeHtml(note)}</textarea>
                            </div>
                            
                            <div class="expanded-detail-tags">
                                <div class="detail-section-label">Tags</div>
                                <div class="tags-input-container" id="tags-container-${node.folder_name}">
                                    ${tags.map(tag => `
                                        <span class="tag-pill">
                                            ${this.escapeHtml(tag)}
                                            <button onclick="app.removeTagFromNode('${this.escapeHtml(node.folder_name)}', '${this.escapeHtml(tag)}')">&times;</button>
                                        </span>
                                    `).join('')}
                                    <input type="text" 
                                           class="tags-add-input" 
                                           placeholder="Add tag..."
                                           onkeydown="if(event.key==='Enter'){app.addTagToNode('${this.escapeHtml(node.folder_name)}', this.value); this.value='';}"
                                    >
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <div class="expanded-detail-resizer" data-grid-id="detail-grid-${node.folder_name}"></div>
                    
                    <div class="expanded-detail-requirements">
                        <div class="detail-section-label">Requirements</div>
                        <div class="requirements-wrapper">
                            <div class="requirements-list" id="requirements-${node.folder_name}">
                                <div class="no-requirements">Loading...</div>
                            </div>
                        </div>
                    </div>
                </div>
                
                <div class="expanded-detail-actions">
                    ${node.is_git_repo ? `
                    <button class="btn btn-primary" onclick="app.updateNodeInline('${this.escapeHtml(node.folder_name)}')">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M23 4v6h-6"/>
                            <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/>
                        </svg>
                        Update
                    </button>
                    ` : ''}
                    ${node.git_url ? `
                    <a class="btn btn-secondary" href="${this.escapeHtml(node.git_url)}" target="_blank">
                        <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
                            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                        </svg>
                        GitHub
                    </a>
                    ` : ''}
                    <button class="btn btn-secondary" onclick="app.openFolderInline('${this.escapeHtml(node.folder_name)}')">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z"/>
                        </svg>
                        Open Folder
                    </button>
                    <button class="btn ${isFav ? 'btn-warning' : 'btn-secondary'}" onclick="app.toggleFavorite('${this.escapeHtml(node.folder_name)}')">
                        <svg viewBox="0 0 24 24" fill="${isFav ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
                        </svg>
                        ${isFav ? 'Favorited' : 'Favorite'}
                    </button>
                    <div class="action-spacer"></div>
                    <button class="btn btn-warning" onclick="app.deactivateNodeInline('${this.escapeHtml(node.folder_name)}')">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>
                        </svg>
                        Deactivate
                    </button>
                    <button class="btn btn-danger" onclick="app.removeNodeInline('${this.escapeHtml(node.folder_name)}')">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
                        </svg>
                        Remove
                    </button>
                </div>
            </div>
        `;
    }
    
    async loadRequirementsInline(folderName) {
        const container = document.getElementById(`requirements-${folderName}`);
        if (!container) return;
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/requirements`);
            const data = await response.json();
            
            if (!data.success || data.requirements.length === 0) {
                container.innerHTML = '<div class="no-requirements">No requirements.txt found</div>';
                return;
            }
            
            container.innerHTML = data.requirements.map(req => {
                let icon = '';
                let hint = '';
                let statusText = '';
                
                // Handle git requirements specially
                const isGitReq = req.is_git || req.raw?.includes('github.com') || req.raw?.startsWith('git+');
                let displayName = req.name;
                
                // For git URLs, extract a cleaner display name
                if (isGitReq && req.raw) {
                    const urlMatch = req.raw.match(/github\.com\/([^\/]+\/[^\/]+)/);
                    if (urlMatch) {
                        displayName = urlMatch[1].replace('.git', '');
                    } else {
                        // Just show last part of URL
                        displayName = req.raw.split('/').pop()?.replace('.git', '') || req.name;
                    }
                }
                
                switch (req.status) {
                    case 'installed':
                        icon = `<svg class="requirement-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                            <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>
                            <polyline points="22 4 12 14.01 9 11.01"/>
                        </svg>`;
                        statusText = req.message || req.version_spec || '';
                        break;
                    case 'missing':
                        icon = `<svg class="requirement-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="15" y1="9" x2="9" y2="15"/>
                            <line x1="9" y1="9" x2="15" y2="15"/>
                        </svg>`;
                        statusText = 'Not installed';
                        hint = `<span class="requirement-install-hint" data-package="${this.escapeHtml(req.raw || req.name)}" data-name="${this.escapeHtml(displayName)}" data-folder="${folderName}">Click to install</span>`;
                        break;
                    case 'warning':
                        icon = `<svg class="requirement-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
                            <line x1="12" y1="9" x2="12" y2="13"/>
                            <line x1="12" y1="17" x2="12.01" y2="17"/>
                        </svg>`;
                        statusText = req.message || 'Version mismatch';
                        break;
                }
                
                // Show git badge for git dependencies
                const gitBadge = isGitReq ? '<span class="requirement-git-badge" title="Git dependency">git</span>' : '';
                
                // Jump to packages icon (only show for non-git requirements)
                const jumpIcon = !isGitReq ? `
                    <button class="requirement-jump-btn" data-package="${this.escapeHtml(req.name)}" title="View in Packages tab">
                        <svg viewBox="0 0 24 24" fill="currentColor">
                            <path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/>
                        </svg>
                    </button>
                ` : '';
                
                return `
                    <div class="requirement-item ${req.status}" title="${this.escapeHtml(req.raw || req.name)}">
                        ${icon}
                        <span class="requirement-name">${this.escapeHtml(displayName)}</span>
                        ${gitBadge}
                        <span class="requirement-version">${this.escapeHtml(statusText)}</span>
                        ${hint}
                        ${jumpIcon}
                    </div>
                `;
            }).join('');
            
            // Add click handlers for install hints using event delegation
            container.querySelectorAll('.requirement-install-hint').forEach(hint => {
                hint.addEventListener('click', (e) => {
                    const pkg = e.target.dataset.package;
                    const name = e.target.dataset.name;
                    const folder = e.target.dataset.folder;
                    this.installPackageInline(name, pkg, folder);
                });
            });
            
            // Add click handlers for jump to packages button
            container.querySelectorAll('.requirement-jump-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const packageName = btn.dataset.package;
                    this.jumpToPackage(packageName);
                });
            });
        } catch (error) {
            console.error('Error loading requirements:', error);
            container.innerHTML = '<div class="no-requirements">Error loading requirements</div>';
        }
    }
    
    async installPackageInline(packageName, rawSpec, folderName) {
        const confirmed = await this.showConfirm({
            title: `Install "${packageName}"?`,
            message: `This will run: pip install ${rawSpec}`,
            type: 'info',
            confirmText: 'Install'
        });
        if (!confirmed) return;
        
        this.log(`Installing package: ${rawSpec}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/install-package`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: rawSpec })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Installed: ${packageName}`, 'success');
                this.showToast('success', `Installed ${packageName}`);
                // Reload requirements
                await this.loadRequirementsInline(folderName);
            } else {
                this.log(`Installation failed: ${data.message}`, 'error');
                this.showToast('error', `Failed to install ${packageName}`);
            }
        } catch (error) {
            console.error('Error installing package:', error);
            this.log(`Installation error: ${error.message}`, 'error');
            this.showToast('error', `Failed to install ${packageName}`);
        }
    }
    
    async updateNodeInline(folderName) {
        const node = this.nodes.find(n => n.folder_name === folderName);
        if (!node) return;
        
        this.log(`Updating "${node.display_name}" (${folderName})...`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/update`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Update complete: ${data.message}`, 'success');
                this.showToast('success', data.message);
            } else {
                this.log(`Update failed: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.log(`Update error: ${error.message}`, 'error');
            this.showToast('error', 'Failed to update node');
        }
    }
    
    async openFolderInline(folderName) {
        try {
            await fetch(`${this.apiBase}/api/nodes/${folderName}/open-folder`, { method: 'POST' });
        } catch (error) {
            this.showToast('error', 'Failed to open folder');
        }
    }
    
    async deactivateNodeInline(folderName) {
        const node = this.nodes.find(n => n.folder_name === folderName);
        if (!node) return;
        
        const confirmed = await this.showConfirm({
            title: `Deactivate "${node.display_name}"?`,
            message: `Restart ComfyUI for changes to take effect.`,
            type: 'warning',
            confirmText: 'Deactivate'
        });
        if (!confirmed) return;
        
        this.log(`Deactivating "${node.display_name}"...`, 'warning');
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/deactivate`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Deactivated: ${data.message}`, 'success');
                this.showToast('success', data.message);
                this.closeNodeDetails(folderName);
                await this.refreshNodes();
            } else {
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.showToast('error', 'Failed to deactivate node');
        }
    }
    
    async removeNodeInline(folderName) {
        const node = this.nodes.find(n => n.folder_name === folderName);
        if (!node) return;
        
        // Store git URL for potential recovery
        const gitUrl = node.github_url || node.git_url;
        
        if (this.settings.confirmRemove) {
            const hasGit = gitUrl ? '\n\nNote: This node can be reinstalled from GitHub if needed.' : '';
            const confirmed = await this.showConfirm({
                title: `Remove "${node.display_name}"?`,
                message: `This will PERMANENTLY DELETE the folder.${hasGit}`,
                type: 'danger',
                confirmText: 'Delete',
                confirmClass: 'btn-danger'
            });
            if (!confirmed) return;
            
            const doubleConfirmed = await this.showConfirm({
                title: 'Are you ABSOLUTELY SURE?',
                message: `Folder: ${folderName}\n\nClick Delete to confirm permanent deletion.`,
                type: 'danger',
                confirmText: 'Delete',
                confirmClass: 'btn-danger'
            });
            if (!doubleConfirmed) return;
        }
        
        this.log(`Removing "${node.display_name}"...`, 'warning');
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/remove`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Removed: ${data.message}`, 'success');
                this.closeNodeDetails(folderName);
                await this.refreshNodes();
                
                // If it was a git repo, offer undo via reinstall
                if (gitUrl) {
                    this.pushUndo({
                        type: 'remove_node',
                        message: `Removed "${node.display_name}"`,
                        undo: async () => {
                            this.showToast('info', `Reinstalling "${node.display_name}"...`);
                            await this.installFromUrlDirect(gitUrl);
                        }
                    });
                } else {
                    this.showToast('success', data.message);
                }
            } else {
                this.showToast('error', this.parseError(data.message, 'Failed to remove node'));
            }
        } catch (error) {
            console.error('Error removing node:', error);
            this.showErrorWithRetry(
                this.parseError(error, 'Failed to remove node'),
                () => this.removeNodeInline(folderName)
            );
        }
    }
    
    /**
     * Install from URL without opening modal (for undo operations)
     */
    async installFromUrlDirect(url) {
        try {
            const response = await this.withRetry(
                () => fetch(`${this.apiBase}/api/nodes/install`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                }),
                { retries: 1 }
            );
            
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', 'Node reinstalled successfully');
                await this.refreshNodes();
            } else {
                throw new Error(data.message || 'Installation failed');
            }
        } catch (error) {
            this.showErrorWithRetry(
                this.parseError(error, 'Failed to reinstall node'),
                () => this.installFromUrlDirect(url)
            );
        }
    }
    
    addTagToNode(folderName, tag) {
        tag = tag.trim();
        if (!tag) return;
        
        const currentTags = this.getTags(folderName);
        if (!currentTags.includes(tag)) {
            currentTags.push(tag);
            this.setTags(folderName, currentTags);
            
            // Re-render the expanded detail if it's open
            if (this.selectedNode && this.selectedNode.folder_name === folderName) {
                const detailSection = document.getElementById(`detail-${folderName}`);
                if (detailSection) {
                    const node = this.nodes.find(n => n.folder_name === folderName);
                    if (node) {
                        detailSection.innerHTML = this.buildExpandedDetailHTML(node);
                        this.loadRequirementsInline(folderName);
                    }
                }
            }
        }
    }
    
    removeTagFromNode(folderName, tag) {
        const currentTags = this.getTags(folderName);
        const newTags = currentTags.filter(t => t !== tag);
        this.setTags(folderName, newTags);
        
        // Re-render the expanded detail if it's open
        if (this.selectedNode && this.selectedNode.folder_name === folderName) {
            const detailSection = document.getElementById(`detail-${folderName}`);
            if (detailSection) {
                const node = this.nodes.find(n => n.folder_name === folderName);
                if (node) {
                    detailSection.innerHTML = this.buildExpandedDetailHTML(node);
                    this.loadRequirementsInline(folderName);
                }
            }
        }
    }
    
    async loadRequirements(folderName) {
        // Show loading state
        this.requirementsList.innerHTML = '<div class="no-requirements">Loading requirements...</div>';
        this.requirementsCount.textContent = '';
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/requirements`);
            const data = await response.json();
            
            if (!data.success || data.requirements.length === 0) {
                this.requirementsList.innerHTML = '<div class="no-requirements">No requirements.txt found</div>';
                this.requirementsCount.textContent = '0 packages';
                return;
            }
            
            // Update count
            const installed = data.installed || 0;
            const total = data.total || 0;
            const missing = data.missing || 0;
            const warnings = data.warnings || 0;
            
            this.requirementsCount.innerHTML = `
                <span style="color: var(--accent-success)">${installed} installed</span>
                ${missing > 0 ? `<span style="color: var(--accent-danger)">, ${missing} missing</span>` : ''}
                ${warnings > 0 ? `<span style="color: var(--accent-warning)">, ${warnings} warnings</span>` : ''}
            `;
            
            // Render requirements
            this.requirementsList.innerHTML = '';
            
            for (const req of data.requirements) {
                const item = document.createElement('div');
                item.className = `requirement-item ${req.status}`;
                item.dataset.package = req.name;
                
                let icon = '';
                let hint = '';
                
                switch (req.status) {
                    case 'installed':
                        icon = `<svg class="requirement-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                            <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>
                            <polyline points="22 4 12 14.01 9 11.01"/>
                        </svg>`;
                        break;
                    case 'missing':
                        icon = `<svg class="requirement-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                            <circle cx="12" cy="12" r="10"/>
                            <line x1="15" y1="9" x2="9" y2="15"/>
                            <line x1="9" y1="9" x2="15" y2="15"/>
                        </svg>`;
                        hint = '<span class="requirement-install-hint">Click to install</span>';
                        break;
                    case 'warning':
                        icon = `<svg class="requirement-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                            <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
                            <line x1="12" y1="9" x2="12" y2="13"/>
                            <line x1="12" y1="17" x2="12.01" y2="17"/>
                        </svg>`;
                        break;
                }
                
                // Check if this is a git requirement
                const isGitReq = req.is_git || req.raw?.includes('github.com') || req.raw?.startsWith('git+');
                
                // Jump to packages button (only for non-git requirements)
                const jumpBtn = !isGitReq ? `
                    <button class="requirement-jump-btn" data-package="${this.escapeHtml(req.name)}" title="View in Packages tab">
                        <svg viewBox="0 0 24 24" fill="currentColor">
                            <path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/>
                        </svg>
                    </button>
                ` : '';
                
                item.innerHTML = `
                    ${icon}
                    <span class="requirement-name">${this.escapeHtml(req.name)}</span>
                    <span class="requirement-version" title="${this.escapeHtml(req.message || '')}">${this.escapeHtml(req.message || req.version_spec || '')}</span>
                    ${hint}
                    ${jumpBtn}
                `;
                
                // Add click handler for missing packages
                if (req.status === 'missing') {
                    item.addEventListener('click', (e) => {
                        // Don't trigger install if clicking the jump button
                        if (!e.target.closest('.requirement-jump-btn')) {
                            this.installPackage(req.name, req.raw, item);
                        }
                    });
                }
                
                // Add click handler for jump button
                const jumpBtnEl = item.querySelector('.requirement-jump-btn');
                if (jumpBtnEl) {
                    jumpBtnEl.addEventListener('click', (e) => {
                        e.stopPropagation();
                        this.jumpToPackage(req.name);
                    });
                }
                
                this.requirementsList.appendChild(item);
            }
        } catch (error) {
            console.error('Error loading requirements:', error);
            this.requirementsList.innerHTML = '<div class="no-requirements">Error loading requirements</div>';
        }
    }
    
    async installPackage(packageName, rawSpec, itemElement) {
        const confirmed = await this.showConfirm({
            title: `Install "${packageName}"?`,
            message: `This will run: pip install ${rawSpec}`,
            type: 'info',
            confirmText: 'Install'
        });
        if (!confirmed) return;
        
        // Show installing state
        itemElement.classList.add('installing');
        itemElement.querySelector('.requirement-install-hint').textContent = 'Installing...';
        
        this.log(`Installing package: ${rawSpec}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/install-package`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ package_name: rawSpec })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Installed: ${packageName}`, 'success');
                this.showToast('success', `Installed ${packageName}`);
                
                // Reload requirements to update status
                if (this.selectedNode) {
                    await this.loadRequirements(this.selectedNode.folder_name);
                }
            } else {
                this.log(`Installation failed: ${data.message}`, 'error');
                this.showToast('error', `Failed to install ${packageName}`);
                itemElement.classList.remove('installing');
                itemElement.querySelector('.requirement-install-hint').textContent = 'Click to install';
            }
        } catch (error) {
            console.error('Error installing package:', error);
            this.log(`Installation error: ${error.message}`, 'error');
            this.showToast('error', `Failed to install ${packageName}`);
            itemElement.classList.remove('installing');
            itemElement.querySelector('.requirement-install-hint').textContent = 'Click to install';
        }
    }
    
    closeDetailPanel() {
        // Close old side panel if it exists
        if (this.detailPanel) {
            this.detailPanel.style.display = 'none';
        }
        
        // Close any expanded node details
        if (this.selectedNode) {
            this.closeNodeDetails(this.selectedNode.folder_name);
        }
        this.selectedNode = null;
    }
    
    async updateSelectedNode() {
        if (!this.selectedNode || !this.selectedNode.is_git_repo) return;
        
        const nodeName = this.selectedNode.display_name;
        const folderName = this.selectedNode.folder_name;
        
        this.detailUpdate.disabled = true;
        this.detailUpdate.innerHTML = `
            <div class="loading-spinner" style="width: 16px; height: 16px; margin: 0;"></div>
            Updating...
        `;
        
        this.log(`Updating "${nodeName}" (${folderName})...`, 'info');
        this.log(`Running: git pull`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/update`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Update complete: ${data.message}`, 'success');
                this.showToast('success', data.message);
            } else {
                this.log(`Update failed: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            console.error('Error updating node:', error);
            this.log(`Update error: ${error.message}`, 'error');
            this.showToast('error', 'Failed to update node');
        } finally {
            this.detailUpdate.disabled = false;
            this.detailUpdate.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M23 4v6h-6"/>
                    <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/>
                </svg>
                Update
            `;
        }
    }
    
    async openNodeFolder() {
        if (!this.selectedNode) return;
        
        try {
            await fetch(`${this.apiBase}/api/nodes/${this.selectedNode.folder_name}/open-folder`, {
                method: 'POST'
            });
        } catch (error) {
            console.error('Error opening folder:', error);
            this.showToast('error', 'Failed to open folder');
        }
    }
    
    async deactivateSelectedNode() {
        if (!this.selectedNode) return;
        
        const nodeName = this.selectedNode.display_name;
        const folderName = this.selectedNode.folder_name;
        
        // Confirm action
        const confirmed = await this.showConfirm({
            title: `Deactivate "${nodeName}"?`,
            message: `This will rename the folder to "${folderName}.disabled".\nYou can reactivate it later.\n\nRestart ComfyUI for changes to take effect.`,
            type: 'warning',
            confirmText: 'Deactivate'
        });
        if (!confirmed) return;
        
        this.detailDeactivate.disabled = true;
        this.log(`Deactivating "${nodeName}"...`, 'warning');
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/deactivate`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Deactivated: ${data.message}`, 'success');
                this.showToast('success', data.message);
                this.closeDetailPanel();
                await this.refreshNodes();
            } else {
                this.log(`Deactivation failed: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            console.error('Error deactivating node:', error);
            this.log(`Deactivation error: ${error.message}`, 'error');
            this.showToast('error', 'Failed to deactivate node');
        } finally {
            this.detailDeactivate.disabled = false;
        }
    }
    
    async removeSelectedNode() {
        if (!this.selectedNode) return;
        
        const nodeName = this.selectedNode.display_name;
        const folderName = this.selectedNode.folder_name;
        
        // Double confirm for destructive action (if enabled)
        if (this.settings.confirmRemove) {
            const confirmed = await this.showConfirm({
                title: `Remove "${nodeName}"?`,
                message: `This will PERMANENTLY DELETE the folder:\n${folderName}\n\nThis action cannot be undone!`,
                type: 'danger',
                confirmText: 'Delete',
                confirmClass: 'btn-danger'
            });
            if (!confirmed) return;
            
            const doubleConfirmed = await this.showConfirm({
                title: 'Are you ABSOLUTELY SURE?',
                message: `Type of action: PERMANENT DELETION\nFolder: ${folderName}\n\nClick Delete to confirm.`,
                type: 'danger',
                confirmText: 'Delete',
                confirmClass: 'btn-danger'
            });
            if (!doubleConfirmed) return;
        }
        
        this.detailRemove.disabled = true;
        this.log(`Removing "${nodeName}" (${folderName})...`, 'warning');
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/remove`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Removed: ${data.message}`, 'success');
                this.showToast('success', data.message);
                this.closeDetailPanel();
                await this.refreshNodes();
            } else {
                this.log(`Removal failed: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            console.error('Error removing node:', error);
            this.log(`Removal error: ${error.message}`, 'error');
            this.showToast('error', 'Failed to remove node');
        } finally {
            this.detailRemove.disabled = false;
        }
    }
    
    // Install Modal
    openInstallModal() {
        this.gitUrlInput.value = '';
        this.folderNameInput.value = '';
        this.installDepsCheckbox.checked = true;
        this.installModal.classList.add('show');
        this.gitUrlInput.focus();
    }
    
    closeInstallModal() {
        this.installModal.classList.remove('show');
    }
    
    async installFromUrl() {
        const url = this.gitUrlInput.value.trim();
        if (!url) {
            this.showToast('error', 'Please enter a Git URL');
            return;
        }
        
        const folderName = this.folderNameInput.value.trim() || null;
        const installDeps = this.installDepsCheckbox.checked;
        
        this.modalInstall.disabled = true;
        this.modalInstall.innerHTML = `
            <div class="loading-spinner" style="width: 16px; height: 16px; margin: 0;"></div>
            Cloning...
        `;
        
        this.log(`Installing from URL: ${url}`, 'info');
        this.log(`Running: git clone ${url}`, 'info');
        if (installDeps) {
            this.log('Will install requirements.txt after cloning', 'info');
        }
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, folder_name: folderName, install_deps: installDeps })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Installation complete: ${data.message}`, 'success');
                this.showToast('success', data.message);
                this.closeInstallModal();
                await this.refreshNodes();
            } else {
                this.log(`Installation failed: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            console.error('Error installing node:', error);
            this.log(`Installation error: ${error.message}`, 'error');
            this.showToast('error', 'Failed to install node');
        } finally {
            this.modalInstall.disabled = false;
            this.modalInstall.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                Clone Repository
            `;
        }
    }
    
    // Toast notifications
    showToast(type, message) {
        const icons = {
            success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
            error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
            info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
            warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
        };
        
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${icons[type]}</span>
            <span class="toast-message">${this.escapeHtml(message)}</span>
            <button class="toast-close">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"/>
                    <line x1="6" y1="6" x2="18" y2="18"/>
                </svg>
            </button>
        `;
        
        toast.querySelector('.toast-close').addEventListener('click', () => {
            toast.remove();
        });
        
        this.toastContainer.appendChild(toast);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (toast.parentNode) {
                toast.style.animation = 'fadeIn 0.3s ease reverse';
                setTimeout(() => toast.remove(), 300);
            }
        }, 5000);
    }
    
    // Custom confirm modal
    showConfirm(options = {}) {
        return new Promise((resolve) => {
            const {
                title = 'Confirm',
                message = 'Are you sure?',
                type = 'info', // info, warning, danger, success
                confirmText = 'OK',
                cancelText = 'Cancel',
                confirmClass = '' // optional: btn-danger, btn-warning, etc.
            } = options;
            
            const modal = document.getElementById('confirm-modal');
            const iconEl = document.getElementById('confirm-icon');
            const titleEl = document.getElementById('confirm-title');
            const messageEl = document.getElementById('confirm-message');
            const okBtn = document.getElementById('confirm-ok-btn');
            const cancelBtn = document.getElementById('confirm-cancel-btn');
            
            if (!modal) {
                // Fallback to native confirm if modal not found
                resolve(confirm(message));
                return;
            }
            
            // Set content
            titleEl.textContent = title;
            messageEl.textContent = message;
            okBtn.textContent = confirmText;
            cancelBtn.textContent = cancelText;
            
            // Set icon type
            iconEl.className = `confirm-icon ${type}`;
            
            // Set icon SVG based on type (explicit width/height for consistent sizing)
            const icons = {
                info: '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
                warning: '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
                danger: '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
                success: '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'
            };
            iconEl.innerHTML = icons[type] || icons.info;
            
            // Set button style
            okBtn.className = `btn-primary-glass ${confirmClass || (type === 'danger' ? 'btn-danger' : '')}`;
            
            // Show modal
            modal.classList.add('show');
            
            // Handle clicks
            const handleOk = () => {
                cleanup();
                resolve(true);
            };
            
            const handleCancel = () => {
                cleanup();
                resolve(false);
            };
            
            const handleOverlay = (e) => {
                if (e.target === modal) {
                    handleCancel();
                }
            };
            
            const handleKeydown = (e) => {
                if (e.key === 'Escape') {
                    handleCancel();
                } else if (e.key === 'Enter') {
                    handleOk();
                }
            };
            
            const cleanup = () => {
                modal.classList.remove('show');
                okBtn.removeEventListener('click', handleOk);
                cancelBtn.removeEventListener('click', handleCancel);
                modal.removeEventListener('click', handleOverlay);
                document.removeEventListener('keydown', handleKeydown);
            };
            
            okBtn.addEventListener('click', handleOk);
            cancelBtn.addEventListener('click', handleCancel);
            modal.addEventListener('click', handleOverlay);
            document.addEventListener('keydown', handleKeydown);
            
            // Focus OK button
            okBtn.focus();
        });
    }
    
    showPrompt(options = {}) {
        return new Promise((resolve) => {
            const {
                title = 'Enter Value',
                message = 'Please enter a value:',
                placeholder = '',
                defaultValue = '',
                confirmText = 'OK',
                cancelText = 'Cancel'
            } = options;
            
            const modal = document.getElementById('prompt-modal');
            const titleEl = document.getElementById('prompt-title');
            const messageEl = document.getElementById('prompt-message');
            const inputEl = document.getElementById('prompt-input');
            const okBtn = document.getElementById('prompt-ok-btn');
            const cancelBtn = document.getElementById('prompt-cancel-btn');
            
            if (!modal) {
                // Fallback to native prompt if modal not found
                resolve(prompt(message, defaultValue));
                return;
            }
            
            // Set content
            titleEl.textContent = title;
            messageEl.textContent = message;
            inputEl.placeholder = placeholder;
            inputEl.value = defaultValue;
            okBtn.textContent = confirmText;
            cancelBtn.textContent = cancelText;
            
            // Show modal
            modal.classList.add('show');
            
            // Handle clicks
            const handleOk = () => {
                cleanup();
                resolve(inputEl.value);
            };
            
            const handleCancel = () => {
                cleanup();
                resolve(null);
            };
            
            const handleOverlay = (e) => {
                if (e.target === modal) {
                    handleCancel();
                }
            };
            
            const handleKeydown = (e) => {
                if (e.key === 'Escape') {
                    handleCancel();
                } else if (e.key === 'Enter') {
                    handleOk();
                }
            };
            
            const cleanup = () => {
                modal.classList.remove('show');
                okBtn.removeEventListener('click', handleOk);
                cancelBtn.removeEventListener('click', handleCancel);
                modal.removeEventListener('click', handleOverlay);
                document.removeEventListener('keydown', handleKeydown);
            };
            
            okBtn.addEventListener('click', handleOk);
            cancelBtn.addEventListener('click', handleCancel);
            modal.addEventListener('click', handleOverlay);
            document.addEventListener('keydown', handleKeydown);
            
            // Focus input and select all
            inputEl.focus();
            inputEl.select();
        });
    }
    
    showLoading(show) {
        if (!this.loadingState) {
            return;
        }
        this.loadingState.style.display = show ? 'flex' : 'none';
        if (show) {
            if (this.nodeList) {
                this.nodeList.innerHTML = '';
            }
            if (this.emptyState) {
                this.emptyState.style.display = 'none';
            }
        }
    }
    
    // Console methods
    log(message, type = 'info') {
        // Ensure consoleContent is initialized
        if (!this.consoleContent) {
            this.consoleContent = document.getElementById('console-content');
        }
        
        // If still not available, log to browser console as fallback
        if (!this.consoleContent) {
            console.log(`[MF Conductor] ${message}`);
            return;
        }
        
        const timestamp = new Date().toLocaleTimeString();
        const entry = document.createElement('div');
        entry.className = `console-entry ${type}`;
        entry.innerHTML = `
            <span class="console-timestamp">[${timestamp}]</span>
            <span class="console-message">${this.escapeHtml(message)}</span>
        `;
        
        // Remove welcome message if it exists
        const welcome = this.consoleContent.querySelector('.console-welcome');
        if (welcome) welcome.remove();
        
        this.consoleContent.appendChild(entry);
        
        // Auto-scroll to bottom
        this.consoleContent.scrollTop = this.consoleContent.scrollHeight;
        
        // Update badge
        this.logCount++;
        this.updateConsoleBadge();
    }
    
    updateConsoleBadge() {
        this.consoleBadge.textContent = this.logCount;
        this.consoleBadge.classList.toggle('empty', this.logCount === 0);
    }
    
    toggleConsole() {
        const isCollapsed = this.consolePanel.classList.toggle('collapsed');
        
        // Apply saved height when expanding
        if (!isCollapsed && this.consoleBody) {
            this.consoleBody.style.height = `${this.consoleHeight}px`;
        }
        
        // Immediately adjust main content area
        this.updateMainContentPadding();
        
        // Save preference
        this.saveUserPreferences();
    }
    
    updateMainContentPadding() {
        if (!this.consolePanel) return;
        
        const isCollapsed = this.consolePanel.classList.contains('collapsed');
        const headerHeight = 40; // Console header height
        
        // Calculate total console panel height
        let consolePanelHeight;
        if (isCollapsed) {
            consolePanelHeight = headerHeight;
        } else {
            consolePanelHeight = headerHeight + (this.consoleHeight || 300);
        }
        
        // Set CSS variable for console height so content can adjust
        document.documentElement.style.setProperty('--console-panel-height', `${consolePanelHeight}px`);
    }
    
    initConsoleResizer() {
        if (!this.consoleResizeHandle || !this.consoleBody) return;
        
        // Apply initial height
        this.consoleBody.style.height = `${this.consoleHeight}px`;
        
        // Set initial padding for main content
        this.updateMainContentPadding();
        
        let startY = 0;
        let startHeight = 0;
        let isResizing = false;
        
        const onMouseDown = (e) => {
            if (this.consolePanel.classList.contains('collapsed')) return;
            
            isResizing = true;
            startY = e.clientY;
            startHeight = this.consoleBody.offsetHeight;
            
            this.consolePanel.classList.add('resizing');
            document.body.style.cursor = 'ns-resize';
            document.body.style.userSelect = 'none';
            
            e.preventDefault();
        };
        
        const onMouseMove = (e) => {
            if (!isResizing) return;
            
            const deltaY = startY - e.clientY;
            const newHeight = Math.min(Math.max(startHeight + deltaY, 100), window.innerHeight * 0.7);
            
            this.consoleBody.style.height = `${newHeight}px`;
            this.consoleHeight = newHeight;
            
            // Update main content padding during resize
            this.updateMainContentPadding();
        };
        
        const onMouseUp = () => {
            if (!isResizing) return;
            
            isResizing = false;
            this.consolePanel.classList.remove('resizing');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
            
            // Save the height preference
            localStorage.setItem('mfc_console_height', this.consoleHeight.toString());
            
            // Final update of main content padding
            this.updateMainContentPadding();
        };
        
        this.consoleResizeHandle.addEventListener('mousedown', onMouseDown);
        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
        
        // Touch support for mobile/tablets
        this.consoleResizeHandle.addEventListener('touchstart', (e) => {
            if (this.consolePanel.classList.contains('collapsed')) return;
            const touch = e.touches[0];
            onMouseDown({ clientY: touch.clientY, preventDefault: () => {} });
        });
        
        document.addEventListener('touchmove', (e) => {
            if (!isResizing) return;
            const touch = e.touches[0];
            onMouseMove({ clientY: touch.clientY });
        });
        
        document.addEventListener('touchend', onMouseUp);
    }
    
    // Utility functions
    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    formatBytes(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }
    
    formatNumber(num) {
        if (num >= 1000000) {
            return (num / 1000000).toFixed(1) + 'M';
        }
        if (num >= 1000) {
            return (num / 1000).toFixed(1) + 'K';
        }
        return num.toString();
    }
    
    formatDate(dateStr) {
        if (!dateStr) return 'Unknown';
        try {
            const date = new Date(dateStr);
            return date.toLocaleDateString('en-US', {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch {
            return dateStr;
        }
    }
    
    formatRelativeDate(dateStr) {
        if (!dateStr) return 'Unknown';
        try {
            const date = new Date(dateStr);
            const now = new Date();
            const diffMs = now - date;
            const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
            
            if (diffDays === 0) return 'Today';
            if (diffDays === 1) return 'Yesterday';
            if (diffDays < 7) return `${diffDays} days ago`;
            if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
            if (diffDays < 365) return `${Math.floor(diffDays / 30)} months ago`;
            return `${Math.floor(diffDays / 365)} years ago`;
        } catch {
            return dateStr;
        }
    }
    
    // ==================== KEYBOARD SHORTCUTS ====================
    
    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Don't trigger if typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                if (e.key === 'Escape') {
                    e.target.blur();
                }
                return;
            }
            
            // / - Focus search
            if (e.key === '/') {
                e.preventDefault();
                this.searchInput.focus();
            }
            
            // Escape - Close modals/panels
            if (e.key === 'Escape') {
                this.closeDetailPanel();
                this.closeInstallModal();
                this.closeBrowseModal();
                this.closeSettingsModal();
                this.closeUsageModal();
                this.selectedNodes.clear();
                this.renderNodes();
            }
            
            // r - Refresh
            if (e.key === 'r' && !e.ctrlKey && !e.metaKey) {
                this.refreshNodes();
            }
            
            // n - New install
            if (e.key === 'n' && !e.ctrlKey && !e.metaKey) {
                this.openInstallModal();
            }
            
            // b - Browse nodes
            if (e.key === 'b' && !e.ctrlKey && !e.metaKey) {
                this.openBrowseModal();
            }
            
            // u - Check for updates
            if (e.key === 'u' && !e.ctrlKey && !e.metaKey) {
                this.checkAllUpdates();
            }
            
            // a - Select all (when in list view)
            if (e.key === 'a' && (e.ctrlKey || e.metaKey)) {
                e.preventDefault();
                this.selectAllNodes();
            }
            
            // Delete - Remove selected nodes
            if (e.key === 'Delete' && this.selectedNodes.size > 0) {
                this.bulkRemoveSelected();
            }
            
            // ? - Show shortcuts help
            if (e.key === '?') {
                this.showShortcutsHelp();
            }
        });
    }
    
    showShortcutsHelp() {
        const shortcuts = [
            { key: '/', desc: 'Focus search' },
            { key: 'Escape', desc: 'Close panels / Clear selection' },
            { key: 'R', desc: 'Refresh nodes' },
            { key: 'N', desc: 'Install new node' },
            { key: 'B', desc: 'Browse available nodes' },
            { key: 'U', desc: 'Check for updates' },
            { key: 'Ctrl+A', desc: 'Select all nodes' },
            { key: 'Delete', desc: 'Remove selected nodes' },
            { key: '?', desc: 'Show this help' }
        ];
        
        const html = shortcuts.map(s => `<div><kbd>${s.key}</kbd> ${s.desc}</div>`).join('');
        this.showToast('info', 'Keyboard Shortcuts:\n' + shortcuts.map(s => `${s.key}: ${s.desc}`).join('\n'));
    }
    
    // ==================== USER DATA (Favorites, Tags, Notes) ====================
    
    async loadUserData() {
        try {
            const response = await fetch(`${this.apiBase}/api/user-data`);
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    this.userData = {
                        favorites: data.favorites || [],
                        tags: data.tags || {},
                        notes: data.notes || {},
                        usage: data.usage || {}
                    };
                    const favCount = this.userData.favorites.length;
                    const tagCount = Object.keys(this.userData.tags).length;
                    this.log(`User data loaded (${favCount} favorites, ${tagCount} tagged nodes)`, 'success');
                }
            }
        } catch (error) {
            this.log(`Error loading user data: ${error.message}`, 'error');
            console.error('Error loading user data:', error);
        }
    }
    
    isFavorite(folderName) {
        return this.userData.favorites.includes(folderName);
    }
    
    async toggleFavorite(folderName) {
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/toggle-favorite`, {
                method: 'POST'
            });
            const data = await response.json();
            
            if (data.success) {
                if (data.is_favorite) {
                    if (!this.userData.favorites.includes(folderName)) {
                        this.userData.favorites.push(folderName);
                    }
                } else {
                    this.userData.favorites = this.userData.favorites.filter(f => f !== folderName);
                }
                this.renderNodes();
                this.showToast('success', data.is_favorite ? 'Added to favorites' : 'Removed from favorites');
            }
        } catch (error) {
            console.error('Error toggling favorite:', error);
            this.showToast('error', 'Failed to update favorite');
        }
    }
    
    getTags(folderName) {
        return this.userData.tags[folderName] || [];
    }
    
    async setTags(folderName, tags) {
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/tags`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tags })
            });
            const data = await response.json();
            
            if (data.success) {
                this.userData.tags[folderName] = tags;
                this.renderNodes();
            }
        } catch (error) {
            console.error('Error setting tags:', error);
        }
    }
    
    // ==================== BATCH TAG ASSIGNMENT ====================
    
    async batchAddTag() {
        if (this.selectedNodes.size === 0) {
            this.showToast('warning', 'No nodes selected. Use Ctrl+Click to select multiple nodes.');
            return;
        }
        
        // Create a simple prompt for tag input
        const tag = await this.showPrompt({
            title: 'Add Tag to Selected Nodes',
            message: `Add a tag to ${this.selectedNodes.size} selected nodes:`,
            placeholder: 'Enter tag name',
            confirmText: 'Add Tag'
        });
        
        if (!tag || !tag.trim()) return;
        
        const trimmedTag = tag.trim();
        let addedCount = 0;
        
        for (const folderName of this.selectedNodes) {
            const currentTags = this.getTags(folderName);
            if (!currentTags.includes(trimmedTag)) {
                currentTags.push(trimmedTag);
                await this.setTags(folderName, currentTags);
                addedCount++;
            }
        }
        
        this.showToast('success', `Added tag "${trimmedTag}" to ${addedCount} nodes`);
        this.selectedNodes.clear();
        this.renderNodes();
    }
    
    async batchRemoveTag() {
        if (this.selectedNodes.size === 0) {
            this.showToast('warning', 'No nodes selected. Use Ctrl+Click to select multiple nodes.');
            return;
        }
        
        // Collect all unique tags from selected nodes
        const allTags = new Set();
        for (const folderName of this.selectedNodes) {
            this.getTags(folderName).forEach(t => allTags.add(t));
        }
        
        if (allTags.size === 0) {
            this.showToast('info', 'Selected nodes have no tags');
            return;
        }
        
        // Show tag selection
        const tag = await this.showSelect({
            title: 'Remove Tag from Selected Nodes',
            message: `Remove a tag from ${this.selectedNodes.size} selected nodes:`,
            options: Array.from(allTags),
            confirmText: 'Remove Tag'
        });
        
        if (!tag) return;
        
        let removedCount = 0;
        
        for (const folderName of this.selectedNodes) {
            const currentTags = this.getTags(folderName);
            if (currentTags.includes(tag)) {
                const newTags = currentTags.filter(t => t !== tag);
                await this.setTags(folderName, newTags);
                removedCount++;
            }
        }
        
        this.showToast('success', `Removed tag "${tag}" from ${removedCount} nodes`);
        this.selectedNodes.clear();
        this.renderNodes();
    }
    
    /**
     * Show a prompt dialog
     */
    async showPrompt(options) {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'modal-overlay modal-confirm active';
            modal.innerHTML = `
                <div class="modal modal-prompt">
                    <div class="modal-header">
                        <h3>${this.escapeHtml(options.title || 'Input')}</h3>
                        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">×</button>
                    </div>
                    <div class="modal-body">
                        <p>${this.escapeHtml(options.message || '')}</p>
                        <input type="text" class="prompt-input" placeholder="${this.escapeHtml(options.placeholder || '')}" autofocus>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary cancel-btn">Cancel</button>
                        <button class="btn btn-primary confirm-btn">${this.escapeHtml(options.confirmText || 'OK')}</button>
                    </div>
                </div>
            `;
            
            const input = modal.querySelector('.prompt-input');
            const confirmBtn = modal.querySelector('.confirm-btn');
            const cancelBtn = modal.querySelector('.cancel-btn');
            
            const close = (value) => {
                modal.remove();
                resolve(value);
            };
            
            confirmBtn.addEventListener('click', () => close(input.value));
            cancelBtn.addEventListener('click', () => close(null));
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') close(input.value);
                if (e.key === 'Escape') close(null);
            });
            modal.addEventListener('click', (e) => {
                if (e.target === modal) close(null);
            });
            
            document.body.appendChild(modal);
            input.focus();
        });
    }
    
    /**
     * Show a select dialog
     */
    async showSelect(options) {
        return new Promise((resolve) => {
            const optionsHtml = options.options.map(opt => 
                `<option value="${this.escapeHtml(opt)}">${this.escapeHtml(opt)}</option>`
            ).join('');
            
            const modal = document.createElement('div');
            modal.className = 'modal-overlay modal-confirm active';
            modal.innerHTML = `
                <div class="modal modal-prompt">
                    <div class="modal-header">
                        <h3>${this.escapeHtml(options.title || 'Select')}</h3>
                        <button class="modal-close" onclick="this.closest('.modal-overlay').remove()">×</button>
                    </div>
                    <div class="modal-body">
                        <p>${this.escapeHtml(options.message || '')}</p>
                        <select class="prompt-select">${optionsHtml}</select>
                    </div>
                    <div class="modal-footer">
                        <button class="btn btn-secondary cancel-btn">Cancel</button>
                        <button class="btn btn-primary confirm-btn">${this.escapeHtml(options.confirmText || 'OK')}</button>
                    </div>
                </div>
            `;
            
            const select = modal.querySelector('.prompt-select');
            const confirmBtn = modal.querySelector('.confirm-btn');
            const cancelBtn = modal.querySelector('.cancel-btn');
            
            const close = (value) => {
                modal.remove();
                resolve(value);
            };
            
            confirmBtn.addEventListener('click', () => close(select.value));
            cancelBtn.addEventListener('click', () => close(null));
            modal.addEventListener('click', (e) => {
                if (e.target === modal) close(null);
            });
            
            document.body.appendChild(modal);
        });
    }
    
    getAllTags() {
        const tags = new Set();
        Object.values(this.userData.tags).forEach(nodeTags => {
            nodeTags.forEach(tag => tags.add(tag));
        });
        return Array.from(tags).sort();
    }
    
    getNote(folderName) {
        return this.userData.notes[folderName] || '';
    }
    
    async setNote(folderName, note) {
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/note`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ note })
            });
            const data = await response.json();
            
            if (data.success) {
                if (note) {
                    this.userData.notes[folderName] = note;
                } else {
                    delete this.userData.notes[folderName];
                }
            }
        } catch (error) {
            console.error('Error setting note:', error);
        }
    }
    
    // ==================== PROFILES ====================
    
    async getProfiles() {
        try {
            const response = await fetch(`${this.apiBase}/api/profiles`);
            const data = await response.json();
            return data.success ? data.profiles : {};
        } catch (error) {
            console.error('Error getting profiles:', error);
            return {};
        }
    }
    
    // Removed duplicate saveProfile - using the version in Profile Editor section
    
    async applyProfile(name) {
        const confirmed = await this.showConfirm({
            title: `Apply profile "${name}"?`,
            message: `This will enable/disable nodes according to the profile.\nRestart ComfyUI for changes to take effect.`,
            type: 'info',
            confirmText: 'Apply'
        });
        if (!confirmed) return;
        
        this.log(`Applying profile: ${name}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/profiles/apply`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            const data = await response.json();
            
            if (data.success) {
                const results = data.results;
                this.log(`Enabled: ${results.enabled.length}, Disabled: ${results.disabled.length}`, 'success');
                if (results.errors.length > 0) {
                    results.errors.forEach(err => this.log(err, 'warning'));
                }
                this.showToast('success', 'Profile applied. Restart ComfyUI for changes.');
                await this.refreshNodes();
            } else {
                this.showToast('error', data.message);
            }
        } catch (error) {
            console.error('Error applying profile:', error);
            this.showToast('error', 'Failed to apply profile');
        }
    }
    
    async deleteProfile(name) {
        const confirmed = await this.showConfirm({
            title: `Delete profile "${name}"?`,
            message: `This profile will be permanently deleted.`,
            type: 'danger',
            confirmText: 'Delete',
            confirmClass: 'btn-danger'
        });
        if (!confirmed) return;
        
        this.log(`Deleting profile: ${name}`, 'warning');
        try {
            const response = await fetch(`${this.apiBase}/api/profiles/delete`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            const data = await response.json();
            
            if (data.success) {
                this.log(`Profile "${name}" deleted successfully`, 'success');
                this.showToast('success', `Profile "${name}" deleted`);
            } else {
                this.log(`Failed to delete profile: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            this.log(`Error deleting profile: ${error.message}`, 'error');
            console.error('Error deleting profile:', error);
        }
    }
    
    // ==================== BACKUP / RESTORE ====================
    
    async exportBackup() {
        this.log('Exporting backup...', 'info');
        try {
            const response = await fetch(`${this.apiBase}/api/backup`);
            const data = await response.json();
            
            if (data.success) {
                const blob = new Blob([JSON.stringify(data.backup, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                const filename = `mf_conductor_backup_${new Date().toISOString().split('T')[0]}.json`;
                a.download = filename;
                a.click();
                URL.revokeObjectURL(url);
                this.log(`Backup exported successfully: ${filename}`, 'success');
                this.showToast('success', 'Backup exported');
            } else {
                this.log(`Failed to export backup: ${data.message}`, 'error');
                this.showToast('error', 'Failed to export backup');
            }
        } catch (error) {
            this.log(`Error exporting backup: ${error.message}`, 'error');
            console.error('Error exporting backup:', error);
            this.showToast('error', 'Failed to export backup');
        }
    }
    
    async importBackup() {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        
        input.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            this.log(`Importing backup from: ${file.name}`, 'info');
            try {
                const text = await file.text();
                const backupData = JSON.parse(text);
                
                const merge = await this.showConfirm({
                    title: 'Merge with existing data?',
                    message: `Click Merge to combine with existing data, or Replace to overwrite all data.`,
                    type: 'info',
                    confirmText: 'Merge',
                    cancelText: 'Replace'
                });
                
                this.log(`Importing backup (${merge ? 'merge' : 'replace'} mode)...`, 'info');
                const response = await fetch(`${this.apiBase}/api/backup/import`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ data: backupData, merge })
                });
                const data = await response.json();
                
                if (data.success) {
                    this.log('Backup imported successfully', 'success');
                    this.showToast('success', 'Backup imported successfully');
                    await this.loadUserData();
                    this.renderNodes();
                } else {
                    this.log(`Failed to import backup: ${data.message}`, 'error');
                    this.showToast('error', data.message);
                }
            } catch (error) {
                this.log(`Error importing backup: ${error.message}`, 'error');
                console.error('Error importing backup:', error);
                this.showToast('error', 'Failed to import backup - invalid file');
            }
        };
        
        input.click();
    }
    
    async exportNodeList() {
        try {
            const response = await fetch(`${this.apiBase}/api/export-nodes`);
            const data = await response.json();
            
            if (data.success) {
                const blob = new Blob([JSON.stringify(data.data, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `comfyui_nodes_${new Date().toISOString().split('T')[0]}.json`;
                a.click();
                URL.revokeObjectURL(url);
                this.showToast('success', `Exported ${data.data.node_count} nodes`);
            }
        } catch (error) {
            console.error('Error exporting node list:', error);
            this.showToast('error', 'Failed to export node list');
        }
    }
    
    // ==================== UPDATE CHECKING ====================
    
    async checkAllUpdates() {
        this.log('Checking all nodes for updates...', 'info');
        this.showToast('info', 'Checking for updates...');
        
        try {
            const response = await this.withRetry(
                () => fetch(`${this.apiBase}/api/check-updates`),
                { retries: 2, retryDelay: 1000 }
            );
            const data = await response.json();
            
            if (data.success) {
                this.updateStatus = data.nodes;
                const count = data.updates_available;
                this.nodesWithUpdates = count;
                
                // Update the badge on the Nodes tab
                this.updateNodesBadge(count);
                
                if (count > 0) {
                    this.log(`Found ${count} nodes with updates available`, 'success');
                    this.showToast('info', `${count} updates available`);
                } else {
                    this.log('All nodes are up to date', 'success');
                    this.showToast('success', 'All nodes are up to date');
                }
                
                this.renderNodes(); // Re-render to show update badges
            }
        } catch (error) {
            console.error('Error checking updates:', error);
            this.log(`Update check failed: ${error.message}`, 'error');
            this.showErrorWithRetry(
                this.parseError(error, 'Failed to check for updates'),
                () => this.checkAllUpdates()
            );
        }
    }
    
    /**
     * Update the badge on the Nodes tab showing available updates
     * @param {number} count - Number of updates available
     */
    updateNodesBadge(count) {
        // Update the sidebar nodes update badge
        const nodesUpdateBadge = document.getElementById('nodes-update-badge');
        if (nodesUpdateBadge) {
            if (count > 0) {
                nodesUpdateBadge.classList.remove('hidden');
            } else {
                nodesUpdateBadge.classList.add('hidden');
            }
        }
        
        // Legacy support for old tab badge
        const nodesTab = document.querySelector('.main-tab[data-tab="nodes"]');
        if (!nodesTab) return;
        
        // Remove existing badge
        const existingBadge = nodesTab.querySelector('.tab-badge');
        if (existingBadge) existingBadge.remove();
        
        // Add badge if there are updates
        if (count > 0) {
            const badge = document.createElement('span');
            badge.className = 'tab-badge';
            badge.textContent = count > 99 ? '99+' : count;
            badge.title = `${count} updates available`;
            nodesTab.appendChild(badge);
        }
    }
    
    async batchUpdateAll() {
        const nodesWithUpdates = Object.entries(this.updateStatus)
            .filter(([_, status]) => status.has_updates)
            .map(([folder, _]) => folder);
        
        if (nodesWithUpdates.length === 0) {
            this.showToast('info', 'No updates available');
            return;
        }
        
        const confirmed = await this.showConfirm({
            title: `Update ${nodesWithUpdates.length} nodes?`,
            message: `This will run git pull on all nodes with available updates.`,
            type: 'info',
            confirmText: 'Update All'
        });
        if (!confirmed) return;
        
        this.log(`Batch updating ${nodesWithUpdates.length} nodes...`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/batch-update`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_names: nodesWithUpdates })
            });
            const data = await response.json();
            
            if (data.success) {
                this.log(`Updated ${data.updated}/${data.total} nodes`, 'success');
                
                // Log individual results
                Object.entries(data.results).forEach(([folder, result]) => {
                    if (result.success) {
                        this.log(`  ${folder}: ${result.message}`, 'success');
                    } else {
                        this.log(`  ${folder}: ${result.message}`, 'error');
                    }
                });
                
                this.showToast('success', `Updated ${data.updated} nodes`);
                this.updateStatus = {};
                await this.refreshNodes();
            }
        } catch (error) {
            console.error('Error batch updating:', error);
            this.showToast('error', 'Batch update failed');
        }
    }
    
    // ==================== DISK USAGE ====================
    
    async loadDiskUsage() {
        try {
            const response = await fetch(`${this.apiBase}/api/disk-usage`);
            const data = await response.json();
            
            if (data.success) {
                this.diskUsage = data.nodes;
                this.log(`Total disk usage: ${data.total_size_formatted}`, 'info');
            }
        } catch (error) {
            console.error('Error loading disk usage:', error);
        }
    }
    
    getDiskUsage(folderName) {
        return this.diskUsage[folderName];
    }
    
    // ==================== BULK SELECTION ====================
    
    toggleNodeSelection(folderName, event) {
        if (event) event.stopPropagation();
        
        if (this.selectedNodes.has(folderName)) {
            this.selectedNodes.delete(folderName);
        } else {
            this.selectedNodes.add(folderName);
        }
        
        this.updateSelectionUI();
    }
    
    selectAllNodes() {
        if (this.selectedNodes.size === this.filteredNodes.length) {
            this.selectedNodes.clear();
        } else {
            this.filteredNodes.forEach(node => this.selectedNodes.add(node.folder_name));
        }
        this.updateSelectionUI();
    }
    
    updateSelectionUI() {
        // Update visual state of all nodes
        document.querySelectorAll('.node-card, .node-row').forEach(el => {
            const isSelected = this.selectedNodes.has(el.dataset.folder);
            el.classList.toggle('selected', isSelected);
        });
        
        // Show/hide bulk actions toolbar
        const bulkBar = document.getElementById('bulk-actions-bar');
        if (bulkBar) {
            bulkBar.style.display = this.selectedNodes.size > 0 ? 'flex' : 'none';
            const countEl = bulkBar.querySelector('.selection-count');
            if (countEl) countEl.textContent = `${this.selectedNodes.size} selected`;
        }
        
        // Show/hide batch tag buttons
        const batchTagBtns = document.getElementById('batch-tag-btns');
        if (batchTagBtns) {
            batchTagBtns.style.display = this.selectedNodes.size > 0 ? 'flex' : 'none';
        }
    }
    
    async bulkUpdateSelected() {
        if (this.selectedNodes.size === 0) return;
        
        const folders = Array.from(this.selectedNodes);
        
        const confirmed = await this.showConfirm({
            title: `Update ${folders.length} selected nodes?`,
            message: `This will run git pull on all selected nodes.`,
            type: 'info',
            confirmText: 'Update All'
        });
        if (!confirmed) return;
        
        this.log(`Updating ${folders.length} selected nodes...`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/batch-update`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_names: folders })
            });
            const data = await response.json();
            
            if (data.success) {
                this.log(`Updated ${data.updated}/${data.total} nodes`, 'success');
                this.showToast('success', `Updated ${data.updated} nodes`);
                this.selectedNodes.clear();
                await this.refreshNodes();
            }
        } catch (error) {
            console.error('Error bulk updating:', error);
            this.showToast('error', 'Bulk update failed');
        }
    }
    
    async bulkDeactivateSelected() {
        if (this.selectedNodes.size === 0) return;
        
        const folders = Array.from(this.selectedNodes);
        
        const confirmed = await this.showConfirm({
            title: `Deactivate ${folders.length} selected nodes?`,
            message: `Restart ComfyUI for changes to take effect.`,
            type: 'warning',
            confirmText: 'Deactivate All'
        });
        if (!confirmed) return;
        
        this.log(`Deactivating ${folders.length} nodes...`, 'warning');
        
        for (const folder of folders) {
            try {
                await fetch(`${this.apiBase}/api/nodes/${folder}/deactivate`, { method: 'POST' });
            } catch (e) {}
        }
        
        this.selectedNodes.clear();
        await this.refreshNodes();
        this.showToast('success', 'Nodes deactivated. Restart ComfyUI.');
    }
    
    async bulkRemoveSelected() {
        if (this.selectedNodes.size === 0) return;
        
        const folders = Array.from(this.selectedNodes);
        
        const confirmed = await this.showConfirm({
            title: `Delete ${folders.length} selected nodes?`,
            message: `This will PERMANENTLY DELETE all selected nodes.\nThis cannot be undone!`,
            type: 'danger',
            confirmText: 'Delete All',
            confirmClass: 'btn-danger'
        });
        if (!confirmed) return;
        
        const doubleConfirmed = await this.showConfirm({
            title: 'Are you ABSOLUTELY SURE?',
            message: `You are about to delete ${folders.length} nodes permanently.`,
            type: 'danger',
            confirmText: 'Yes, Delete All',
            confirmClass: 'btn-danger'
        });
        if (!doubleConfirmed) return;
        
        this.log(`Removing ${folders.length} nodes...`, 'warning');
        
        let removed = 0;
        for (const folder of folders) {
            try {
                const response = await fetch(`${this.apiBase}/api/nodes/${folder}/remove`, { method: 'POST' });
                const data = await response.json();
                if (data.success) removed++;
            } catch (e) {}
        }
        
        this.selectedNodes.clear();
        await this.refreshNodes();
        this.showToast('success', `Removed ${removed} nodes`);
    }
    
    // ==================== BROWSE NEW NODES ====================
    
    async openBrowseModal() {
        const modal = document.getElementById('browse-modal');
        if (modal) {
            modal.classList.add('show');
            this.initBrowseControls();
            await this.loadBrowseNodes();
        }
    }
    
    initBrowseControls() {
        // Only init once
        if (this.browseInitialized) return;
        this.browseInitialized = true;
        
        // Browse state - preserve browseViewMode if already loaded from preferences
        this.browseSearch = '';
        this.browseCategory = '';
        this.browseSort = 'stars';
        this.browseSortDesc = true;
        if (!this.browseViewMode) {
            this.browseViewMode = 'grid';
        }
        
        const searchInput = document.getElementById('browse-search');
        const hideInstalledCheckbox = document.getElementById('browse-hide-installed');
        const sortSelect = document.getElementById('browse-sort');
        const sortDirBtn = document.getElementById('browse-sort-dir');
        const viewGridBtn = document.getElementById('browse-view-grid');
        const viewListBtn = document.getElementById('browse-view-list');
        const refreshBtn = document.getElementById('browse-refresh');
        
        // Debounced search
        let searchTimeout;
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    this.browseSearch = searchInput.value;
                    this.filterBrowseNodes();
                }, 200);
            });
        }
        
        // Hide installed toggle
        if (hideInstalledCheckbox) {
            hideInstalledCheckbox.addEventListener('change', () => {
                this.browseHideInstalled = hideInstalledCheckbox.checked;
                this.filterBrowseNodes();
            });
        }
        
        // Sort
        if (sortSelect) {
            sortSelect.addEventListener('change', () => {
                this.browseSort = sortSelect.value;
                this.filterBrowseNodes();
            });
        }
        
        // Sort direction
        if (sortDirBtn) {
            sortDirBtn.addEventListener('click', () => {
                this.browseSortDesc = !this.browseSortDesc;
                sortDirBtn.classList.toggle('desc', this.browseSortDesc);
                this.filterBrowseNodes();
            });
            sortDirBtn.classList.add('desc');
        }
        
        // View toggle
        if (viewGridBtn) {
            viewGridBtn.addEventListener('click', () => {
                this.browseViewMode = 'grid';
                viewGridBtn.classList.add('active');
                viewListBtn?.classList.remove('active');
                this.saveUserPreferences();
                this.renderBrowseNodes();
            });
        }
        if (viewListBtn) {
            viewListBtn.addEventListener('click', () => {
                this.browseViewMode = 'list';
                viewListBtn.classList.add('active');
                viewGridBtn?.classList.remove('active');
                this.saveUserPreferences();
                this.renderBrowseNodes();
            });
        }
        
        // Restore saved view mode
        if (this.browseViewMode === 'list') {
            viewListBtn?.classList.add('active');
            viewGridBtn?.classList.remove('active');
        } else {
            viewGridBtn?.classList.add('active');
            viewListBtn?.classList.remove('active');
        }
        
        // Refresh
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                this.browseAllNodes = null;
                this.loadBrowseNodes();
            });
        }
    }
    
    closeBrowseModal() {
        const modal = document.getElementById('browse-modal');
        if (modal) {
            modal.classList.remove('show');
        }
    }
    
    async loadBrowseNodes() {
        const container = document.getElementById('browse-nodes-list');
        if (!container) return;
        
        container.innerHTML = '<div class="loading-state"><div class="loading-spinner"></div>Loading available nodes...</div>';
        
        try {
            const params = new URLSearchParams({
                search: '',
                category: '',
                not_installed: 'false',
                sort: 'stars',
                limit: '1000'
            });
            
            const response = await fetch(`${this.apiBase}/api/browse?${params}`);
            const data = await response.json();
            
            if (data.success) {
                this.browseAllNodes = data.nodes;
                this.filterBrowseNodes();
            }
        } catch (error) {
            console.error('Error loading browse nodes:', error);
            container.innerHTML = '<div class="empty-state">Failed to load available nodes</div>';
        }
    }
    
    filterBrowseNodes() {
        if (!this.browseAllNodes) return;
        
        let filtered = [...this.browseAllNodes];
        
        // Filter by search
        if (this.browseSearch) {
            const search = this.browseSearch.toLowerCase();
            filtered = filtered.filter(node => 
                node.title?.toLowerCase().includes(search) ||
                node.author?.toLowerCase().includes(search) ||
                node.description?.toLowerCase().includes(search)
            );
        }
        
        // Hide installed nodes
        if (this.browseHideInstalled) {
            filtered = filtered.filter(node => !node.is_installed);
        }
        
        // Sort
        filtered.sort((a, b) => {
            let aVal, bVal;
            if (this.browseSort === 'stars') {
                aVal = a.stars || 0;
                bVal = b.stars || 0;
            } else if (this.browseSort === 'name') {
                aVal = (a.title || '').toLowerCase();
                bVal = (b.title || '').toLowerCase();
            } else if (this.browseSort === 'author') {
                aVal = (a.author || '').toLowerCase();
                bVal = (b.author || '').toLowerCase();
            }
            
            if (this.browseSort === 'stars') {
                return this.browseSortDesc ? bVal - aVal : aVal - bVal;
            } else {
                const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
                return this.browseSortDesc ? -cmp : cmp;
            }
        });
        
        this.browseNodes = filtered;
        this.renderBrowseNodes();
        
        // Update count
        const countEl = document.getElementById('browse-count');
        if (countEl) {
            countEl.textContent = `${filtered.length} nodes`;
        }
    }
    
    renderBrowseNodes() {
        const container = document.getElementById('browse-nodes-list');
        if (!container) return;
        
        if (!this.browseNodes || this.browseNodes.length === 0) {
            container.innerHTML = '<div class="empty-state">No nodes found matching your criteria</div>';
            return;
        }
        
        // Set view class
        container.className = `browse-nodes-container ${this.browseViewMode || 'grid'}-view`;
        
        container.innerHTML = this.browseNodes.map(node => {
            const stars = node.stars || 0;
            const hasStars = stars > 0;
            const starsClass = hasStars ? '' : 'no-stars';
            const desc = node.description || '';
            const shortDesc = desc.length > 120 ? desc.substring(0, 120) + '...' : desc;
            
            return `
            <div class="browse-node-card ${node.is_installed ? 'installed' : ''}">
                <div class="browse-node-info">
                    <div class="browse-node-header">
                        <div class="browse-node-title">${this.escapeHtml(node.title)}</div>
                        <div class="browse-node-stars grid-only ${starsClass}">
                            <svg viewBox="0 0 24 24" fill="currentColor">
                                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
                            </svg>
                            ${hasStars ? this.formatNumber(stars) : '-'}
                        </div>
                    </div>
                    <div class="browse-node-author">by ${this.escapeHtml(node.author)}</div>
                    <div class="browse-node-desc grid-only">${this.escapeHtml(desc || 'No description')}</div>
                </div>
                <div class="browse-node-desc list-only" title="${this.escapeHtml(desc)}">${this.escapeHtml(shortDesc || 'No description')}</div>
                <div class="browse-node-stars list-only ${starsClass}">
                    <svg viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
                    </svg>
                    ${hasStars ? this.formatNumber(stars) : '-'}
                </div>
                <div class="browse-node-actions">
                    ${node.is_installed 
                        ? '<span class="browse-installed-badge">Installed</span>'
                        : `<button class="btn btn-primary btn-sm" onclick="app.installBrowseNode('${this.escapeHtml(node.reference)}')">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                                <polyline points="7 10 12 15 17 10"/>
                                <line x1="12" y1="15" x2="12" y2="3"/>
                            </svg>
                            Install
                          </button>`
                    }
                    <a href="${this.escapeHtml(node.reference)}" target="_blank" class="btn btn-secondary btn-sm">
                        <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
                            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                        </svg>
                        GitHub
                    </a>
                </div>
            </div>
        `}).join('');
    }
    
    
    async installBrowseNode(url) {
        // Find the button that was clicked and update it
        const cards = document.querySelectorAll('.browse-node-card');
        let targetBtn = null;
        cards.forEach(card => {
            const btn = card.querySelector(`button[onclick*="${url.replace(/'/g, "\\'")}"]`);
            if (btn) targetBtn = btn;
        });
        
        if (targetBtn) {
            targetBtn.disabled = true;
            targetBtn.innerHTML = `
                <div class="loading-spinner" style="width: 14px; height: 14px; margin: 0;"></div>
                Installing...
            `;
        }
        
        this.log(`Installing from browse: ${url}`, 'info');
        this.log(`Running: git clone ${url}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, folder_name: null, install_deps: true })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.log(`Installation complete: ${data.message}`, 'success');
                this.showToast('success', data.message);
                
                // Update the button to show installed
                if (targetBtn) {
                    targetBtn.outerHTML = '<span class="browse-installed-badge">Installed</span>';
                }
                
                // Get the folder name from the response or extract from URL
                const folderName = data.folder_name || url.split('/').pop().replace('.git', '');
                
                // Prompt to enable in profiles
                await this.promptEnableInProfiles(folderName);
                
                // Refresh nodes list in background
                this.refreshNodes();
                
                // Also refresh browse to update installed status
                await this.loadBrowseNodes();
            } else {
                this.log(`Installation failed: ${data.message}`, 'error');
                this.showToast('error', data.message);
                
                // Restore button
                if (targetBtn) {
                    targetBtn.disabled = false;
                    targetBtn.innerHTML = `
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                            <polyline points="7 10 12 15 17 10"/>
                            <line x1="12" y1="15" x2="12" y2="3"/>
                        </svg>
                        Install
                    `;
                }
            }
        } catch (error) {
            console.error('Error installing node:', error);
            this.log(`Installation error: ${error.message}`, 'error');
            this.showToast('error', 'Failed to install node');
            
            // Restore button
            if (targetBtn) {
                targetBtn.disabled = false;
                targetBtn.innerHTML = `
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                        <polyline points="7 10 12 15 17 10"/>
                        <line x1="12" y1="15" x2="12" y2="3"/>
                    </svg>
                    Install
                `;
            }
        }
    }
    
    // ==================== BROKEN NODE DETECTION ====================
    
    async detectBrokenNodes() {
        this.log('Scanning for broken nodes...', 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/broken-nodes`);
            const data = await response.json();
            
            if (data.success) {
                if (data.count === 0) {
                    this.log('No broken nodes detected', 'success');
                    this.showToast('success', 'All nodes appear to be working');
                } else {
                    this.log(`Found ${data.count} nodes with issues:`, 'warning');
                    data.broken_nodes.forEach(node => {
                        this.log(`  ${node.display_name}: ${node.issues.join(', ')}`, 'warning');
                    });
                    this.showToast('warning', `${data.count} nodes have issues - check console`);
                }
            }
        } catch (error) {
            console.error('Error detecting broken nodes:', error);
            this.showToast('error', 'Failed to scan for broken nodes');
        }
    }
    
    // ==================== GIT HISTORY / ROLLBACK ====================
    
    async showGitHistory(folderName) {
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/git-log?count=20`);
            const data = await response.json();
            
            if (data.success && data.commits.length > 0) {
                const historyHtml = data.commits.map(commit => `
                    <div class="git-commit" onclick="app.rollbackToCommit('${folderName}', '${commit.hash}')">
                        <div class="commit-hash">${commit.short_hash}</div>
                        <div class="commit-message">${this.escapeHtml(commit.message)}</div>
                        <div class="commit-meta">${commit.author} - ${commit.date}</div>
                    </div>
                `).join('');
                
                // You could show this in a modal - for now just log
                this.log(`Git history for ${folderName}: ${data.commits.length} commits`, 'info');
            }
        } catch (error) {
            console.error('Error loading git history:', error);
        }
    }
    
    async rollbackToCommit(folderName, commitHash) {
        const confirmed = await this.showConfirm({
            title: `Rollback to commit ${commitHash.slice(0, 8)}?`,
            message: `This will change the node to an older version.`,
            type: 'warning',
            confirmText: 'Rollback'
        });
        if (!confirmed) return;
        
        try {
            const response = await fetch(`${this.apiBase}/api/nodes/${folderName}/rollback`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ commit_hash: commitHash })
            });
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', data.message);
                this.log(data.message, 'success');
            } else {
                this.showToast('error', data.message);
            }
        } catch (error) {
            console.error('Error rolling back:', error);
            this.showToast('error', 'Rollback failed');
        }
    }
    
    // ==================== SETTINGS ====================
    
    loadSettings() {
        // Load settings from localStorage
        const savedSettings = localStorage.getItem('mf_conductor_settings');
        if (savedSettings) {
            try {
                const parsed = JSON.parse(savedSettings);
                this.settings = { ...this.settings, ...parsed };
            } catch (e) {
                console.error('Error loading settings:', e);
            }
        }
        
        // Apply settings to DOM
        this.applySettings();
    }
    
    saveSettings() {
        this.log('Settings saved', 'info');
        localStorage.setItem('mf_conductor_settings', JSON.stringify(this.settings));
        this.applySettings();
    }
    
    applySettings() {
        const html = document.documentElement;
        
        // Apply theme
        html.setAttribute('data-theme', this.settings.theme);
        
        // Apply accent color
        if (this.settings.accent === 'custom') {
            // Apply custom color directly via CSS variables
            html.style.setProperty('--accent-primary', this.settings.customAccentColor);
            html.style.setProperty('--accent-secondary', this.lightenColor(this.settings.customAccentColor, 20));
            html.removeAttribute('data-accent');
        } else {
            html.setAttribute('data-accent', this.settings.accent);
            html.style.removeProperty('--accent-primary');
            html.style.removeProperty('--accent-secondary');
        }
        
        // Apply button colors only if user has customized them
        if (this.settings.useCustomBtnColors) {
            html.style.setProperty('--accent-success', this.settings.btnColorSuccess);
            html.style.setProperty('--accent-warning', this.settings.btnColorWarning);
            html.style.setProperty('--accent-danger', this.settings.btnColorDanger);
        } else {
            // Remove inline styles to let theme CSS take over
            html.style.removeProperty('--accent-success');
            html.style.removeProperty('--accent-warning');
            html.style.removeProperty('--accent-danger');
        }
        
        // Apply animations
        html.setAttribute('data-animations', this.settings.animations ? 'true' : 'false');
        
        // Apply UI scale (0=compact, 1=normal, 2=old person)
        const uiScale = this.settings.uiScale ?? 1;
        html.setAttribute('data-compact', uiScale === 0 ? 'true' : 'false');
        html.setAttribute('data-large-text', uiScale === 2 ? 'true' : 'false');
        
        // Apply console autoscroll
        this.consoleAutoScroll = this.settings.consoleAutoscroll;
        
        // Update sort if default sort changed
        if (this.sortField !== this.settings.defaultSort && !this._sortManuallyChanged) {
            this.sortField = this.settings.defaultSort;
        }
    }
    
    // Helper to lighten a hex color
    lightenColor(hex, percent) {
        const num = parseInt(hex.replace('#', ''), 16);
        const amt = Math.round(2.55 * percent);
        const R = Math.min(255, (num >> 16) + amt);
        const G = Math.min(255, ((num >> 8) & 0x00FF) + amt);
        const B = Math.min(255, (num & 0x0000FF) + amt);
        return '#' + (0x1000000 + R * 0x10000 + G * 0x100 + B).toString(16).slice(1);
    }
    
    bindSettingsEvents() {
        // Settings button
        const settingsBtn = document.getElementById('settings-btn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', () => this.openSettingsModal());
        }
        
        // Click outside to close
        const settingsModal = document.getElementById('settings-modal');
        if (settingsModal) {
            settingsModal.addEventListener('click', (e) => {
                if (e.target === settingsModal) {
                    this.closeSettingsModal();
                }
            });
        }
        
        // Usage modal - click outside to close
        const usageModal = document.getElementById('usage-modal');
        if (usageModal) {
            usageModal.addEventListener('click', (e) => {
                if (e.target === usageModal) {
                    this.closeUsageModal();
                }
            });
        }
        
        // Theme selector
        const themeSelector = document.getElementById('theme-selector');
        if (themeSelector) {
            themeSelector.addEventListener('click', (e) => {
                const option = e.target.closest('.theme-option');
                if (option) {
                    const theme = option.dataset.theme;
                    this.setTheme(theme);
                }
            });
        }
        
        // Accent selector
        const accentSelector = document.getElementById('accent-selector');
        if (accentSelector) {
            accentSelector.addEventListener('click', (e) => {
                const option = e.target.closest('.accent-option');
                if (option) {
                    const accent = option.dataset.accent;
                    this.setAccent(accent);
                }
            });
        }
        
        // Initialize custom color picker
        this.initColorPicker();
        
        // Toggle settings
        const toggleIds = [
            'setting-animations',
            'setting-system-theme',
            'setting-auto-refresh',
            'setting-show-disabled',
            'setting-console-autoscroll',
            'setting-confirm-remove',
            'setting-console-timestamps'
        ];
        
        toggleIds.forEach(id => {
            const toggle = document.getElementById(id);
            if (toggle) {
                toggle.addEventListener('change', () => this.handleToggleSetting(id, toggle.checked));
            }
        });
        
        // Select settings
        const defaultSort = document.getElementById('setting-default-sort');
        if (defaultSort) {
            defaultSort.addEventListener('change', () => {
                this.settings.defaultSort = defaultSort.value;
                this.saveSettings();
            });
        }
        
        const consoleBuffer = document.getElementById('setting-console-buffer');
        if (consoleBuffer) {
            consoleBuffer.addEventListener('change', () => {
                this.settings.consoleBuffer = parseInt(consoleBuffer.value, 10);
                this.saveSettings();
            });
        }
        
        // UI Scale slider
        const uiScaleSlider = document.getElementById('setting-ui-scale');
        if (uiScaleSlider) {
            uiScaleSlider.addEventListener('input', () => {
                const value = parseInt(uiScaleSlider.value, 10);
                this.settings.uiScale = value;
                this.saveSettings();
                this.updateUiScaleLabels(value);
            });
        }
        
        // UI Scale labels are clickable
        const uiScaleLabels = document.querySelectorAll('.ui-scale-labels span');
        uiScaleLabels.forEach(label => {
            label.addEventListener('click', () => {
                const value = parseInt(label.dataset.value, 10);
                if (uiScaleSlider) {
                    uiScaleSlider.value = value;
                }
                this.settings.uiScale = value;
                this.saveSettings();
                this.updateUiScaleLabels(value);
            });
        });
    }
    
    updateUiScaleLabels(value) {
        const labels = document.querySelectorAll('.ui-scale-labels span');
        labels.forEach(label => {
            const labelValue = parseInt(label.dataset.value, 10);
            label.classList.toggle('active', labelValue === value);
        });
    }
    
    handleToggleSetting(id, value) {
        const settingMap = {
            'setting-animations': 'animations',
            'setting-system-theme': 'systemThemeSync',
            'setting-auto-refresh': 'autoRefresh',
            'setting-show-disabled': 'showDisabled',
            'setting-console-autoscroll': 'consoleAutoscroll',
            'setting-confirm-remove': 'confirmRemove',
            'setting-console-timestamps': 'consoleTimestamps'
        };
        
        const key = settingMap[id];
        if (key) {
            this.settings[key] = value;
            this.saveSettings();
            
            // Special handling for system theme sync
            if (key === 'systemThemeSync' && value) {
                this.applySystemTheme();
            }
        }
    }
    
    setTheme(theme) {
        this.settings.theme = theme;
        this.saveSettings();
        this.updateThemeSelector();
        // Update button color pickers to show new theme colors
        setTimeout(() => this.updateButtonColorPickers(), 50);
    }
    
    setAccent(accent) {
        this.settings.accent = accent;
        this.saveSettings();
        this.updateAccentSelector();
    }
    
    setCustomAccent(color) {
        this.settings.accent = 'custom';
        this.settings.customAccentColor = color;
        this.saveSettings();
        this.updateAccentSelector();
    }
    
    setButtonColor(type, color) {
        const key = `btnColor${type.charAt(0).toUpperCase() + type.slice(1)}`;
        this.settings[key] = color;
        this.settings.useCustomBtnColors = true;  // User has customized
        this.saveSettings();
    }
    
    resetButtonColors() {
        this.settings.btnColorSuccess = null;
        this.settings.btnColorWarning = null;
        this.settings.btnColorDanger = null;
        this.settings.useCustomBtnColors = false;  // Use theme defaults
        this.saveSettings();
        this.updateButtonColorPickers();
        this.showToast('success', 'Button colors reset to theme defaults');
    }
    
    updateButtonColorPickers() {
        const successPicker = document.getElementById('btn-color-success');
        const warningPicker = document.getElementById('btn-color-warning');
        const dangerPicker = document.getElementById('btn-color-danger');
        
        // Get computed theme colors if not using custom
        const computedStyle = getComputedStyle(document.documentElement);
        const getColor = (settingValue, cssVar) => {
            if (this.settings.useCustomBtnColors && settingValue) {
                return settingValue;
            }
            // Get the theme's color from computed style
            const computed = computedStyle.getPropertyValue(cssVar).trim();
            return computed || '#888888';
        };
        
        if (successPicker) successPicker.style.background = getColor(this.settings.btnColorSuccess, '--accent-success');
        if (warningPicker) warningPicker.style.background = getColor(this.settings.btnColorWarning, '--accent-warning');
        if (dangerPicker) dangerPicker.style.background = getColor(this.settings.btnColorDanger, '--accent-danger');
    }
    
    updateThemeSelector() {
        const options = document.querySelectorAll('.theme-option');
        options.forEach(opt => {
            opt.classList.toggle('active', opt.dataset.theme === this.settings.theme);
        });
    }
    
    updateAccentSelector() {
        const options = document.querySelectorAll('.accent-option');
        options.forEach(opt => {
            opt.classList.toggle('active', opt.dataset.accent === this.settings.accent);
        });
        
        // Update custom picker swatch
        const customPicker = document.getElementById('accent-custom-picker');
        if (customPicker) {
            customPicker.style.background = this.settings.customAccentColor;
            customPicker.classList.toggle('active', this.settings.accent === 'custom');
        }
    }
    
    updateSettingsModal() {
        // Update theme selector
        this.updateThemeSelector();
        
        // Update accent selector
        this.updateAccentSelector();
        
        // Update button color pickers
        this.updateButtonColorPickers();
        
        // Update toggles
        const toggles = {
            'setting-animations': this.settings.animations,
            'setting-system-theme': this.settings.systemThemeSync,
            'setting-auto-refresh': this.settings.autoRefresh,
            'setting-show-disabled': this.settings.showDisabled,
            'setting-console-autoscroll': this.settings.consoleAutoscroll,
            'setting-confirm-remove': this.settings.confirmRemove,
            'setting-console-timestamps': this.settings.consoleTimestamps
        };
        
        Object.entries(toggles).forEach(([id, value]) => {
            const el = document.getElementById(id);
            if (el) el.checked = value;
        });
        
        // Update selects
        const defaultSort = document.getElementById('setting-default-sort');
        if (defaultSort) defaultSort.value = this.settings.defaultSort;
        
        const consoleBuffer = document.getElementById('setting-console-buffer');
        if (consoleBuffer) consoleBuffer.value = this.settings.consoleBuffer;
        
        // Update UI scale slider
        const uiScaleSlider = document.getElementById('setting-ui-scale');
        if (uiScaleSlider) {
            uiScaleSlider.value = this.settings.uiScale ?? 1;
            this.updateUiScaleLabels(this.settings.uiScale ?? 1);
        }
    }
    
    openSettingsModal() {
        const modal = document.getElementById('settings-modal');
        if (modal) {
            modal.classList.add('show');
            this.updateSettingsModal();
        }
    }
    
    closeSettingsModal() {
        const modal = document.getElementById('settings-modal');
        if (modal) {
            modal.classList.remove('show');
        }
    }
    
    // ==================== USAGE ANALYTICS ====================
    
    openUsageModal() {
        const modal = document.getElementById('usage-modal');
        if (modal) {
            modal.classList.add('show');
            this.loadUsageStats();
        }
    }
    
    closeUsageModal() {
        const modal = document.getElementById('usage-modal');
        if (modal) {
            modal.classList.remove('show');
        }
    }
    
    async loadUsageStats() {
        const container = document.getElementById('usage-stats-container');
        const lastScanEl = document.getElementById('usage-last-scan');
        
        try {
            const response = await fetch(`${this.apiBase}/api/usage/stats`);
            const data = await response.json();
            
            if (!data.success) {
                container.innerHTML = `
                    <div class="text-center py-8">
                        <i class="fa-solid fa-exclamation-triangle text-4xl text-yellow-500 mb-4"></i>
                        <p class="text-slate-400">${data.message || 'Failed to load usage stats'}</p>
                    </div>
                `;
                return;
            }
            
            // Update last scan time
            if (data.last_scan) {
                const date = new Date(data.last_scan);
                lastScanEl.textContent = `Last scan: ${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
            } else {
                lastScanEl.textContent = 'Never scanned';
            }
            
            // Render stats
            this.renderUsageStats(data);
            
        } catch (error) {
            container.innerHTML = `
                <div class="text-center py-8">
                    <i class="fa-solid fa-exclamation-triangle text-4xl text-red-500 mb-4"></i>
                    <p class="text-slate-400">Error loading usage stats: ${error.message}</p>
                </div>
            `;
        }
    }
    
    renderUsageStats(data) {
        const container = document.getElementById('usage-stats-container');
        
        if (!data.total_workflows && data.package_stats.length === 0) {
            container.innerHTML = `
                <div class="text-center py-8">
                    <i class="fa-solid fa-chart-bar text-4xl text-slate-600 mb-4"></i>
                    <p class="text-slate-400">No usage data yet. Scan your workflows to get started.</p>
                    <p class="text-xs text-slate-500 mt-2">This will analyze PNG/WebP files in your output folder to see which nodes you use.</p>
                </div>
            `;
            return;
        }
        
        // Build the stats HTML
        let html = `
            <div class="usage-summary grid grid-cols-3 gap-4 mb-6">
                <div class="glass-panel p-4 rounded-lg text-center">
                    <div class="text-2xl font-bold text-white">${data.total_workflows || 0}</div>
                    <div class="text-xs text-slate-400">Workflows Scanned</div>
                </div>
                <div class="glass-panel p-4 rounded-lg text-center">
                    <div class="text-2xl font-bold text-white">${data.package_stats?.length || 0}</div>
                    <div class="text-xs text-slate-400">Packages Tracked</div>
                </div>
                <div class="glass-panel p-4 rounded-lg text-center">
                    <div class="text-2xl font-bold ${data.unused_packages?.length > 0 ? 'text-yellow-400' : 'text-green-400'}">${data.unused_packages?.length || 0}</div>
                    <div class="text-xs text-slate-400">Never Used</div>
                </div>
            </div>
        `;
        
        // Recommendations
        if (data.recommendations && data.recommendations.length > 0) {
            html += `<div class="usage-recommendations mb-6">`;
            for (const rec of data.recommendations) {
                const iconClass = rec.severity === 'warning' ? 'text-yellow-500' : 'text-blue-400';
                html += `
                    <div class="glass-panel p-4 rounded-lg mb-3">
                        <div class="flex items-start gap-3">
                            <i class="fa-solid fa-lightbulb ${iconClass} mt-1"></i>
                            <div class="flex-1">
                                <div class="text-sm font-medium text-white">${rec.title}</div>
                                <div class="text-xs text-slate-400 mt-1">${rec.description}</div>
                                ${rec.packages && rec.packages.length > 0 ? `
                                    <div class="flex flex-wrap gap-1 mt-2">
                                        ${rec.packages.slice(0, 5).map(pkg => `
                                            <span class="text-xs bg-slate-700 px-2 py-0.5 rounded">${pkg}</span>
                                        `).join('')}
                                        ${rec.packages.length > 5 ? `<span class="text-xs text-slate-500">+${rec.packages.length - 5} more</span>` : ''}
                                    </div>
                                ` : ''}
                            </div>
                        </div>
                    </div>
                `;
            }
            html += `</div>`;
        }
        
        // Package usage table
        if (data.package_stats && data.package_stats.length > 0) {
            html += `
                <div class="usage-packages">
                    <h4 class="text-sm font-semibold text-white mb-3">Package Usage</h4>
                    <div class="glass-panel rounded-lg overflow-hidden">
                        <table class="w-full text-sm">
                            <thead class="bg-black/30">
                                <tr>
                                    <th class="text-left p-3 text-slate-400 font-medium">Package</th>
                                    <th class="text-center p-3 text-slate-400 font-medium w-24">Used</th>
                                    <th class="text-center p-3 text-slate-400 font-medium w-32">Last Used</th>
                                    <th class="text-center p-3 text-slate-400 font-medium w-20">Nodes</th>
                                </tr>
                            </thead>
                            <tbody>
            `;
            
            for (const pkg of data.package_stats.slice(0, 30)) {
                const lastUsed = pkg.last_used ? new Date(pkg.last_used).toLocaleDateString() : 'Never';
                const usageClass = pkg.count === 0 ? 'text-red-400' : pkg.count < 3 ? 'text-yellow-400' : 'text-green-400';
                html += `
                    <tr class="border-t border-border-subtle hover:bg-white/5">
                        <td class="p-3 text-slate-300">${pkg.name}</td>
                        <td class="p-3 text-center ${usageClass}">${pkg.count}×</td>
                        <td class="p-3 text-center text-slate-400 text-xs">${lastUsed}</td>
                        <td class="p-3 text-center text-slate-400">${pkg.nodes_used || 0}</td>
                    </tr>
                `;
            }
            
            html += `
                            </tbody>
                        </table>
                        ${data.package_stats.length > 30 ? `
                            <div class="text-center p-3 text-xs text-slate-500 border-t border-border-subtle">
                                Showing top 30 of ${data.package_stats.length} packages
                            </div>
                        ` : ''}
                    </div>
                </div>
            `;
        }
        
        container.innerHTML = html;
    }
    
    async scanUsage(force = false) {
        const scanBtn = document.getElementById('usage-scan-btn');
        const rescanBtn = document.getElementById('usage-rescan-btn');
        
        if (scanBtn) scanBtn.disabled = true;
        if (rescanBtn) rescanBtn.disabled = true;
        
        try {
            const response = await fetch(`${this.apiBase}/api/usage/scan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ force })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showToast('info', 'Scanning workflows...');
                // Poll for progress
                this.pollUsageScanProgress();
            } else {
                this.showToast('error', data.message || 'Failed to start scan');
                if (scanBtn) scanBtn.disabled = false;
                if (rescanBtn) rescanBtn.disabled = false;
            }
        } catch (error) {
            this.showToast('error', 'Error starting scan: ' + error.message);
            if (scanBtn) scanBtn.disabled = false;
            if (rescanBtn) rescanBtn.disabled = false;
        }
    }
    
    async pollUsageScanProgress() {
        const container = document.getElementById('usage-stats-container');
        const scanBtn = document.getElementById('usage-scan-btn');
        const rescanBtn = document.getElementById('usage-rescan-btn');
        
        const poll = async () => {
            try {
                const response = await fetch(`${this.apiBase}/api/usage/progress`);
                const data = await response.json();
                
                if (data.status === 'scanning') {
                    const pct = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
                    container.innerHTML = `
                        <div class="text-center py-8">
                            <i class="fa-solid fa-spinner fa-spin text-4xl text-indigo-400 mb-4"></i>
                            <p class="text-slate-300">Scanning workflows...</p>
                            <div class="w-64 mx-auto mt-4 bg-slate-700 rounded-full h-2">
                                <div class="bg-indigo-500 h-2 rounded-full transition-all" style="width: ${pct}%"></div>
                            </div>
                            <p class="text-xs text-slate-500 mt-2">${data.current} / ${data.total} files</p>
                        </div>
                    `;
                    setTimeout(poll, 500);
                } else if (data.status === 'complete') {
                    this.showToast('success', 'Scan complete!');
                    this.loadUsageStats();
                    if (scanBtn) scanBtn.disabled = false;
                    if (rescanBtn) rescanBtn.disabled = false;
                } else if (data.status === 'error') {
                    this.showToast('error', 'Scan failed');
                    this.loadUsageStats();
                    if (scanBtn) scanBtn.disabled = false;
                    if (rescanBtn) rescanBtn.disabled = false;
                } else {
                    // Idle or unknown - just refresh stats
                    this.loadUsageStats();
                    if (scanBtn) scanBtn.disabled = false;
                    if (rescanBtn) rescanBtn.disabled = false;
                }
            } catch (error) {
                this.showToast('error', 'Error checking scan progress');
                if (scanBtn) scanBtn.disabled = false;
                if (rescanBtn) rescanBtn.disabled = false;
            }
        };
        
        poll();
    }
    
    async clearUsageData() {
        if (!confirm('Are you sure you want to clear all usage data? This cannot be undone.')) {
            return;
        }
        
        try {
            const response = await fetch(`${this.apiBase}/api/usage/clear`, {
                method: 'POST'
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', 'Usage data cleared');
                this.loadUsageStats();
            } else {
                this.showToast('error', data.message || 'Failed to clear data');
            }
        } catch (error) {
            this.showToast('error', 'Error clearing data: ' + error.message);
        }
    }
    
    exportSettings() {
        const data = {
            settings: this.settings,
            profiles: this.profiles,
            userData: this.userData,
            exportedAt: new Date().toISOString(),
            version: '1.0'
        };
        
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `mf_conductor_settings_${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        URL.revokeObjectURL(url);
        
        this.showToast('success', 'Settings exported successfully');
    }
    
    importSettings() {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            try {
                const text = await file.text();
                const data = JSON.parse(text);
                
                if (data.settings) {
                    this.settings = { ...this.settings, ...data.settings };
                    this.saveSettings();
                }
                
                // Optionally import other data
                if (data.userData) {
                    // Could merge with existing user data
                    this.log('User data found in import - skipping (use backup/restore for full data)', 'info');
                }
                
                this.showToast('success', 'Settings imported successfully');
                this.updateSettingsModal();
            } catch (error) {
                console.error('Error importing settings:', error);
                this.showToast('error', this.parseError(error, 'Failed to import settings - invalid file format'));
            }
        };
        input.click();
    }
    
    // ==================== PROFILE EXPORT/IMPORT ====================
    
    exportProfile(profileName) {
        const profile = this.profiles[profileName];
        if (!profile) {
            this.showToast('error', 'Profile not found');
            return;
        }
        
        this.log(`Exporting profile: ${profileName}`, 'info');
        const exportData = {
            type: 'mf_conductor_profile',
            version: '1.0',
            name: profileName,
            profile: profile,
            exportedAt: new Date().toISOString(),
            exportedBy: 'MF Conductor'
        };
        
        const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `mf_profile_${profileName.replace(/[^a-z0-9]/gi, '_')}_${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        URL.revokeObjectURL(url);
        
        this.log(`Profile "${profileName}" exported successfully`, 'success');
        this.showToast('success', `Profile "${profileName}" exported successfully`);
    }
    
    importProfile() {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.json';
        input.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            
            this.log(`Importing profile from: ${file.name}`, 'info');
            try {
                const text = await file.text();
                const data = JSON.parse(text);
                
                // Validate profile format
                if (data.type !== 'mf_conductor_profile' || !data.profile) {
                    throw new Error('Invalid profile file format');
                }
                
                let profileName = data.name || 'Imported Profile';
                
                // Check for name collision
                if (this.profiles[profileName]) {
                    const confirmed = await this.showConfirm({
                        title: 'Profile exists',
                        message: `A profile named "${profileName}" already exists.\n\nOverwrite it or import with a new name?`,
                        type: 'warning',
                        confirmText: 'Overwrite',
                        cancelText: 'New Name'
                    });
                    
                    if (!confirmed) {
                        // Generate new name
                        let counter = 1;
                        while (this.profiles[`${profileName} (${counter})`]) {
                            counter++;
                        }
                        profileName = `${profileName} (${counter})`;
                    }
                }
                
                // Save the profile
                const response = await fetch(`${this.apiBase}/api/profiles/save`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: profileName,
                        ...data.profile
                    })
                });
                
                if (response.ok) {
                    this.log(`Profile "${profileName}" imported successfully`, 'success');
                    await this.loadProfiles();
                    this.renderProfilesGrid();
                    this.showToast('success', `Profile "${profileName}" imported successfully`);
                } else {
                    throw new Error('Failed to save imported profile');
                }
            } catch (error) {
                this.log(`Failed to import profile: ${error.message}`, 'error');
                console.error('Error importing profile:', error);
                this.showToast('error', this.parseError(error, 'Failed to import profile'));
            }
        };
        input.click();
    }
    
    async resetSettings() {
        const confirmed = await this.showConfirm({
            title: 'Reset all settings?',
            message: `This will reset all settings to their defaults.\nThis cannot be undone.`,
            type: 'warning',
            confirmText: 'Reset'
        });
        if (!confirmed) return;
        
        this.log('Resetting all settings to defaults', 'warning');
        
        this.settings = {
            theme: 'dark',
            accent: 'blue',
            customAccentColor: '#4a9eff',
            btnColorSuccess: null,
            btnColorWarning: null,
            btnColorDanger: null,
            useCustomBtnColors: false,
            animations: true,
            uiScale: 1,  // 0=compact, 1=normal, 2=old person
            autoRefresh: true,
            showDisabled: true,
            consoleAutoscroll: true,
            confirmRemove: true,
            defaultSort: 'name',
            consoleBuffer: 1000,
            consoleTimestamps: false
        };
        
        this.saveSettings();
        this.updateSettingsModal();
        this.showToast('success', 'Settings reset to defaults');
    }
    
    restartConductor() {
        this.showToast('info', 'Restarting MF Conductor...');
        setTimeout(() => {
            window.location.reload();
        }, 500);
    }
    
    async loadPresetProfiles() {
        try {
            const response = await fetch(`${this.apiBase}/api/profiles/load-presets`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', data.message);
                await this.loadProfiles();
                this.renderProfilesGrid();
                this.updateComfyControls();
            } else {
                this.showToast('error', data.message || 'Failed to load preset profiles');
            }
        } catch (error) {
            this.showToast('error', this.parseError(error, 'Failed to load preset profiles'));
        }
    }
    
    // ==================== CUSTOM COLOR PICKER ====================
    
    initColorPicker() {
        const saturationEl = document.getElementById('color-saturation');
        const hueEl = document.getElementById('color-hue');
        const hexInput = document.getElementById('color-hex-input');
        const presetsContainer = document.querySelector('.color-picker-presets');
        const modal = document.getElementById('color-picker-modal');
        
        if (!saturationEl || !hueEl) return;
        
        // Saturation/Brightness picker
        let isDraggingSat = false;
        
        const updateSaturation = (e) => {
            const rect = saturationEl.getBoundingClientRect();
            const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
            const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
            
            this.colorPicker.saturation = x * 100;
            this.colorPicker.brightness = (1 - y) * 100;
            this.updateColorPickerUI();
        };
        
        saturationEl.addEventListener('mousedown', (e) => {
            isDraggingSat = true;
            updateSaturation(e);
        });
        
        // Hue picker
        let isDraggingHue = false;
        
        const updateHue = (e) => {
            const rect = hueEl.getBoundingClientRect();
            const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
            this.colorPicker.hue = y * 360;
            this.updateColorPickerUI();
        };
        
        hueEl.addEventListener('mousedown', (e) => {
            isDraggingHue = true;
            updateHue(e);
        });
        
        // Global mouse events
        document.addEventListener('mousemove', (e) => {
            if (isDraggingSat) updateSaturation(e);
            if (isDraggingHue) updateHue(e);
        });
        
        document.addEventListener('mouseup', () => {
            isDraggingSat = false;
            isDraggingHue = false;
        });
        
        // Hex input
        if (hexInput) {
            hexInput.addEventListener('input', (e) => {
                let value = e.target.value;
                if (!value.startsWith('#')) value = '#' + value;
                if (/^#[0-9A-Fa-f]{6}$/.test(value)) {
                    this.setColorPickerFromHex(value);
                }
            });
            
            hexInput.addEventListener('blur', (e) => {
                let value = e.target.value;
                if (!value.startsWith('#')) value = '#' + value;
                if (!/^#[0-9A-Fa-f]{6}$/.test(value)) {
                    e.target.value = this.colorPicker.currentColor;
                }
            });
        }
        
        // Presets
        if (presetsContainer) {
            presetsContainer.addEventListener('click', (e) => {
                const preset = e.target.closest('.color-preset');
                if (preset) {
                    const color = preset.dataset.color;
                    this.setColorPickerFromHex(color);
                }
            });
        }
        
        // Close on overlay click
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (e.target === modal) {
                    this.closeColorPicker();
                }
            });
        }
    }
    
    openColorPicker(target) {
        const modal = document.getElementById('color-picker-modal');
        if (!modal) return;
        
        this.colorPicker.target = target;
        this.colorPicker.isOpen = true;
        
        // Get current color
        let currentColor = '#4a9eff';
        if (target === 'accent') {
            currentColor = this.settings.customAccentColor || '#4a9eff';
        } else if (target === 'success') {
            currentColor = this.settings.btnColorSuccess || this.getComputedColor('--accent-success');
        } else if (target === 'warning') {
            currentColor = this.settings.btnColorWarning || this.getComputedColor('--accent-warning');
        } else if (target === 'danger') {
            currentColor = this.settings.btnColorDanger || this.getComputedColor('--accent-danger');
        }
        
        this.colorPicker.originalColor = currentColor;
        this.setColorPickerFromHex(currentColor);
        
        // Set original color preview
        const originalPreview = document.getElementById('color-preview-current');
        if (originalPreview) originalPreview.style.background = currentColor;
        
        modal.classList.add('show');
    }
    
    closeColorPicker() {
        const modal = document.getElementById('color-picker-modal');
        if (modal) modal.classList.remove('show');
        this.colorPicker.isOpen = false;
    }
    
    confirmColorPicker() {
        const color = this.colorPicker.currentColor;
        const target = this.colorPicker.target;
        
        if (target === 'accent') {
            this.setCustomAccent(color);
        } else if (target === 'success' || target === 'warning' || target === 'danger') {
            this.setButtonColor(target, color);
        }
        
        this.closeColorPicker();
        this.updateButtonColorPickers();
        this.updateAccentSelector();
    }
    
    getComputedColor(cssVar) {
        const computed = getComputedStyle(document.documentElement).getPropertyValue(cssVar).trim();
        return computed || '#888888';
    }
    
    setColorPickerFromHex(hex) {
        const hsb = this.hexToHsb(hex);
        this.colorPicker.hue = hsb.h;
        this.colorPicker.saturation = hsb.s;
        this.colorPicker.brightness = hsb.b;
        this.updateColorPickerUI();
    }
    
    updateColorPickerUI() {
        const { hue, saturation, brightness } = this.colorPicker;
        
        // Update saturation background color
        const satEl = document.getElementById('color-saturation');
        if (satEl) {
            satEl.style.background = `hsl(${hue}, 100%, 50%)`;
        }
        
        // Update saturation cursor position
        const satCursor = document.getElementById('saturation-cursor');
        if (satCursor) {
            satCursor.style.left = `${saturation}%`;
            satCursor.style.top = `${100 - brightness}%`;
        }
        
        // Update hue cursor position
        const hueCursor = document.getElementById('hue-cursor');
        if (hueCursor) {
            hueCursor.style.top = `${(hue / 360) * 100}%`;
        }
        
        // Calculate current color
        const color = this.hsbToHex(hue, saturation, brightness);
        this.colorPicker.currentColor = color;
        
        // Update preview
        const newPreview = document.getElementById('color-preview-new');
        if (newPreview) newPreview.style.background = color;
        
        // Update hex input
        const hexInput = document.getElementById('color-hex-input');
        if (hexInput && document.activeElement !== hexInput) {
            hexInput.value = color.toUpperCase();
        }
    }
    
    // Color conversion utilities
    hexToHsb(hex) {
        const r = parseInt(hex.slice(1, 3), 16) / 255;
        const g = parseInt(hex.slice(3, 5), 16) / 255;
        const b = parseInt(hex.slice(5, 7), 16) / 255;
        
        const max = Math.max(r, g, b);
        const min = Math.min(r, g, b);
        const d = max - min;
        
        let h = 0;
        const s = max === 0 ? 0 : (d / max) * 100;
        const v = max * 100;
        
        if (d !== 0) {
            switch (max) {
                case r: h = ((g - b) / d + (g < b ? 6 : 0)) * 60; break;
                case g: h = ((b - r) / d + 2) * 60; break;
                case b: h = ((r - g) / d + 4) * 60; break;
            }
        }
        
        return { h, s, b: v };
    }
    
    hsbToHex(h, s, b) {
        s /= 100;
        b /= 100;
        
        const c = b * s;
        const x = c * (1 - Math.abs((h / 60) % 2 - 1));
        const m = b - c;
        
        let r, g, bl;
        
        if (h < 60) { r = c; g = x; bl = 0; }
        else if (h < 120) { r = x; g = c; bl = 0; }
        else if (h < 180) { r = 0; g = c; bl = x; }
        else if (h < 240) { r = 0; g = x; bl = c; }
        else if (h < 300) { r = x; g = 0; bl = c; }
        else { r = c; g = 0; bl = x; }
        
        const toHex = (v) => {
            const hex = Math.round((v + m) * 255).toString(16);
            return hex.length === 1 ? '0' + hex : hex;
        };
        
        return `#${toHex(r)}${toHex(g)}${toHex(bl)}`;
    }
    
    // ==================== UI HELPERS ====================
    
    updateTagsDropdown() {
        if (!this.filterTagSelect) return;
        
        const tags = this.getAllTags();
        this.filterTagSelect.innerHTML = '<option value="">All Tags</option>' +
            tags.map(tag => `<option value="${this.escapeHtml(tag)}">${this.escapeHtml(tag)}</option>`).join('');
    }
    
    openProfilesModal() {
        const modal = document.getElementById('profiles-modal');
        if (modal) {
            modal.classList.add('show');
            this.initProfilesUI();
        }
    }
    
    closeProfilesModal() {
        const modal = document.getElementById('profiles-modal');
        if (modal) {
            modal.classList.remove('show');
        }
    }
    
    async initProfilesUI() {
        // Initialize state
        this.profileSelectedNodes = new Set();
        this.profileCustomFlags = [];
        this.profileExcludedPackages = new Set();
        this.currentProfileName = '';
        
        // Load profiles into dropdown
        await this.loadProfileDropdown();
        
        // Render nodes
        this.renderAvailableNodes();
        this.renderSelectedNodes();
        this.renderCustomFlags();
        
        // Load packages
        await this.loadPackagesList();
        
        // Bind events if not already bound
        if (!this.profilesInitialized) {
            this.profilesInitialized = true;
            this.bindProfileEvents();
        }
    }
    
    bindProfileEvents() {
        const profileSelect = document.getElementById('profile-select');
        const profileNameInput = document.getElementById('new-profile-name');
        const saveBtn = document.getElementById('profile-save-btn');
        const deleteBtn = document.getElementById('profile-delete-btn');
        const addAllBtn = document.getElementById('add-all-nodes');
        const removeAllBtn = document.getElementById('remove-all-nodes');
        const addSelectedBtn = document.getElementById('add-selected-nodes');
        const removeSelectedBtn = document.getElementById('remove-selected-nodes');
        const applyBtn = document.getElementById('apply-profile-btn');
        const availableSearch = document.getElementById('available-search');
        const selectedSearch = document.getElementById('selected-search');
        const packagesSearch = document.getElementById('packages-search');
        const refreshPackagesBtn = document.getElementById('refresh-packages');
        const addCustomFlagBtn = document.getElementById('add-custom-flag');
        const customFlagInput = document.getElementById('custom-flag-input');
        
        // Tab switching
        document.querySelectorAll('.profile-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.profile-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.profile-tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const tabId = 'tab-' + tab.dataset.tab;
                document.getElementById(tabId)?.classList.add('active');
            });
        });
        
        // Profile selection
        profileSelect?.addEventListener('change', async () => {
            const name = profileSelect.value;
            if (name) {
                await this.loadProfileData(name);
                profileNameInput.value = name;
                deleteBtn.style.display = 'inline-flex';
            } else {
                this.profileSelectedNodes.clear();
                this.profileCustomFlags = [];
                this.profileExcludedPackages.clear();
                this.renderSelectedNodes();
                this.renderCustomFlags();
                this.renderPackagesList();
                this.clearProfileFlags();
                profileNameInput.value = '';
                deleteBtn.style.display = 'none';
            }
            this.currentProfileName = name;
        });
        
        // Save profile
        saveBtn?.addEventListener('click', () => {
            const name = profileNameInput.value.trim();
            if (name) {
                this.saveProfileAdvanced(name);
            } else {
                this.showToast('error', 'Please enter a profile name');
            }
        });
        
        // Delete profile
        deleteBtn?.addEventListener('click', async () => {
            if (this.currentProfileName) {
                const confirmed = await this.showConfirm({
                    title: `Delete profile "${this.currentProfileName}"?`,
                    message: `This profile will be permanently deleted.`,
                    type: 'danger',
                    confirmText: 'Delete',
                    confirmClass: 'btn-danger'
                });
                if (confirmed) {
                    await this.deleteProfile(this.currentProfileName);
                    await this.loadProfileDropdown();
                    this.profileSelectedNodes.clear();
                    this.profileCustomFlags = [];
                    this.renderSelectedNodes();
                    this.renderCustomFlags();
                    this.clearProfileFlags();
                    profileSelect.value = '';
                    profileNameInput.value = '';
                    deleteBtn.style.display = 'none';
                    this.currentProfileName = '';
                }
            }
        });
        
        // Add/Remove all nodes
        addAllBtn?.addEventListener('click', () => {
            this.nodes.forEach(n => this.profileSelectedNodes.add(n.folder_name));
            this.renderAvailableNodes();
            this.renderSelectedNodes();
        });
        
        removeAllBtn?.addEventListener('click', () => {
            this.profileSelectedNodes.clear();
            this.renderAvailableNodes();
            this.renderSelectedNodes();
        });
        
        // Add/Remove selected (checked) nodes
        addSelectedBtn?.addEventListener('click', () => {
            document.querySelectorAll('#available-nodes-list .profile-node-item.selected').forEach(item => {
                this.profileSelectedNodes.add(item.dataset.folder);
            });
            this.renderAvailableNodes();
            this.renderSelectedNodes();
        });
        
        removeSelectedBtn?.addEventListener('click', () => {
            document.querySelectorAll('#selected-nodes-list .profile-node-item.selected').forEach(item => {
                this.profileSelectedNodes.delete(item.dataset.folder);
            });
            this.renderAvailableNodes();
            this.renderSelectedNodes();
        });
        
        // Apply profile
        applyBtn?.addEventListener('click', () => {
            const name = document.getElementById('new-profile-name').value.trim() || this.currentProfileName;
            if (name) {
                this.applyProfileAdvanced(name);
            } else {
                this.showToast('error', 'Please select or create a profile first');
            }
        });
        
        // Search filters
        availableSearch?.addEventListener('input', () => this.renderAvailableNodes(availableSearch.value));
        selectedSearch?.addEventListener('input', () => this.renderSelectedNodes(selectedSearch.value));
        packagesSearch?.addEventListener('input', () => this.renderPackagesList(packagesSearch.value));
        
        // Refresh packages
        refreshPackagesBtn?.addEventListener('click', () => this.loadPackagesList(true));
        
        // Add custom flag
        const addCustomFlag = () => {
            const flag = customFlagInput?.value.trim();
            if (flag && !this.profileCustomFlags.find(f => f.value === flag)) {
                this.profileCustomFlags.push({ value: flag, enabled: true });
                customFlagInput.value = '';
                this.renderCustomFlags();
            }
        };
        
        addCustomFlagBtn?.addEventListener('click', addCustomFlag);
        customFlagInput?.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') addCustomFlag();
        });
    }
    
    async loadProfileDropdown() {
        const select = document.getElementById('profile-select');
        if (!select) return;
        
        const profiles = await this.getProfiles();
        const names = Object.keys(profiles).sort();
        
        select.innerHTML = '<option value="">-- Select or Create Profile --</option>' +
            names.map(name => `<option value="${this.escapeHtml(name)}">${this.escapeHtml(name)}</option>`).join('');
    }
    
    async loadProfileData(name) {
        const profiles = await this.getProfiles();
        const profile = profiles[name];
        
        if (profile) {
            // Load selected nodes
            this.profileSelectedNodes.clear();
            (profile.enabled || []).forEach(n => this.profileSelectedNodes.add(n));
            
            this.renderAvailableNodes();
            this.renderSelectedNodes();
            
            // Load flags
            this.loadProfileFlags(profile.flags || {});
            
            // Load custom flags
            this.profileCustomFlags = (profile.custom_flags_list || []).map(f => 
                typeof f === 'string' ? { value: f, enabled: true } : f
            );
            // Legacy support for string custom_flags
            if (profile.custom_flags && !profile.custom_flags_list) {
                this.profileCustomFlags = profile.custom_flags.split(/\s+/).filter(f => f).map(f => ({ value: f, enabled: true }));
            }
            this.renderCustomFlags();
            
            // Load excluded packages
            this.profileExcludedPackages = new Set(profile.excluded_packages || []);
            this.renderPackagesList();
        }
    }
    
    loadProfileFlags(flags) {
        // Clear all flags first
        this.clearProfileFlags();
        
        // Set radio buttons
        ['vram', 'attention', 'precision', 'vae', 'cache'].forEach(group => {
            if (flags[group]) {
                const input = document.querySelector(`#tab-flags input[name="${group}"][value="${flags[group]}"]`);
                if (input) input.checked = true;
            }
        });
        
        // Set checkboxes
        document.querySelectorAll('#tab-flags .flag-option input[type="checkbox"]').forEach(cb => {
            cb.checked = flags[cb.name] === cb.value;
        });
    }
    
    clearProfileFlags() {
        // Reset radio buttons to defaults
        ['vram', 'attention', 'precision', 'vae', 'cache'].forEach(group => {
            const defaultInput = document.querySelector(`#tab-flags input[name="${group}"][value=""]`);
            if (defaultInput) defaultInput.checked = true;
        });
        
        // Uncheck all checkboxes
        document.querySelectorAll('#tab-flags .flag-option input[type="checkbox"]').forEach(cb => {
            cb.checked = false;
        });
        
        // Clear custom flags
        this.profileCustomFlags = [];
        this.renderCustomFlags();
    }
    
    getSelectedFlags() {
        const flags = {};
        
        // Get radio button values
        ['vram', 'attention', 'precision', 'vae', 'cache'].forEach(group => {
            const checked = document.querySelector(`#tab-flags input[name="${group}"]:checked`);
            if (checked && checked.value) {
                flags[group] = checked.value;
            }
        });
        
        // Get checkbox values
        document.querySelectorAll('#tab-flags .flag-option input[type="checkbox"]:checked').forEach(cb => {
            flags[cb.name] = cb.value;
        });
        
        return flags;
    }
    
    renderCustomFlags() {
        const container = document.getElementById('custom-flags-list');
        if (!container) return;
        
        container.innerHTML = this.profileCustomFlags.map((flag, index) => `
            <div class="custom-flag-item">
                <input type="checkbox" ${flag.enabled ? 'checked' : ''} 
                    onchange="app.toggleCustomFlag(${index}, this.checked)">
                <span class="flag-text">${this.escapeHtml(flag.value)}</span>
                <button class="flag-remove" onclick="app.removeCustomFlag(${index})" title="Remove">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12">
                        <path d="M18 6L6 18M6 6l12 12"/>
                    </svg>
                </button>
            </div>
        `).join('');
    }
    
    toggleCustomFlag(index, enabled) {
        if (this.profileCustomFlags[index]) {
            this.profileCustomFlags[index].enabled = enabled;
        }
    }
    
    removeCustomFlag(index) {
        this.profileCustomFlags.splice(index, 1);
        this.renderCustomFlags();
    }
    
    renderAvailableNodes(filter = '') {
        const container = document.getElementById('available-nodes-list');
        const countEl = document.getElementById('available-count');
        if (!container) return;
        
        const filterLower = filter.toLowerCase();
        const available = this.nodes.filter(n => 
            !this.profileSelectedNodes.has(n.folder_name) &&
            (!filter || n.display_name.toLowerCase().includes(filterLower) || n.folder_name.toLowerCase().includes(filterLower))
        );
        
        container.innerHTML = available.map(n => `
            <div class="profile-node-item" data-folder="${this.escapeHtml(n.folder_name)}" 
                 onclick="app.toggleNodeSelection(this)" ondblclick="app.addNodeToProfile('${this.escapeHtml(n.folder_name)}')">
                <span class="node-name" title="${this.escapeHtml(n.folder_name)}">${this.escapeHtml(n.display_name)}</span>
            </div>
        `).join('') || '<div class="empty-state" style="padding:20px;color:var(--text-muted);font-size:11px;">All nodes in profile</div>';
        
        if (countEl) countEl.textContent = available.length;
        
        // Setup drag events
        this.setupNodeDrag(container, 'available');
    }
    
    renderSelectedNodes(filter = '') {
        const container = document.getElementById('selected-nodes-list');
        const countEl = document.getElementById('selected-count');
        if (!container) return;
        
        const filterLower = filter.toLowerCase();
        const selectedArray = Array.from(this.profileSelectedNodes);
        const filtered = selectedArray.filter(folder => {
            if (!filter) return true;
            const node = this.nodes.find(n => n.folder_name === folder);
            return node && (node.display_name.toLowerCase().includes(filterLower) || folder.toLowerCase().includes(filterLower));
        });
        
        container.innerHTML = filtered.map(folder => {
            const node = this.nodes.find(n => n.folder_name === folder);
            const displayName = node?.display_name || folder;
            return `
                <div class="profile-node-item" data-folder="${this.escapeHtml(folder)}" 
                     onclick="app.toggleNodeSelection(this)" ondblclick="app.removeNodeFromProfile('${this.escapeHtml(folder)}')">
                    <span class="node-name" title="${this.escapeHtml(folder)}">${this.escapeHtml(displayName)}</span>
                </div>
            `;
        }).join('') || '<div class="empty-state" style="padding:20px;color:var(--text-muted);font-size:11px;">Double-click or use arrows to add nodes</div>';
        
        if (countEl) countEl.textContent = this.profileSelectedNodes.size;
        
        // Setup drag events
        this.setupNodeDrag(container, 'selected');
    }
    
    toggleNodeSelection(element) {
        element.classList.toggle('selected');
    }
    
    setupNodeDrag(container, type) {
        const items = container.querySelectorAll('.profile-node-item');
        
        items.forEach(item => {
            item.draggable = true;
            item.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', item.dataset.folder);
                e.dataTransfer.setData('source', type);
                item.classList.add('dragging');
            });
            
            item.addEventListener('dragend', () => {
                item.classList.remove('dragging');
            });
        });
        
        // Drop zone - only add once
        if (!container.dataset.dropBound) {
            container.dataset.dropBound = 'true';
            
            container.addEventListener('dragover', (e) => {
                e.preventDefault();
                container.classList.add('drag-over');
            });
            
            container.addEventListener('dragleave', (e) => {
                if (!container.contains(e.relatedTarget)) {
                    container.classList.remove('drag-over');
                }
            });
            
            container.addEventListener('drop', (e) => {
                e.preventDefault();
                container.classList.remove('drag-over');
                
                const folder = e.dataTransfer.getData('text/plain');
                const source = e.dataTransfer.getData('source');
                
                if (type === 'selected' && source === 'available') {
                    this.addNodeToProfile(folder);
                } else if (type === 'available' && source === 'selected') {
                    this.removeNodeFromProfile(folder);
                }
            });
        }
    }
    
    addNodeToProfile(folder) {
        this.profileSelectedNodes.add(folder);
        this.renderAvailableNodes(document.getElementById('available-search')?.value || '');
        this.renderSelectedNodes(document.getElementById('selected-search')?.value || '');
    }
    
    removeNodeFromProfile(folder) {
        this.profileSelectedNodes.delete(folder);
        this.renderAvailableNodes(document.getElementById('available-search')?.value || '');
        this.renderSelectedNodes(document.getElementById('selected-search')?.value || '');
    }
    
    // Package management
    async loadPackagesList(refresh = false) {
        const container = document.getElementById('packages-list');
        const statsEl = document.getElementById('packages-stats');
        
        if (container) {
            container.innerHTML = '<div class="empty-state" style="padding:20px;color:var(--text-muted);">Loading packages...</div>';
        }
        if (statsEl) statsEl.textContent = 'Loading...';
        
        try {
            const url = refresh ? `${this.apiBase}/api/packages?refresh=true` : `${this.apiBase}/api/packages`;
            const response = await fetch(url);
            
            // Check if response is OK before parsing
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                throw new Error('Response is not JSON');
            }
            
            const data = await response.json();
            
            if (data.success && data.packages) {
                this.installedPackages = data.packages;
                if (container) {
                    this.renderPackagesList();
                }
                if (statsEl) {
                    statsEl.textContent = `${data.packages.length} packages`;
                }
            } else {
                const msg = data.message || 'Could not load packages';
                if (container) {
                    container.innerHTML = `<div class="empty-state" style="padding:20px;color:var(--text-muted);">${this.escapeHtml(msg)}</div>`;
                }
                if (statsEl) statsEl.textContent = 'Error';
            }
        } catch (error) {
            console.error('Error loading packages:', error);
            if (container) {
                container.innerHTML = `<div class="empty-state" style="padding:20px;color:var(--text-muted);">Error: ${this.escapeHtml(error.message)}</div>`;
            }
            if (statsEl) statsEl.textContent = 'Error';
        }
    }
    
    renderPackagesList(filter = '') {
        const container = document.getElementById('packages-list');
        if (!container || !this.installedPackages) return;
        
        const filterLower = filter.toLowerCase();
        const filtered = this.installedPackages.filter(pkg => 
            !filter || pkg.name.toLowerCase().includes(filterLower)
        );
        
        container.innerHTML = filtered.map(pkg => {
            const isExcluded = this.profileExcludedPackages.has(pkg.name);
            return `
                <div class="package-item">
                    <input type="checkbox" ${!isExcluded ? 'checked' : ''} 
                        onchange="app.togglePackage('${this.escapeHtml(pkg.name)}', this.checked)">
                    <span class="package-name">${this.escapeHtml(pkg.name)}</span>
                    <span class="package-version">${this.escapeHtml(pkg.version || '')}</span>
                </div>
            `;
        }).join('') || '<div class="empty-state" style="padding:20px;color:var(--text-muted);">No packages found</div>';
    }
    
    togglePackage(name, included) {
        if (included) {
            this.profileExcludedPackages.delete(name);
        } else {
            this.profileExcludedPackages.add(name);
        }
    }
    
    async saveProfileAdvanced(name) {
        // Ensure required nodes are always enabled
        this.requiredNodes.forEach(folder => this.profileSelectedNodes.add(folder));
        
        const enabled = Array.from(this.profileSelectedNodes);
        const disabled = this.nodes
            .filter(n => !this.profileSelectedNodes.has(n.folder_name) && !this.requiredNodes.has(n.folder_name))
            .map(n => n.folder_name);
        
        const flags = this.getSelectedFlags();
        const customFlagsList = this.profileCustomFlags;
        const customFlagsString = this.profileCustomFlags.filter(f => f.enabled).map(f => f.value).join(' ');
        const excludedPackages = Array.from(this.profileExcludedPackages);
        
        try {
            const response = await fetch(`${this.apiBase}/api/profiles/save`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    name, 
                    enabled, 
                    disabled,
                    flags,
                    custom_flags: customFlagsString,
                    custom_flags_list: customFlagsList,
                    excluded_packages: excludedPackages
                })
            });
            const data = await response.json();
            
            if (data.success) {
                this.showToast('success', `Profile "${name}" saved`);
                await this.loadProfileDropdown();
                document.getElementById('profile-select').value = name;
                document.getElementById('profile-delete-btn').style.display = 'inline-flex';
                this.currentProfileName = name;
            } else {
                this.showToast('error', data.message);
            }
        } catch (error) {
            console.error('Error saving profile:', error);
            this.showToast('error', 'Failed to save profile');
        }
    }
    
    async applyProfileAdvanced(name) {
        // First save the current state
        await this.saveProfileAdvanced(name);
        
        const flags = this.getSelectedFlags();
        const customFlagsString = this.profileCustomFlags.filter(f => f.enabled).map(f => f.value).join(' ');
        
        // Build command line
        let cmdLine = Object.values(flags).filter(f => f).join(' ');
        if (customFlagsString) {
            cmdLine += ' ' + customFlagsString;
        }
        
        const nodeCount = this.profileSelectedNodes.size;
        const totalNodes = this.nodes.length;
        const excludedPkgCount = this.profileExcludedPackages.size;
        
        let confirmMsg = `Apply profile "${name}"?\n\n` +
            `Nodes: ${nodeCount} enabled, ${totalNodes - nodeCount} disabled\n` +
            `Flags: ${cmdLine || '(none)'}`;
        
        if (excludedPkgCount > 0) {
            confirmMsg += `\nExcluded packages: ${excludedPkgCount}`;
        }
        
        confirmMsg += `\n\nThis will:\n` +
            `- Enable/disable nodes by renaming folders\n` +
            `- Create a launch batch file with selected flags`;
        
        if (excludedPkgCount > 0) {
            confirmMsg += `\n- Note: Package exclusion requires manual pip operations`;
        }
        
        confirmMsg += `\n\nRestart ComfyUI for changes to take effect.`;
        
        const confirmed = await this.showConfirm({
            title: `Apply profile "${name}"?`,
            message: confirmMsg,
            type: 'info',
            confirmText: 'Apply Profile'
        });
        if (!confirmed) return;
        
        this.log(`Applying profile: ${name}`, 'info');
        
        try {
            const response = await fetch(`${this.apiBase}/api/profiles/apply`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    name,
                    flags: cmdLine
                })
            });
            const data = await response.json();
            
            if (data.success) {
                this.log(data.message, 'success');
                this.showToast('success', data.message);
                this.closeProfilesModal();
                await this.refreshNodes();
            } else {
                this.log(`Failed: ${data.message}`, 'error');
                this.showToast('error', data.message);
            }
        } catch (error) {
            console.error('Error applying profile:', error);
            this.log(`Error: ${error.message}`, 'error');
            this.showToast('error', 'Failed to apply profile');
        }
    }
}

// Initialize the app and expose globally for inline handlers
const app = new MFConductor();
window.app = app;

