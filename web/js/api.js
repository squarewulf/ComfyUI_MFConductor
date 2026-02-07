/**
 * MF Conductor - API Service
 * Centralized API communication layer
 */

import { getApiBase } from './utils.js';

class APIService {
    constructor() {
        this.baseUrl = getApiBase();
    }

    /**
     * Make an API request
     * @param {string} endpoint - API endpoint
     * @param {Object} options - Fetch options
     * @returns {Promise<Object>} Response data
     */
    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        };

        if (options.body && typeof options.body === 'object') {
            config.body = JSON.stringify(options.body);
        }

        try {
            const response = await fetch(url, config);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }
            
            return data;
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            throw error;
        }
    }

    // ==================== NODE OPERATIONS ====================

    async getNodes() {
        return this.request('/api/nodes');
    }

    async refreshNodes() {
        return this.request('/api/nodes/refresh', { method: 'POST' });
    }

    async installNode(url, folderName = null, installDeps = true) {
        return this.request('/api/nodes/install', {
            method: 'POST',
            body: { url, folder_name: folderName, install_deps: installDeps }
        });
    }

    async updateNode(folderName) {
        return this.request(`/api/nodes/${folderName}/update`, { method: 'POST' });
    }

    async removeNode(folderName) {
        return this.request(`/api/nodes/${folderName}/remove`, { method: 'POST' });
    }

    async activateNode(folderName) {
        return this.request(`/api/nodes/${folderName}/activate`, { method: 'POST' });
    }

    async deactivateNode(folderName) {
        return this.request(`/api/nodes/${folderName}/deactivate`, { method: 'POST' });
    }

    async openNodeFolder(folderName) {
        return this.request(`/api/nodes/${folderName}/open-folder`, { method: 'POST' });
    }

    async getNodeRequirements(folderName) {
        return this.request(`/api/nodes/${folderName}/requirements`);
    }

    // ==================== PACKAGE OPERATIONS ====================

    async getPackages() {
        return this.request('/api/packages');
    }

    async installPackage(packageName) {
        return this.request('/api/install-package', {
            method: 'POST',
            body: { package_name: packageName }
        });
    }

    async uninstallPackage(packageName) {
        return this.request('/api/uninstall-package', {
            method: 'POST',
            body: { package_name: packageName }
        });
    }

    async upgradePackage(packageName) {
        return this.request('/api/upgrade-package', {
            method: 'POST',
            body: { package_name: packageName }
        });
    }

    async reinstallPackage(packageName) {
        return this.request('/api/reinstall-package', {
            method: 'POST',
            body: { package_name: packageName }
        });
    }

    async checkPackageUpdates() {
        return this.request('/api/packages/check-updates', { method: 'POST' });
    }

    async checkSinglePackageUpdate(packageName) {
        return this.request('/api/packages/check-single-update', {
            method: 'POST',
            body: { package_name: packageName }
        });
    }

    // ==================== USER DATA OPERATIONS ====================

    async getUserData() {
        return this.request('/api/user-data');
    }

    async getFavorites() {
        return this.request('/api/favorites');
    }

    async toggleFavorite(folderName) {
        return this.request(`/api/favorites/${folderName}/toggle`, { method: 'POST' });
    }

    async getTags(folderName = null) {
        const endpoint = folderName ? `/api/tags/${folderName}` : '/api/tags';
        return this.request(endpoint);
    }

    async setTags(folderName, tags) {
        return this.request(`/api/tags/${folderName}`, {
            method: 'POST',
            body: { tags }
        });
    }

    async getNote(folderName) {
        return this.request(`/api/notes/${folderName}`);
    }

    async setNote(folderName, note) {
        return this.request(`/api/notes/${folderName}`, {
            method: 'POST',
            body: { note }
        });
    }

    // ==================== PROFILE OPERATIONS ====================

    async getProfiles() {
        return this.request('/api/profiles');
    }

    async getProfile(name) {
        return this.request(`/api/profiles/${encodeURIComponent(name)}`);
    }

    async saveProfile(name, data) {
        return this.request(`/api/profiles/${encodeURIComponent(name)}`, {
            method: 'POST',
            body: data
        });
    }

    async deleteProfile(name) {
        return this.request(`/api/profiles/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });
    }

    async setDefaultProfile(name) {
        return this.request(`/api/profiles/${encodeURIComponent(name)}/set-default`, {
            method: 'POST'
        });
    }

    async applyProfile(name) {
        return this.request(`/api/profiles/${encodeURIComponent(name)}/apply`, {
            method: 'POST'
        });
    }

    async loadPresetProfiles() {
        return this.request('/api/profiles/load-presets', { method: 'POST' });
    }

    // ==================== BROWSE OPERATIONS ====================

    async browseNodes(query = '', category = '', page = 1, perPage = 50) {
        const params = new URLSearchParams({
            query,
            category,
            page: page.toString(),
            per_page: perPage.toString()
        });
        return this.request(`/api/browse?${params}`);
    }

    async getBrowseCategories() {
        return this.request('/api/browse/categories');
    }

    async refreshBrowseDatabase() {
        return this.request('/api/browse/refresh', { method: 'POST' });
    }

    async getBrowseNodeDetails(reference) {
        return this.request(`/api/browse/details?reference=${encodeURIComponent(reference)}`);
    }

    // ==================== SETTINGS OPERATIONS ====================

    async getSettings() {
        return this.request('/api/settings');
    }

    async saveSettings(settings) {
        return this.request('/api/settings', {
            method: 'POST',
            body: settings
        });
    }

    async resetSettings() {
        return this.request('/api/settings/reset', { method: 'POST' });
    }

    // ==================== BACKUP OPERATIONS ====================

    async exportBackup() {
        return this.request('/api/backup/export');
    }

    async importBackup(data, merge = false) {
        return this.request('/api/backup/import', {
            method: 'POST',
            body: { data, merge }
        });
    }

    // ==================== COMFY OPERATIONS ====================

    async getComfyStatus() {
        return this.request('/api/comfy/status');
    }

    async launchComfy(profile = null) {
        return this.request('/api/comfy/launch', {
            method: 'POST',
            body: { profile }
        });
    }

    async stopComfy() {
        return this.request('/api/comfy/stop', { method: 'POST' });
    }

    async restartComfy() {
        return this.request('/api/comfy/restart', { method: 'POST' });
    }

    async getComfyOutput() {
        return this.request('/api/comfy/output');
    }

    // ==================== BACKEND LOGS ====================

    async getBackendLogs(sinceIndex = 0) {
        return this.request(`/api/backend-logs?since=${sinceIndex}`);
    }

    // ==================== SHORTCUT OPERATIONS ====================

    async createConductorShortcut(savePath, avatar = 'default') {
        return this.request('/api/shortcuts/conductor', {
            method: 'POST',
            body: { save_path: savePath, avatar }
        });
    }

    async createProfileShortcut(profileName, savePath) {
        return this.request('/api/shortcuts/profile', {
            method: 'POST',
            body: { profile_name: profileName, save_path: savePath }
        });
    }

    async getDesktopPath() {
        return this.request('/api/system/desktop-path');
    }

    async showSaveDialog(suggestedName) {
        return this.request('/api/system/save-dialog', {
            method: 'POST',
            body: { suggested_name: suggestedName }
        });
    }
}

// Export singleton instance
export const api = new APIService();
export default api;







