/**
 * MF Conductor - WebSocket Manager
 * Provides real-time communication with the backend
 */

import { isStandaloneMode } from './utils.js';

class WebSocketManager {
    constructor() {
        this.ws = null;
        this.url = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000;
        this.handlers = new Map();
        this.connected = false;
        this.messageQueue = [];
    }

    /**
     * Connect to the WebSocket server
     * @param {string} customUrl - Optional custom WebSocket URL
     */
    connect(customUrl = null) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            return Promise.resolve();
        }

        return new Promise((resolve, reject) => {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const port = isStandaloneMode() ? '8199' : '8188';
            const path = isStandaloneMode() ? '/ws' : '/mf_conductor/ws';
            
            this.url = customUrl || `${protocol}//${window.location.hostname}:${port}${path}`;

            try {
                this.ws = new WebSocket(this.url);

                this.ws.onopen = () => {
                    console.log('[MF Conductor] WebSocket connected');
                    this.connected = true;
                    this.reconnectAttempts = 0;
                    
                    // Send queued messages
                    while (this.messageQueue.length > 0) {
                        const msg = this.messageQueue.shift();
                        this.send(msg.type, msg.data);
                    }
                    
                    this.emit('connected');
                    resolve();
                };

                this.ws.onmessage = (event) => {
                    try {
                        const message = JSON.parse(event.data);
                        this.handleMessage(message);
                    } catch (e) {
                        console.warn('[MF Conductor] Invalid WebSocket message:', e);
                    }
                };

                this.ws.onclose = (event) => {
                    console.log('[MF Conductor] WebSocket closed:', event.code);
                    this.connected = false;
                    this.emit('disconnected', event);
                    
                    // Attempt reconnection
                    if (this.reconnectAttempts < this.maxReconnectAttempts) {
                        setTimeout(() => {
                            this.reconnectAttempts++;
                            console.log(`[MF Conductor] Reconnecting (attempt ${this.reconnectAttempts})...`);
                            this.connect();
                        }, this.reconnectDelay * Math.pow(2, this.reconnectAttempts));
                    }
                };

                this.ws.onerror = (error) => {
                    console.error('[MF Conductor] WebSocket error:', error);
                    this.emit('error', error);
                    reject(error);
                };
            } catch (e) {
                console.error('[MF Conductor] Failed to create WebSocket:', e);
                reject(e);
            }
        });
    }

    /**
     * Disconnect from the WebSocket server
     */
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
            this.connected = false;
        }
    }

    /**
     * Send a message to the server
     * @param {string} type - Message type
     * @param {Object} data - Message data
     */
    send(type, data = {}) {
        const message = JSON.stringify({ type, data, timestamp: Date.now() });
        
        if (this.connected && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(message);
        } else {
            // Queue message for later
            this.messageQueue.push({ type, data });
        }
    }

    /**
     * Handle incoming message
     * @param {Object} message - Parsed message object
     */
    handleMessage(message) {
        const { type, data } = message;
        
        // Emit to type-specific handlers
        this.emit(type, data);
        
        // Emit to global handlers
        this.emit('message', message);
    }

    /**
     * Register an event handler
     * @param {string} event - Event name
     * @param {Function} handler - Event handler
     */
    on(event, handler) {
        if (!this.handlers.has(event)) {
            this.handlers.set(event, new Set());
        }
        this.handlers.get(event).add(handler);
        
        return () => this.off(event, handler);
    }

    /**
     * Remove an event handler
     * @param {string} event - Event name
     * @param {Function} handler - Event handler
     */
    off(event, handler) {
        const handlers = this.handlers.get(event);
        if (handlers) {
            handlers.delete(handler);
        }
    }

    /**
     * Emit an event to all handlers
     * @param {string} event - Event name
     * @param {any} data - Event data
     */
    emit(event, data) {
        const handlers = this.handlers.get(event);
        if (handlers) {
            handlers.forEach(handler => {
                try {
                    handler(data);
                } catch (e) {
                    console.error(`[MF Conductor] Handler error for ${event}:`, e);
                }
            });
        }
    }

    /**
     * Check if connected
     * @returns {boolean}
     */
    isConnected() {
        return this.connected && this.ws && this.ws.readyState === WebSocket.OPEN;
    }

    /**
     * Subscribe to console output
     */
    subscribeToConsole() {
        this.send('subscribe', { channel: 'console' });
    }

    /**
     * Subscribe to status updates
     */
    subscribeToStatus() {
        this.send('subscribe', { channel: 'status' });
    }

    /**
     * Unsubscribe from a channel
     * @param {string} channel - Channel name
     */
    unsubscribe(channel) {
        this.send('unsubscribe', { channel });
    }
}

// Export singleton instance
export const websocket = new WebSocketManager();
export default websocket;







