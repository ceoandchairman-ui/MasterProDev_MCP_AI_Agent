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
      isTyping: false
    },

    init: function(customConfig = {}) {
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
    },

    createWidget: function() {
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
              <textarea 
                id="mpd-chat-input" 
                placeholder="Type your message..."
                rows="1"
                maxlength="1000"
              ></textarea>
              <button id="mpd-chat-send" aria-label="Send message">
                <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      `;

      document.body.insertAdjacentHTML('beforeend', widgetHTML);
    },

    attachEventListeners: function() {
      const chatButton = document.getElementById('mpd-chat-button');
      const chatClose = document.getElementById('mpd-chat-close');
      const chatSend = document.getElementById('mpd-chat-send');
      const chatInput = document.getElementById('mpd-chat-input');
      const quickActions = document.querySelectorAll('.mpd-quick-action');

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
      
      if (!message || this.state.isTyping) return;

      // Add user message to UI
      this.addMessage(message, 'user');
      input.value = '';
      input.style.height = 'auto';

      // Show typing indicator
      this.showTyping(true);

      try {
        // Check authentication
        if (!this.state.isAuthenticated) {
          await this.authenticate();
        }

        // Send message to API
        const response = await fetch(`${this.config.apiUrl}/chat`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${this.state.authToken}`
          },
          body: JSON.stringify({
            message: message,
            conversation_id: this.state.conversationId
          })
        });

        if (!response.ok) {
          if (response.status === 401) {
            // Token expired, re-authenticate
            this.state.isAuthenticated = false;
            await this.authenticate();
            return this.sendMessage(); // Retry
          }
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

      } catch (error) {
        console.error('Chat error:', error);
        this.showTyping(false);
        this.addMessage('Sorry, I encountered an error. Please try again.', 'bot', true);
      }
    },

    authenticate: async function() {
      try {
        // Check for saved token
        const savedToken = localStorage.getItem('mpd_auth_token');
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
        localStorage.setItem('mpd_auth_token', data.access_token);

      } catch (error) {
        console.error('Authentication error:', error);
        throw error;
      }
    },

    loadAuthToken: function() {
      const savedToken = localStorage.getItem('mpd_auth_token');
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
