/**
 * Armosa Chat Widget v4.1
 * "Mobile App" Edition - Smartphone UI Aesthetic
 * 
 * Design Philosophy:
 * - ChatGPT familiarity (bubbles, avatars)
 * - Claude cleanliness (typography, spacing)
 * - Perplexity utility (smart parsing)
 * - Brand Immersion (Blue #2563EB, Gold #FFB800, Green #00C896)
 * 
 * Authentication:
 * - Built-in login modal with email/password
 * - Persists auth state in localStorage (armosa_widget_token, armosa_widget_email)
 * - Sends Authorization header with all API requests when authenticated
 * - Public API: setAuthToken(token, email), getAuthState(), isAuthenticated()
 * 
 * Inject via: <script src="chat-widget.js"></script>
 * 
 * Configuration options:
 *   new ArmosaChatWidget({
 *     apiUrl: '/chat',           // Chat endpoint
 *     voiceUrl: '/voice',        // Voice endpoint
 *     loginUrl: '/login',        // Login endpoint
 *     theme: 'light',            // Theme (currently only light)
 *     position: 'bottom-right'   // Widget position
 *   });
 */

class ArmosaChatWidget {
    constructor(config = {}) {
        const API_URL = window.location.origin;
        
        this.config = {
            apiUrl: config.apiUrl || `${API_URL}/chat`,
            voiceUrl: config.voiceUrl || `${API_URL}/voice`,
            containerId: config.containerId || 'armosa-widget-container',
            theme: config.theme || 'light',
            position: config.position || 'bottom-right',
            ...config
        };
        
        this.messages = [];
        this.conversationId = null;
        this.currentMode = 'chat';
        this.isRecording = false;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.selectedFile = null;
        
        // Auth state
        this.authToken = null;
        this.userEmail = null;
        this.loginUrl = config.loginUrl || `${API_URL}/login`;
        
        this.init();
    }
    
    // ==================== AUTHENTICATION ====================
    
    loadAuthState() {
        const savedToken = localStorage.getItem('armosa_widget_token');
        const savedEmail = localStorage.getItem('armosa_widget_email');
        if (savedToken && savedEmail) {
            this.authToken = savedToken;
            this.userEmail = savedEmail;
            return true;
        }
        return false;
    }
    
    saveAuthState(token, email) {
        this.authToken = token;
        this.userEmail = email;
        localStorage.setItem('armosa_widget_token', token);
        localStorage.setItem('armosa_widget_email', email);
    }
    
    clearAuthState() {
        this.authToken = null;
        this.userEmail = null;
        localStorage.removeItem('armosa_widget_token');
        localStorage.removeItem('armosa_widget_email');
    }
    
    updateAuthUI() {
        const loginBtn = this.widget.querySelector('#auth-login-btn');
        const userInfo = this.widget.querySelector('#auth-user-info');
        const userEmail = this.widget.querySelector('#auth-user-email');
        
        if (this.authToken && this.userEmail) {
            // Logged in
            loginBtn.style.display = 'none';
            userInfo.style.display = 'flex';
            userEmail.textContent = this.userEmail.split('@')[0];
        } else {
            // Guest
            loginBtn.style.display = 'flex';
            userInfo.style.display = 'none';
        }
    }
    
    showLoginModal() {
        const modal = this.widget.querySelector('#armosa-login-modal');
        modal.classList.add('visible');
        this.widget.querySelector('#login-email').focus();
    }
    
    hideLoginModal() {
        const modal = this.widget.querySelector('#armosa-login-modal');
        modal.classList.remove('visible');
        this.widget.querySelector('#login-email').value = '';
        this.widget.querySelector('#login-password').value = '';
        this.widget.querySelector('#login-error').textContent = '';
    }
    
    async performLogin() {
        const email = this.widget.querySelector('#login-email').value.trim();
        const password = this.widget.querySelector('#login-password').value;
        const errorEl = this.widget.querySelector('#login-error');
        const submitBtn = this.widget.querySelector('#login-submit');
        
        if (!email || !password) {
            errorEl.textContent = 'Please enter email and password';
            return;
        }
        
        submitBtn.disabled = true;
        submitBtn.textContent = 'Signing in...';
        errorEl.textContent = '';
        
        try {
            const response = await fetch(this.loginUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, password })
            });
            
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || 'Login failed');
            }
            
            const data = await response.json();
            this.saveAuthState(data.access_token, email);
            this.updateAuthUI();
            this.hideLoginModal();
            this.addBotMessage(`Welcome back, ${email.split('@')[0]}! 👋`);
        } catch (err) {
            errorEl.textContent = err.message || 'Login failed';
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Sign In';
        }
    }
    
    async performLogout() {
        try {
            // Call logout endpoint if we have a token
            if (this.authToken) {
                await fetch(`${window.location.origin}/logout`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${this.authToken}` }
                }).catch(() => {}); // Ignore errors
            }
        } finally {
            this.clearAuthState();
            this.updateAuthUI();
            this.addBotMessage('You\'ve been logged out. Continue as guest or sign in again.');
        }
    }
    
    // ==================== PUBLIC AUTH API ====================
    
    /**
     * Set auth token programmatically (for external auth systems)
     * @param {string} token - JWT access token
     * @param {string} email - User email for display
     */
    setAuthToken(token, email) {
        if (token && email) {
            this.saveAuthState(token, email);
            this.updateAuthUI();
        }
    }
    
    /**
     * Get current auth state
     * @returns {{ authenticated: boolean, email: string|null }}
     */
    getAuthState() {
        return {
            authenticated: !!this.authToken,
            email: this.userEmail
        };
    }
    
    /**
     * Check if user is authenticated
     * @returns {boolean}
     */
    isAuthenticated() {
        return !!this.authToken;
    }

    init() {
        this.injectStyles();
        this.createWidget();
        this.attachEventListeners();
        
        // Load saved auth state and update UI
        const wasLoggedIn = this.loadAuthState();
        this.updateAuthUI();
        
        // Personalized greeting
        if (wasLoggedIn && this.userEmail) {
            this.addBotMessage(`Welcome back, ${this.userEmail.split('@')[0]}! 👋 How can I help you today?`);
        } else {
            this.addBotMessage('Hello! I\'m Armosa. How can I help you today?');
        }
    }

    injectStyles() {
        const styleId = 'armosa-widget-styles';
        const existing = document.getElementById(styleId);
        if (existing) existing.remove();
        
        const style = document.createElement('style');
        style.id = styleId;
        style.textContent = `
            /* ============================================================
               ARMOSA CHAT WIDGET v4.0 - "MOBILE APP" EDITION
               ============================================================
               
               BRAND COLORS:
               - Blue:  #2563EB (Primary Accent)
               - Gold:  #FFB800 (Highlight)
               - Green: #00C896 (Action/Success)
               
               SMARTPHONE METAPHOR:
               - Widget = Phone Chassis (rounded, gradient bezel)
               - Background = Mobile Wallpaper (gradient)
               - Components = Floating App Cards (islands)
               ============================================================ */

            /* ==================== HARD RESET ==================== */
            #armosa-fab,
            #armosa-widget,
            #armosa-widget *,
            #armosa-widget *::before,
            #armosa-widget *::after {
                margin: 0 !important;
                padding: 0 !important;
                box-sizing: border-box !important;
                border: none !important;
                outline: none !important;
            }

            /* ==================== FLOATING ACTION BUTTON ==================== */
            #armosa-fab {
                all: unset !important;
                position: fixed !important;
                bottom: 24px !important;
                right: 24px !important;
                width: 60px !important;
                height: 60px !important;
                border-radius: 50% !important;
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%) !important;
                border: 3px solid #FFB800 !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                z-index: 999998 !important;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
                box-shadow: 0 4px 20px rgba(0, 200, 150, 0.4),
                            0 2px 8px rgba(0, 0, 0, 0.15) !important;
            }

            #armosa-fab:hover {
                transform: scale(1.1) rotate(10deg) !important;
                box-shadow: 0 6px 28px rgba(0, 200, 150, 0.5),
                            0 4px 12px rgba(0, 0, 0, 0.2) !important;
            }

            #armosa-fab.hidden {
                transform: scale(0) !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }

            /* ==================== WIDGET - THE "SMARTPHONE" ==================== */
            #armosa-widget {
                all: unset !important;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif !important;
                position: fixed !important;
                bottom: 24px !important;
                right: 24px !important;
                width: 380px !important;
                height: 680px !important;
                border-radius: 32px !important;
                display: flex !important;
                flex-direction: column !important;
                z-index: 999999 !important;
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1) !important;
                transform-origin: bottom right !important;
                
                /* Gradient "Bezel" Border */
                background: linear-gradient(135deg, #2563EB 0%, #FFB800 50%, #00C896 100%) !important;
                padding: 3px !important;
                
                box-shadow: 
                    0 25px 60px -12px rgba(0, 0, 0, 0.35),
                    0 0 0 1px rgba(255, 255, 255, 0.1) inset !important;
                overflow: hidden !important;
            }

            #armosa-widget.hidden {
                transform: translateY(20px) scale(0.95) !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }

            /* ==================== INNER CONTAINER - "PHONE SCREEN" ==================== */
            #armosa-widget .widget-inner {
                flex: 1 !important;
                background: linear-gradient(180deg, 
                    rgba(37, 99, 235, 0.08) 0%, 
                    rgba(255, 184, 0, 0.05) 50%, 
                    rgba(0, 200, 150, 0.08) 100%) !important;
                border-radius: 29px !important;
                display: flex !important;
                flex-direction: column !important;
                gap: 12px !important;
                padding: 12px !important;
                overflow: hidden !important;
            }

            /* ==================== HEADER ISLAND ==================== */
            #armosa-widget .armosa-header {
                background: #FFFFFF !important;
                border-radius: 20px !important;
                border: 2px solid rgba(37, 99, 235, 0.15) !important;
                display: flex !important;
                align-items: center !important;
                justify-content: space-between !important;
                padding: 12px 16px !important;
                flex-shrink: 0 !important;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
            }

            #armosa-widget .header-left {
                display: flex !important;
                align-items: center !important;
                gap: 10px !important;
            }

            #armosa-widget .armosa-logo {
                width: 36px !important;
                height: 36px !important;
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%) !important;
                border-radius: 10px !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                box-shadow: 0 2px 8px rgba(0, 200, 150, 0.3) !important;
            }

            #armosa-widget .armosa-title {
                font-size: 16px !important;
                font-weight: 700 !important;
                background: linear-gradient(90deg, #2563EB, #00C896) !important;
                -webkit-background-clip: text !important;
                -webkit-text-fill-color: transparent !important;
                background-clip: text !important;
            }

            #armosa-widget .header-right {
                display: flex !important;
                align-items: center !important;
                gap: 6px !important;
            }

            #armosa-widget .mode-btn {
                all: unset !important;
                width: 36px !important;
                height: 36px !important;
                border-radius: 10px !important;
                background: #F4F4F5 !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                color: #71717A !important;
                transition: all 0.2s ease !important;
            }

            #armosa-widget .mode-btn:hover {
                background: #E4E4E7 !important;
                color: #2563EB !important;
            }

            #armosa-widget .mode-btn.active {
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%) !important;
                color: #FFFFFF !important;
                box-shadow: 0 2px 8px rgba(0, 200, 150, 0.3) !important;
            }

            #armosa-widget .close-btn {
                all: unset !important;
                width: 36px !important;
                height: 36px !important;
                border-radius: 10px !important;
                background: transparent !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                color: #71717A !important;
                transition: all 0.2s ease !important;
            }

            #armosa-widget .close-btn:hover {
                background: #FEE2E2 !important;
                color: #EF4444 !important;
            }

            /* ==================== AUTH UI ELEMENTS ==================== */
            #armosa-widget .auth-login-btn {
                all: unset !important;
                padding: 6px 12px !important;
                border-radius: 8px !important;
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%) !important;
                color: white !important;
                font-size: 12px !important;
                font-weight: 600 !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                gap: 4px !important;
                transition: all 0.2s ease !important;
            }

            #armosa-widget .auth-login-btn:hover {
                transform: scale(1.05) !important;
                box-shadow: 0 2px 8px rgba(0, 200, 150, 0.3) !important;
            }

            #armosa-widget .auth-user-info {
                display: flex !important;
                align-items: center !important;
                gap: 6px !important;
                padding: 4px 10px !important;
                background: rgba(0, 200, 150, 0.1) !important;
                border-radius: 8px !important;
                border: 1px solid rgba(0, 200, 150, 0.2) !important;
            }

            #armosa-widget .auth-user-email {
                font-size: 12px !important;
                font-weight: 600 !important;
                color: #2563EB !important;
                max-width: 80px !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
                white-space: nowrap !important;
            }

            #armosa-widget .auth-logout-btn {
                all: unset !important;
                width: 20px !important;
                height: 20px !important;
                border-radius: 4px !important;
                background: transparent !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                color: #71717A !important;
                transition: all 0.2s ease !important;
            }

            #armosa-widget .auth-logout-btn:hover {
                background: #FEE2E2 !important;
                color: #EF4444 !important;
            }

            /* ==================== LOGIN MODAL ==================== */
            #armosa-login-modal {
                position: absolute !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                background: rgba(0, 0, 0, 0.5) !important;
                backdrop-filter: blur(4px) !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                z-index: 100 !important;
                opacity: 0 !important;
                pointer-events: none !important;
                transition: opacity 0.3s ease !important;
                border-radius: 28px !important;
            }

            #armosa-login-modal.visible {
                opacity: 1 !important;
                pointer-events: auto !important;
            }

            #armosa-login-modal .login-card {
                background: white !important;
                border-radius: 20px !important;
                padding: 28px !important;
                width: 85% !important;
                max-width: 300px !important;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2) !important;
                border: 2px solid rgba(0, 200, 150, 0.15) !important;
            }

            #armosa-login-modal .login-title {
                font-size: 20px !important;
                font-weight: 700 !important;
                text-align: center !important;
                margin-bottom: 20px !important;
                background: linear-gradient(90deg, #2563EB, #00C896) !important;
                -webkit-background-clip: text !important;
                -webkit-text-fill-color: transparent !important;
                background-clip: text !important;
            }

            #armosa-login-modal .login-input {
                all: unset !important;
                width: 100% !important;
                padding: 12px 14px !important;
                border: 2px solid #E4E4E7 !important;
                border-radius: 12px !important;
                font-size: 14px !important;
                background: #FAFAFA !important;
                margin-bottom: 12px !important;
                box-sizing: border-box !important;
                transition: border-color 0.2s ease !important;
            }

            #armosa-login-modal .login-input:focus {
                border-color: #2563EB !important;
                background: white !important;
            }

            #armosa-login-modal .login-input::placeholder {
                color: #A1A1AA !important;
            }

            #armosa-login-modal .login-error {
                color: #EF4444 !important;
                font-size: 12px !important;
                text-align: center !important;
                margin-bottom: 12px !important;
                min-height: 16px !important;
            }

            #armosa-login-modal .login-submit {
                all: unset !important;
                width: 100% !important;
                padding: 12px !important;
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%) !important;
                color: white !important;
                font-size: 14px !important;
                font-weight: 600 !important;
                text-align: center !important;
                border-radius: 12px !important;
                cursor: pointer !important;
                box-sizing: border-box !important;
                transition: all 0.2s ease !important;
            }

            #armosa-login-modal .login-submit:hover:not(:disabled) {
                transform: translateY(-2px) !important;
                box-shadow: 0 4px 16px rgba(0, 200, 150, 0.4) !important;
            }

            #armosa-login-modal .login-submit:disabled {
                opacity: 0.7 !important;
                cursor: not-allowed !important;
            }

            #armosa-login-modal .login-cancel {
                all: unset !important;
                width: 100% !important;
                padding: 10px !important;
                text-align: center !important;
                font-size: 13px !important;
                color: #71717A !important;
                cursor: pointer !important;
                margin-top: 8px !important;
                box-sizing: border-box !important;
            }

            #armosa-login-modal .login-cancel:hover {
                color: #2563EB !important;
                text-decoration: underline !important;
            }

            /* ==================== CHAT ISLAND (MESSAGES PLANE) ==================== */
            #armosa-widget .armosa-messages {
                flex: 1 !important;
                background: #FFFFFF !important;
                border-radius: 20px !important;
                border: 2px solid rgba(0, 200, 150, 0.12) !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
                padding: 16px !important;
                display: flex !important;
                flex-direction: column !important;
                gap: 12px !important;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06) !important;
            }

            #armosa-widget .armosa-messages::-webkit-scrollbar {
                width: 6px !important;
            }

            #armosa-widget .armosa-messages::-webkit-scrollbar-track {
                background: transparent !important;
            }

            #armosa-widget .armosa-messages::-webkit-scrollbar-thumb {
                background: linear-gradient(180deg, #2563EB, #00C896) !important;
                border-radius: 3px !important;
            }

            /* ==================== MESSAGE BUBBLES ==================== */
            #armosa-widget .message-group {
                display: flex !important;
                gap: 10px !important;
                animation: slideUp 0.3s ease !important;
            }

            @keyframes slideUp {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }

            #armosa-widget .message-group.user {
                flex-direction: row-reverse !important;
            }

            #armosa-widget .message-avatar {
                width: 36px !important;
                height: 36px !important;
                min-width: 36px !important;
                border-radius: 12px !important;
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%) !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                flex-shrink: 0 !important;
                box-shadow: 0 2px 6px rgba(0, 0, 0, 0.1) !important;
            }

            #armosa-widget .message-group.user .message-avatar {
                background: #00C896 !important;
            }

            #armosa-widget .message-bubble {
                max-width: 75% !important;
                display: flex !important;
                flex-direction: column !important;
                gap: 4px !important;
            }

            #armosa-widget .bot-message-content {
                background: #F4F4F5 !important;
                border: 1px solid #E4E4E7 !important;
                border-radius: 18px 18px 18px 4px !important;
                padding: 12px 16px !important;
                font-size: 14px !important;
                line-height: 1.6 !important;
                color: #18181B !important;
            }

            #armosa-widget .bot-message-content strong {
                color: #00C896 !important;
                font-weight: 600 !important;
            }

            #armosa-widget .bot-message-content em {
                color: #2563EB !important;
            }

            #armosa-widget .user-message-content {
                background: linear-gradient(135deg, #00C896 0%, #2563EB 100%) !important;
                border-radius: 18px 18px 4px 18px !important;
                padding: 12px 16px !important;
                color: #FFFFFF !important;
                font-size: 14px !important;
                line-height: 1.6 !important;
            }

            #armosa-widget .message-time {
                font-size: 10px !important;
                color: #A1A1AA !important;
                padding: 0 4px !important;
            }

            #armosa-widget .message-group.user .message-time {
                text-align: right !important;
            }

            /* ==================== CODE BLOCKS ==================== */
            #armosa-widget .code-block {
                background: #1E1E1E !important;
                border-radius: 12px !important;
                padding: 12px !important;
                margin-top: 8px !important;
                overflow-x: auto !important;
                border: 1px solid #333 !important;
            }

            #armosa-widget .code-header {
                display: flex !important;
                justify-content: space-between !important;
                align-items: center !important;
                margin-bottom: 8px !important;
                padding-bottom: 8px !important;
                border-bottom: 1px solid #333 !important;
            }

            #armosa-widget .code-language {
                font-size: 11px !important;
                font-weight: 600 !important;
                color: #FFB800 !important;
                text-transform: uppercase !important;
            }

            #armosa-widget .code-copy-btn {
                background: rgba(0, 200, 150, 0.2) !important;
                border: none !important;
                color: #00C896 !important;
                padding: 4px 10px !important;
                border-radius: 6px !important;
                cursor: pointer !important;
                font-size: 11px !important;
                transition: all 0.2s ease !important;
            }

            #armosa-widget .code-copy-btn:hover {
                background: rgba(0, 200, 150, 0.35) !important;
            }

            #armosa-widget .code-content {
                font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace !important;
                font-size: 12px !important;
                color: #E5E7EB !important;
                white-space: pre-wrap !important;
                line-height: 1.5 !important;
            }

            /* ==================== LISTS & RECOMMENDATIONS ==================== */
            #armosa-widget .recommendation-block {
                background: rgba(255, 184, 0, 0.08) !important;
                border-left: 3px solid #FFB800 !important;
                border-radius: 0 12px 12px 0 !important;
                padding: 12px 14px !important;
                margin-top: 8px !important;
            }

            #armosa-widget .recommendation-label {
                font-weight: 600 !important;
                color: #FFB800 !important;
                font-size: 12px !important;
                margin-bottom: 6px !important;
            }

            #armosa-widget .list-block {
                background: rgba(0, 200, 150, 0.05) !important;
                border-left: 3px solid #00C896 !important;
                border-radius: 0 12px 12px 0 !important;
                padding: 12px 14px !important;
                margin-top: 8px !important;
            }

            #armosa-widget .list-block ul {
                list-style: none !important;
                padding-left: 0 !important;
                margin: 0 !important;
            }

            #armosa-widget .list-block li {
                padding: 4px 0 4px 16px !important;
                position: relative !important;
                font-size: 13px !important;
                color: #374151 !important;
            }

            #armosa-widget .list-block li:before {
                content: "→" !important;
                position: absolute !important;
                left: 0 !important;
                color: #00C896 !important;
            }

            /* ==================== TYPING INDICATOR ==================== */
            #armosa-widget .typing-indicator {
                display: flex !important;
                gap: 5px !important;
                padding: 12px 16px !important;
                background: #F4F4F5 !important;
                border-radius: 18px 18px 18px 4px !important;
                width: fit-content !important;
            }

            #armosa-widget .typing-dot {
                width: 8px !important;
                height: 8px !important;
                border-radius: 50% !important;
                background: linear-gradient(135deg, #2563EB, #00C896) !important;
                animation: typingBounce 1.4s infinite !important;
            }

            #armosa-widget .typing-dot:nth-child(2) { animation-delay: 0.2s !important; }
            #armosa-widget .typing-dot:nth-child(3) { animation-delay: 0.4s !important; }

            @keyframes typingBounce {
                0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
                30% { transform: translateY(-8px); opacity: 1; }
            }

            /* ==================== INPUT ISLAND ==================== */
            #armosa-widget .armosa-input-container {
                background: #FFFFFF !important;
                border-radius: 20px !important;
                border: 2px solid rgba(255, 184, 0, 0.15) !important;
                display: flex !important;
                align-items: center !important;
                padding: 8px 12px !important;
                gap: 8px !important;
                flex-shrink: 0 !important;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
            }

            #armosa-widget .action-btn {
                all: unset !important;
                width: 40px !important;
                height: 40px !important;
                border-radius: 12px !important;
                background: #F4F4F5 !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                color: #71717A !important;
                transition: all 0.2s ease !important;
                flex-shrink: 0 !important;
            }

            #armosa-widget .action-btn:hover {
                background: #E4E4E7 !important;
                color: #2563EB !important;
            }

            #armosa-widget .action-btn.recording {
                background: #EF4444 !important;
                color: #FFFFFF !important;
                animation: recordPulse 1s infinite !important;
            }

            @keyframes recordPulse {
                0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
                50% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
            }

            #armosa-widget #armosa-input {
                all: unset !important;
                flex: 1 !important;
                min-height: 40px !important;
                padding: 0 12px !important;
                font-size: 14px !important;
                color: #18181B !important;
                background: transparent !important;
            }

            #armosa-widget #armosa-input::placeholder {
                color: #A1A1AA !important;
            }

            #armosa-widget .send-btn {
                all: unset !important;
                width: 44px !important;
                height: 44px !important;
                border-radius: 14px !important;
                background: linear-gradient(135deg, #00C896 0%, #2563EB 100%) !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                color: #FFFFFF !important;
                transition: all 0.2s ease !important;
                flex-shrink: 0 !important;
                box-shadow: 0 4px 12px rgba(0, 200, 150, 0.35) !important;
            }

            #armosa-widget .send-btn:hover:not(:disabled) {
                transform: scale(1.05) !important;
                box-shadow: 0 6px 16px rgba(0, 200, 150, 0.45) !important;
            }

            #armosa-widget .send-btn:disabled {
                opacity: 0.5 !important;
                cursor: not-allowed !important;
            }

            /* ==================== FILE PREVIEW ==================== */
            #armosa-widget .file-preview {
                display: none !important;
                background: rgba(37, 99, 235, 0.08) !important;
                border: 1px solid rgba(37, 99, 235, 0.2) !important;
                border-radius: 10px !important;
                padding: 8px 12px !important;
                margin-bottom: 8px !important;
                font-size: 12px !important;
                color: #2563EB !important;
                align-items: center !important;
                gap: 8px !important;
            }

            #armosa-widget .file-preview.active {
                display: flex !important;
            }

            #armosa-widget .remove-file-btn {
                all: unset !important;
                color: #EF4444 !important;
                cursor: pointer !important;
                font-size: 16px !important;
                margin-left: auto !important;
            }

            /* ==================== RESPONSIVE ==================== */
            @media (max-width: 420px) {
                #armosa-widget {
                    width: 100% !important;
                    height: 100% !important;
                    border-radius: 0 !important;
                    bottom: 0 !important;
                    right: 0 !important;
                    padding: 0 !important;
                }

                #armosa-widget .widget-inner {
                    border-radius: 0 !important;
                    gap: 8px !important;
                    padding: 8px !important;
                }

                #armosa-widget .armosa-header,
                #armosa-widget .armosa-messages,
                #armosa-widget .armosa-input-container {
                    border-radius: 16px !important;
                }
            }
        `;
        
        document.head.appendChild(style);
    }

    createWidget() {
        // Load Iconify
        if (!document.querySelector('script[src*="iconify"]')) {
            const script = document.createElement('script');
            script.src = 'https://code.iconify.design/iconify-icon/1.0.7/iconify-icon.min.js';
            document.head.appendChild(script);
        }

        // FAB
        const fab = document.createElement('button');
        fab.id = 'armosa-fab';
        fab.innerHTML = `<iconify-icon icon="mdi:chat" style="font-size: 26px; color: white;"></iconify-icon>`;
        fab.title = 'Chat with Armosa';
        document.body.appendChild(fab);
        this.fab = fab;

        // Widget
        const widget = document.createElement('div');
        widget.id = 'armosa-widget';
        widget.classList.add('hidden');
        widget.innerHTML = `
            <div class="widget-inner">
                <!-- HEADER ISLAND -->
                <div class="armosa-header">
                    <div class="header-left">
                        <div class="armosa-logo">
                            <iconify-icon icon="mdi:robot-happy-outline" style="font-size: 22px; color: white;"></iconify-icon>
                        </div>
                        <span class="armosa-title">Armosa</span>
                    </div>
                    <div class="header-right">
                        <!-- Auth UI -->
                        <button class="auth-login-btn" id="auth-login-btn" title="Sign In">
                            <iconify-icon icon="mdi:login" style="font-size: 14px;"></iconify-icon>
                            <span>Sign In</span>
                        </button>
                        <div class="auth-user-info" id="auth-user-info" style="display: none;">
                            <iconify-icon icon="mdi:account-circle" style="font-size: 16px; color: #00C896;"></iconify-icon>
                            <span class="auth-user-email" id="auth-user-email"></span>
                            <button class="auth-logout-btn" id="auth-logout-btn" title="Sign Out">
                                <iconify-icon icon="mdi:logout" style="font-size: 14px;"></iconify-icon>
                            </button>
                        </div>
                        
                        <button class="mode-btn active" data-mode="chat" title="Chat">
                            <iconify-icon icon="mdi:chat-outline" style="font-size: 18px;"></iconify-icon>
                        </button>
                        <button class="mode-btn" data-mode="voice" title="Voice">
                            <iconify-icon icon="mdi:microphone-outline" style="font-size: 18px;"></iconify-icon>
                        </button>
                        <button class="close-btn" id="close-widget" title="Close">
                            <iconify-icon icon="mdi:close" style="font-size: 18px;"></iconify-icon>
                        </button>
                    </div>
                </div>

                <!-- CHAT ISLAND -->
                <div class="armosa-messages" id="armosa-messages"></div>

                <!-- INPUT ISLAND -->
                <div class="armosa-input-container">
                    <input type="file" id="file-input" accept="audio/*,video/*,image/*,.pdf,.docx,.doc,.txt" style="display: none;">
                    <button class="action-btn" id="file-btn" title="Attach file">
                        <iconify-icon icon="mdi:paperclip" style="font-size: 20px;"></iconify-icon>
                    </button>
                    <button class="action-btn" id="voice-btn" title="Record voice">
                        <iconify-icon icon="mdi:microphone" style="font-size: 20px;"></iconify-icon>
                    </button>
                    <input type="text" id="armosa-input" placeholder="Message Armosa...">
                    <button class="send-btn" id="send-btn" title="Send">
                        <iconify-icon icon="mdi:send" style="font-size: 20px;"></iconify-icon>
                    </button>
                </div>

                <!-- LOGIN MODAL -->
                <div id="armosa-login-modal">
                    <div class="login-card">
                        <div class="login-title">Sign In to Armosa</div>
                        <input type="email" class="login-input" id="login-email" placeholder="Email address">
                        <input type="password" class="login-input" id="login-password" placeholder="Password">
                        <div class="login-error" id="login-error"></div>
                        <button class="login-submit" id="login-submit">Sign In</button>
                        <button class="login-cancel" id="login-cancel">Continue as Guest</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(widget);
        this.widget = widget;
        this.messagesContainer = widget.querySelector('#armosa-messages');
        this.isOpen = false;
    }

    toggleWidget() {
        this.isOpen = !this.isOpen;
        this.widget.classList.toggle('hidden', !this.isOpen);
        this.fab.classList.toggle('hidden', this.isOpen);
    }

    attachEventListeners() {
        this.fab.addEventListener('click', () => this.toggleWidget());
        this.widget.querySelector('#close-widget').addEventListener('click', () => this.toggleWidget());

        this.widget.querySelectorAll('.mode-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchMode(e.target.closest('.mode-btn').dataset.mode));
        });

        const input = this.widget.querySelector('#armosa-input');
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        this.widget.querySelector('#send-btn').addEventListener('click', () => this.sendMessage());

        const fileBtn = this.widget.querySelector('#file-btn');
        const fileInput = this.widget.querySelector('#file-input');
        fileBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => this.handleFileSelect(e));

        this.widget.querySelector('#voice-btn').addEventListener('click', () => this.toggleRecording());
        
        // Auth event listeners
        this.widget.querySelector('#auth-login-btn').addEventListener('click', () => this.showLoginModal());
        this.widget.querySelector('#auth-logout-btn').addEventListener('click', () => this.performLogout());
        this.widget.querySelector('#login-submit').addEventListener('click', () => this.performLogin());
        this.widget.querySelector('#login-cancel').addEventListener('click', () => this.hideLoginModal());
        
        // Login form keyboard support
        this.widget.querySelector('#login-password').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                this.performLogin();
            }
        });
    }

    switchMode(mode) {
        this.currentMode = mode;
        this.widget.querySelectorAll('.mode-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
    }

    handleFileSelect(e) {
        const file = e.target.files[0];
        if (file) {
            this.selectedFile = file;
            this.showFilePreview(file.name);
        }
    }

    showFilePreview(filename) {
        let preview = this.widget.querySelector('.file-preview');
        if (!preview) {
            preview = document.createElement('div');
            preview.className = 'file-preview';
            this.widget.querySelector('.armosa-input-container').insertBefore(preview, this.widget.querySelector('#file-btn'));
        }
        preview.innerHTML = `
            <iconify-icon icon="mdi:file-document" style="font-size: 16px;"></iconify-icon>
            <span>${filename}</span>
            <button class="remove-file-btn">✕</button>
        `;
        preview.classList.add('active');
        preview.querySelector('.remove-file-btn').addEventListener('click', () => this.removeFile());
    }

    removeFile() {
        this.selectedFile = null;
        const preview = this.widget.querySelector('.file-preview');
        if (preview) preview.classList.remove('active');
    }

    toggleRecording() {
        if (this.isRecording) {
            this.stopRecording();
        } else {
            this.startRecording();
        }
    }

    startRecording() {
        navigator.mediaDevices.getUserMedia({ audio: true })
            .then(stream => {
                this.mediaRecorder = new MediaRecorder(stream);
                this.audioChunks = [];

                this.mediaRecorder.ondataavailable = (e) => this.audioChunks.push(e.data);

                this.mediaRecorder.onstart = () => {
                    this.isRecording = true;
                    this.widget.querySelector('#voice-btn').classList.add('recording');
                };

                this.mediaRecorder.onstop = () => {
                    this.isRecording = false;
                    this.widget.querySelector('#voice-btn').classList.remove('recording');
                    const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
                    this.sendAudioMessage(audioBlob);
                };

                this.mediaRecorder.start();
            })
            .catch(err => console.error('Microphone access denied:', err));
    }

    stopRecording() {
        if (this.mediaRecorder) {
            this.mediaRecorder.stop();
            this.mediaRecorder.stream.getTracks().forEach(track => track.stop());
        }
    }

    sendAudioMessage(audioBlob) {
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        
        this.showTypingIndicator();
        
        fetch(this.config.voiceUrl, {
            method: 'POST',
            headers: this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {},
            body: formData
        })
        .then(async response => {
            if (!response.ok) throw new Error(`Voice request failed (${response.status})`);
            
            const contentType = response.headers.get('Content-Type');
            
            if (contentType && contentType.includes('application/json')) {
                const data = await response.json();
                if (data.transcription) this.addUserMessage(`🎤 "${data.transcription}"`);
                if (data.response) {
                    this.addBotMessage(data.response);
                    if (data.use_browser_tts && 'speechSynthesis' in window) {
                        this.speakText(data.response);
                    }
                }
            } else {
                const audioResponse = await response.blob();
                const transcription = response.headers.get('X-Transcription');
                const responseText = response.headers.get('X-Response-Text');
                
                if (transcription) this.addUserMessage(`🎤 "${transcription}"`);
                if (responseText) this.addBotMessage(decodeURIComponent(responseText));
                
                const audioUrl = URL.createObjectURL(audioResponse);
                const audio = new Audio(audioUrl);
                audio.play();
                audio.onended = () => URL.revokeObjectURL(audioUrl);
            }
        })
        .catch(err => {
            this.addBotMessage('Sorry, there was an error processing your voice message.');
            console.error('Voice error:', err);
        })
        .finally(() => this.removeTypingIndicator());
    }

    speakText(text) {
        if ('speechSynthesis' in window) {
            speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'en-US';
            utterance.rate = 1.0;
            speechSynthesis.speak(utterance);
        }
    }

    sendMessage() {
        const input = this.widget.querySelector('#armosa-input');
        const message = input.value.trim();

        if (!message && !this.selectedFile) return;

        const displayMessage = this.selectedFile ? `${message}\n📎 ${this.selectedFile.name}` : message;
        this.addUserMessage(displayMessage || 'Please analyze this file');
        
        input.value = '';
        this.showTypingIndicator();

        const formData = new FormData();
        formData.append('message', message || 'Please analyze this file');
        if (this.conversationId) formData.append('conversation_id', this.conversationId);
        if (this.selectedFile) formData.append('file', this.selectedFile);

        fetch(this.config.apiUrl, {
            method: 'POST',
            headers: this.authToken ? { 'Authorization': `Bearer ${this.authToken}` } : {},
            body: formData
        })
        .then(response => {
            if (!response.ok) throw new Error(`Request failed (${response.status})`);
            return response.json();
        })
        .then(data => {
            this.removeTypingIndicator();
            if (data.conversation_id) this.conversationId = data.conversation_id;
            this.addBotMessage(data.response);
        })
        .catch(err => {
            this.removeTypingIndicator();
            this.addBotMessage('Sorry, I encountered an error. Please try again.');
            console.error('Chat error:', err);
        })
        .finally(() => this.removeFile());
    }

    addUserMessage(message) {
        this.messages.push({ role: 'user', content: message });
        this.messagesContainer.appendChild(this.createMessageElement(message, 'user'));
        this.scrollToBottom();
    }

    addBotMessage(message) {
        this.messages.push({ role: 'bot', content: message });
        this.messagesContainer.appendChild(this.createMessageElement(message, 'bot'));
        this.scrollToBottom();
    }

    createMessageElement(content, role) {
        const group = document.createElement('div');
        group.className = `message-group ${role}`;

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.innerHTML = role === 'bot'
            ? '<iconify-icon icon="mdi:robot" style="font-size: 18px; color: white;"></iconify-icon>'
            : '<iconify-icon icon="mdi:account" style="font-size: 18px; color: white;"></iconify-icon>';
        group.appendChild(avatar);

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.innerHTML = this.parseMessage(content, role);

        const time = document.createElement('div');
        time.className = 'message-time';
        time.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        bubble.appendChild(time);

        group.appendChild(bubble);
        return group;
    }

    parseMessage(content, role) {
        let html = '';
        const blocks = content.split('\n\n');

        for (const block of blocks) {
            if (block.includes('```')) {
                html += this.parseCodeBlock(block);
            } else if (block.match(/^(Recommendation|💡|⭐|Tip):/i)) {
                html += this.parseRecommendation(block);
            } else if (block.split('\n').some(line => line.match(/^[-•*]\s/))) {
                html += this.parseList(block);
            } else {
                html += `<div class="${role}-message-content">${this.parseInlineMarkdown(block)}</div>`;
            }
        }
        return html;
    }

    parseCodeBlock(block) {
        const match = block.match(/```(\w+)?\n([\s\S]*?)```/);
        if (!match) return '';
        const language = match[1] || 'text';
        const code = match[2].trim();
        return `
            <div class="code-block">
                <div class="code-header">
                    <span class="code-language">${language}</span>
                    <button class="code-copy-btn" onclick="navigator.clipboard.writeText(\`${code.replace(/`/g, '\\`')}\`)">Copy</button>
                </div>
                <div class="code-content">${this.escapeHtml(code)}</div>
            </div>
        `;
    }

    parseRecommendation(block) {
        const lines = block.split('\n');
        return `
            <div class="recommendation-block">
                <div class="recommendation-label">💡 ${this.escapeHtml(lines[0])}</div>
                <div>${this.parseInlineMarkdown(lines.slice(1).join('\n'))}</div>
            </div>
        `;
    }

    parseList(block) {
        const items = block.split('\n').filter(l => l.trim());
        let html = '<div class="list-block"><ul>';
        items.forEach(item => {
            const text = item.replace(/^[-•*]\s/, '').trim();
            html += `<li>${this.parseInlineMarkdown(text)}</li>`;
        });
        html += '</ul></div>';
        return html;
    }

    parseInlineMarkdown(text) {
        text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
        text = text.replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank" style="color: #2563EB; text-decoration: underline;">$1</a>');
        text = text.replace(/`(.*?)`/g, '<code style="background: rgba(0,200,150,0.1); color: #00C896; padding: 2px 6px; border-radius: 4px; font-family: monospace;">$1</code>');
        return text;
    }

    showTypingIndicator() {
        const indicator = document.createElement('div');
        indicator.className = 'message-group';
        indicator.id = 'typing-indicator';
        indicator.innerHTML = `
            <div class="message-avatar">
                <iconify-icon icon="mdi:robot" style="font-size: 18px; color: white;"></iconify-icon>
            </div>
            <div class="message-bubble">
                <div class="typing-indicator">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        `;
        this.messagesContainer.appendChild(indicator);
        this.scrollToBottom();
    }

    removeTypingIndicator() {
        const indicator = this.messagesContainer.querySelector('#typing-indicator');
        if (indicator) indicator.remove();
    }

    scrollToBottom() {
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Auto-initialize
document.addEventListener('DOMContentLoaded', () => {
    window.armosaChatWidget = new ArmosaChatWidget();
});

// ES Module export
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ArmosaChatWidget;
}
