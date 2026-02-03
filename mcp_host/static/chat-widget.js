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
               ARMOSA CHAT WIDGET - GEOMETRIC DESIGN SYSTEM
               Frame: 360×720 (1:2 ratio), border-radius: 28px
               Gradient: #7F5CFF (purple) → #4ED1C1 (teal)
               All strokes: 1px black, consistent throughout
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
                background: linear-gradient(180deg, #7F5CFF 0%, #4ED1C1 100%);
                border: 2px solid black;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 999998;
                transition: all 0.3s ease;
            }

            #armosa-fab:hover {
                transform: scale(1.08);
            }

            #armosa-fab.hidden {
                transform: scale(0);
                opacity: 0;
                pointer-events: none;
            }

            /* ===================== WIDGET OUTER FRAME ===================== */
            /* Geometric Frame: 360×720, ratio 1:2, border-radius: 28px */
            #armosa-widget {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                position: fixed;
                bottom: 24px;
                right: 24px;
                width: 360px;
                height: 720px;
                background: linear-gradient(180deg, #7F5CFF 0%, #4ED1C1 100%);
                border-radius: 28px;
                border: 3px solid black;
                padding: 16px;
                display: flex;
                flex-direction: column;
                gap: 16px;
                z-index: 999999;
                transition: all 0.3s ease;
                transform-origin: bottom right;
            }

            #armosa-widget.hidden {
                transform: scale(0);
                opacity: 0;
                pointer-events: none;
            }

            /* ===================== HEADER ZONE ===================== */
            /* 328×64px, border-radius: 20px, white fill, 1px black stroke */
            .armosa-header {
                width: 328px;
                height: 64px;
                background: white;
                border-radius: 20px;
                border: 1px solid black;
                display: flex;
                align-items: center;
                padding: 0 12px;
                gap: 10px;
                position: relative;
                flex-shrink: 0;
            }

            /* Close button - top right of header */
            .close-btn {
                position: absolute;
                top: 8px;
                right: 8px;
                width: 20px;
                height: 20px;
                border-radius: 50%;
                background: white;
                border: 1px solid black;
                color: black;
                font-size: 12px;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: all 0.2s;
            }

            .close-btn:hover {
                background: #f0f0f0;
            }

            /* Avatar circle - radius 12px (24px diameter) */
            .armosa-logo {
                width: 24px;
                height: 24px;
                background: white;
                border-radius: 50%;
                border: 1px solid black;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                flex-shrink: 0;
            }

            /* Title pill - 160×32px, border-radius: 16px */
            .armosa-title {
                width: 160px;
                height: 32px;
                background: white;
                border-radius: 16px;
                border: 1px solid black;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 14px;
                font-weight: 600;
                color: black;
            }

            /* Mode Buttons - 72×24px each, border-radius: 12px */
            .mode-buttons {
                display: flex;
                gap: 8px;
                margin-left: auto;
                margin-right: 24px;
            }

            .mode-btn {
                width: 36px;
                height: 24px;
                border-radius: 12px;
                background: white;
                border: 1px solid black;
                color: black;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
                transition: all 0.2s;
            }

            .mode-btn:hover {
                background: #f5f5f5;
            }

            .mode-btn.active {
                background: linear-gradient(180deg, #7F5CFF 0%, #4ED1C1 100%);
                color: white;
            }

            .mode-btn-icon {
                font-size: 14px;
            }

            /* ===================== CENTRAL REGION (CHAT AREA) ===================== */
            /* 328px wide, fills vertical space, border-radius: 16px */
            .armosa-messages {
                width: 328px;
                flex: 1;
                background: white;
                border-radius: 16px;
                border: 1px solid black;
                overflow-y: auto;
                padding: 12px;
                display: flex;
                flex-direction: column;
                gap: 10px;
            }

            .armosa-messages::-webkit-scrollbar {
                width: 4px;
            }

            .armosa-messages::-webkit-scrollbar-track {
                background: transparent;
            }

            .armosa-messages::-webkit-scrollbar-thumb {
                background: #ccc;
                border-radius: 2px;
            }

            /* Message Container */
            .message-group {
                display: flex;
                gap: 8px;
                animation: slideIn 0.25s ease;
            }

            @keyframes slideIn {
                from { opacity: 0; transform: translateY(8px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .message-group.user {
                flex-direction: row-reverse;
            }

            .message-avatar {
                width: 24px;
                height: 24px;
                border-radius: 50%;
                background: linear-gradient(180deg, #7F5CFF 0%, #4ED1C1 100%);
                border: 1px solid black;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 12px;
                flex-shrink: 0;
            }

            .message-group.user .message-avatar {
                background: #4ED1C1;
            }

            /* Chat Bubble */
            .message-bubble {
                max-width: 75%;
            }

            .bot-message-content {
                background: white;
                border: 1px solid black;
                border-radius: 12px;
                padding: 10px;
                font-size: 13px;
                line-height: 1.4;
            }

            .user-message-content {
                background: linear-gradient(180deg, #7F5CFF 0%, #4ED1C1 100%);
                border: 1px solid black;
                border-radius: 12px;
                padding: 10px;
                color: white;
                font-size: 13px;
                line-height: 1.4;
            }

            .message-text {
                line-height: 1.4;
                font-size: 13px;
            }

            /* Code Block */
            .code-block {
                background: #1e1e1e;
                border-radius: 8px;
                border: 1px solid black;
                padding: 10px;
                overflow-x: auto;
                margin-top: 6px;
            }

            .code-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 6px;
                font-size: 11px;
                color: #888;
            }

            .code-language {
                font-weight: 600;
                color: #4ED1C1;
            }

            .code-copy-btn {
                background: transparent;
                border: 1px solid #4ED1C1;
                color: #4ED1C1;
                padding: 2px 6px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 10px;
                transition: all 0.2s;
            }

            .code-copy-btn:hover {
                background: rgba(78, 209, 193, 0.2);
            }

            .code-content {
                font-family: 'Courier New', monospace;
                font-size: 12px;
                color: #d4d4d4;
                white-space: pre-wrap;
                word-break: break-all;
            }

            /* Recommendation Block */
            .recommendation-block {
                background: rgba(127, 92, 255, 0.1);
                border-left: 3px solid #7F5CFF;
                border-radius: 6px;
                padding: 10px;
                margin-top: 6px;
            }

            .recommendation-label {
                font-weight: 600;
                color: #7F5CFF;
                font-size: 12px;
                margin-bottom: 4px;
            }

            .recommendation-content {
                font-size: 12px;
                color: #333;
                line-height: 1.4;
            }

            .recommendation-list {
                list-style: none;
                padding-left: 0;
                margin-top: 6px;
            }

            .recommendation-list li {
                padding: 3px 0 3px 16px;
                position: relative;
                font-size: 12px;
            }

            .recommendation-list li:before {
                content: "→";
                position: absolute;
                left: 0;
                color: #7F5CFF;
            }

            /* List Block */
            .list-block {
                background: rgba(0, 0, 0, 0.03);
                border-radius: 6px;
                padding: 10px;
                margin-top: 6px;
            }

            .list-block ul {
                list-style: none;
                padding-left: 0;
                margin: 0;
            }

            .list-block li {
                padding: 3px 0 3px 16px;
                position: relative;
                font-size: 12px;
            }

            .list-block li:before {
                content: "•";
                position: absolute;
                left: 4px;
                color: #4ED1C1;
            }

            /* Link */
            .message-link {
                color: #7F5CFF;
                text-decoration: none;
                border-bottom: 1px dashed #7F5CFF;
            }

            .user-message-content .message-link {
                color: white;
                border-bottom-color: white;
            }

            /* Typing Indicator */
            .typing-indicator {
                display: flex;
                gap: 4px;
                padding: 10px;
                background: white;
                border-radius: 12px;
                border: 1px solid black;
                width: fit-content;
            }

            .typing-dot {
                width: 6px;
                height: 6px;
                border-radius: 50%;
                background: #7F5CFF;
                animation: typing 1.4s infinite;
            }

            .typing-dot:nth-child(2) { animation-delay: 0.2s; }
            .typing-dot:nth-child(3) { animation-delay: 0.4s; }

            @keyframes typing {
                0%, 60%, 100% { transform: translateY(0); }
                30% { transform: translateY(-6px); }
            }

            /* ===================== INPUT BAR (BOTTOM) ===================== */
            /* 328×48px, border-radius: 24px (pill), 1px black stroke */
            .armosa-input-container {
                width: 328px;
                height: 48px;
                background: white;
                border-radius: 24px;
                border: 1px solid black;
                display: flex;
                align-items: center;
                padding: 0 8px;
                gap: 6px;
                flex-shrink: 0;
            }

            /* Circle buttons - radius 10px (20px diameter) */
            .action-btn {
                width: 20px;
                height: 20px;
                border-radius: 50%;
                background: white;
                border: 1px solid black;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 10px;
                transition: all 0.2s;
                flex-shrink: 0;
            }

            .action-btn:hover {
                background: #f5f5f5;
            }

            .action-btn.recording {
                background: #ef4444;
                color: white;
                border-color: #ef4444;
                animation: recordPulse 1s infinite;
            }

            @keyframes recordPulse {
                0%, 100% { transform: scale(1); }
                50% { transform: scale(1.1); }
            }

            /* Text input - flexible width, 32px height */
            #armosa-input {
                flex: 1;
                height: 32px;
                border: 1px solid black;
                border-radius: 16px;
                padding: 0 12px;
                font-size: 12px;
                font-family: inherit;
                outline: none;
                resize: none;
            }

            #armosa-input:focus {
                border-color: #7F5CFF;
            }

            /* Send button - radius 14px (28px diameter), yellow fill */
            .send-btn {
                width: 28px;
                height: 28px;
                border-radius: 50%;
                background: #FFD700;
                border: 1px solid black;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                color: black;
                font-size: 12px;
                transition: all 0.2s;
                flex-shrink: 0;
            }

            .send-btn:hover:not(:disabled) {
                background: #FFC400;
            }

            .send-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }

            /* File Preview */
            .file-preview {
                display: none;
                padding: 6px 10px;
                background: #f5f5f5;
                border-radius: 6px;
                border: 1px solid black;
                font-size: 11px;
                align-items: center;
                gap: 6px;
            }

            .file-preview.active {
                display: flex;
            }

            .remove-file-btn {
                background: none;
                border: none;
                color: #ef4444;
                cursor: pointer;
                font-size: 14px;
            }

            /* ===================== RESPONSIVE ===================== */
            @media (max-width: 400px) {
                #armosa-widget {
                    width: 100%;
                    height: 100%;
                    border-radius: 0;
                    bottom: 0;
                    right: 0;
                    padding: 8px;
                }

                .armosa-header,
                .armosa-messages,
                .armosa-input-container {
                    width: 100%;
                }
            }

            /* Syntax Highlighting */
            .code-keyword { color: #569cd6; }
            .code-string { color: #ce9178; }
            .code-number { color: #b5cea8; }
            .code-function { color: #dcdcaa; }
            .code-comment { color: #6a9955; }
        `;
        
        document.head.appendChild(style);
    }

    createWidget() {
        // Create FAB (Floating Action Button) - 56px circle with gradient
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

        // Create Widget (hidden by default) - 360×720 geometric frame
        const widget = document.createElement('div');
        widget.id = 'armosa-widget';
        widget.classList.add('hidden');
        widget.innerHTML = `
            <!-- HEADER: 328×64px, border-radius: 20px -->
            <div class="armosa-header">
                <button class="close-btn" id="close-widget" title="Close">✕</button>
                <div class="armosa-logo">A</div>
                <div class="armosa-title">Ask Armosa</div>
                <div class="mode-buttons">
                    <button class="mode-btn active" data-mode="chat" title="Chat">
                        <span class="mode-btn-icon">💬</span>
                    </button>
                    <button class="mode-btn" data-mode="avatar" title="Avatar">
                        <span class="mode-btn-icon">👤</span>
                    </button>
                </div>
            </div>

            <!-- CENTRAL REGION: 328px wide, fills space -->
            <div class="armosa-messages" id="armosa-messages"></div>

            <!-- INPUT BAR: 328×48px, pill shape -->
            <div class="armosa-input-container">
                <input type="file" id="file-input" style="display: none;">
                <button class="action-btn" id="file-btn" title="Attach">+</button>
                <input type="text" id="armosa-input" placeholder="Type your message...">
                <button class="action-btn" id="voice-btn" title="Voice">🎤</button>
                <button class="send-btn" id="send-btn" title="Send">➤</button>
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
