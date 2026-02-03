/**
 * Armosa Chat Widget
 * Self-contained embeddable chat widget with smart message parsing
 * Inject via: <script src="chat-widget.js"></script>
 */

class ArmosChatWidget {
    constructor(config = {}) {
        this.config = {
            apiUrl: config.apiUrl || '/api/chat',
            containerId: config.containerId || 'armosa-widget-container',
            theme: config.theme || 'light',
            position: config.position || 'bottom-right',
            ...config
        };
        
        this.messages = [];
        this.currentMode = 'chat'; // 'chat' or 'avatar'
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
        if (document.getElementById(styleId)) return;
        
        const style = document.createElement('style');
        style.id = styleId;
        style.textContent = `
            /* ============================================================
               ARMOSA CHAT WIDGET - PREMIUM AI-NATIVE DESIGN SYSTEM
               Visual Language: ChatGPT / Cursor / Copilot tier
               Frame: 360×720 (1:2 ratio), border-radius: 28px
               Colors: Blue #2563EB → Green #00C896, Gold #FFB800
               Strokes: Soft charcoal rgba(0,0,0,0.1), shadows over borders
               ============================================================ */

            /* Scoped Reset */
            #armosa-fab,
            #armosa-widget,
            #armosa-widget *,
            #armosa-widget *::before,
            #armosa-widget *::after {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }

            /* ===================== FLOATING ACTION BUTTON ===================== */
            #armosa-fab {
                position: fixed;
                bottom: 24px;
                right: 24px;
                width: 56px;
                height: 56px;
                border-radius: 50%;
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%);
                border: none;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 999998;
                transition: all 0.3s ease;
                box-shadow: 0 4px 16px rgba(0, 200, 150, 0.35),
                            0 2px 4px rgba(0, 0, 0, 0.1);
            }

            #armosa-fab:hover {
                transform: scale(1.08);
                box-shadow: 0 6px 24px rgba(0, 200, 150, 0.45),
                            0 4px 8px rgba(0, 0, 0, 0.12);
            }

            #armosa-fab.hidden {
                transform: scale(0);
                opacity: 0;
                pointer-events: none;
            }

            /* ===================== WIDGET OUTER FRAME ===================== */
            /* Premium frame with gradient border glow effect */
            #armosa-widget {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                position: fixed;
                bottom: 24px;
                right: 24px;
                width: 360px;
                height: 720px;
                background: white;
                border-radius: 28px;
                padding: 3px;
                display: flex;
                flex-direction: column;
                z-index: 999999;
                transition: all 0.3s ease;
                transform-origin: bottom right;
                /* Gradient border effect */
                background: linear-gradient(180deg, #2563EB 0%, #00C896 100%);
                box-shadow: 0 8px 32px rgba(0, 200, 150, 0.2),
                            0 4px 16px rgba(37, 99, 235, 0.15),
                            0 2px 8px rgba(0, 0, 0, 0.08);
            }

            #armosa-widget.hidden {
                transform: scale(0);
                opacity: 0;
                pointer-events: none;
            }

            /* Inner container - white background */
            .widget-inner {
                flex: 1;
                background: white;
                border-radius: 25px;
                display: flex;
                flex-direction: column;
                gap: 12px;
                padding: 12px;
                overflow: hidden;
            }

            /* ===================== HEADER ZONE ===================== */
            /* Two-row header: Logo+Title on top, Mode buttons below */
            .armosa-header {
                width: 100%;
                background: white;
                border-radius: 16px;
                border: none;
                display: flex;
                flex-direction: column;
                align-items: center;
                padding: 16px;
                gap: 12px;
                position: relative;
                flex-shrink: 0;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
            }

            /* Top row: Logo + Title */
            .header-top {
                display: flex;
                align-items: center;
                gap: 10px;
            }

            /* Close button - subtle, top right */
            .close-btn {
                position: absolute;
                top: 12px;
                right: 12px;
                width: 24px;
                height: 24px;
                border-radius: 50%;
                background: transparent;
                border: none;
                color: #9CA3AF;
                font-size: 14px;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.2s;
            }

            .close-btn:hover {
                background: rgba(0, 0, 0, 0.05);
                color: #1F2937;
            }

            /* Avatar - gradient filled */
            .armosa-logo {
                width: 36px;
                height: 36px;
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%);
                border-radius: 50%;
                border: none;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                font-weight: 600;
                color: white;
                flex-shrink: 0;
            }

            /* Title - clean text */
            .armosa-title {
                font-size: 17px;
                font-weight: 600;
                color: #1F2937;
            }

            /* Mode Buttons - centered below */
            .mode-buttons {
                display: flex;
                gap: 4px;
                background: #F3F4F6;
                border-radius: 10px;
                padding: 3px;
            }

            .mode-btn {
                width: 32px;
                height: 28px;
                border-radius: 8px;
                background: transparent;
                border: none;
                color: #6B7280;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 14px;
                transition: all 0.2s;
            }

            .mode-btn:hover {
                color: #1F2937;
            }

            .mode-btn.active {
                background: white;
                color: #00C896;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
            }

            .mode-btn-icon {
                font-size: 14px;
            }

            /* ===================== CHAT AREA ===================== */
            /* Clean, no border, subtle inner feel */
            .armosa-messages {
                width: 100%;
                flex: 1;
                background: #FAFAFA;
                border-radius: 16px;
                border: none;
                overflow-y: auto;
                padding: 16px;
                display: flex;
                flex-direction: column;
                gap: 16px;
            }

            .armosa-messages::-webkit-scrollbar {
                width: 4px;
            }

            .armosa-messages::-webkit-scrollbar-track {
                background: transparent;
            }

            .armosa-messages::-webkit-scrollbar-thumb {
                background: rgba(0, 0, 0, 0.15);
                border-radius: 2px;
            }

            /* ===================== MESSAGE BUBBLES ===================== */
            /* Smart bubbling with proper visual hierarchy */
            
            .message-group {
                display: flex;
                gap: 10px;
                animation: slideIn 0.3s ease;
            }

            @keyframes slideIn {
                from { opacity: 0; transform: translateY(8px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .message-group.user {
                flex-direction: row-reverse;
            }

            /* Avatar - bot only shows avatar */
            .message-avatar {
                width: 28px;
                height: 28px;
                border-radius: 50%;
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%);
                border: none;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 12px;
                flex-shrink: 0;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            }

            .message-group.user .message-avatar {
                background: linear-gradient(135deg, #00C896 0%, #059669 100%);
            }

            /* Chat Bubble */
            .message-bubble {
                max-width: 80%;
            }

            /* Bot Message - light, breathable */
            .bot-message-content {
                background: white;
                border: none;
                border-radius: 4px 18px 18px 18px;
                padding: 12px 16px;
                font-size: 14px;
                line-height: 1.5;
                color: #1F2937;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
            }

            /* User Message - solid, confident */
            .user-message-content {
                background: linear-gradient(135deg, #2563EB 0%, #00C896 100%);
                border: none;
                border-radius: 18px 4px 18px 18px;
                padding: 12px 16px;
                color: white;
                font-size: 14px;
                line-height: 1.5;
                box-shadow: 0 2px 8px rgba(37, 99, 235, 0.25);
            }

            .message-text {
                line-height: 1.5;
                font-size: 14px;
            }

            /* Code Block - refined dark theme */
            .code-block {
                background: #1E1E1E;
                border-radius: 12px;
                border: none;
                padding: 12px;
                overflow-x: auto;
                margin-top: 8px;
                box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.2);
            }

            .code-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 8px;
                font-size: 11px;
                color: #9CA3AF;
            }

            .code-language {
                font-weight: 600;
                color: #00C896;
            }

            .code-copy-btn {
                background: rgba(0, 200, 150, 0.15);
                border: none;
                color: #00C896;
                padding: 4px 10px;
                border-radius: 6px;
                cursor: pointer;
                font-size: 11px;
                transition: all 0.2s;
            }

            .code-copy-btn:hover {
                background: rgba(0, 200, 150, 0.25);
            }

            .code-content {
                font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                color: #E5E7EB;
                white-space: pre-wrap;
                word-break: break-all;
                line-height: 1.5;
            }

            /* Recommendation Block - left accent style */
            .recommendation-block {
                background: rgba(0, 200, 150, 0.06);
                border-left: 3px solid #00C896;
                border-radius: 0 12px 12px 0;
                padding: 12px 14px;
                margin-top: 8px;
            }

            .recommendation-label {
                font-weight: 600;
                color: #00C896;
                font-size: 12px;
                margin-bottom: 6px;
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .recommendation-content {
                font-size: 13px;
                color: #374151;
                line-height: 1.5;
            }

            .recommendation-list {
                list-style: none;
                padding-left: 0;
                margin-top: 8px;
            }

            .recommendation-list li {
                padding: 4px 0 4px 18px;
                position: relative;
                font-size: 13px;
                color: #374151;
            }

            .recommendation-list li:before {
                content: "→";
                position: absolute;
                left: 0;
                color: #00C896;
                font-weight: 500;
            }

            /* List Block */
            .list-block {
                background: rgba(0, 0, 0, 0.02);
                border-radius: 10px;
                padding: 12px;
                margin-top: 8px;
            }

            .list-block ul {
                list-style: none;
                padding-left: 0;
                margin: 0;
            }

            .list-block li {
                padding: 4px 0 4px 18px;
                position: relative;
                font-size: 13px;
                color: #374151;
            }

            .list-block li:before {
                content: "•";
                position: absolute;
                left: 4px;
                color: #00C896;
                font-weight: bold;
            }

            /* Links */
            .message-link {
                color: #2563EB;
                text-decoration: none;
                border-bottom: 1px solid rgba(37, 99, 235, 0.3);
                transition: all 0.2s;
            }

            .message-link:hover {
                border-bottom-color: #2563EB;
            }

            .user-message-content .message-link {
                color: white;
                border-bottom-color: rgba(255, 255, 255, 0.5);
            }

            /* Typing Indicator */
            .typing-indicator {
                display: flex;
                gap: 5px;
                padding: 12px 16px;
                background: white;
                border-radius: 4px 18px 18px 18px;
                border: none;
                width: fit-content;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
            }

            .typing-dot {
                width: 7px;
                height: 7px;
                border-radius: 50%;
                background: linear-gradient(135deg, #2563EB, #00C896);
                animation: typing 1.4s infinite;
            }

            .typing-dot:nth-child(2) { animation-delay: 0.2s; }
            .typing-dot:nth-child(3) { animation-delay: 0.4s; }

            @keyframes typing {
                0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
                30% { transform: translateY(-6px); opacity: 1; }
            }

            /* ===================== INPUT BAR ===================== */
            /* Clean pill, subtle border, premium feel */
            .armosa-input-container {
                width: 100%;
                height: 52px;
                background: white;
                border-radius: 26px;
                border: 1px solid rgba(0, 0, 0, 0.08);
                display: flex;
                align-items: center;
                padding: 0 8px 0 16px;
                gap: 8px;
                flex-shrink: 0;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
                transition: all 0.2s;
            }

            .armosa-input-container:focus-within {
                border-color: rgba(0, 200, 150, 0.4);
                box-shadow: 0 0 0 3px rgba(0, 200, 150, 0.1);
            }

            /* Action buttons - subtle, icon-based */
            .action-btn {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                background: transparent;
                border: none;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                color: #9CA3AF;
                transition: all 0.2s;
                flex-shrink: 0;
            }

            .action-btn:hover {
                background: rgba(0, 0, 0, 0.05);
                color: #1F2937;
            }

            .action-btn.recording {
                background: #EF4444;
                color: white;
                animation: recordPulse 1s infinite;
            }

            @keyframes recordPulse {
                0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
                50% { transform: scale(1.05); box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
            }

            /* Text input - minimal, clean */
            #armosa-input {
                flex: 1;
                height: 36px;
                border: none;
                background: transparent;
                padding: 0 8px;
                font-size: 14px;
                font-family: inherit;
                outline: none;
                color: #1F2937;
            }

            #armosa-input::placeholder {
                color: #9CA3AF;
            }

            /* Send button - golden accent, premium */
            .send-btn {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background: linear-gradient(135deg, #FFB800 0%, #FF9500 100%);
                border: none;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 14px;
                transition: all 0.2s;
                flex-shrink: 0;
                box-shadow: 0 2px 8px rgba(255, 184, 0, 0.35);
            }

            .send-btn:hover:not(:disabled) {
                transform: scale(1.08);
                box-shadow: 0 4px 12px rgba(255, 184, 0, 0.45);
            }

            .send-btn:disabled {
                opacity: 0.4;
                cursor: not-allowed;
                transform: none;
                box-shadow: none;
            }

            /* File Preview */
            .file-preview {
                display: none;
                padding: 8px 12px;
                background: #F3F4F6;
                border-radius: 10px;
                border: none;
                font-size: 12px;
                align-items: center;
                gap: 8px;
                margin-bottom: 8px;
            }

            .file-preview.active {
                display: flex;
            }

            .remove-file-btn {
                background: none;
                border: none;
                color: #EF4444;
                cursor: pointer;
                font-size: 16px;
                transition: all 0.2s;
            }

            .remove-file-btn:hover {
                transform: scale(1.1);
            }

            /* ===================== RESPONSIVE ===================== */
            @media (max-width: 400px) {
                #armosa-widget {
                    width: 100%;
                    height: 100%;
                    border-radius: 0;
                    bottom: 0;
                    right: 0;
                    padding: 0;
                }

                .widget-inner {
                    border-radius: 0;
                }

                .armosa-header,
                .armosa-messages,
                .armosa-input-container {
                    width: 100%;
                }
            }

            /* Syntax Highlighting - refined */
            .code-keyword { color: #569CD6; }
            .code-string { color: #CE9178; }
            .code-number { color: #B5CEA8; }
            .code-function { color: #DCDCAA; }
            .code-comment { color: #6A9955; font-style: italic; }
        `;
        
        document.head.appendChild(style);
    }

    createWidget() {
        // Create FAB (Floating Action Button) - premium gradient with shadow
        const fab = document.createElement('button');
        fab.id = 'armosa-fab';
        fab.innerHTML = `
            <svg viewBox="0 0 24 24" width="24" height="24" fill="white">
                <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/>
            </svg>
        `;
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
                    <button class="close-btn" id="close-widget" title="Close">✕</button>
                    <div class="header-top">
                        <div class="armosa-logo">A</div>
                        <div class="armosa-title">Ask Armosa</div>
                    </div>
                    <div class="mode-buttons">
                        <button class="mode-btn active" data-mode="chat" title="Chat">
                            <span class="mode-btn-icon">💬</span>
                        </button>
                        <button class="mode-btn" data-mode="avatar" title="Avatar">
                            <span class="mode-btn-icon">👤</span>
                        </button>
                    </div>
                </div>

                <!-- CHAT AREA: Clean, scrollable -->
                <div class="armosa-messages" id="armosa-messages"></div>

                <!-- INPUT BAR: Premium pill -->
                <div class="armosa-input-container">
                    <input type="file" id="file-input" style="display: none;">
                    <button class="action-btn" id="file-btn" title="Attach file">📎</button>
                    <input type="text" id="armosa-input" placeholder="Ask anything...">
                    <button class="action-btn" id="voice-btn" title="Voice input">🎤</button>
                    <button class="send-btn" id="send-btn" title="Send">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                        </svg>
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
        }
    }

    sendAudioMessage(audioBlob) {
        const formData = new FormData();
        formData.append('audio', audioBlob, 'message.wav');
        
        this.addUserMessage('[🎤 Voice message]');
        this.showTypingIndicator();
        
        fetch(`${this.config.apiUrl}/audio`, {
            method: 'POST',
            body: formData
        })
        .then(r => r.json())
        .then(data => {
            this.removeTypingIndicator();
            this.addBotMessage(data.response);
        })
        .catch(err => {
            this.removeTypingIndicator();
            this.addBotMessage('Sorry, there was an error processing your voice message.');
            console.error(err);
        });
    }

    sendMessage() {
        const input = this.widget.querySelector('#armosa-input');
        const message = input.value.trim();

        if (!message) return;

        // Add user message
        this.addUserMessage(message);
        input.value = '';
        input.style.height = 'auto';
        this.removeFile();

        // Show typing indicator
        this.showTypingIndicator();

        // Send to API
        fetch(this.config.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, mode: this.currentMode })
        })
        .then(r => r.json())
        .then(data => {
            this.removeTypingIndicator();
            this.addBotMessage(data.response);
        })
        .catch(err => {
            this.removeTypingIndicator();
            this.addBotMessage('Sorry, I encountered an error. Please try again.');
            console.error(err);
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

        // Add avatar
        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.textContent = role === 'bot' ? '🤖' : '👤';
        group.appendChild(avatar);

        // Parse and create message bubble
        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';
        bubble.innerHTML = this.parseMessage(content, role);
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
            <div class="message-avatar">🤖</div>
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
