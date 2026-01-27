/**
 * Master Pro Dev Chat Widget
 * Embeddable AI Agent Chat Interface
 */

(function() {
  'use strict';

  const MCPChat = {
    config: {
      apiUrl: 'http://localhost:8000',
      position: 'bottom-right',
      primaryColor: '#00C896',
      secondaryColor: '#6B5CE7',
      accentColor: '#FFB800',
      brandName: 'Master Pro Dev',
      welcomeMessage: 'Hi! I\'m your AI assistant. How can I help you today?',
      quickActions: [
        { icon: '📅', text: 'Check my calendar', action: 'calendar' },
        { icon: '📧', text: 'Read my emails', action: 'email' },
        { icon: '💡', text: 'Get suggestions', action: 'suggestions' }
      ]
    },

    state: {
      isOpen: false,
      isAuthenticated: false,
      authToken: null,
      conversationId: null,
      messages: [],
      isTyping: false,
      selectedFile: null,
      voiceMode: false,
      mediaRecorder: null,
      audioChunks: []
    },

    init: function(customConfig = {}) {
      try {
        // Merge custom config
        this.config = { ...this.config, ...customConfig };
        // Check if already initialized
        if (document.getElementById('mpd-chat-widget')) {
          console.warn('MCP Chat Widget already initialized');
          return;
        }
        // Create widget HTML
        this.createWidget();
        // Attach event listeners
        this.attachEventListeners();
        // Load saved token
        this.loadAuthToken();
        console.log('MCP Chat Widget initialized');
      } catch (e) {
        console.error('MCP Chat Widget failed to initialize:', e);
        alert('Chat Widget failed to load: ' + e.message);
      }
    },

    createWidget: function() {
      try {
        const widgetHTML = `
        <div id="mpd-chat-widget">
          <!-- Chat Button -->
          <button id="mpd-chat-button" aria-label="Open chat">
            <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/>
            </svg>
            <span id="mpd-chat-badge"></span>
          </button>

          <!-- Chat Window -->
          <div id="mpd-chat-window">
            <!-- Header -->
            <div id="mpd-chat-header">
              <div id="mpd-chat-header-content">
                <div id="mpd-chat-logo">
                  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path fill="#00C896" d="M12 2L2 7v10c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-10-5z"/>
                    <circle cx="12" cy="10" r="2" fill="#FFB800"/>
                    <circle cx="12" cy="14" r="1.5" fill="#FFD93D"/>
                    <circle cx="12" cy="17" r="1" fill="#6B5CE7"/>
                  </svg>
                </div>
                <div>
                  <h3 id="mpd-chat-title">${this.config.brandName}</h3>
                  <div id="mpd-chat-status">
                    <span id="mpd-status-dot"></span>
                    <span>Online</span>
                  </div>
                </div>
              </div>
              <button id="mpd-chat-close" aria-label="Close chat">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M18 6L6 18M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                </svg>
              </button>
            </div>

            <!-- Messages Area -->
            <div id="mpd-chat-messages">
              <div class="mpd-welcome">
                <div class="mpd-welcome-icon">
                  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-4h2v2h-2zm0-10h2v6h-2z"/>
                  </svg>
                </div>
                <h3>Welcome to ${this.config.brandName}!</h3>
                <p>${this.config.welcomeMessage}</p>
                <div class="mpd-quick-actions">
                  ${this.config.quickActions.map((action, index) => `
                    <button class="mpd-quick-action" data-action="${action.action}">
                      <span class="mpd-quick-action-icon">${action.icon}</span>
                      <span>${action.text}</span>
                    </button>
                  `).join('')}
                </div>
              </div>
            </div>

            <!-- Typing Indicator -->
            <div class="mpd-typing">
              <div class="mpd-typing-dots">
                <span class="mpd-typing-dot"></span>
                <span class="mpd-typing-dot"></span>
                <span class="mpd-typing-dot"></span>
              </div>
            </div>

            <!-- Input Area -->
            <div id="mpd-chat-input-container">
              <!-- File Preview -->
              <div id="mpd-file-preview" class="mpd-file-preview">
                <span id="mpd-file-name">📎 file.pdf</span>
                <button id="mpd-remove-file" aria-label="Remove file">×</button>
              </div>
              
              <!-- Input Row -->
              <div class="mpd-input-row">
                <!-- Hidden File Input -->
                <input type="file" id="mpd-file-input" accept="audio/*,video/*,image/*,.pdf,.docx,.doc,.txt" style="display: none;">
                
                <!-- Action Buttons -->
                <button id="mpd-attach-btn" class="mpd-action-btn" aria-label="Attach file" title="Attach file">
                  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" width="20" height="20">
                    <path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z" fill="currentColor"/>
                  </svg>
                </button>
                
                <button id="mpd-voice-btn" class="mpd-action-btn" aria-label="Voice message" title="Record voice">
                  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg" width="20" height="20">
                    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z" fill="currentColor"/>
                  </svg>
                </button>
                
                <!-- Text Input -->
                <textarea 
                  id="mpd-chat-input" 
                  placeholder="Type your message..."
                  rows="1"
                  maxlength="1000"
                ></textarea>
                
                <!-- Send Button -->
                <button id="mpd-chat-send" aria-label="Send message">
                  <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                  </svg>
                </button>
              </div>
            </div>
          </div>
        </div>
      `;

        document.body.insertAdjacentHTML('beforeend', widgetHTML);
      } catch (e) {
        console.error('Failed to create chat widget HTML:', e);
        alert('Failed to create chat widget: ' + e.message);
      }
    },

    attachEventListeners: function() {
      const chatButton = document.getElementById('mpd-chat-button');
      const chatClose = document.getElementById('mpd-chat-close');
      const chatSend = document.getElementById('mpd-chat-send');
      const chatInput = document.getElementById('mpd-chat-input');
      const quickActions = document.querySelectorAll('.mpd-quick-action');
      
      // File upload elements
      const attachButton = document.getElementById('mpd-attach-btn');
      const fileInput = document.getElementById('mpd-file-input');
      const removeFileButton = document.getElementById('mpd-remove-file');
      
      // Voice button
      const voiceButton = document.getElementById('mpd-voice-btn');

      chatButton.addEventListener('click', () => this.toggleChat());
      chatClose.addEventListener('click', () => this.toggleChat());
      chatSend.addEventListener('click', () => this.sendMessage());
      
      chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.sendMessage();
        }
      });

      chatInput.addEventListener('input', () => this.autoResize(chatInput));

      quickActions.forEach(btn => {
        btn.addEventListener('click', (e) => {
          const action = e.currentTarget.dataset.action;
          this.handleQuickAction(action);
        });
      });
      
      // File upload handlers
      if (attachButton) {
        attachButton.addEventListener('click', () => fileInput.click());
      }
      
      if (fileInput) {
        fileInput.addEventListener('change', (e) => this.handleFileSelect(e));
      }
      
      if (removeFileButton) {
        removeFileButton.addEventListener('click', () => this.removeFile());
      }
      
      // Voice recording handler
      if (voiceButton) {
        voiceButton.addEventListener('click', () => this.toggleRecording());
      }
    },
    
    handleFileSelect: function(event) {
      const file = event.target.files[0];
      if (!file) return;
      
      // Check file size (max 25MB)
      if (file.size > 25 * 1024 * 1024) {
        alert('File too large. Maximum size is 25MB.');
        return;
      }
      
      // Store file reference
      this.state.selectedFile = file;
      
      // Show file preview
      const filePreview = document.getElementById('mpd-file-preview');
      const fileName = document.getElementById('mpd-file-name');
      
      if (filePreview && fileName) {
        fileName.textContent = `📎 ${file.name}`;
        filePreview.classList.add('show');
      }
    },
    
    removeFile: function() {
      const fileInput = document.getElementById('mpd-file-input');
      const filePreview = document.getElementById('mpd-file-preview');
      
      if (fileInput) fileInput.value = '';
      if (filePreview) filePreview.classList.remove('show');
      
      this.state.selectedFile = null;
    },
    
    switchMode: function(mode) {
      const textModeBtn = document.getElementById('text-mode-btn');
      const voiceModeBtn = document.getElementById('voice-mode-btn');
      const textContainer = document.getElementById('text-mode-container');
      const voiceContainer = document.getElementById('voice-mode-container');
      
      if (mode === 'voice') {
        this.state.voiceMode = true;
        textModeBtn.classList.remove('active');
        voiceModeBtn.classList.add('active');
        textContainer.style.display = 'none';
        voiceContainer.style.display = 'block';
      } else {
        this.state.voiceMode = false;
        voiceModeBtn.classList.remove('active');
        textModeBtn.classList.add('active');
        voiceContainer.style.display = 'none';
        textContainer.style.display = 'block';
      }
    },
    
    setVoiceStatus: function(text, emoji = '😊') {
      const status = document.getElementById('voice-status');
      const avatarState = document.getElementById('avatar-state');
      
      if (status) status.textContent = text;
      if (avatarState) avatarState.textContent = emoji;
    },
    
    toggleRecording: async function() {
      const recordButton = document.getElementById('mpd-voice-btn');
      
      if (!this.state.mediaRecorder || this.state.mediaRecorder.state === 'inactive') {
        try {
          // Request microphone access
          const stream = await navigator.mediaDevices.getUserMedia({ 
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true
            } 
          });
          
          this.state.mediaRecorder = new MediaRecorder(stream, {
            mimeType: 'audio/webm;codecs=opus'
          });
          this.state.audioChunks = [];
          
          this.state.mediaRecorder.ondataavailable = (event) => {
            if (event.data.size > 0) {
              this.state.audioChunks.push(event.data);
            }
          };
          
          this.state.mediaRecorder.onstop = async () => {
            await this.processVoiceRecording();
          };
          
          // Start recording
          this.state.mediaRecorder.start();
          recordButton.classList.add('recording');
          this.setVoiceStatus('Recording... (click to stop)', '🎤');
          
        } catch (error) {
          console.error('Microphone access error:', error);
          alert('Microphone access denied. Please allow microphone access.');
        }
        
      } else if (this.state.mediaRecorder.state === 'recording') {
        // Stop recording
        this.state.mediaRecorder.stop();
        this.state.mediaRecorder.stream.getTracks().forEach(track => track.stop());
        recordButton.classList.remove('recording');
        this.setVoiceStatus('Processing...', '⌛');
      }
    },
    
    processVoiceRecording: async function() {
      try {
        const audioBlob = new Blob(this.state.audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        
        this.setVoiceStatus('Processing your voice...', '🤔');
        
        const response = await fetch(`${this.config.apiUrl}/voice`, {
          method: 'POST',
          body: formData
        });
        
        if (!response.ok) {
          throw new Error(`Server error: ${response.status}`);
        }
        
        // Check content type - could be audio or JSON (for browser TTS fallback)
        const contentType = response.headers.get('Content-Type');
        const transcription = document.getElementById('voice-transcription');
        
        if (contentType && contentType.includes('application/json')) {
          // Server returned JSON - use browser TTS
          const data = await response.json();
          
          if (data.transcription && transcription) {
            transcription.textContent = `You said: "${data.transcription}"`;
            transcription.style.display = 'block';
          }
          
          // Add messages to chat
          if (data.transcription) {
            this.addMessage(data.transcription, true);
          }
          if (data.response) {
            this.addMessage(data.response, false);
          }
          
          // Use browser's speechSynthesis for TTS
          if (data.use_browser_tts && data.response && 'speechSynthesis' in window) {
            const utterance = new SpeechSynthesisUtterance(data.response);
            utterance.lang = 'en-US';
            utterance.rate = 1.0;
            
            this.setVoiceStatus('Speaking...', '🗣️');
            utterance.onend = () => {
              this.setVoiceStatus('Click the microphone to speak', '😊');
              if (transcription) {
                setTimeout(() => { transcription.style.display = 'none'; }, 3000);
              }
            };
            
            speechSynthesis.speak(utterance);
          } else {
            this.setVoiceStatus('Click the microphone to speak', '😊');
          }
        } else {
          // Server returned audio
          const heard = response.headers.get('X-Transcription');
          
          if (heard && transcription) {
            transcription.textContent = `You said: "${heard}"`;
            transcription.style.display = 'block';
          }
          
          // Play response audio
          const audioResponseBlob = await response.blob();
          const audioUrl = URL.createObjectURL(audioResponseBlob);
          const audio = new Audio(audioUrl);
          
          this.setVoiceStatus('Speaking...', '🗣️');
          audio.play();
          
          audio.onended = () => {
            this.setVoiceStatus('Click the microphone to speak', '😊');
            URL.revokeObjectURL(audioUrl);
            if (transcription) {
              setTimeout(() => {
                transcription.style.display = 'none';
              }, 3000);
            }
          };
          
          audio.onerror = () => {
            this.setVoiceStatus('Click the microphone to speak', '😊');
            alert('Could not play audio response');
          };
        }
        
      } catch (error) {
        console.error('Voice chat error:', error);
        this.setVoiceStatus('Click the microphone to speak', '😊');
        alert(error.message || 'Voice processing failed');
      }
    },

    toggleChat: function() {
      const chatWindow = document.getElementById('mpd-chat-window');
      this.state.isOpen = !this.state.isOpen;
      
      if (this.state.isOpen) {
        chatWindow.classList.add('open');
        document.getElementById('mpd-chat-input').focus();
        this.clearNotifications();
      } else {
        chatWindow.classList.remove('open');
      }
    },

    autoResize: function(textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    },

    sendMessage: async function() {
      const input = document.getElementById('mpd-chat-input');
      const message = input.value.trim();
      const file = this.state.selectedFile;
      
      if ((!message && !file) || this.state.isTyping) return;

      // Add user message to UI
      const displayMessage = file ? `${message}\n📎 ${file.name}` : message;
      this.addMessage(displayMessage, 'user');
      input.value = '';
      input.style.height = 'auto';

      // Show typing indicator
      this.showTyping(true);

      try {
        // Prepare form data
        const formData = new FormData();
        formData.append('message', message || 'Please analyze this file');
        if (this.state.conversationId) {
          formData.append('conversation_id', this.state.conversationId);
        }
        if (file) {
          formData.append('file', file);
        }

        // Send message to API
        const response = await fetch(`${this.config.apiUrl}/chat`, {
          method: 'POST',
          headers: this.state.authToken ? {
            'Authorization': `Bearer ${this.state.authToken}`
          } : {},
          body: formData
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        
        // Update conversation ID
        if (data.conversation_id) {
          this.state.conversationId = data.conversation_id;
        }

        // Add bot response
        this.showTyping(false);
        this.addMessage(data.response, 'bot');
        
        // Clear file selection
        this.removeFile();

      } catch (error) {
        console.error('Chat error:', error);
        this.showTyping(false);
        this.addMessage('Sorry, I encountered an error. Please try again.', 'bot', true);
        this.removeFile();
      }
    },

    authenticate: async function() {
      try {
        // Check for saved token
        const savedToken = localStorage.getItem('mcp_auth_token');
        if (savedToken) {
          this.state.authToken = savedToken;
          this.state.isAuthenticated = true;
          return;
        }

        // Perform guest authentication
        const response = await fetch(`${this.config.apiUrl}/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: 'guest_' + Date.now() + '@example.com',
            password: 'guest'
          })
        });

        if (!response.ok) throw new Error('Authentication failed');

        const data = await response.json();
        this.state.authToken = data.access_token;
        this.state.isAuthenticated = true;
        
        // Save token
        localStorage.setItem('mcp_auth_token', data.access_token);

      } catch (error) {
        console.error('Authentication error:', error);
        throw error;
      }
    },

    loadAuthToken: function() {
      const savedToken = localStorage.getItem('mcp_auth_token');
      if (savedToken) {
        this.state.authToken = savedToken;
        this.state.isAuthenticated = true;
      }
    },

    addMessage: function(text, sender, isError = false) {
      const messagesContainer = document.getElementById('mpd-chat-messages');
      const welcome = messagesContainer.querySelector('.mpd-welcome');
      
      // Remove welcome message on first user message
      if (welcome && sender === 'user') {
        welcome.remove();
      }

      const messageHTML = `
        <div class="mpd-message ${sender}">
          <div class="mpd-message-avatar">
            ${sender === 'bot' ? '🤖' : '👤'}
          </div>
          <div class="mpd-message-content ${isError ? 'mpd-error' : ''}">
            ${this.escapeHtml(text)}
            <div class="mpd-message-time">${this.formatTime(new Date())}</div>
          </div>
        </div>
      `;

      messagesContainer.insertAdjacentHTML('beforeend', messageHTML);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;

      // Store message
      this.state.messages.push({ text, sender, timestamp: new Date() });

      // Show notification if chat is closed
      if (!this.state.isOpen && sender === 'bot') {
        this.showNotification();
      }
    },

    showTyping: function(show) {
      const typing = document.querySelector('.mpd-typing');
      this.state.isTyping = show;
      
      if (show) {
        typing.classList.add('show');
      } else {
        typing.classList.remove('show');
      }
    },

    handleQuickAction: function(action) {
      const actions = {
        calendar: 'Show me my calendar for today',
        email: 'Check my recent emails',
        suggestions: 'Give me some suggestions on what you can help with'
      };

      const input = document.getElementById('mpd-chat-input');
      input.value = actions[action] || '';
      this.sendMessage();
    },

    showNotification: function() {
      const badge = document.getElementById('mpd-chat-badge');
      const count = parseInt(badge.textContent || '0') + 1;
      badge.textContent = count;
      badge.classList.add('show');
    },

    clearNotifications: function() {
      const badge = document.getElementById('mpd-chat-badge');
      badge.textContent = '';
      badge.classList.remove('show');
    },

    formatTime: function(date) {
      return date.toLocaleTimeString('en-US', { 
        hour: 'numeric', 
        minute: '2-digit',
        hour12: true 
      });
    },

    escapeHtml: function(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }
  };

  // Expose to global scope
  window.MCPChat = MCPChat;

  // Auto-initialize if data attribute is present
  const script = document.currentScript;
  if (script && script.hasAttribute('data-auto-init')) {
    document.addEventListener('DOMContentLoaded', () => {
      MCPChat.init();
    });
  }

})();
