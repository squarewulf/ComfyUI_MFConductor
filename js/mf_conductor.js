import { app } from "../../scripts/app.js";

// MF Conductor - ComfyUI Integration
app.registerExtension({
    name: "MF.Conductor",
    
    async setup() {
        // Create the modal structure
        this.createModal();
        // Add menu button after ComfyUI loads
        setTimeout(() => this.addMenuButton(), 1000);
    },
    
    createModal() {
        // Create modal overlay
        const overlay = document.createElement('div');
        overlay.id = 'mf-conductor-overlay';
        overlay.style.cssText = `
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: rgba(0, 0, 0, 0.8);
            z-index: 10000;
            justify-content: center;
            align-items: center;
            backdrop-filter: blur(4px);
        `;
        
        // Create modal container
        const modal = document.createElement('div');
        modal.id = 'mf-conductor-modal';
        modal.style.cssText = `
            width: 90vw;
            height: 90vh;
            max-width: 1400px;
            background: #1a1a1a;
            border-radius: 12px;
            box-shadow: 0 25px 50px rgba(0, 0, 0, 0.5);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            border: 1px solid #333;
        `;
        
        // Create minimal header (just action buttons, no duplicate title)
        const header = document.createElement('div');
        header.style.cssText = `
            display: flex;
            justify-content: flex-end;
            align-items: center;
            padding: 8px 12px;
            background: transparent;
            position: absolute;
            top: 0;
            right: 0;
            z-index: 100;
        `;
        
        const headerActions = document.createElement('div');
        headerActions.style.cssText = `display: flex; gap: 6px; align-items: center;`;
        
        // Pop-out button
        const popoutBtn = document.createElement('button');
        popoutBtn.title = 'Open in new tab';
        popoutBtn.style.cssText = `
            background: #333;
            border: 1px solid #444;
            border-radius: 6px;
            padding: 8px;
            cursor: pointer;
            color: #aaa;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        popoutBtn.innerHTML = `
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                <polyline points="15 3 21 3 21 9"/>
                <line x1="10" y1="14" x2="21" y2="3"/>
            </svg>
        `;
        popoutBtn.onclick = () => window.open('/mf_conductor/', '_blank');
        popoutBtn.onmouseenter = () => popoutBtn.style.background = '#444';
        popoutBtn.onmouseleave = () => popoutBtn.style.background = '#333';
        
        // Close button
        const closeBtn = document.createElement('button');
        closeBtn.title = 'Close';
        closeBtn.style.cssText = `
            background: #333;
            border: 1px solid #444;
            border-radius: 6px;
            padding: 8px;
            cursor: pointer;
            color: #aaa;
            display: flex;
            align-items: center;
            justify-content: center;
        `;
        closeBtn.innerHTML = `
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
        `;
        closeBtn.onclick = () => this.closeModal();
        closeBtn.onmouseenter = () => { closeBtn.style.background = '#f87171'; closeBtn.style.color = '#fff'; };
        closeBtn.onmouseleave = () => { closeBtn.style.background = '#333'; closeBtn.style.color = '#aaa'; };
        
        headerActions.appendChild(popoutBtn);
        headerActions.appendChild(closeBtn);
        header.appendChild(headerActions);
        
        // Create iframe container
        const iframeContainer = document.createElement('div');
        iframeContainer.style.cssText = `flex: 1; overflow: hidden;`;
        
        const iframe = document.createElement('iframe');
        iframe.id = 'mf-conductor-iframe';
        iframe.style.cssText = `
            width: 100%;
            height: 100%;
            border: none;
            background: #1a1a1a;
        `;
        
        iframeContainer.appendChild(iframe);
        modal.appendChild(header);
        modal.appendChild(iframeContainer);
        overlay.appendChild(modal);
        
        // Close on overlay click
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                this.closeModal();
            }
        });
        
        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && overlay.style.display === 'flex') {
                this.closeModal();
            }
        });
        
        document.body.appendChild(overlay);
        
        this.overlay = overlay;
        this.iframe = iframe;
    },
    
    openModal() {
        if (!this.overlay) return;
        
        // Load the iframe content
        this.iframe.src = '/mf_conductor/index.html';
        this.overlay.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    },
    
    closeModal() {
        if (!this.overlay) return;
        
        this.overlay.style.display = 'none';
        this.iframe.src = 'about:blank';
        document.body.style.overflow = '';
    },
    
    addMenuButton() {
        // Check if already added
        if (document.getElementById('mf-conductor-btn')) return;
        
        let sidebarNav = null;
        
        // Method 1: Look for the sidebar by finding known items and traversing up
        const sidebarTexts = ['Assets', 'Nodes', 'Models', 'Workflows', 'Templates'];
        for (const text of sidebarTexts) {
            // Find elements with this exact text
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            while (walker.nextNode()) {
                if (walker.currentNode.textContent.trim() === text) {
                    // Found the text, traverse up to find the sidebar container
                    let parent = walker.currentNode.parentElement;
                    for (let i = 0; i < 10 && parent; i++) {
                        // Look for a flex column container with multiple items
                        const style = getComputedStyle(parent);
                        if (style.display === 'flex' && style.flexDirection === 'column') {
                            // Check if this looks like the sidebar (has multiple similar children)
                            const children = Array.from(parent.children);
                            if (children.length >= 4) {
                                sidebarNav = parent;
                                break;
                            }
                        }
                        parent = parent.parentElement;
                    }
                    if (sidebarNav) break;
                }
            }
            if (sidebarNav) break;
        }
        
        // Method 2: Find by common class patterns
        if (!sidebarNav) {
            sidebarNav = document.querySelector('.side-bar-content') ||
                         document.querySelector('nav.side-bar-content') ||
                         document.querySelector('.comfyui-body-left nav') ||
                         document.querySelector('[class*="sidebar"] nav') ||
                         document.querySelector('.side-bar-panel');
        }
        
        // Method 3: Find by position and structure
        if (!sidebarNav) {
            const allElements = document.querySelectorAll('div, nav, aside, ul');
            for (const el of allElements) {
                const rect = el.getBoundingClientRect();
                const style = getComputedStyle(el);
                // Left sidebar characteristics
                if (rect.left < 100 && 
                    rect.width > 40 && rect.width < 200 && 
                    rect.height > 300 &&
                    style.display === 'flex' && 
                    style.flexDirection === 'column' &&
                    el.children.length >= 4) {
                    sidebarNav = el;
                    console.log('[MF Conductor] Found sidebar by position:', el);
                    break;
                }
            }
        }
        
        if (!sidebarNav) {
            // Retry if not found yet
            if (!this._menuRetryCount) this._menuRetryCount = 0;
            this._menuRetryCount++;
            if (this._menuRetryCount < 20) {
                setTimeout(() => this.addMenuButton(), 500);
                if (this._menuRetryCount % 5 === 0) {
                    console.log(`[MF Conductor] Sidebar not found, retrying... (${this._menuRetryCount}/20)`);
                }
            } else {
                console.log('[MF Conductor] Could not find sidebar, creating floating button');
                this.createFloatingButton();
            }
            return;
        }
        
        console.log('[MF Conductor] Found sidebar container:', sidebarNav);
        
        // Create button matching the sidebar style
        const btnContainer = document.createElement('div');
        btnContainer.id = 'mf-conductor-btn';
        btnContainer.title = 'MF Conductor - Node Manager';
        btnContainer.setAttribute('role', 'button');
        btnContainer.setAttribute('tabindex', '0');
        
        // Copy styles from an existing sidebar item if possible
        const existingItem = sidebarNav.querySelector('[role="button"], button') || sidebarNav.children[0];
        if (existingItem) {
            const existingStyle = getComputedStyle(existingItem);
            btnContainer.style.cssText = `
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: ${existingStyle.padding || '8px 4px'};
                background: transparent;
                border: none;
                border-radius: ${existingStyle.borderRadius || '8px'};
                color: ${existingStyle.color || '#888'};
                cursor: pointer;
                transition: all 0.15s ease;
                gap: 4px;
                min-width: ${existingStyle.minWidth || '64px'};
                width: 100%;
                box-sizing: border-box;
            `;
        } else {
            btnContainer.style.cssText = `
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 8px 4px;
                background: transparent;
                border: none;
                border-radius: 8px;
                color: #888;
                cursor: pointer;
                transition: all 0.15s ease;
                gap: 4px;
                min-width: 64px;
                width: 100%;
                box-sizing: border-box;
            `;
        }
        
        btnContainer.innerHTML = `
            <svg viewBox="0 0 388.15 344.51" width="20" height="20" fill="currentColor" style="flex-shrink: 0;">
                <path d="M119.35,286.29c-19.17.33-44.79,3.24-46.01-23.2,0,0,0-128.35,0-128.35,19.17-.33,44.79-3.24,46.01,23.2,0,0,0,128.35,0,128.35ZM170.32,344.26c-19.17.32-44.79,3.24-46.01-23.2,0,0,0-186.51,0-186.51,19.17-.32,44.79-3.24,46.01,23.2,0,0,0,186.51,0,186.51ZM221.29,321.06c-1.22,26.45-26.88,23.52-46.01,23.2v-96.31c7.47-15.72,32.33-10.76,46.01-11.46v84.57ZM275.64,208.33c-3.58,46.05-78.43,6.96-100.36,31.56.6-6.9-1.54-34.07,1.77-40.07,3.61-8.69,12.02-14.31,21.43-14.31h77.16v22.82Z"/>
                <path d="M216,94.07c.62-5.52-2.16-9.58-7.85-10.03-11.87-.93-24.95.71-36.95.02-1.69-.04-3.09-1.33-3.29-2.99l10.26-36.28c.6-1.54,1.26-2.27,2.97-2.43,3.9-.37,9.32-.16,13.39-.22,8.43-.11,18.38.74,26.57,0,14.75-1.31,15.25-21.21,19.09-31.88.5-4.74-1.4-8.53-6.18-9.74-15.28.06-30.87-1-46.17-.28-4.83.23-8.64,1.48-12.09,4.97-5.19,5.24-5.24,14.06-7.92,20.58-.43,1.04-1.21,2.18-2.43,2.32-5.79.68-12.35-1.08-18.03,1.19-3.74,1.49-6.78,4.45-8.68,7.95l-14.65,49.82v5.18c.47.69.67,1.54,1.11,2.23,3.66,5.66,12.41,2.86,17.98,3.62,1.93.26,2.88,1.87,2.7,3.74-.63,6.52-7.41,15.72-1.92,21.61,1.49,1.6,3.77,2.35,5.92,2.5,14.9,1.04,30.99-.8,46.02,0,5.52-.28,11.25-4.35,13.59-9.3,1.05-2.22,6.26-19.87,6.57-22.59Z"/>
                <path d="M176.43,156.9c1.15-11.27,10.87-19.04,21.83-19.75,26.41-1.72,54.69,1.31,81.3.03,1.04-.06,2.07-.29,3.04-.63,4.09-1.44,11.68-11.32,14.7-15.06,2.81-3.48,5.01-8.23,8.86-10.71s8.91-4.13,13.16-5.39c-.25-2,.38-3.97.47-5.84,1.26-26.81.64-54.24,2.44-80.98.16-2.41.5-6.99,3.55-7.46,4.2-.65,4.46,5.07,4.63,7.85,1.19,19.65,1.35,39.72,2.04,59.4.13,3.79-.04,24.94.89,26.59.54.96,2.5,1.77,3.48,4.46,3.72,10.31,2.3,18.3-2.68,27.63-9.6,18-27.95,42.17-50.08,43.69-28.46,1.95-59.12-1.5-87.81-.01-8.02.6-14.43,4.49-19.81,10.17v-33.97Z"/>
                <path d="M68.62,186.4c-21.95-1.59-55.34,7.56-61.13-21.89C4.05,147.02,3.13,128.54,0,110.94c-.08-14.37,8.83-17.26,21.41-15.23,20.05,3.24,16.72,19.74,22.6,35.26,2.65,6.98,8.14,4.12,13.59,6.39,4.5,1.87,11.02,9.32,11.02,14.24v34.79Z"/>
            </svg>
            <span style="font-size: 9px; white-space: nowrap;">MF Conductor</span>
        `;
        
        btnContainer.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.openModal();
        };
        
        btnContainer.onmouseenter = () => {
            btnContainer.style.background = 'rgba(74, 158, 255, 0.15)';
            btnContainer.style.color = '#4a9eff';
        };
        
        btnContainer.onmouseleave = () => {
            btnContainer.style.background = 'transparent';
            btnContainer.style.color = existingItem ? getComputedStyle(existingItem).color : '#888';
        };
        
        // Find where to insert (before Settings/Help if found)
        let insertBefore = null;
        for (const child of sidebarNav.children) {
            const text = (child.textContent || '').toLowerCase();
            const title = (child.getAttribute('title') || '').toLowerCase();
            if (text.includes('setting') || title.includes('setting') ||
                text.includes('help') || title.includes('help') ||
                text.includes('console') || title.includes('console')) {
                insertBefore = child;
                break;
            }
        }
        
        if (insertBefore) {
            sidebarNav.insertBefore(btnContainer, insertBefore);
        } else {
            sidebarNav.appendChild(btnContainer);
        }
        
        console.log('[MF Conductor] Button added to ComfyUI sidebar');
    },
    
    createFloatingButton() {
        // Fallback: create a floating button in the corner
        const btn = document.createElement('button');
        btn.id = 'mf-conductor-btn';
        btn.title = 'MF Conductor - Node Manager';
        btn.innerHTML = `
            <svg viewBox="0 0 388.15 344.51" width="24" height="24" fill="currentColor">
                <path d="M119.35,286.29c-19.17.33-44.79,3.24-46.01-23.2,0,0,0-128.35,0-128.35,19.17-.33,44.79-3.24,46.01,23.2,0,0,0,128.35,0,128.35ZM170.32,344.26c-19.17.32-44.79,3.24-46.01-23.2,0,0,0-186.51,0-186.51,19.17-.32,44.79-3.24,46.01,23.2,0,0,0,186.51,0,186.51ZM221.29,321.06c-1.22,26.45-26.88,23.52-46.01,23.2v-96.31c7.47-15.72,32.33-10.76,46.01-11.46v84.57ZM275.64,208.33c-3.58,46.05-78.43,6.96-100.36,31.56.6-6.9-1.54-34.07,1.77-40.07,3.61-8.69,12.02-14.31,21.43-14.31h77.16v22.82Z"/>
                <path d="M216,94.07c.62-5.52-2.16-9.58-7.85-10.03-11.87-.93-24.95.71-36.95.02-1.69-.04-3.09-1.33-3.29-2.99l10.26-36.28c.6-1.54,1.26-2.27,2.97-2.43,3.9-.37,9.32-.16,13.39-.22,8.43-.11,18.38.74,26.57,0,14.75-1.31,15.25-21.21,19.09-31.88.5-4.74-1.4-8.53-6.18-9.74-15.28.06-30.87-1-46.17-.28-4.83.23-8.64,1.48-12.09,4.97-5.19,5.24-5.24,14.06-7.92,20.58-.43,1.04-1.21,2.18-2.43,2.32-5.79.68-12.35-1.08-18.03,1.19-3.74,1.49-6.78,4.45-8.68,7.95l-14.65,49.82v5.18c.47.69.67,1.54,1.11,2.23,3.66,5.66,12.41,2.86,17.98,3.62,1.93.26,2.88,1.87,2.7,3.74-.63,6.52-7.41,15.72-1.92,21.61,1.49,1.6,3.77,2.35,5.92,2.5,14.9,1.04,30.99-.8,46.02,0,5.52-.28,11.25-4.35,13.59-9.3,1.05-2.22,6.26-19.87,6.57-22.59Z"/>
                <path d="M176.43,156.9c1.15-11.27,10.87-19.04,21.83-19.75,26.41-1.72,54.69,1.31,81.3.03,1.04-.06,2.07-.29,3.04-.63,4.09-1.44,11.68-11.32,14.7-15.06,2.81-3.48,5.01-8.23,8.86-10.71s8.91-4.13,13.16-5.39c-.25-2,.38-3.97.47-5.84,1.26-26.81.64-54.24,2.44-80.98.16-2.41.5-6.99,3.55-7.46,4.2-.65,4.46,5.07,4.63,7.85,1.19,19.65,1.35,39.72,2.04,59.4.13,3.79-.04,24.94.89,26.59.54.96,2.5,1.77,3.48,4.46,3.72,10.31,2.3,18.3-2.68,27.63-9.6,18-27.95,42.17-50.08,43.69-28.46,1.95-59.12-1.5-87.81-.01-8.02.6-14.43,4.49-19.81,10.17v-33.97Z"/>
                <path d="M68.62,186.4c-21.95-1.59-55.34,7.56-61.13-21.89C4.05,147.02,3.13,128.54,0,110.94c-.08-14.37,8.83-17.26,21.41-15.23,20.05,3.24,16.72,19.74,22.6,35.26,2.65,6.98,8.14,4.12,13.59,6.39,4.5,1.87,11.02,9.32,11.02,14.24v34.79Z"/>
            </svg>
        `;
        btn.style.cssText = `
            position: fixed;
            bottom: 80px;
            left: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 48px;
            height: 48px;
            padding: 10px;
            background: #1a1a2e;
            border: 2px solid #4a9eff;
            border-radius: 50%;
            color: #4a9eff;
            cursor: pointer;
            transition: all 0.15s ease;
            z-index: 9999;
            box-shadow: 0 4px 12px rgba(0,0,0,0.4);
        `;
        
        btn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.openModal();
        };
        
        btn.onmouseenter = () => {
            btn.style.transform = 'scale(1.1)';
            btn.style.boxShadow = '0 6px 20px rgba(74, 158, 255, 0.4)';
        };
        
        btn.onmouseleave = () => {
            btn.style.transform = 'scale(1)';
            btn.style.boxShadow = '0 4px 12px rgba(0,0,0,0.4)';
        };
        
        document.body.appendChild(btn);
        console.log('[MF Conductor] Floating button created as fallback');
    }
});
