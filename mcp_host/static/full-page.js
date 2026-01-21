/**
 * MasterProDev AI Agent - Full Page Chat
 */

(function() {
    'use strict';

    const API_URL = window.location.origin;
    
    // State
    let currentMode = 'text';
    let isRecording = false;
    let mediaRecorder = null;
    let audioChunks = [];
    let selectedFile = null;
    let conversationId = null;
    let authToken = null;
    let isAuthenticated = false;

    // Elements
    const chatMessages = document.getElementById('chat-messages');
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const attachBtn = document.getElementById('attach-btn');
    const voiceBtn = document.getElementById('voice-btn');
    const fileInput = document.getElementById('file-input');
    const filePreview = document.getElementById('file-preview');
    const fileName = document.getElementById('file-name');
    const removeFileBtn = document.getElementById('remove-file');
    const typingIndicator = document.getElementById('typing-indicator');
    const avatar = document.getElementById('avatar');
    const avatarContainer = document.getElementById('avatar-container');
    const avatarStatus = document.getElementById('avatar-status');
    const modeBtns = document.querySelectorAll('.mode-btn');

    // Initialize
    async function init() {
        await authenticate();
        attachEventListeners();
    }

    // Authentication
    async function authenticate() {
        try {
            const savedToken = localStorage.getItem('mcp_auth_token');
            if (savedToken) {
                authToken = savedToken;
                isAuthenticated = true;
                return;
            }

            const response = await fetch(`${API_URL}/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email: 'guest_' + Date.now() + '@example.com',
                    password: 'guest'
                })
            });

            if (!response.ok) throw new Error('Authentication failed');

            const data = await response.json();
            authToken = data.access_token;
            isAuthenticated = true;
            localStorage.setItem('mcp_auth_token', authToken);
        } catch (error) {
            console.error('Auth error:', error);
            addMessage('Authentication failed. Please refresh the page.', 'bot');
        }
    }

    // Event Listeners
    function attachEventListeners() {
        // Mode toggle
        modeBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                modeBtns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentMode = btn.dataset.mode;
                
                if (currentMode === 'voice') {
                    avatarContainer.classList.add('active');
                    avatar.className = 'avatar idle';
                    avatarStatus.textContent = 'Click the microphone to speak';
                } else {
                    avatarContainer.classList.remove('active');
                }
            });
        });

        // Auto-resize textarea
        chatInput.addEventListener('input', () => {
            chatInput.style.height = 'auto';
            chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + 'px';
        });

        // Send on Enter
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        sendBtn.addEventListener('click', sendMessage);

        // File upload
        attachBtn.addEventListener('click', () => fileInput.click());
        
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                if (file.size > 25 * 1024 * 1024) {
                    alert('File too large. Maximum size is 25MB.');
                    return;
                }
                selectedFile = file;
                fileName.textContent = `📎 ${file.name}`;
                filePreview.classList.add('active');
            }
        });

        removeFileBtn.addEventListener('click', () => {
            selectedFile = null;
            fileInput.value = '';
            filePreview.classList.remove('active');
        });

        // Voice recording
        voiceBtn.addEventListener('click', toggleRecording);
    }

    // Voice Recording
    async function toggleRecording() {
        if (!isRecording) {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                mediaRecorder = new MediaRecorder(stream);
                audioChunks = [];

                mediaRecorder.ondataavailable = (e) => audioChunks.push(e.data);
                mediaRecorder.onstop = () => sendVoiceMessage();

                mediaRecorder.start();
                isRecording = true;
                voiceBtn.classList.add('recording');
                avatar.className = 'avatar listening';
                avatarStatus.textContent = 'Recording... Click to stop';
            } catch (error) {
                alert('Microphone access denied');
            }
        } else {
            mediaRecorder.stop();
            mediaRecorder.stream.getTracks().forEach(track => track.stop());
            isRecording = false;
            voiceBtn.classList.remove('recording');
        }
    }

    async function sendVoiceMessage() {
        avatar.className = 'avatar thinking';
        avatarStatus.textContent = 'Processing...';
        
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');

        try {
            if (!isAuthenticated) await authenticate();

            typingIndicator.classList.add('active');
            scrollToBottom();

            const response = await fetch(`${API_URL}/voice`, {
                method: 'POST',
                headers: authToken ? { 'Authorization': `Bearer ${authToken}` } : {},
                body: formData
            });

            if (!response.ok) {
                if (response.status === 401) {
                    isAuthenticated = false;
                    localStorage.removeItem('mcp_auth_token');
                    await authenticate();
                    return sendVoiceMessage();
                }
                throw new Error('Voice request failed');
            }

            const audioResponse = await response.blob();
            const transcription = response.headers.get('X-Transcription');
            const responseText = response.headers.get('X-Response-Text');

            // Show user transcription
            if (transcription) {
                addMessage(transcription, 'user');
            }

            // Show bot response text
            if (responseText) {
                addMessage(decodeURIComponent(responseText), 'bot');
            }

            // Play audio response
            const audioUrl = URL.createObjectURL(audioResponse);
            const audio = new Audio(audioUrl);
            avatar.className = 'avatar speaking';
            avatarStatus.textContent = 'Speaking...';
            audio.play();
            
            audio.onended = () => {
                avatar.className = 'avatar idle';
                avatarStatus.textContent = 'Click the microphone to speak';
                URL.revokeObjectURL(audioUrl);
            };

        } catch (error) {
            console.error('Voice error:', error);
            addMessage('Sorry, voice processing failed. Please try again.', 'bot');
            avatar.className = 'avatar idle';
            avatarStatus.textContent = 'Click the microphone to speak';
        } finally {
            typingIndicator.classList.remove('active');
        }
    }

    // Send Text Message
    async function sendMessage() {
        const message = chatInput.value.trim();
        if (!message && !selectedFile) return;

        const displayMessage = selectedFile ? `${message}\n📎 ${selectedFile.name}` : message;
        addMessage(displayMessage, 'user');
        chatInput.value = '';
        chatInput.style.height = 'auto';

        typingIndicator.classList.add('active');
        scrollToBottom();

        const formData = new FormData();
        formData.append('message', message || 'Please analyze this file');
        if (conversationId) formData.append('conversation_id', conversationId);
        if (selectedFile) formData.append('file', selectedFile);

        try {
            if (!isAuthenticated) await authenticate();

            const response = await fetch(`${API_URL}/chat`, {
                method: 'POST',
                headers: authToken ? { 'Authorization': `Bearer ${authToken}` } : {},
                body: formData
            });

            if (!response.ok) {
                if (response.status === 401) {
                    isAuthenticated = false;
                    localStorage.removeItem('mcp_auth_token');
                    await authenticate();
                    return sendMessage();
                }
                throw new Error('Chat request failed');
            }

            const data = await response.json();
            conversationId = data.conversation_id;
            addMessage(data.response, 'bot');

            if (selectedFile) {
                selectedFile = null;
                fileInput.value = '';
                filePreview.classList.remove('active');
            }

        } catch (error) {
            console.error('Chat error:', error);
            addMessage('Sorry, something went wrong. Please try again.', 'bot');
        } finally {
            typingIndicator.classList.remove('active');
        }
    }

    // Add Message to UI
    function addMessage(text, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}`;
        
        const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        
        messageDiv.innerHTML = `
            <div class="message-avatar">${sender === 'bot' ? '🤖' : '👤'}</div>
            <div class="message-content">
                <p style="white-space: pre-wrap;">${escapeHtml(text)}</p>
                <div class="message-time">${time}</div>
            </div>
        `;
        
        chatMessages.insertBefore(messageDiv, typingIndicator);
        scrollToBottom();
    }

    function scrollToBottom() {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
