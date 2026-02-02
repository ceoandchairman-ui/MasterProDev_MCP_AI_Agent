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
            /* Armosa Chat Widget Styles */
            #armosa-widget {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                position: fixed;
                bottom: 20px;
                right: 20px;
                width: 400px;
                height: 600px;
                background: white;
                border-radius: 16px;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.16);
                display: flex;
                flex-direction: column;
                z-index: 999999;
                overflow: hidden;
                border: 1px solid rgba(0, 0, 0, 0.1);
            }

            /* Header with Dynamic Gradient */
            .armosa-header {
                background: linear-gradient(135deg, #00C896 0%, #FFB800 40%, #2563EB 80%, #00C896 100%);
                background-size: 400% 400%;
                animation: gradientShift 15s ease infinite;
                padding: 20px;
                color: white;
                display: flex;
                flex-direction: column;
                align-items: center;
                position: relative;
                overflow: hidden;
            }

            @keyframes gradientShift {
                0% { background-position: 0% 50%; }
                50% { background-position: 100% 50%; }
                100% { background-position: 0% 50%; }
            }

            /* Logo Circle */
            .armosa-logo {
                width: 60px;
                height: 60px;
                background: white;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 28px;
                margin-bottom: 12px;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                font-weight: bold;
                color: #00C896;
            }

            .armosa-title {
                font-size: 18px;
                font-weight: 600;
                margin-bottom: 16px;
            }

            /* Mode Buttons */
            .mode-buttons {
                display: flex;
                gap: 16px;
                justify-content: center;
            }

            .mode-btn {
                width: 60px;
                height: 60px;
                border-radius: 50%;
                background: rgba(255, 255, 255, 0.2);
                border: 2px solid rgba(255, 255, 255, 0.4);
                color: white;
                cursor: pointer;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                gap: 4px;
                font-size: 12px;
                transition: all 0.3s;
                font-weight: 500;
            }

            .mode-btn:hover {
                background: rgba(255, 255, 255, 0.3);
                transform: scale(1.1);
            }

            .mode-btn.active {
                background: white;
                color: #00C896;
            }

            .mode-btn-icon {
                font-size: 24px;
            }

            /* Messages Area */
            .armosa-messages {
                flex: 1;
                overflow-y: auto;
                padding: 16px;
                background: linear-gradient(180deg, #f8f9fa 0%, white 100%);
                display: flex;
                flex-direction: column;
                gap: 12px;
            }

            .armosa-messages::-webkit-scrollbar {
                width: 6px;
            }

            .armosa-messages::-webkit-scrollbar-track {
                background: transparent;
            }

            .armosa-messages::-webkit-scrollbar-thumb {
                background: #ddd;
                border-radius: 3px;
            }

            .armosa-messages::-webkit-scrollbar-thumb:hover {
                background: #ccc;
            }

            /* Message Container */
            .message-group {
                display: flex;
                gap: 8px;
                animation: slideIn 0.3s ease;
            }

            @keyframes slideIn {
                from {
                    opacity: 0;
                    transform: translateY(10px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }

            .message-group.user {
                flex-direction: row-reverse;
                justify-content: flex-end;
            }

            .message-avatar {
                width: 32px;
                height: 32px;
                border-radius: 50%;
                background: linear-gradient(135deg, #00C896 0%, #2563EB 100%);
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 16px;
                flex-shrink: 0;
            }

            .message-group.user .message-avatar {
                background: #00C896;
            }

            /* Chat Bubble */
            .message-bubble {
                max-width: 75%;
                word-wrap: break-word;
            }

            .message-group.user .message-bubble {
                max-width: 85%;
            }

            /* Bot Message */
            .bot-message-content {
                background: white;
                border: 1px solid #e5e5e5;
                border-radius: 12px;
                padding: 12px;
                display: flex;
                flex-direction: column;
                gap: 8px;
            }

            /* User Message */
            .user-message-content {
                background: linear-gradient(135deg, #00C896 0%, #009977 100%);
                color: white;
                border-radius: 12px;
                padding: 12px;
                display: flex;
                flex-direction: column;
                gap: 8px;
            }

            /* Message Text */
            .message-text {
                line-height: 1.4;
                font-size: 14px;
            }

            /* Code Block Capsule */
            .code-block {
                background: #1e1e1e;
                border-radius: 8px;
                padding: 12px;
                overflow-x: auto;
                position: relative;
                margin-top: 8px;
            }

            .code-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 8px;
                font-size: 12px;
                color: #888;
            }

            .code-language {
                font-weight: 600;
                color: #FFB800;
            }

            .code-copy-btn {
                background: rgba(255, 184, 0, 0.2);
                border: 1px solid #FFB800;
                color: #FFB800;
                padding: 4px 8px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 12px;
                transition: all 0.2s;
            }

            .code-copy-btn:hover {
                background: rgba(255, 184, 0, 0.3);
            }

            .code-content {
                font-family: 'Courier New', monospace;
                font-size: 13px;
                color: #d4d4d4;
                white-space: pre-wrap;
                word-break: break-all;
            }

            /* Recommendation Capsule */
            .recommendation-block {
                background: linear-gradient(135deg, rgba(0, 200, 150, 0.1) 0%, rgba(37, 99, 235, 0.1) 100%);
                border-left: 3px solid #00C896;
                border-radius: 8px;
                padding: 12px;
                margin-top: 8px;
            }

            .recommendation-label {
                font-weight: 600;
                color: #00C896;
                font-size: 13px;
                margin-bottom: 6px;
                display: flex;
                align-items: center;
                gap: 4px;
            }

            .recommendation-content {
                font-size: 13px;
                color: #333;
                line-height: 1.4;
            }

            .recommendation-list {
                list-style: none;
                padding-left: 0;
                margin-top: 8px;
            }

            .recommendation-list li {
                padding: 4px 0 4px 20px;
                position: relative;
                color: #333;
                font-size: 13px;
            }

            .recommendation-list li:before {
                content: "→";
                position: absolute;
                left: 0;
                color: #00C896;
                font-weight: bold;
            }

            /* List Capsule */
            .list-block {
                background: rgba(0, 0, 0, 0.02);
                border-radius: 8px;
                padding: 12px;
                margin-top: 8px;
            }

            .list-block ul {
                list-style: none;
                padding-left: 0;
                margin: 0;
            }

            .list-block li {
                padding: 4px 0 4px 20px;
                position: relative;
                font-size: 13px;
                color: #333;
            }

            .list-block li:before {
                content: "•";
                position: absolute;
                left: 4px;
                color: #FFB800;
            }

            /* Link */
            .message-link {
                color: #2563EB;
                text-decoration: none;
                border-bottom: 1px dashed #2563EB;
                cursor: pointer;
                transition: all 0.2s;
            }

            .message-link:hover {
                color: #1E4FBD;
                border-bottom-color: #1E4FBD;
            }

            .user-message-content .message-link {
                color: white;
                border-bottom-color: white;
            }

            /* Typing Indicator */
            .typing-indicator {
                display: flex;
                gap: 4px;
                padding: 12px;
                background: white;
                border-radius: 12px;
                width: fit-content;
                border: 1px solid #e5e5e5;
            }

            .typing-dot {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #00C896;
                animation: typing 1.4s infinite;
            }

            .typing-dot:nth-child(2) {
                animation-delay: 0.2s;
            }

            .typing-dot:nth-child(3) {
                animation-delay: 0.4s;
            }

            @keyframes typing {
                0%, 60%, 100% { transform: translateY(0); }
                30% { transform: translateY(-8px); }
            }

            /* Input Area */
            .armosa-input-container {
                padding: 16px;
                background: white;
                border-top: 1px solid #e5e5e5;
                display: flex;
                gap: 8px;
                align-items: flex-end;
            }

            .input-row {
                display: flex;
                gap: 8px;
                flex: 1;
            }

            .action-btn {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background: #f0f0f0;
                border: none;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                color: #666;
                transition: all 0.2s;
                font-size: 18px;
            }

            .action-btn:hover {
                background: #e0e0e0;
                color: #00C896;
            }

            .action-btn.recording {
                background: #ef4444;
                color: white;
                animation: recordPulse 1s infinite;
            }

            @keyframes recordPulse {
                0%, 100% { transform: scale(1); }
                50% { transform: scale(1.1); }
            }

            #armosa-input {
                flex: 1;
                border: 1px solid #e5e5e5;
                border-radius: 20px;
                padding: 8px 14px;
                font-size: 13px;
                resize: none;
                max-height: 100px;
                font-family: inherit;
                outline: none;
                transition: all 0.2s;
            }

            #armosa-input:focus {
                border-color: #00C896;
                box-shadow: 0 0 0 2px rgba(0, 200, 150, 0.1);
            }

            .send-btn {
                width: 36px;
                height: 36px;
                border-radius: 50%;
                background: linear-gradient(135deg, #00C896 0%, #FFB800 50%, #2563EB 100%);
                border: none;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                transition: all 0.2s;
                flex-shrink: 0;
                font-size: 18px;
            }

            .send-btn:hover:not(:disabled) {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(0, 200, 150, 0.3);
            }

            .send-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }

            /* File Preview */
            .file-preview {
                display: none;
                padding: 8px 12px;
                background: #f0f0f0;
                border-radius: 8px;
                font-size: 12px;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 8px;
                gap: 8px;
            }

            .file-preview.active {
                display: flex;
            }

            .remove-file-btn {
                background: none;
                border: none;
                color: #ef4444;
                cursor: pointer;
                font-size: 16px;
                transition: color 0.2s;
            }

            .remove-file-btn:hover {
                color: #dc2626;
            }

            /* Responsive */
            @media (max-width: 600px) {
                #armosa-widget {
                    width: 100%;
                    height: 100%;
                    max-width: 100%;
                    max-height: 100%;
                    border-radius: 0;
                    bottom: 0;
                    right: 0;
                    position: fixed;
                }

                .message-bubble {
                    max-width: 90%;
                }

                .message-group.user .message-bubble {
                    max-width: 90%;
                }
            }

            /* Syntax Highlighting (basic) */
            .code-keyword { color: #569cd6; }
            .code-string { color: #ce9178; }
            .code-number { color: #b5cea8; }
            .code-function { color: #dcdcaa; }
            .code-comment { color: #6a9955; }
        `;
        
        document.head.appendChild(style);
    }

    createWidget() {
        const widget = document.createElement('div');
        widget.id = 'armosa-widget';
        widget.innerHTML = `
            <div class="armosa-header">
                <div class="armosa-logo">🤖</div>
                <div class="armosa-title">Ask Armosa</div>
                <div class="mode-buttons">
                    <button class="mode-btn active" data-mode="chat">
                        <span class="mode-btn-icon">💬</span>
                        <span>Chat</span>
                    </button>
                    <button class="mode-btn" data-mode="avatar">
                        <span class="mode-btn-icon">👤</span>
                        <span>Avatar</span>
                    </button>
                </div>
            </div>

            <div class="armosa-messages" id="armosa-messages"></div>

            <div class="armosa-input-container">
                <div class="input-row">
                    <button class="action-btn" id="file-btn" title="Attach file">📎</button>
                    <input type="file" id="file-input" style="display: none;">
                    <textarea id="armosa-input" placeholder="Type your message..." rows="1"></textarea>
                    <button class="action-btn" id="voice-btn" title="Voice message">🎤</button>
                </div>
                <button class="send-btn" id="send-btn">➤</button>
            </div>
        `;
        
        document.body.appendChild(widget);
        this.widget = widget;
        this.messagesContainer = widget.querySelector('#armosa-messages');
    }

    attachEventListeners() {
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
            this.widget.querySelector('.armosa-input-container').insertBefore(preview, this.widget.querySelector('.input-row'));
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
