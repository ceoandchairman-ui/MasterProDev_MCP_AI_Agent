/**
 * MasterProDev Chat Widget - Embeddable 3D Avatar Chat
 * Self-contained, globally accessible MCPChat object
 */

(function() {
    'use strict';

    // CDN URLs for Three.js
    const THREE_CDN = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js';
    const GLTFLoader_CDN = 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/js/loaders/GLTFLoader.js';
    const OrbitControls_CDN = 'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/js/controls/OrbitControls.js';

    // Viseme mapping
    const VISEME_NAMES = [
        'viseme_sil', 'viseme_PP', 'viseme_FF', 'viseme_TH', 'viseme_DD',
        'viseme_kk', 'viseme_CH', 'viseme_SS', 'viseme_nn', 'viseme_RR',
        'viseme_aa', 'viseme_E', 'viseme_I', 'viseme_O', 'viseme_U'
    ];

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

    // Avatar Gallery
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
            url: 'https://cdn.sketchfab.com/models/b6f6740f883b4749abac47af0045a9dd/model.glb',
            thumbnail: '👨‍💼',
            gender: 'male'
        },
        {
            id: 'supportwoman',
            name: 'Support Agent (F)',
            description: 'Friendly female support agent',
            url: 'https://cdn.sketchfab.com/models/ed3154322eee4bdda8241aeb6024c129/model.glb',
            thumbnail: '👩‍🦰',
            gender: 'female'
        },
        {
            id: 'supportman',
            name: 'Support Agent (M)',
            description: 'Friendly male support agent',
            url: 'https://cdn.sketchfab.com/models/72164207fe884fd285a03779987d0509/model.glb',
            thumbnail: '🧑‍💻',
            gender: 'male'
        }
    ];

    // Global state
    const state = {
        isOpen: false,
        currentMode: 'avatar',
        isRecording: false,
        selectedFile: null,
        conversationId: null,
        authToken: null,
        isAuthenticated: false,
        currentAvatarId: localStorage.getItem('selectedAvatar') || 'businesswoman'
    };

    // MCPChat API
    const MCPChat = {
        config: {
            apiUrl: 'http://localhost:8000',
            brandName: 'MasterProDev AI Agent',
            position: 'bottom-right'
        },

        init: function(options) {
            Object.assign(this.config, options);
            this.createWidget();
            this.loadThreeJS();
        },

        createWidget: function() {
            // Create main container
            const widget = document.createElement('div');
            widget.id = 'mpd-chat-widget';
            widget.innerHTML = `
                <button id="mpd-chat-button" class="mpd-chat-btn" title="Chat with AI">
                    <span>💬</span>
                </button>
                <div id="mpd-chat-window" class="mpd-chat-window" style="display: none;">
                    <div class="mpd-chat-header">
                        <h3>${this.config.brandName}</h3>
                        <button id="mpd-chat-close" class="mpd-close-btn">×</button>
                    </div>
                    <div id="mpd-avatar-3d-container" class="mpd-avatar-container">
                        <canvas id="mpd-avatar-canvas"></canvas>
                        <div id="mpd-avatar-3d-status" class="mpd-avatar-status">Loading 3D Avatar...</div>
                    </div>
                    <div id="mpd-chat-messages" class="mpd-messages"></div>
                    <div class="mpd-input-area">
                        <input type="text" id="mpd-chat-input" placeholder="Type message..." />
                        <button id="mpd-send-btn" class="mpd-send-btn">Send</button>
                    </div>
                </div>
            `;
            document.body.appendChild(widget);

            // Attach listeners
            document.getElementById('mpd-chat-button').addEventListener('click', () => this.toggleChat());
            document.getElementById('mpd-chat-close').addEventListener('click', () => this.toggleChat());
            document.getElementById('mpd-send-btn').addEventListener('click', () => this.sendMessage());
            document.getElementById('mpd-chat-input').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') this.sendMessage();
            });
        },

        toggleChat: function() {
            const window = document.getElementById('mpd-chat-window');
            state.isOpen = !state.isOpen;
            window.style.display = state.isOpen ? 'flex' : 'none';
            
            if (state.isOpen && !window.dataset.initialized) {
                this.init3DAvatar();
                window.dataset.initialized = 'true';
            }
        },

        loadThreeJS: function() {
            if (window.THREE) return; // Already loaded
            
            const script = document.createElement('script');
            script.src = THREE_CDN;
            script.onload = () => {
                // Load GLTFLoader
                const loaderScript = document.createElement('script');
                loaderScript.src = GLTFLoader_CDN;
                loaderScript.onload = () => {
                    window.GLTFLoader = THREE.GLTFLoader;
                    // Load OrbitControls
                    const controlsScript = document.createElement('script');
                    controlsScript.src = OrbitControls_CDN;
                    controlsScript.onload = () => {
                        window.OrbitControls = THREE.OrbitControls;
                        console.log('✓ Three.js dependencies loaded');
                    };
                    document.head.appendChild(controlsScript);
                };
                document.head.appendChild(loaderScript);
            };
            document.head.appendChild(script);
        },

        init3DAvatar: function() {
            const avatarData = AVATAR_GALLERY.find(a => a.id === state.currentAvatarId) || AVATAR_GALLERY[0];
            const canvas = document.getElementById('mpd-avatar-canvas');
            const status = document.getElementById('mpd-avatar-3d-status');
            const container = document.getElementById('mpd-avatar-3d-container');

            if (!container || !canvas) return;

            canvas.width = container.clientWidth || 400;
            canvas.height = container.clientHeight || 400;

            // Wait for Three.js to load
            if (!window.THREE) {
                setTimeout(() => this.init3DAvatar(), 500);
                return;
            }

            const THREE = window.THREE;
            const loader = new THREE.GLTFLoader();

            // Scene setup
            const scene = new THREE.Scene();
            scene.background = new THREE.Color(0xf5f5f5);

            const camera = new THREE.PerspectiveCamera(75, canvas.width / canvas.height, 0.1, 1000);
            camera.position.set(0, 1.5, 2.5);

            const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
            renderer.setSize(canvas.width, canvas.height);
            renderer.setPixelRatio(window.devicePixelRatio);

            // Lighting
            const light = new THREE.DirectionalLight(0xffffff, 1);
            light.position.set(5, 5, 5);
            scene.add(light);
            scene.add(new THREE.AmbientLight(0xffffff, 0.5));

            // Load avatar model
            loader.load(
                avatarData.url,
                (gltf) => {
                    const avatar = gltf.scene;
                    avatar.position.set(0, 0, 0);
                    avatar.scale.set(1, 1, 1);
                    scene.add(avatar);
                    status.textContent = `Loaded: ${avatarData.name}`;
                },
                undefined,
                (error) => {
                    status.textContent = `Failed to load avatar: ${error.message}`;
                    console.error('Avatar load error:', error);
                }
            );

            // Animation loop
            function animate() {
                requestAnimationFrame(animate);
                renderer.render(scene, camera);
            }
            animate();
        },

        sendMessage: async function() {
            const input = document.getElementById('mpd-chat-input');
            const message = input.value.trim();
            
            if (!message) return;

            this.addMessage(message, 'user');
            input.value = '';

            try {
                const response = await fetch(`${this.config.apiUrl}/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: message,
                        conversation_id: state.conversationId
                    })
                });

                if (!response.ok) throw new Error('Chat request failed');

                const data = await response.json();
                state.conversationId = data.conversation_id;
                this.addMessage(data.response, 'bot');
            } catch (error) {
                console.error('Chat error:', error);
                this.addMessage('Sorry, something went wrong. Please try again.', 'bot');
            }
        },

        addMessage: function(text, sender) {
            const messagesContainer = document.getElementById('mpd-chat-messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = `mpd-message mpd-message-${sender}`;
            messageDiv.textContent = text;
            messagesContainer.appendChild(messageDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    };

    // Expose globally
    window.MCPChat = MCPChat;

    // Auto-init if data attribute is present
    const script = document.currentScript;
    if (script && script.hasAttribute('data-auto-init')) {
        document.addEventListener('DOMContentLoaded', () => {
            MCPChat.init({
                apiUrl: script.getAttribute('data-api-url') || 'http://localhost:8000'
            });
        });
    }
})();
