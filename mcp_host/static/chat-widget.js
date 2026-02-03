/**
 * Armosa Chat Widget
 * Self-contained embeddable chat widget with smart message parsing
 * Inject via: <script src="chat-widget.js"></script>
 */

class ArmosChatWidget {
    constructor(config = {}) {
        // Get base URL from current location (works for all deployments)
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
        this.conversationId = null;  // Track conversation for context
        this.currentMode = 'chat'; // 'chat', 'voice', or 'avatar'
        this.isRecording = false;
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.selectedFile = null;
        
        this.init();
    }

    init() {
        // Inject CSS
        this.injectStyles();
        
        // Create widget container
        this.createWidget();
        
        // Attach event listeners
        this.attachEventListeners();
        
        // Load initial greeting
        this.addBotMessage('Hello! I\'m Armosa. How can I help you today?');
    }

    injectStyles() {
        const styleId = 'armosa-widget-styles';
        // Remove existing styles to prevent caching issues
        const existing = document.getElementById(styleId);
        if (existing) existing.remove();
        
        const style = document.createElement('style');
        style.id = styleId;
        style.textContent = `
            /* ============================================================
               ARMOSA CHAT WIDGET - PREMIUM AI-NATIVE DESIGN SYSTEM v2.0
               Geometric Proportions (Golden Ratio & Similarity Principles)
               ============================================================
               
               DESIGN MATHEMATICS:
               - Frame: 360×720px (1:2 ratio, φ-inspired)
               - Border Radius Scale: 28px → 25px → 16px → 10px → 8px (÷1.2)
               - Spacing Scale: 24px → 16px → 12px → 8px → 4px
               - Icon Scale: 56px → 36px → 32px → 28px → 24px
               
               SIMILARITY RULES (SSS/SAS/AAA):
               - All circles: Same gradient (135deg, blue→green)
               - All containers: Same shadow formula
               - All buttons: Proportional sizing (1:1 ratio for icons)
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
            /* Circle: 56×56px, gradient fill, shadow depth 1 */
            #armosa-fab {
                all: unset !important;
                position: fixed !important;
                bottom: 24px !important;
                right: 24px !important;
                width: 56px !important;
                height: 56px !important;
                border-radius: 50% !important;
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%) !important;
                border: none !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                z-index: 999998 !important;
                transition: transform 0.3s ease, box-shadow 0.3s ease !important;
                box-shadow: 0 4px 16px rgba(0, 200, 150, 0.35),
                            0 2px 4px rgba(0, 0, 0, 0.1) !important;
            }

            #armosa-fab:hover {
                transform: scale(1.08) !important;
                box-shadow: 0 6px 24px rgba(0, 200, 150, 0.45),
                            0 4px 8px rgba(0, 0, 0, 0.12) !important;
            }

            #armosa-fab.hidden {
                transform: scale(0) !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }

            #armosa-fab svg {
                width: 24px !important;
                height: 24px !important;
                fill: white !important;
            }

            /* ==================== WIDGET OUTER FRAME ==================== */
            /* Rectangle: 360×720px, 28px radius, 3px gradient border */
            #armosa-widget {
                all: unset !important;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif !important;
                position: fixed !important;
                bottom: 24px !important;
                right: 24px !important;
                width: 360px !important;
                height: 720px !important;
                border-radius: 16px !important;
                padding: 0 !important;
                display: flex !important;
                flex-direction: column !important;
                z-index: 999999 !important;
                transition: transform 0.3s ease, opacity 0.3s ease !important;
                transform-origin: bottom right !important;
                background: #FFFFFF !important;
                border: 1px solid rgba(0, 0, 0, 0.1) !important;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25) !important;
                overflow: hidden !important;
            }

            #armosa-widget.hidden {
                transform: scale(0) !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }

            /* ==================== INNER CONTAINER ==================== */
            /* Full height flex container */
            #armosa-widget .widget-inner {
                flex: 1 !important;
                background: #FFFFFF !important;
                border-radius: 0 !important;
                display: flex !important;
                flex-direction: column !important;
                gap: 0 !important;
                padding: 0 !important;
                overflow: hidden !important;
                border: none !important;
            }

            /* ==================== HEADER ==================== */
            /* Match full-page: clean white, border-bottom */
            #armosa-widget .armosa-header {
                width: 100% !important;
                background: #FFFFFF !important;
                border-radius: 0 !important;
                border: none !important;
                border-bottom: 1px solid #e8e8e8 !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: center !important;
                padding: 12px 16px !important;
                gap: 12px !important;
                position: relative !important;
                flex-shrink: 0 !important;
            }

            /* Row 1: Logo + Title */
            #armosa-widget .header-top {
                display: flex !important;
                align-items: center !important;
                gap: 12px !important;
                padding: 0 !important;
                margin: 0 !important;
            }

            /* Close Button: Match full-page header icon btn */
            #armosa-widget .close-btn {
                all: unset !important;
                position: absolute !important;
                top: 10px !important;
                right: 10px !important;
                width: 36px !important;
                height: 36px !important;
                border-radius: 8px !important;
                background: transparent !important;
                border: none !important;
                color: #71717a !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                transition: all 0.15s ease !important;
            }

            #armosa-widget .close-btn:hover {
                background: #f4f4f5 !important;
                color: #18181b !important;
            }

            /* ==================== LOGO ==================== */
            /* Match full-page: 32x32, rounded square, primary bg */
            #armosa-widget .armosa-logo {
                width: 32px !important;
                height: 32px !important;
                min-width: 32px !important;
                min-height: 32px !important;
                background: #00C896 !important;
                border-radius: 8px !important;
                border: none !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                flex-shrink: 0 !important;
            }

            /* Title Text - match full-page */
            #armosa-widget .armosa-title {
                font-size: 15px !important;
                font-weight: 600 !important;
                color: #202123 !important;
                letter-spacing: -0.01em !important;
            }

            /* ==================== MODE BUTTONS ==================== */
            /* Match full-page mode toggle exactly */
            #armosa-widget .mode-buttons {
                display: inline-flex !important;
                gap: 4px !important;
                background: #f4f4f5 !important;
                border-radius: 10px !important;
                padding: 4px !important;
                border: none !important;
            }

            /* Mode Button: match full-page */
            #armosa-widget .mode-btn {
                all: unset !important;
                width: 36px !important;
                height: 32px !important;
                border-radius: 8px !important;
                background: transparent !important;
                border: none !important;
                color: #71717a !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                transition: all 0.15s ease !important;
            }

            #armosa-widget .mode-btn:hover {
                color: #3f3f46 !important;
            }

            #armosa-widget .mode-btn.active {
                background: #FFFFFF !important;
                color: #00C896 !important;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
            }

            #armosa-widget .mode-btn iconify-icon {
                font-size: 16px !important;
                transition: all 0.2s !important;
            }

            #armosa-widget .mode-btn:hover iconify-icon {
                transform: scale(1.1) !important;
            }

            /* ==================== CHAT MESSAGES AREA ==================== */
            /* Match full-page: clean white, no border */
            #armosa-widget .armosa-messages {
                width: 100% !important;
                flex: 1 !important;
                background: #FFFFFF !important;
                border-radius: 0 !important;
                border: none !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
                padding: 24px !important;
                display: flex !important;
                flex-direction: column !important;
                gap: 16px !important;
            }

            #armosa-widget .armosa-messages::-webkit-scrollbar {
                width: 4px !important;
            }

            #armosa-widget .armosa-messages::-webkit-scrollbar-track {
                background: transparent !important;
            }

            #armosa-widget .armosa-messages::-webkit-scrollbar-thumb {
                background: rgba(0, 0, 0, 0.15) !important;
                border-radius: 2px !important;
            }

            /* ==================== MESSAGE BUBBLES ==================== */
            /* Smart bubbling with asymmetric radius for direction indication */
            
            #armosa-widget .message-group {
                display: flex !important;
                gap: 10px !important;
                animation: slideIn 0.3s ease !important;
                margin: 0 !important;
                padding: 0 !important;
                border: none !important;
            }

            @keyframes slideIn {
                from { opacity: 0; transform: translateY(8px); }
                to { opacity: 1; transform: translateY(0); }
            }

            #armosa-widget .message-group.user {
                flex-direction: row-reverse !important;
            }

            /* Message Avatar: Match full-page - 40x40px circle */
            #armosa-widget .message-avatar {
                width: 40px !important;
                height: 40px !important;
                min-width: 40px !important;
                min-height: 40px !important;
                border-radius: 50% !important;
                background: linear-gradient(135deg, #00C896 0%, #2563EB 100%) !important;
                border: none !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                flex-shrink: 0 !important;
            }

            #armosa-widget .message-group.user .message-avatar {
                background: #00C896 !important;
            }

            /* Message Bubble Container */
            #armosa-widget .message-bubble {
                max-width: 70% !important;
                border: none !important;
            }

            /* Bot Message: Match full-page - light gray bg */
            #armosa-widget .bot-message-content {
                background: #f4f4f5 !important;
                border: none !important;
                border-radius: 18px !important;
                padding: 12px 16px !important;
                font-size: 14px !important;
                line-height: 1.5 !important;
                color: #1F2937 !important;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04) !important;
            }

            /* Bot message text styling */
            #armosa-widget .bot-message-content strong,
            #armosa-widget .bot-message-content b {
                color: #00C896 !important;
                font-weight: 600 !important;
            }

            #armosa-widget .bot-message-content em,
            #armosa-widget .bot-message-content i {
                color: #2563EB !important;
                font-style: italic !important;
            }

            /* User Message: Match full-page - primary green bg */
            #armosa-widget .user-message-content {
                background: #00C896 !important;
                border: none !important;
                border-radius: 18px !important;
                padding: 12px 16px !important;
                color: #FFFFFF !important;
                font-size: 14px !important;
                line-height: 1.5 !important;
            }

            /* User message link styling */
            #armosa-widget .user-message-content a {
                color: #FFFFFF !important;
                text-decoration: underline !important;
                text-decoration-color: rgba(255, 255, 255, 0.5) !important;
            }

            #armosa-widget .user-message-content a:hover {
                text-decoration-color: #FFFFFF !important;
            }

            #armosa-widget .message-text {
                line-height: 1.5 !important;
                font-size: 14px !important;
                border: none !important;
                word-wrap: break-word !important;
            }

            /* Timestamp styling - match full-page */
            #armosa-widget .message-time {
                font-size: 11px !important;
                opacity: 0.6 !important;
                margin-top: 8px !important;
                text-align: right !important;
                opacity: 0.7 !important;
            }

            #armosa-widget .message-group.user .message-time {
                color: rgba(255, 255, 255, 0.7) !important;
            }

            /* Inline code in messages */
            #armosa-widget .message-text code {
                background: rgba(0, 200, 150, 0.1) !important;
                color: #059669 !important;
                padding: 2px 6px !important;
                border-radius: 4px !important;
                font-family: 'SF Mono', 'Consolas', monospace !important;
                font-size: 13px !important;
            }

            #armosa-widget .user-message-content code {
                background: rgba(255, 255, 255, 0.2) !important;
                color: #FFFFFF !important;
            }

            /* Code Block: Dark theme, 12px radius */
            #armosa-widget .code-block {
                background: #1E1E1E !important;
                border-radius: 12px !important;
                border: none !important;
                padding: 12px !important;
                overflow-x: auto !important;
                margin-top: 8px !important;
                box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.2) !important;
            }

            #armosa-widget .code-header {
                display: flex !important;
                justify-content: space-between !important;
                align-items: center !important;
                margin-bottom: 8px !important;
                font-size: 11px !important;
                color: #9CA3AF !important;
                border: none !important;
            }

            #armosa-widget .code-language {
                font-weight: 600 !important;
                color: #00C896 !important;
            }

            #armosa-widget .code-copy-btn {
                background: rgba(0, 200, 150, 0.15) !important;
                border: none !important;
                color: #00C896 !important;
                padding: 4px 10px !important;
                border-radius: 6px !important;
                cursor: pointer !important;
                font-size: 11px !important;
                transition: all 0.2s ease !important;
            }

            #armosa-widget .code-copy-btn:hover {
                background: rgba(0, 200, 150, 0.25) !important;
            }

            #armosa-widget .code-content {
                font-family: 'SF Mono', 'Consolas', 'Monaco', monospace !important;
                font-size: 12px !important;
                color: #E5E7EB !important;
                white-space: pre-wrap !important;
                word-break: break-all !important;
                line-height: 1.5 !important;
                border: none !important;
            }

            /* Recommendation Block: Left accent style */
            #armosa-widget .recommendation-block {
                background: rgba(0, 200, 150, 0.06) !important;
                border: none !important;
                border-left: 3px solid #00C896 !important;
                border-radius: 0 12px 12px 0 !important;
                padding: 12px 14px !important;
                margin-top: 8px !important;
            }

            #armosa-widget .recommendation-label {
                font-weight: 600 !important;
                color: #00C896 !important;
                font-size: 12px !important;
                margin-bottom: 6px !important;
                display: flex !important;
                align-items: center !important;
                gap: 6px !important;
                border: none !important;
            }

            #armosa-widget .recommendation-content {
                font-size: 13px !important;
                color: #374151 !important;
                line-height: 1.5 !important;
                border: none !important;
            }

            #armosa-widget .recommendation-list {
                list-style: none !important;
                padding-left: 0 !important;
                margin-top: 8px !important;
                border: none !important;
            }

            #armosa-widget .recommendation-list li {
                padding: 4px 0 4px 18px !important;
                position: relative !important;
                font-size: 13px !important;
                color: #374151 !important;
                border: none !important;
            }

            #armosa-widget .recommendation-list li:before {
                content: "→" !important;
                position: absolute !important;
                left: 0 !important;
                color: #00C896 !important;
                font-weight: 500 !important;
            }

            /* List Block: Clean with green bullet points */
            #armosa-widget .list-block {
                background: rgba(0, 200, 150, 0.03) !important;
                border-radius: 10px !important;
                padding: 12px 16px !important;
                margin-top: 8px !important;
                border: none !important;
                border-left: 2px solid rgba(0, 200, 150, 0.3) !important;
            }

            #armosa-widget .list-block ul {
                list-style: none !important;
                padding-left: 0 !important;
                margin: 0 !important;
                border: none !important;
            }

            #armosa-widget .list-block li {
                padding: 6px 0 6px 20px !important;
                position: relative !important;
                font-size: 13px !important;
                color: #374151 !important;
                border: none !important;
                line-height: 1.5 !important;
            }

            #armosa-widget .list-block li:before {
                content: "•" !important;
                position: absolute !important;
                left: 4px !important;
                color: #00C896 !important;
                font-weight: bold !important;
                font-size: 16px !important;
            }

            /* Links: Blue brand color with hover effect */
            #armosa-widget .message-link {
                color: #2563EB !important;
                text-decoration: none !important;
                border: none !important;
                border-bottom: 1px solid rgba(37, 99, 235, 0.3) !important;
                transition: all 0.2s ease !important;
            }

            #armosa-widget .message-link:hover {
                border-bottom-color: #2563EB !important;
            }

            #armosa-widget .user-message-content .message-link {
                color: #FFFFFF !important;
                border-bottom-color: rgba(255, 255, 255, 0.5) !important;
            }

            /* Typing Indicator: Animated dots */
            #armosa-widget .typing-indicator {
                display: flex !important;
                gap: 5px !important;
                padding: 12px 16px !important;
                background: #FFFFFF !important;
                border-radius: 4px 18px 18px 18px !important;
                border: none !important;
                width: fit-content !important;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
            }

            #armosa-widget .typing-dot {
                width: 7px !important;
                height: 7px !important;
                border-radius: 50% !important;
                background: linear-gradient(135deg, #2563EB, #00C896) !important;
                animation: typing 1.4s infinite !important;
                border: none !important;
            }

            #armosa-widget .typing-dot:nth-child(2) { animation-delay: 0.2s !important; }
            #armosa-widget .typing-dot:nth-child(3) { animation-delay: 0.4s !important; }

            @keyframes typing {
                0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
                30% { transform: translateY(-6px); opacity: 1; }
            }

            /* ==================== INPUT BAR ==================== */
            /* Match full-page: row layout with gap */
            #armosa-widget .armosa-input-container {
                width: 100% !important;
                display: flex !important;
                align-items: flex-end !important;
                padding: 0 !important;
                gap: 10px !important;
                flex-shrink: 0 !important;
                background: transparent !important;
                border: none !important;
                border-top: 1px solid #e8e8e8 !important;
                padding: 16px 20px !important;
            }

            /* Text Input: Match full-page - standalone with border */
            #armosa-widget #armosa-input {
                all: unset !important;
                flex: 1 !important;
                min-height: 40px !important;
                border: 1px solid #e5e5e5 !important;
                border-radius: 12px !important;
                padding: 10px 16px !important;
                font-size: 14px !important;
                font-family: inherit !important;
                background: #fafafa !important;
                color: #1F2937 !important;
                transition: all 0.15s ease !important;
            }

            #armosa-widget #armosa-input:focus {
                border-color: #00C896 !important;
                background: #FFFFFF !important;
                box-shadow: 0 0 0 2px rgba(0, 200, 150, 0.1) !important;
            }

            #armosa-widget #armosa-input::placeholder {
                color: #9CA3AF !important;
            }

            /* Action Buttons: Match full-page exactly - 40x40, border, transparent */
            #armosa-widget .action-btn {
                all: unset !important;
                width: 40px !important;
                height: 40px !important;
                border-radius: 10px !important;
                background: transparent !important;
                border: 1px solid #e5e5e5 !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                color: #71717a !important;
                transition: all 0.15s ease !important;
                flex-shrink: 0 !important;
            }

            #armosa-widget .action-btn:hover {
                background: #f4f4f5 !important;
                border-color: #d4d4d8 !important;
                color: #00C896 !important;
            }

            #armosa-widget .action-btn:hover iconify-icon {
                transform: scale(1.1) !important;
            }

            #armosa-widget .action-btn.recording {
                background: #EF4444 !important;
                color: #FFFFFF !important;
                animation: recordPulse 1s infinite !important;
            }

            @keyframes recordPulse {
                0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
                50% { transform: scale(1.05); box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
            }

            /* Text Input: Clean, minimal */
            #armosa-widget #armosa-input {
                all: unset !important;
                flex: 1 !important;
                height: 36px !important;
                border: none !important;
                background: transparent !important;
                padding: 0 8px !important;
                font-size: 14px !important;
                font-family: inherit !important;
                outline: none !important;
                color: #1F2937 !important;
            }

            #armosa-widget #armosa-input::placeholder {
                color: #9CA3AF !important;
            }

            /* Send Button: Match full-page - 40x40, primary green */
            #armosa-widget .send-btn {
                all: unset !important;
                width: 40px !important;
                height: 40px !important;
                min-width: 40px !important;
                min-height: 40px !important;
                border-radius: 10px !important;
                background: #00C896 !important;
                border: none !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                color: #FFFFFF !important;
                transition: all 0.15s ease !important;
                flex-shrink: 0 !important;
            }

            #armosa-widget .send-btn:hover:not(:disabled) {
                background: #009977 !important;
            }

            #armosa-widget .send-btn:disabled {
                opacity: 0.5 !important;
                cursor: not-allowed !important;
            }

            /* File Preview */
            #armosa-widget .file-preview {
                display: none !important;
                padding: 8px 12px !important;
                background: #F3F4F6 !important;
                border-radius: 10px !important;
                border: none !important;
                font-size: 12px !important;
                align-items: center !important;
                gap: 8px !important;
                margin-bottom: 8px !important;
            }

            #armosa-widget .file-preview.active {
                display: flex !important;
            }

            #armosa-widget .remove-file-btn {
                all: unset !important;
                background: none !important;
                border: none !important;
                color: #EF4444 !important;
                cursor: pointer !important;
                font-size: 16px !important;
                transition: all 0.2s ease !important;
            }

            #armosa-widget .remove-file-btn:hover {
                transform: scale(1.1) !important;
            }

            /* ==================== RESPONSIVE ==================== */
            @media (max-width: 400px) {
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
                }

                #armosa-widget .armosa-header,
                #armosa-widget .armosa-messages,
                #armosa-widget .armosa-input-container {
                    width: 100% !important;
                }
            }

            /* Syntax Highlighting */
            #armosa-widget .code-keyword { color: #569CD6 !important; }
            #armosa-widget .code-string { color: #CE9178 !important; }
            #armosa-widget .code-number { color: #B5CEA8 !important; }
            #armosa-widget .code-function { color: #DCDCAA !important; }
            #armosa-widget .code-comment { color: #6A9955 !important; font-style: italic !important; }
        `;
        
        document.head.appendChild(style);
    }

    createWidget() {
        // Load Iconify script if not already loaded
        if (!document.querySelector('script[src*="iconify"]')) {
            const iconifyScript = document.createElement('script');
            iconifyScript.src = 'https://code.iconify.design/iconify-icon/1.0.7/iconify-icon.min.js';
            document.head.appendChild(iconifyScript);
        }

        // Create FAB (Floating Action Button) - premium gradient with shadow
        const fab = document.createElement('button');
        fab.id = 'armosa-fab';
        fab.innerHTML = `<iconify-icon icon="mdi:chat" style="font-size: 24px; color: white;"></iconify-icon>`;
        fab.title = 'Chat with Armosa';
        document.body.appendChild(fab);
        this.fab = fab;

        // Create Widget (hidden by default) - premium AI-native design
        const widget = document.createElement('div');
        widget.id = 'armosa-widget';
        widget.classList.add('hidden');
        widget.innerHTML = `
            <!-- Inner container for white background -->
            <div class="widget-inner">
                <!-- HEADER: Two-row layout -->
                <div class="armosa-header">
                    <button class="close-btn" id="close-widget" title="Close">
                        <iconify-icon icon="mdi:close" style="font-size: 16px;"></iconify-icon>
                    </button>
                    <div class="header-top">
                        <div class="armosa-logo">
                            <iconify-icon icon="mdi:robot-happy-outline" style="font-size: 20px; color: white;"></iconify-icon>
                        </div>
                        <div class="armosa-title">Ask Armosa</div>
                    </div>
                    <div class="mode-buttons">
                        <button class="mode-btn active" data-mode="chat" title="Chat">
                            <iconify-icon icon="mdi:chat-outline" class="mode-btn-icon"></iconify-icon>
                        </button>
                        <button class="mode-btn" data-mode="avatar" title="Avatar">
                            <iconify-icon icon="mdi:face-agent" class="mode-btn-icon"></iconify-icon>
                        </button>
                    </div>
                </div>

                <!-- CHAT AREA: Clean, scrollable -->
                <div class="armosa-messages" id="armosa-messages"></div>

                <!-- INPUT BAR: Same as full-page -->
                <div class="armosa-input-container">
                    <input type="file" id="file-input" accept="audio/*,video/*,image/*,.pdf,.docx,.doc,.txt" style="display: none;">
                    <button class="action-btn" id="file-btn" title="Attach file">
                        <iconify-icon icon="mdi:paperclip" style="font-size: 18px;"></iconify-icon>
                    </button>
                    <button class="action-btn" id="voice-btn" title="Record voice">
                        <iconify-icon icon="mdi:microphone" style="font-size: 18px;"></iconify-icon>
                    </button>
                    <input type="text" id="armosa-input" placeholder="Type your message...">
                    <button class="send-btn" id="send-btn" title="Send">
                        <iconify-icon icon="mdi:send" style="font-size: 18px;"></iconify-icon>
                    </button>
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
        // FAB click to open
        this.fab.addEventListener('click', () => this.toggleWidget());

        // Close button
        this.widget.querySelector('#close-widget').addEventListener('click', () => this.toggleWidget());

        // Mode buttons
        this.widget.querySelectorAll('.mode-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchMode(e.target.closest('.mode-btn').dataset.mode));
        });

        // Input
        const input = this.widget.querySelector('#armosa-input');
        input.addEventListener('input', () => this.autoResizeInput(input));
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Send button
        this.widget.querySelector('#send-btn').addEventListener('click', () => this.sendMessage());

        // File button
        const fileBtn = this.widget.querySelector('#file-btn');
        const fileInput = this.widget.querySelector('#file-input');
        fileBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => this.handleFileSelect(e));

        // Voice button
        this.widget.querySelector('#voice-btn').addEventListener('click', () => this.toggleRecording());
    }

    switchMode(mode) {
        this.currentMode = mode;
        
        // Update button states
        this.widget.querySelectorAll('.mode-btn').forEach(btn => {
            btn.classList.remove('active');
            if (btn.dataset.mode === mode) {
                btn.classList.add('active');
            }
        });

        // Could add mode-specific behavior here (avatar rendering, etc.)
    }

    autoResizeInput(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 100) + 'px';
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
            <span>📄 ${filename}</span>
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
                
                this.mediaRecorder.ondataavailable = (e) => {
                    this.audioChunks.push(e.data);
                };

                this.mediaRecorder.onstart = () => {
                    this.isRecording = true;
                    this.widget.querySelector('#voice-btn').classList.add('recording');
                };

                this.mediaRecorder.onstop = () => {
                    this.isRecording = false;
                    this.widget.querySelector('#voice-btn').classList.remove('recording');
                    
                    const audioBlob = new Blob(this.audioChunks, { type: 'audio/wav' });
                    this.sendAudioMessage(audioBlob);
                };

                this.mediaRecorder.start();
            })
            .catch(err => console.error('Microphone access denied:', err));
    }

    stopRecording() {
        if (this.mediaRecorder) {
            this.mediaRecorder.stop();
            // Stop all tracks to release microphone
            this.mediaRecorder.stream.getTracks().forEach(track => track.stop());
        }
    }

    sendAudioMessage(audioBlob) {
        const formData = new FormData();
        // Use 'audio' field name with webm format (like full-page)
        formData.append('audio', audioBlob, 'recording.webm');
        
        this.showTypingIndicator();
        
        // Use correct /voice endpoint (same as full-page)
        fetch(this.config.voiceUrl, {
            method: 'POST',
            body: formData
        })
        .then(async response => {
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `Voice request failed (${response.status})`);
            }
            
            // Check content type - could be audio or JSON
            const contentType = response.headers.get('Content-Type');
            
            if (contentType && contentType.includes('application/json')) {
                // Server returned JSON - use browser TTS fallback
                const data = await response.json();
                
                // Show user transcription
                if (data.transcription) {
                    this.addUserMessage(`🎤 "${data.transcription}"`);
                }
                
                // Show and optionally speak bot response
                if (data.response) {
                    this.addBotMessage(data.response);
                    
                    // Use browser TTS if available
                    if (data.use_browser_tts && 'speechSynthesis' in window) {
                        this.speakText(data.response);
                    }
                }
            } else {
                // Server returned audio
                const audioResponse = await response.blob();
                const transcription = response.headers.get('X-Transcription');
                const responseText = response.headers.get('X-Response-Text');
                const decodedResponseText = responseText ? decodeURIComponent(responseText) : '';
                
                // Show user transcription
                if (transcription) {
                    this.addUserMessage(`🎤 "${transcription}"`);
                }
                
                // Show bot response text
                if (decodedResponseText) {
                    this.addBotMessage(decodedResponseText);
                }
                
                // Play audio response
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
        .finally(() => {
            this.removeTypingIndicator();
        });
    }
    
    // Browser TTS for voice responses
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

        // Show what user typed with file attachment indicator
        const displayMessage = this.selectedFile ? `${message}\n📎 ${this.selectedFile.name}` : message;
        this.addUserMessage(displayMessage || 'Please analyze this file');
        
        input.value = '';
        input.style.height = 'auto';

        // Show typing indicator
        this.showTypingIndicator();

        // Use FormData like full-page (backend expects multipart/form-data)
        const formData = new FormData();
        formData.append('message', message || 'Please analyze this file');
        if (this.conversationId) {
            formData.append('conversation_id', this.conversationId);
        }
        if (this.selectedFile) {
            formData.append('file', this.selectedFile);
        }

        // Send to API
        fetch(this.config.apiUrl, {
            method: 'POST',
            body: formData  // No Content-Type header - browser sets it with boundary
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`Request failed (${response.status})`);
            }
            return response.json();
        })
        .then(data => {
            this.removeTypingIndicator();
            // Store conversation ID for context continuity
            if (data.conversation_id) {
                this.conversationId = data.conversation_id;
            }
            this.addBotMessage(data.response);
        })
        .catch(err => {
            this.removeTypingIndicator();
            this.addBotMessage('Sorry, I encountered an error. Please try again.');
            console.error('Chat error:', err);
        })
        .finally(() => {
            this.removeFile();
        });
    }

    addUserMessage(message) {
        this.messages.push({ role: 'user', content: message });
        const msgElement = this.createMessageElement(message, 'user');
        this.messagesContainer.appendChild(msgElement);
        this.scrollToBottom();
    }

    addBotMessage(message) {
        this.messages.push({ role: 'bot', content: message });
        const msgElement = this.createMessageElement(message, 'bot');
        this.messagesContainer.appendChild(msgElement);
        this.scrollToBottom();
    }

    createMessageElement(content, role) {
        const group = document.createElement('div');
        group.className = `message-group ${role}`;

        // Add avatar with Iconify icon (like full-page)
        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        if (role === 'bot') {
            avatar.innerHTML = '<iconify-icon icon="mdi:robot" style="font-size: 20px; color: #00C896;"></iconify-icon>';
        } else {
            avatar.innerHTML = '<iconify-icon icon="mdi:account" style="font-size: 20px; color: white;"></iconify-icon>';
        }
        group.appendChild(avatar);

        // Parse and create message bubble
        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.innerHTML = this.parseMessage(content, role);
        
        // Add timestamp
        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const timestamp = document.createElement('div');
        timestamp.className = 'message-time';
        timestamp.textContent = time;
        bubble.appendChild(timestamp);
        
        group.appendChild(bubble);

        return group;
    }

    parseMessage(content, role) {
        let html = '';

        // Split by double newlines to identify blocks
        const blocks = content.split('\n\n');

        for (const block of blocks) {
            // Code block detection
            if (block.includes('```')) {
                html += this.parseCodeBlock(block);
            }
            // Recommendation detection
            else if (block.match(/^(Recommendation|💡|⭐|Suggested|Tip):/i)) {
                html += this.parseRecommendation(block);
            }
            // List detection
            else if (block.split('\n').some(line => line.match(/^[-•*]\s/))) {
                html += this.parseList(block);
            }
            // Regular text
            else {
                html += `<div class="${role}-message-content"><div class="message-text">${this.parseInlineMarkdown(block)}</div></div>`;
            }
        }

        return html;
    }

    parseCodeBlock(block) {
        const codeMatch = block.match(/```(\w+)?\n([\s\S]*?)```/);
        if (!codeMatch) return '';

        const language = codeMatch[1] || 'text';
        const code = codeMatch[2].trim();

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
        const header = lines[0];
        const content = lines.slice(1).join('\n');

        let html = `
            <div class="recommendation-block">
                <div class="recommendation-label">💡 ${this.escapeHtml(header)}</div>
                <div class="recommendation-content">${this.parseInlineMarkdown(content)}</div>
        `;

        // Check for list items in recommendation
        const listItems = content.split('\n').filter(l => l.match(/^[-•*]\s/));
        if (listItems.length > 0) {
            html += `<ul class="recommendation-list">`;
            listItems.forEach(item => {
                html += `<li>${this.escapeHtml(item.replace(/^[-•*]\s/, ''))}</li>`;
            });
            html += `</ul>`;
        }

        html += `</div>`;
        return html;
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
        // Bold
        text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        
        // Italic
        text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
        
        // Links
        text = text.replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" class="message-link" target="_blank">$1</a>');
        
        // Inline code
        text = text.replace(/`(.*?)`/g, '<code style="background: rgba(0,0,0,0.1); padding: 2px 6px; border-radius: 3px; font-family: monospace; font-size: 0.9em;">$1</code>');

        return text;
    }

    showTypingIndicator() {
        const indicator = document.createElement('div');
        indicator.className = 'message-group';
        indicator.id = 'typing-indicator';
        indicator.innerHTML = `
            <div class="message-avatar">
                <iconify-icon icon="mdi:robot" style="font-size: 20px; color: #00C896;"></iconify-icon>
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

// Auto-initialize widget when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.armosChatWidget = new ArmosChatWidget({
        apiUrl: window.ARMOSA_CONFIG?.apiUrl || '/api/chat'
    });
});

// Export for use as ES module
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ArmosChatWidget;
}
