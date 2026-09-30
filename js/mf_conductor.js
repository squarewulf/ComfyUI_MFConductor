import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "MF.Conductor",

    commands: [
        {
            id: "MF.Conductor.Open",
            label: "Open MF Conductor",
            icon: "pi pi-sliders-h",
            function: () => window._mfConductorOpen?.(),
        },
    ],

    menuCommands: [
        {
            path: ["Extensions"],
            commands: ["MF.Conductor.Open"],
        },
    ],

    async setup() {
        this.createModal();
        window._mfConductorOpen = () => this.openModal();
        this.loadPendingWorkflow();

        const manager = app.extensionManager;
        if (manager && typeof manager.registerSidebarTab === "function") {
            manager.registerSidebarTab({
                id: "mf-conductor",
                icon: "pi pi-sliders-h",
                title: "MF Conductor",
                tooltip: "MF Conductor",
                type: "custom",
                render: (el) => {
                    el.replaceChildren();
                    el.style.cssText = "display:flex;flex-direction:column;height:100%;min-height:0;";
                    const iframe = document.createElement("iframe");
                    iframe.src = "/mf_conductor/index.html";
                    iframe.style.cssText = "width:100%;height:100%;border:none;flex:1;background:#1a1a1a;";
                    el.appendChild(iframe);
                },
            });
            return;
        }

        this.createFloatingButton();
    },

    createModal() {
        const overlay = document.createElement("div");
        overlay.id = "mf-conductor-overlay";
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

        const modal = document.createElement("div");
        modal.id = "mf-conductor-modal";
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

        const header = document.createElement("div");
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

        const headerActions = document.createElement("div");
        headerActions.style.cssText = "display: flex; gap: 6px; align-items: center;";

        const popoutBtn = document.createElement("button");
        popoutBtn.title = "Open in new tab";
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
        popoutBtn.onclick = () => window.open("/mf_conductor/", "_blank");
        popoutBtn.onmouseenter = () => { popoutBtn.style.background = "#444"; };
        popoutBtn.onmouseleave = () => { popoutBtn.style.background = "#333"; };

        const closeBtn = document.createElement("button");
        closeBtn.title = "Close";
        closeBtn.style.cssText = popoutBtn.style.cssText;
        closeBtn.innerHTML = `
            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
        `;
        closeBtn.onclick = () => this.closeModal();
        closeBtn.onmouseenter = () => { closeBtn.style.background = "#f87171"; closeBtn.style.color = "#fff"; };
        closeBtn.onmouseleave = () => { closeBtn.style.background = "#333"; closeBtn.style.color = "#aaa"; };

        headerActions.appendChild(popoutBtn);
        headerActions.appendChild(closeBtn);
        header.appendChild(headerActions);

        const iframeContainer = document.createElement("div");
        iframeContainer.style.cssText = "flex: 1; overflow: hidden;";

        const iframe = document.createElement("iframe");
        iframe.id = "mf-conductor-iframe";
        iframe.style.cssText = "width: 100%; height: 100%; border: none; background: #1a1a1a;";

        iframeContainer.appendChild(iframe);
        modal.appendChild(header);
        modal.appendChild(iframeContainer);
        overlay.appendChild(modal);

        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) this.closeModal();
        });
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && overlay.style.display === "flex") this.closeModal();
        });

        document.body.appendChild(overlay);
        this.overlay = overlay;
        this.iframe = iframe;
    },

    openModal() {
        if (!this.overlay) return;
        this.iframe.src = "/mf_conductor/index.html";
        this.overlay.style.display = "flex";
        document.body.style.overflow = "hidden";
    },

    closeModal() {
        if (!this.overlay) return;
        this.overlay.style.display = "none";
        this.iframe.src = "about:blank";
        document.body.style.overflow = "";
    },

    createFloatingButton() {
        if (document.getElementById("mf-conductor-btn")) return;
        const btn = document.createElement("button");
        btn.id = "mf-conductor-btn";
        btn.title = "MF Conductor";
        btn.textContent = "MF";
        btn.style.cssText = `
            position: fixed;
            bottom: 80px;
            left: 10px;
            width: 48px;
            height: 48px;
            background: #1a1a2e;
            border: 2px solid #4a9eff;
            border-radius: 50%;
            color: #4a9eff;
            cursor: pointer;
            z-index: 9999;
            font-weight: 700;
        `;
        btn.onclick = () => this.openModal();
        document.body.appendChild(btn);
    },

    async loadPendingWorkflow() {
        let payload = null;
        for (const delay of [600, 1500, 3000]) {
            await new Promise((resolve) => setTimeout(resolve, delay));
            try {
                const response = await fetch("/mf_conductor/api/workflows/pending");
                payload = await response.json();
                if (payload && payload.success) {
                    break;
                }
            } catch (error) {
                payload = null;
            }
        }
        if (!payload?.pending || !payload.workflow) {
            return;
        }

        let workflow = payload.workflow;
        if (payload.path) {
            try {
                const userFile = `workflows/${payload.path}`;
                const response = await fetch(`/api/userdata/${encodeURIComponent(userFile)}`);
                if (response.ok) {
                    const fromUser = await response.json();
                    if (fromUser && fromUser.nodes) {
                        workflow = fromUser;
                    }
                }
            } catch (error) {
                // Use the pending JSON already fetched from MF Conductor.
            }
        }

        if (typeof app.loadGraphData !== "function") {
            return;
        }
        try {
            await app.loadGraphData(workflow);
        } catch (error) {
            return;
        }
        try {
            await fetch("/mf_conductor/api/workflows/pending/ack", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            });
        } catch (error) {
            // Keep the pending file so a refresh can still open the workflow.
        }
    },
});
