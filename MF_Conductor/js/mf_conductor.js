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
        
        // Create header
        const header = document.createElement('div');
        header.style.cssText = `
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 20px;
            background: #232323;
            border-bottom: 1px solid #333;
        `;
        
        const title = document.createElement('div');
        title.style.cssText = `
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 16px;
            font-weight: 600;
            color: #e0e0e0;
        `;
        title.innerHTML = `
            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#4a9eff" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
            </svg>
            <span>MF<span style="color: #4a9eff;">Conductor</span></span>
        `;
        
        const headerActions = document.createElement('div');
        headerActions.style.cssText = `display: flex; gap: 8px; align-items: center;`;
        
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
        header.appendChild(title);
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
        
        // Try to find the side toolbar container
        const sideToolbar = document.querySelector('.side-tool-bar-container') ||
                           document.querySelector('[class*="side-tool-bar"]') ||
                           document.querySelector('.comfyui-body-left');
        
        if (!sideToolbar) {
            // Retry if not found yet
            setTimeout(() => this.addMenuButton(), 1000);
            return;
        }
        
        // Create button matching the toolbar style
        const btn = document.createElement('button');
        btn.id = 'mf-conductor-btn';
        btn.title = 'Node Manager (MF Conductor)';
        btn.innerHTML = `
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                <path d="M2 17l10 5 10-5"/>
                <path d="M2 12l10 5 10-5"/>
            </svg>
        `;
        btn.className = 'comfyui-button side-bar-button';
        btn.style.cssText = `
            display: flex;
            align-items: center;
            justify-content: center;
            width: 32px;
            height: 32px;
            padding: 6px;
            background: transparent;
            border: none;
            border-radius: 4px;
            color: #aaa;
            cursor: pointer;
            transition: all 0.15s ease;
        `;
        
        btn.onclick = () => this.openModal();
        
        btn.onmouseenter = () => {
            btn.style.background = 'rgba(74, 158, 255, 0.2)';
            btn.style.color = '#4a9eff';
        };
        
        btn.onmouseleave = () => {
            btn.style.background = 'transparent';
            btn.style.color = '#aaa';
        };
        
        // Add to the side toolbar
        sideToolbar.appendChild(btn);
        
        console.log('[MF Conductor] Button added to side toolbar');
    }
});
