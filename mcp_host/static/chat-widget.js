/**
 * Master Pro Dev Chat Widget
 * Embeddable AI Agent Chat Interface
 */

// === 3D Avatar/Avatar Gallery Imports (via CDN) ===
const THREE_CDN = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
const GLTFLoader_CDN = 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js';
const OrbitControls_CDN = 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/controls/OrbitControls.js';

// Viseme mapping for ReadyPlayer.me avatars (Oculus visemes)
const VISEME_NAMES = [
    'viseme_sil',   // 0: Silence
    'viseme_PP',    // 1: P, B, M
    'viseme_FF',    // 2: F, V  
    'viseme_TH',    // 3: TH
    'viseme_DD',    // 4: T, D
    'viseme_kk',    // 5: K, G
    'viseme_CH',    // 6: CH, J, SH
    'viseme_SS',    // 7: S, Z
    'viseme_nn',    // 8: N, L
    'viseme_RR',    // 9: R
    'viseme_aa',    // 10: A
    'viseme_E',     // 11: E
    'viseme_I',     // 12: I
    'viseme_O',     // 13: O
    'viseme_U'      // 14: U
];

// Global avatar gallery
const AVATAR_GALLERY = [
  {
    id: 'businesswoman',
    name: 'Business Woman',
    description: 'Professional, realistic business woman avatar',
    url: 'https://models.readyplayer.me/64bfa15f0e72c63d7c3934a6.glb?morphTargets=ARKit,Oculus+Visemes&textureAtlas=1024',
    thumbnail: '👩‍💼',
    gender: 'female'
  },
  {
    id: 'businessman',
    name: 'Business Man',
    description: 'Professional, realistic business man avatar',
    url: 'https://models.readyplayer.me/6479c5f82e7c2c3d3c2b8f19.glb?morphTargets=ARKit,Oculus+Visemes&textureAtlas=1024',
    thumbnail: '👨‍💼',
    gender: 'male'
  },
  {
    id: 'supportwoman',
    name: 'Support Agent (F)',
    description: 'Friendly female support agent',
    url: 'https://models.readyplayer.me/6479c67a2e7c2c3d3c2b8f1a.glb?morphTargets=ARKit,Oculus+Visemes&textureAtlas=1024',
    thumbnail: '👩‍🦰',
    gender: 'female'
  },
  {
    id: 'supportman',
    name: 'Support Agent (M)',
    description: 'Helpful male support agent',
    url: 'https://models.readyplayer.me/6479c6c82e7c2c3d3c2b8f1b.glb?morphTargets=ARKit,Oculus+Visemes&textureAtlas=1024',
    thumbnail: '👨‍🦱',
    gender: 'male'
  }
];

// Text-to-phoneme mapping (approximate)
const CHAR_TO_VISEME = {
    'a': 'viseme_aa', 'à': 'viseme_aa', 'á': 'viseme_aa',
    'e': 'viseme_E', 'è': 'viseme_E', 'é': 'viseme_E',
    'i': 'viseme_I', 'ì': 'viseme_I', 'í': 'viseme_I', 'y': 'viseme_I',
    'o': 'viseme_O', 'ò': 'viseme_O', 'ó': 'viseme_O',
    'u': 'viseme_U', 'ù': 'viseme_U', 'ú': 'viseme_U', 'w': 'viseme_U',
    'p': 'viseme_PP', 'b': 'viseme_PP', 'm': 'viseme_PP',
    'f': 'viseme_FF', 'v': 'viseme_FF',
    't': 'viseme_DD', 'd': 'viseme_DD',
    'k': 'viseme_kk', 'g': 'viseme_kk', 'c': 'viseme_kk', 'q': 'viseme_kk',
    's': 'viseme_SS', 'z': 'viseme_SS', 'x': 'viseme_SS',
    'n': 'viseme_nn', 'l': 'viseme_nn',
    'r': 'viseme_RR',
    'j': 'viseme_CH', 'h': 'viseme_CH',
    ' ': 'viseme_sil', '.': 'viseme_sil', ',': 'viseme_sil', '!': 'viseme_sil', '?': 'viseme_sil'
};

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
      audioChunks: [],
      lipSyncInterval: null,
      currentViseme: 'viseme_sil',
      targetViseme: 'viseme_sil',
      visemeBlendFactor: 0,
      mouthMorphTarget: null,
      visemeInfluences: {},
      avatar3D: null,
      mixer: null,
      clock: null
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
        
        // Initialize lip sync
        this.initLipSync();
        
        // Dynamically load three.js dependencies and setup avatar
        this.loadThreeJSDeps().then(() => {
          this.setupAvatarGallery();
        });
        
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

    // Loads three.js and its loaders from CDN if not already present
    loadThreeJSDeps: async function() {
      if (!window.THREE) {
        await import(THREE_CDN);
      }
      if (!window.THREE.GLTFLoader) {
        await import(GLTFLoader_CDN);
      }
      if (!window.THREE.OrbitControls) {
        await import(OrbitControls_CDN);
      }
    },

    initLipSync: function() {
      this.state.lipSyncInterval = null;
      this.state.currentViseme = 'viseme_sil';
      this.state.targetViseme = 'viseme_sil';
      this.state.visemeBlendFactor = 0;
    },
    // SINGLE setupAvatarGallery function that uses global AVATAR_GALLERY
    setupAvatarGallery: function() {
      // Insert avatar selector UI
      const selectorHTML = `
        <div class="mpd-avatar-selector" id="mpd-avatar-selector">
          <button class="mpd-avatar-selector-toggle" id="mpd-avatar-selector-toggle" title="Change Avatar">
            👤 Change Avatar
          </button>
          <div class="mpd-avatar-selector-dropdown" id="mpd-avatar-selector-dropdown">
            <div class="mpd-avatar-selector-title">Choose Your Assistant</div>
            ${AVATAR_GALLERY.map(av => `
              <div class="mpd-avatar-option" data-avatar-id="${av.id}">
                <span class="mpd-avatar-thumb">${av.thumbnail}</span>
                <div class="mpd-avatar-info">
                  <div class="mpd-avatar-name">${av.name}</div>
                  <div class="mpd-avatar-desc">${av.description}</div>
                </div>
              </div>
            `).join('')}
          </div>
        </div>
      `;
      
      const selectorContainer = document.getElementById('mpd-avatar-selector-container');
      if (selectorContainer) selectorContainer.innerHTML = selectorHTML;

      // Avatar selector toggle
      const toggle = document.getElementById('mpd-avatar-selector-toggle');
      const dropdown = document.getElementById('mpd-avatar-selector-dropdown');
      if (toggle && dropdown) {
        toggle.addEventListener('click', (e) => {
          e.stopPropagation();
          dropdown.classList.toggle('show');
        });
        document.addEventListener('click', () => dropdown.classList.remove('show'));
      }

      // Avatar selection logic
      document.querySelectorAll('.mpd-avatar-option').forEach(option => {
        option.addEventListener('click', (e) => {
          e.stopPropagation();
          const avatarId = option.dataset.avatarId;
          localStorage.setItem('selectedAvatar', avatarId);
          this.load3DAvatar(avatarId); // Remove AVATAR_GALLERY parameter - use global
          dropdown.classList.remove('show');
        });
      });

      // Load initial avatar
      const savedAvatar = localStorage.getItem('selectedAvatar') || 'businesswoman';
      this.load3DAvatar(savedAvatar); // Remove AVATAR_GALLERY parameter - use global
    },
    // Fixed load3DAvatar function that uses global AVATAR_GALLERY
    load3DAvatar: function(avatarId) {
      const avatarData = AVATAR_GALLERY.find(a => a.id === avatarId) || AVATAR_GALLERY[0];
      const container = document.getElementById('mpd-avatar-3d-container');
      const canvas = document.getElementById('mpd-avatar-canvas');
      const status = document.getElementById('mpd-avatar-3d-status');
      
      if (!container || !canvas) return;
      
      container.style.display = 'block';
      status.textContent = `Loading ${avatarData.name}...`;

      // Genie-style pop-out effect
      container.classList.add('mpd-genie-pop');
      setTimeout(() => container.classList.remove('mpd-genie-pop'), 800);

      // Remove previous renderer if any
      if (window.mpdAvatarRenderer && window.mpdAvatarRenderer.dispose) {
        window.mpdAvatarRenderer.dispose();
      }
      
      canvas.width = container.clientWidth || 320;
      canvas.height = container.clientHeight || 320;

      // Setup three.js scene
      const THREE = window.THREE;
      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x1a1a2e);
      const camera = new THREE.PerspectiveCamera(45, canvas.width / canvas.height, 0.1, 100);
      camera.position.set(0, 1.5, 2);
      const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
      renderer.setSize(canvas.width, canvas.height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      
      // Lighting
      scene.add(new THREE.AmbientLight(0xffffff, 0.6));
      const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
      dirLight.position.set(5, 10, 7.5);
      scene.add(dirLight);
      
      // Controls
      const controls = new window.THREE.OrbitControls(camera, canvas);
      controls.target.set(0, 1.2, 0);
      controls.enableDamping = true;
      controls.dampingFactor = 0.05;
      controls.minDistance = 1;
      controls.maxDistance = 5;
      controls.update();
      
      // Load avatar model
      const self = this;
      const loader = new window.THREE.GLTFLoader();
      loader.load(
        avatarData.url,
        (gltf) => {
          const avatar3D = gltf.scene;
          avatar3D.position.set(0, 0, 0);
          avatar3D.scale.set(1, 1, 1);
          scene.add(avatar3D);
          
          // Store avatar for lip sync
          self.state.avatar3D = avatar3D;
          
          // Find mesh with morph targets for lip sync
          avatar3D.traverse((child) => {
            if (child.isMesh && child.morphTargetInfluences && child.morphTargetDictionary) {
              self.state.mouthMorphTarget = child;
              
              // Map all viseme morph targets
              for (const visemeName of VISEME_NAMES) {
                if (child.morphTargetDictionary[visemeName] !== undefined) {
                  self.state.visemeInfluences[visemeName] = child.morphTargetDictionary[visemeName];
                }
              }
              console.log('Found viseme morph targets:', Object.keys(self.state.visemeInfluences));
            }
          });
          
          // Setup animations if available
          if (gltf.animations && gltf.animations.length > 0) {
            self.state.mixer = new window.THREE.AnimationMixer(avatar3D);
            const idleAction = self.state.mixer.clipAction(gltf.animations[0]);
            idleAction.play();
            self.state.clock = new window.THREE.Clock();
          }
          
          status.textContent = `${avatarData.name} - Ready`;
          
          // Animation loop with lip sync
          function animate() {
            requestAnimationFrame(animate);
            
            // Update mixer for animations
            if (self.state.mixer && self.state.clock) {
              const delta = self.state.clock.getDelta();
              self.state.mixer.update(delta);
            }
            
            // Update viseme blending
            self.state.visemeBlendFactor = Math.min(1, self.state.visemeBlendFactor + 0.15);
            
            // Apply visemes to morph targets
            if (self.state.mouthMorphTarget && Object.keys(self.state.visemeInfluences).length > 0) {
              for (const visemeName of VISEME_NAMES) {
                if (self.state.visemeInfluences[visemeName] !== undefined) {
                  const index = self.state.visemeInfluences[visemeName];
                  const currentValue = self.state.mouthMorphTarget.morphTargetInfluences[index];
                  
                  if (visemeName === self.state.targetViseme) {
                    // Blend towards target viseme
                    const targetValue = 0.7;
                    self.state.mouthMorphTarget.morphTargetInfluences[index] = 
                      currentValue + (targetValue - currentValue) * self.state.visemeBlendFactor;
                  } else {
                    // Decay other visemes
                    self.state.mouthMorphTarget.morphTargetInfluences[index] = currentValue * 0.85;
                  }
                }
              }
            }
            
            controls.update();
            renderer.render(scene, camera);
          }
          animate();
        },
        undefined,
        (error) => {
          status.textContent = 'Failed to load avatar.';
          console.error('Avatar load error:', error);
        }
      );
      window.mpdAvatarRenderer = renderer;
    },

    textToVisemes: function(text) {
      const visemes = [];
      const words = text.toLowerCase().split(/\s+/);
      
      for (const word of words) {
        for (let i = 0; i < word.length; i++) {
          const char = word[i];
          
          // Check for digraphs (th, ch, sh)
          if (i < word.length - 1) {
            const digraph = char + word[i + 1];
            if (digraph === 'th') {
              visemes.push('viseme_TH');
              i++;
              continue;
            } else if (digraph === 'ch' || digraph === 'sh') {
              visemes.push('viseme_CH');
              i++;
              continue;
            }
          }
          
          // Single character mapping
          const viseme = CHAR_TO_VISEME[char] || 'viseme_sil';
          visemes.push(viseme);
        }
        // Add silence between words
        visemes.push('viseme_sil');
      }
      
      return visemes;
    },

    startTextLipSync: function(text, durationMs) {
      this.stopLipSync();
      
      const visemes = this.textToVisemes(text);
      if (visemes.length === 0) return;
      
      // Calculate timing - spread visemes over speech duration
      const msPerViseme = durationMs / visemes.length;
      let visemeIndex = 0;
      
      this.state.lipSyncInterval = setInterval(() => {
        if (visemeIndex >= visemes.length) {
          this.stopLipSync();
          return;
        }
        
        this.state.targetViseme = visemes[visemeIndex];
        this.state.visemeBlendFactor = 0;
        visemeIndex++;
      }, msPerViseme);
    },

    stopLipSync: function() {
      if (this.state.lipSyncInterval) {
        clearInterval(this.state.lipSyncInterval);
        this.state.lipSyncInterval = null;
      }
      this.state.targetViseme = 'viseme_sil';
      this.state.visemeBlendFactor = 0;
      
      // Reset all visemes
      if (this.state.mouthMorphTarget && Object.keys(this.state.visemeInfluences).length > 0) {
        for (const visemeName of VISEME_NAMES) {
          if (this.state.visemeInfluences[visemeName] !== undefined) {
            const index = this.state.visemeInfluences[visemeName];
            this.state.mouthMorphTarget.morphTargetInfluences[index] = 0;
          }
        }
      }
    },

    speakText: function(text) {
      // Cancel any ongoing speech
      if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
      this.stopLipSync();
      
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = 'en-US';
      utterance.rate = 1.0;
      
      // Estimate speech duration (~150 words per minute for TTS)
      const wordCount = text.split(/\s+/).length;
      const estimatedDurationMs = (wordCount / 150) * 60 * 1000;
      const minDuration = 1000;
      const durationMs = Math.max(estimatedDurationMs, minDuration);
      
      // Start text-to-viseme lip sync
      const status = document.getElementById('mpd-avatar-3d-status');
      if (status) {
        status.textContent = 'Speaking...';
      }
      this.startTextLipSync(text, durationMs);
      
      const self = this;
      utterance.onend = () => {
        self.stopLipSync();
        if (status) {
          status.textContent = 'Ready';
        }
      };
      utterance.onerror = () => {
        self.stopLipSync();
        if (status) {
          status.textContent = 'Ready';
        }
      };
      
      window.speechSynthesis.speak(utterance);
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
              <!-- Avatar Selector UI -->
              <div id="mpd-avatar-selector-container"></div>
            </div>

            <!-- 3D Avatar Container -->
            <div class="mpd-avatar-3d-container" id="mpd-avatar-3d-container" style="display:none;">
              <canvas id="mpd-avatar-canvas"></canvas>
              <div class="mpd-avatar-3d-status" id="mpd-avatar-3d-status">Loading 3D Avatar...</div>
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
    },

    attachEventListeners: function() {
      const chatButton = document.getElementById('mpd-chat-button');
      const chatClose = document.getElementById('mpd-chat-close');
      const chatSend = document.getElementById('mpd-chat-send');
      const chatInput = document.getElementById('mpd-chat-input');
      const quickActions = document.querySelectorAll('.mpd-quick-action');
      const attachButton = document.getElementById('mpd-attach-btn');
      const voiceButton = document.getElementById('mpd-voice-btn');
      const fileInput = document.getElementById('mpd-file-input');
      const removeFileButton = document.getElementById('mpd-remove-file');

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
          
          // Use browser's speechSynthesis for TTS with lip sync
          if (data.use_browser_tts && data.response && 'speechSynthesis' in window) {
            this.setVoiceStatus('Speaking...', '🗣️');
            this.speakText(data.response);
            
            const utterance = new SpeechSynthesisUtterance(data.response);
            utterance.onend = () => {
              this.setVoiceStatus('Click the microphone to speak', '😊');
              if (transcription) {
                setTimeout(() => { transcription.style.display = 'none'; }, 3000);
              }
            };
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
        
        // Auto-speak response with lip sync if avatar is present
        if (this.state.avatar3D) {
          this.speakText(data.response);
        }
        
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
