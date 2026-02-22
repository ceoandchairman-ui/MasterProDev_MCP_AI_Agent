/**
 * MasterProDev Chat Widget v4.2
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

        // Avatar customization
        this.currentAvatarId = localStorage.getItem('armosa_selected_avatar') || 'bot';
        this.AVATAR_GALLERY = [
            { id: 'bot',     name: 'AI Assistant',   thumbnail: '🤖', icon: 'mdi:robot-happy',         url: null },
            { id: 'woman',   name: 'Business Woman', thumbnail: '👩\u200d💼', icon: 'mdi:face-woman-outline', url: 'https://models.readyplayer.me/64bfa15f0e72c63d7c3934a6.glb?morphTargets=ARKit,Oculus+Visemes&textureAtlas=1024' },
            { id: 'man',     name: 'Business Man',   thumbnail: '👨\u200d💼', icon: 'mdi:face-man-outline',   url: null },
            { id: 'support', name: 'Support Agent',  thumbnail: '🧑\u200d💻', icon: 'mdi:face-agent',         url: null },
        ];

        // Three.js 3D Avatar state (lazy-loaded when avatar tab first opened)
        this.three = {
            loaded: false,
            scene: null, camera: null, renderer: null,
            avatar: null, mixer: null, clock: null,
            mouthMorphTarget: null, visemeInfluences: {},
            animFrameId: null
        };

        // Lip-sync state
        this.lipSync = {
            interval: null,
            targetViseme: 'viseme_sil',
            blendFactor: 0
        };

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
        const statusEl = this.widget && this.widget.querySelector('#armosa-user-status');
        if (!statusEl) return;

        if (this.authToken && this.userEmail) {
            const initials = this.userEmail.charAt(0).toUpperCase();
            const displayName = this.userEmail.split('@')[0];
            statusEl.innerHTML = `
                <div class="armosa-user-badge">
                    <div class="armosa-user-avatar">${initials}</div>
                    <span class="armosa-user-name">${displayName}</span>
                    <button class="armosa-logout-btn" title="Sign out">
                        <iconify-icon icon="mdi:logout-variant" style="font-size: 14px;"></iconify-icon>
                    </button>
                </div>
            `;
            statusEl.querySelector('.armosa-logout-btn').addEventListener('click', () => this.performLogout());
        } else {
            statusEl.innerHTML = `
                <button class="armosa-login-btn" title="Sign in">
                    <iconify-icon icon="mdi:login-variant" style="font-size: 14px;"></iconify-icon>
                    <span>Sign in</span>
                </button>
            `;
            statusEl.querySelector('.armosa-login-btn').addEventListener('click', () => this.showLoginModal());
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
        // Load Iconify FIRST
        this.loadIconify();
        
        this.injectStyles();
        this.createWidget();
        this.populateAvatarSelector();
        this.attachEventListeners();
        
        // Load saved auth state and update UI
        const wasLoggedIn = this.loadAuthState();
        this.updateAuthUI();
        
        // Personalized greeting
        if (wasLoggedIn && this.userEmail) {
            this.addBotMessage(`Welcome back, ${this.userEmail.split('@')[0]}! 👋 How can I help you today?`);
        } else {
            this.addBotMessage('Hi! I\'m your AI assistant. I can help you with:\n\n• **Calendar management** 📅\n• **Email operations** 📧\n• **Document analysis** 📄\n• **Voice conversations** 🎙️\n\nHow can I help you today?');
        }
    }
    
    loadIconify() {
        if (!document.querySelector('script[src*="iconify"]')) {
            const script = document.createElement('script');
            script.src = 'https://code.iconify.design/iconify-icon/1.0.7/iconify-icon.min.js';
            document.head.appendChild(script);
        }
    }

    // ==================== AVATAR CUSTOMIZATION ====================

    populateAvatarSelector() {
        const dropdown = this.widget && this.widget.querySelector('#avatar-selector-dropdown');
        const toggle   = this.widget && this.widget.querySelector('#avatar-selector-toggle');
        if (!dropdown || !toggle) return;

        // Build option buttons
        dropdown.innerHTML = '';
        this.AVATAR_GALLERY.forEach(avatar => {
            const btn = document.createElement('button');
            btn.className = 'avatar-option' + (avatar.id === this.currentAvatarId ? ' selected' : '');
            btn.dataset.avatarId = avatar.id;
            btn.innerHTML = `
                <span class="avatar-option-thumb">${avatar.thumbnail}</span>
                <span class="avatar-option-name">${avatar.name}</span>
                <iconify-icon class="avatar-option-check" icon="mdi:check-bold" style="font-size:14px;"></iconify-icon>
            `;
            btn.addEventListener('click', () => {
                this.selectAvatar(avatar.id);
                dropdown.classList.remove('open');
            });
            dropdown.appendChild(btn);
        });

        // Toggle open/close
        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('open');
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && e.target !== toggle) {
                dropdown.classList.remove('open');
            }
        });

        // Apply currently saved avatar icon on init
        this.selectAvatar(this.currentAvatarId);
    }

    selectAvatar(id) {
        const entry = this.AVATAR_GALLERY.find(a => a.id === id);
        if (!entry) return;

        this.currentAvatarId = id;
        localStorage.setItem('armosa_selected_avatar', id);

        // Update 2D fallback avatar-circle icon
        const circle = this.widget && this.widget.querySelector('#avatar-circle iconify-icon');
        if (circle) circle.setAttribute('icon', entry.icon);

        // Refresh selected state in dropdown
        const dropdown = this.widget && this.widget.querySelector('#avatar-selector-dropdown');
        if (dropdown) {
            dropdown.querySelectorAll('.avatar-option').forEach(opt => {
                opt.classList.toggle('selected', opt.dataset.avatarId === id);
            });
        }

        // If 3D is already running, hot-swap the model
        if (this.three.loaded && this.three.scene) {
            this.load3DAvatarModel(id);
        }
    }

    // ==================== 3D AVATAR ====================

    loadThreeJS() {
        return new Promise((resolve, reject) => {
            if (window.THREE && window.THREE.GLTFLoader) { resolve(); return; }
            const baseUrl = 'https://cdn.jsdelivr.net/npm/three@0.128.0';

            const load = (src) => new Promise((res, rej) => {
                const s = document.createElement('script');
                s.src = src;
                s.onload = res;
                s.onerror = rej;
                document.head.appendChild(s);
            });

            load(`${baseUrl}/build/three.min.js`)
                .then(() => load(`${baseUrl}/examples/js/loaders/GLTFLoader.js`))
                .then(resolve)
                .catch(reject);
        });
    }

    async init3DAvatar() {
        if (this.three.loaded) return;

        const statusEl = this.widget && this.widget.querySelector('#avatar-status-text');
        if (statusEl) statusEl.textContent = 'Loading 3D engine...';

        try {
            await this.loadThreeJS();
        } catch (e) {
            console.warn('ArmosaWidget: Three.js failed to load, using 2D fallback.', e);
            if (statusEl) statusEl.textContent = 'Tap to speak';
            return;
        }

        const T = window.THREE;
        const container = this.avatarView;
        const canvas = this.widget.querySelector('#armosa-avatar-canvas');
        if (!container || !canvas) return;

        // Scene
        this.three.scene = new T.Scene();
        this.three.scene.background = new T.Color(0xEFF6FF);

        // Camera
        const w = container.clientWidth || 300;
        const h = container.clientHeight || 300;
        this.three.camera = new T.PerspectiveCamera(45, w / h, 0.1, 100);
        this.three.camera.position.set(0, 1.5, 2.2);

        // Renderer
        this.three.renderer = new T.WebGLRenderer({ canvas, antialias: true, alpha: true });
        this.three.renderer.setSize(w, h);
        this.three.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        if (T.sRGBEncoding) this.three.renderer.outputEncoding = T.sRGBEncoding;

        // Lighting
        this.three.scene.add(new T.AmbientLight(0xffffff, 0.6));
        const dir = new T.DirectionalLight(0xffffff, 0.8);
        dir.position.set(5, 10, 7.5);
        this.three.scene.add(dir);
        const fill = new T.DirectionalLight(0x00C896, 0.3);
        fill.position.set(-5, 5, -5);
        this.three.scene.add(fill);

        this.three.clock = new T.Clock();
        this.three.loaded = true;

        // Show canvas, hide 2D circle
        canvas.style.display = 'block';
        const circle2D = this.widget.querySelector('#avatar-circle');
        if (circle2D) circle2D.style.display = 'none';

        // Resize observer
        if (window.ResizeObserver) {
            new ResizeObserver(() => this.onAvatar3DResize()).observe(container);
        }

        // Load the selected avatar model
        this.load3DAvatarModel(this.currentAvatarId);

        // Start render loop
        this.animate3D();
    }

    load3DAvatarModel(avatarId) {
        const T = window.THREE;
        if (!T || !this.three.scene) return;

        const entry = this.AVATAR_GALLERY.find(a => a.id === avatarId) || this.AVATAR_GALLERY[0];
        const statusEl = this.widget && this.widget.querySelector('#avatar-status-text');

        // Remove previous avatar
        if (this.three.avatar) {
            this.three.scene.remove(this.three.avatar);
            this.three.avatar = null;
            this.three.mixer = null;
            this.three.mouthMorphTarget = null;
            this.three.visemeInfluences = {};
        }

        if (entry.url) {
            // Load GLTF/GLB from ReadyPlayerMe
            if (statusEl) statusEl.textContent = `Loading ${entry.name}...`;

            const loader = new T.GLTFLoader();
            loader.load(
                entry.url,
                (gltf) => {
                    this.three.avatar = gltf.scene;
                    this.three.avatar.position.set(0, 0, 0);
                    this.three.scene.add(this.three.avatar);

                    // Find morph targets for lip sync (Feature #6)
                    this.three.avatar.traverse((child) => {
                        if (child.isMesh && child.morphTargetInfluences && child.morphTargetDictionary) {
                            this.three.mouthMorphTarget = child;
                            const VISEME_NAMES = [
                                'viseme_sil','viseme_PP','viseme_FF','viseme_TH','viseme_DD',
                                'viseme_kk','viseme_CH','viseme_SS','viseme_nn','viseme_RR',
                                'viseme_aa','viseme_E','viseme_I','viseme_O','viseme_U'
                            ];
                            VISEME_NAMES.forEach(name => {
                                if (child.morphTargetDictionary[name] !== undefined) {
                                    this.three.visemeInfluences[name] = child.morphTargetDictionary[name];
                                }
                            });
                        }
                    });

                    // Play idle animation if available
                    if (gltf.animations && gltf.animations.length > 0) {
                        this.three.mixer = new T.AnimationMixer(this.three.avatar);
                        this.three.mixer.clipAction(gltf.animations[0]).play();
                    }

                    if (statusEl) statusEl.textContent = 'Tap to speak';
                },
                (progress) => {
                    if (progress.total && statusEl) {
                        const pct = Math.round((progress.loaded / progress.total) * 100);
                        statusEl.textContent = `Loading ${entry.name}... ${pct}%`;
                    }
                },
                (err) => {
                    console.warn('ArmosaWidget: Failed to load GLB:', err);
                    this.createFallback3DAvatar(entry);
                    if (statusEl) statusEl.textContent = 'Tap to speak';
                }
            );
        } else {
            // No URL — create a geometric fallback shape
            this.createFallback3DAvatar(entry);
            if (statusEl) statusEl.textContent = 'Tap to speak';
        }
    }

    createFallback3DAvatar(entry) {
        const T = window.THREE;
        if (!T || !this.three.scene) return;

        // Head sphere
        const headGeo = new T.SphereGeometry(0.35, 32, 32);
        const headMat = new T.MeshStandardMaterial({ color: 0x2563EB });
        const head = new T.Mesh(headGeo, headMat);
        head.position.set(0, 1.6, 0);

        // Body cylinder
        const bodyGeo = new T.CylinderGeometry(0.22, 0.28, 0.75, 32);
        const bodyMat = new T.MeshStandardMaterial({ color: 0x00C896 });
        const body = new T.Mesh(bodyGeo, bodyMat);
        body.position.set(0, 1.0, 0);

        const group = new T.Group();
        group.add(head);
        group.add(body);
        group.position.set(0, -0.3, 0);

        this.three.avatar = group;
        this.three.scene.add(group);
    }

    animate3D() {
        if (!this.three.loaded) return;

        this.three.animFrameId = requestAnimationFrame(() => this.animate3D());

        const delta = this.three.clock ? this.three.clock.getDelta() : 0.016;

        if (this.three.mixer) this.three.mixer.update(delta);

        // Viseme-based lip sync
        const mt = this.three.mouthMorphTarget;
        const vi = this.three.visemeInfluences;
        if (mt && Object.keys(vi).length > 0) {
            this.lipSync.blendFactor = Math.min(this.lipSync.blendFactor + delta * 12, 1);
            const VNAMES = [
                'viseme_sil','viseme_PP','viseme_FF','viseme_TH','viseme_DD',
                'viseme_kk','viseme_CH','viseme_SS','viseme_nn','viseme_RR',
                'viseme_aa','viseme_E','viseme_I','viseme_O','viseme_U'
            ];
            VNAMES.forEach(name => {
                if (vi[name] !== undefined) {
                    const idx = vi[name];
                    const cur = mt.morphTargetInfluences[idx];
                    if (name === this.lipSync.targetViseme) {
                        mt.morphTargetInfluences[idx] = cur + (0.7 - cur) * this.lipSync.blendFactor;
                    } else {
                        mt.morphTargetInfluences[idx] = cur * 0.85;
                    }
                }
            });
        }

        // Gentle idle rotation for fallback avatars
        if (this.three.avatar && !this.three.mixer) {
            this.three.avatar.rotation.y = Math.sin(Date.now() * 0.001) * 0.15;
        }

        if (this.three.renderer && this.three.scene && this.three.camera) {
            this.three.renderer.render(this.three.scene, this.three.camera);
        }
    }

    onAvatar3DResize() {
        if (!this.three.camera || !this.three.renderer || !this.avatarView) return;
        const w = this.avatarView.clientWidth;
        const h = this.avatarView.clientHeight;
        if (!w || !h) return;
        this.three.camera.aspect = w / h;
        this.three.camera.updateProjectionMatrix();
        this.three.renderer.setSize(w, h);
    }

    // ==================== LIP-SYNC ====================

    // Character-to-viseme mapping (approximate English phonemes)
    get CHAR_TO_VISEME() {
        return {
            'a':'viseme_aa','à':'viseme_aa','á':'viseme_aa',
            'e':'viseme_E', 'è':'viseme_E', 'é':'viseme_E',
            'i':'viseme_I', 'ì':'viseme_I', 'í':'viseme_I','y':'viseme_I',
            'o':'viseme_O', 'ò':'viseme_O', 'ó':'viseme_O',
            'u':'viseme_U', 'ù':'viseme_U', 'ú':'viseme_U','w':'viseme_U',
            'p':'viseme_PP','b':'viseme_PP','m':'viseme_PP',
            'f':'viseme_FF','v':'viseme_FF',
            't':'viseme_DD','d':'viseme_DD',
            'k':'viseme_kk','g':'viseme_kk','c':'viseme_kk','q':'viseme_kk',
            's':'viseme_SS','z':'viseme_SS','x':'viseme_SS',
            'n':'viseme_nn','l':'viseme_nn',
            'r':'viseme_RR',
            'j':'viseme_CH','h':'viseme_CH',
            ' ':'viseme_sil','.':'viseme_sil',',':'viseme_sil','!':'viseme_sil','?':'viseme_sil'
        };
    }

    textToVisemes(text) {
        const visemes = [];
        const map = this.CHAR_TO_VISEME;
        const words = text.toLowerCase().split(/\s+/);
        for (const word of words) {
            for (let i = 0; i < word.length; i++) {
                const char = word[i];
                // Handle digraphs
                if (i < word.length - 1) {
                    const dg = char + word[i + 1];
                    if (dg === 'th') { visemes.push('viseme_TH'); i++; continue; }
                    if (dg === 'ch' || dg === 'sh') { visemes.push('viseme_CH'); i++; continue; }
                }
                visemes.push(map[char] || 'viseme_sil');
            }
            visemes.push('viseme_sil'); // silence between words
        }
        return visemes;
    }

    startTextLipSync(text, durationMs) {
        this.stopLipSync();
        const visemes = this.textToVisemes(text);
        if (!visemes.length) return;
        const msPerViseme = Math.max(durationMs / visemes.length, 30);
        let idx = 0;
        this.lipSync.interval = setInterval(() => {
            if (idx >= visemes.length) { this.stopLipSync(); return; }
            this.lipSync.targetViseme = visemes[idx++];
            this.lipSync.blendFactor = 0;
        }, msPerViseme);
    }

    startSimulatedLipSync() {
        this.stopLipSync();
        const vowels = ['viseme_aa','viseme_E','viseme_O','viseme_I','viseme_U','viseme_sil'];
        this.lipSync.interval = setInterval(() => {
            this.lipSync.targetViseme = Math.random() > 0.25
                ? vowels[Math.floor(Math.random() * vowels.length)]
                : 'viseme_sil';
            this.lipSync.blendFactor = 0;
        }, 80);
    }

    stopLipSync() {
        if (this.lipSync.interval) {
            clearInterval(this.lipSync.interval);
            this.lipSync.interval = null;
        }
        this.lipSync.targetViseme = 'viseme_sil';
        this.lipSync.blendFactor = 0;
        // Zero-out all morph targets
        const mt = this.three.mouthMorphTarget;
        const vi = this.three.visemeInfluences;
        if (mt && Object.keys(vi).length > 0) {
            Object.values(vi).forEach(idx => { mt.morphTargetInfluences[idx] = 0; });
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
               ARMOSA CHAT WIDGET v5.0 - "PRODUCT" EDITION
               Clean, minimal, ChatGPT/Anthropic-inspired design language.
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
                width: 52px !important;
                height: 52px !important;
                border-radius: 50% !important;
                background: #00C896 !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                z-index: 999998 !important;
                transition: all 0.2s ease !important;
                box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18) !important;
            }

            #armosa-fab:hover {
                background: #009977 !important;
                box-shadow: 0 6px 20px rgba(0, 0, 0, 0.22) !important;
                transform: scale(1.05) !important;
            }

            #armosa-fab.hidden {
                transform: scale(0) !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }

            /* ==================== WIDGET ==================== */
            #armosa-widget {
                all: unset !important;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif !important;
                position: fixed !important;
                bottom: 84px !important;
                right: 24px !important;
                width: 380px !important;
                height: 660px !important;
                border-radius: 16px !important;
                display: flex !important;
                flex-direction: column !important;
                z-index: 999999 !important;
                transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
                transform-origin: bottom right !important;
                background: #ffffff !important;
                border: 1px solid rgba(0, 0, 0, 0.1) !important;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.25) !important;
                overflow: hidden !important;
            }

            #armosa-widget.hidden {
                transform: translateY(12px) scale(0.97) !important;
                opacity: 0 !important;
                pointer-events: none !important;
            }

            /* ==================== INNER CONTAINER ==================== */
            #armosa-widget .widget-inner {
                flex: 1 !important;
                background: #ffffff !important;
                border-radius: 0 !important;
                display: flex !important;
                flex-direction: column !important;
                gap: 0 !important;
                padding: 0 !important;
                overflow: hidden !important;
            }

            /* ==================== HEADER ==================== */
            #armosa-widget .armosa-header {
                background: #ffffff !important;
                border-radius: 0 !important;
                border-bottom: 1px solid #e8e8e8 !important;
                display: flex !important;
                flex-direction: column !important;
                padding: 12px 16px 10px !important;
                flex-shrink: 0 !important;
                gap: 10px !important;
            }

            #armosa-widget .header-row-top {
                display: flex !important;
                align-items: center !important;
                justify-content: space-between !important;
                width: 100% !important;
            }

            #armosa-widget .header-left {
                display: flex !important;
                align-items: center !important;
                gap: 10px !important;
            }

            #armosa-widget .armosa-logo {
                width: 32px !important;
                height: 32px !important;
                background: #00C896 !important;
                border-radius: 8px !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
            }

            #armosa-widget .armosa-title {
                font-size: 15px !important;
                font-weight: 600 !important;
                color: #202123 !important;
                letter-spacing: -0.01em !important;
            }

            #armosa-widget .header-right {
                display: flex !important;
                align-items: center !important;
                justify-content: flex-end !important;
            }

            #armosa-widget .close-btn {
                all: unset !important;
                width: 32px !important;
                height: 32px !important;
                border-radius: 8px !important;
                background: transparent !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                color: #71717a !important;
                transition: all 0.15s ease !important;
            }

            #armosa-widget .close-btn:hover {
                background: #f4f4f5 !important;
                color: #18181b !important;
            }

            #armosa-widget .header-row-bottom {
                display: flex !important;
                width: 100% !important;
                background: #f4f4f5 !important;
                border-radius: 10px !important;
                padding: 3px !important;
                gap: 2px !important;
            }

            #armosa-widget .tab-btn {
                all: unset !important;
                flex: 1 !important;
                padding: 7px 8px !important;
                text-align: center !important;
                border-radius: 8px !important;
                font-size: 13px !important;
                font-weight: 500 !important;
                color: #71717a !important;
                cursor: pointer !important;
                transition: all 0.15s ease !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                gap: 5px !important;
            }

            #armosa-widget .tab-btn.active {
                background: #ffffff !important;
                color: #00C896 !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.05) !important;
            }

            #armosa-widget .tab-btn:hover:not(.active) {
                color: #3f3f46 !important;
            }

            /* ==================== AUTH UI ELEMENTS ==================== */
            #armosa-widget .auth-login-btn {
                all: unset !important;
                padding: 6px 12px !important;
                border-radius: 8px !important;
                background: #00C896 !important;
                color: white !important;
                font-size: 12px !important;
                font-weight: 600 !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                gap: 4px !important;
                transition: background 0.15s ease !important;
            }

            #armosa-widget .auth-login-btn:hover {
                background: #009977 !important;
            }
            }

            #armosa-widget .auth-user-info {
                display: flex !important;
                align-items: center !important;
                gap: 6px !important;
                padding: 4px 8px !important;
                background: #f4f4f5 !important;
                border-radius: 20px !important;
                border: none !important;
            }

            #armosa-widget .auth-user-email {
                font-size: 12px !important;
                font-weight: 500 !important;
                color: #3f3f46 !important;
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
                color: #a1a1aa !important;
                transition: all 0.15s ease !important;
            }

            #armosa-widget .auth-logout-btn:hover {
                color: #ef4444 !important;
            }

            /* ==================== LOGIN MODAL ==================== */
            #armosa-login-modal {
                position: absolute !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                background: rgba(0, 0, 0, 0.45) !important;
                backdrop-filter: blur(4px) !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                z-index: 100 !important;
                opacity: 0 !important;
                pointer-events: none !important;
                transition: opacity 0.2s ease !important;
                border-radius: 15px !important;
            }

            #armosa-login-modal.visible {
                opacity: 1 !important;
                pointer-events: auto !important;
            }

            #armosa-login-modal .login-card {
                background: white !important;
                border-radius: 16px !important;
                padding: 24px !important;
                width: 85% !important;
                max-width: 300px !important;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.2) !important;
                border: 1px solid rgba(0,0,0,0.08) !important;
            }

            #armosa-login-modal .login-title {
                font-size: 18px !important;
                font-weight: 600 !important;
                text-align: center !important;
                margin-bottom: 20px !important;
                color: #18181b !important;
            }

            #armosa-login-modal .login-input {
                all: unset !important;
                width: 100% !important;
                padding: 10px 14px !important;
                border: 1px solid #e5e5e5 !important;
                border-radius: 10px !important;
                font-size: 14px !important;
                background: #fafafa !important;
                margin-bottom: 10px !important;
                box-sizing: border-box !important;
                transition: border-color 0.15s ease !important;
            }

            #armosa-login-modal .login-input:focus {
                border-color: #00C896 !important;
                background: white !important;
                box-shadow: 0 0 0 2px rgba(0,200,150,0.1) !important;
            }

            #armosa-login-modal .login-input::placeholder {
                color: #a1a1aa !important;
            }

            #armosa-login-modal .login-error {
                color: #ef4444 !important;
                font-size: 12px !important;
                text-align: center !important;
                margin-bottom: 10px !important;
                min-height: 16px !important;
            }

            #armosa-login-modal .login-submit {
                all: unset !important;
                width: 100% !important;
                padding: 10px !important;
                background: #00C896 !important;
                color: white !important;
                font-size: 14px !important;
                font-weight: 600 !important;
                text-align: center !important;
                border-radius: 10px !important;
                cursor: pointer !important;
                box-sizing: border-box !important;
                transition: background 0.15s ease !important;
            }

            #armosa-login-modal .login-submit:hover:not(:disabled) {
                background: #009977 !important;
            }

            #armosa-login-modal .login-submit:disabled {
                opacity: 0.6 !important;
                cursor: not-allowed !important;
            }

            #armosa-login-modal .login-cancel {
                all: unset !important;
                width: 100% !important;
                padding: 8px !important;
                text-align: center !important;
                font-size: 13px !important;
                color: #71717a !important;
                cursor: pointer !important;
                margin-top: 6px !important;
                box-sizing: border-box !important;
            }

            #armosa-login-modal .login-cancel:hover {
                color: #00C896 !important;
            }

            /* ==================== MESSAGES ==================== */
            #armosa-widget .armosa-messages {
                flex: 1 !important;
                background: #ffffff !important;
                border-radius: 0 !important;
                border: none !important;
                overflow-y: auto !important;
                overflow-x: hidden !important;
                padding: 20px 16px !important;
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
                background: #d4d4d8 !important;
                border-radius: 2px !important;
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
                border-radius: 50% !important;
                background: #00C896 !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                flex-shrink: 0 !important;
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
                background: #f4f4f5 !important;
                border: none !important;
                border-radius: 18px !important;
                padding: 10px 14px !important;
                font-size: 14px !important;
                line-height: 1.6 !important;
                color: #18181b !important;
            }

            #armosa-widget .bot-message-content strong {
                color: #18181b !important;
                font-weight: 600 !important;
            }

            #armosa-widget .bot-message-content em {
                color: #18181b !important;
            }

            #armosa-widget .user-message-content {
                background: #00C896 !important;
                border-radius: 18px !important;
                padding: 10px 14px !important;
                color: #ffffff !important;
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

            /* ==================== VOICE VIEW ==================== */
            #armosa-widget .voice-view {
                flex: 1 !important;
                display: none !important;
                flex-direction: column !important;
                align-items: center !important;
                justify-content: center !important;
                background: #fafafa !important;
                border-radius: 0 !important;
                border: none !important;
                gap: 20px !important;
            }

            #armosa-widget .voice-view.active {
                display: flex !important;
            }

            #armosa-widget .voice-orb {
                width: 96px !important;
                height: 96px !important;
                border-radius: 50% !important;
                background: #00C896 !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                cursor: pointer !important;
                box-shadow: 0 4px 20px rgba(0, 200, 150, 0.3) !important;
                transition: transform 0.15s ease, box-shadow 0.15s ease !important;
                animation: voiceFloat 3s ease-in-out infinite !important;
            }

            #armosa-widget .voice-orb:hover {
                transform: scale(1.06) !important;
                box-shadow: 0 6px 24px rgba(0, 200, 150, 0.4) !important;
            }

            #armosa-widget .voice-orb.listening {
                animation: voicePulse 1s ease-in-out infinite !important;
                background: #ef4444 !important;
                box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7) !important;
            }

            #armosa-widget .voice-orb.speaking {
                animation: voiceBounce 0.5s ease-in-out infinite alternate !important;
                background: #00C896 !important;
            }

            @keyframes voiceFloat {
                0%, 100% { transform: translateY(0); }
                50% { transform: translateY(-8px); }
            }

            @keyframes voicePulse {
                0% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
                70% { transform: scale(1.1); box-shadow: 0 0 0 16px rgba(239, 68, 68, 0); }
                100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
            }

            @keyframes voiceBounce {
                from { transform: scale(1); }
                to { transform: scale(1.06); }
            }

            #armosa-widget .voice-status-text {
                font-size: 14px !important;
                font-weight: 600 !important;
                color: #71717A !important;
                text-align: center !important;
            }

            /* ==================== AVATAR VIEW ==================== */
            #armosa-widget .avatar-view {
                flex: 1 !important;
                display: none !important;
                flex-direction: column !important;
                align-items: center !important;
                justify-content: center !important;
                background: #fafafa !important;
                border-radius: 0 !important;
                border: none !important;
                padding: 20px !important;
                position: relative !important;
                overflow: hidden !important;
            }

            #armosa-widget .avatar-view.active {
                display: flex !important;
            }

            /* 3D canvas fills the avatar view */
            #armosa-widget #armosa-avatar-canvas {
                display: none;
                position: absolute !important;
                top: 0 !important;
                left: 0 !important;
                width: 100% !important;
                height: 100% !important;
                border-radius: 18px !important;
                z-index: 3 !important;
            }

            /* Keep status text visible above canvas */
            #armosa-widget .avatar-view .avatar-status-text {
                position: absolute !important;
                bottom: 14px !important;
                left: 50% !important;
                transform: translateX(-50%) !important;
                z-index: 4 !important;
                background: rgba(255,255,255,0.85) !important;
                padding: 4px 12px !important;
                border-radius: 20px !important;
                backdrop-filter: blur(4px) !important;
            }

            #armosa-widget .avatar-circle {
                width: 110px !important;
                height: 110px !important;
                border-radius: 50% !important;
                background: #00C896 !important;
                box-shadow: 0 4px 20px rgba(0, 200, 150, 0.3) !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                position: relative !important;
                z-index: 2 !important;
                transition: transform 0.2s ease !important;
            }
            
            #armosa-widget .avatar-circle iconify-icon {
                font-size: 64px !important;
                color: white !important;
                filter: drop-shadow(0 2px 4px rgba(0,0,0,0.2)) !important;
            }

            /* Animations for states */
            #armosa-widget .avatar-circle.listening {
                transform: scale(1.1) !important;
                box-shadow: 0 0 0 0 rgba(0, 200, 150, 0.6) !important;
                animation: listeningPulse 1.5s infinite !important;
            }

            #armosa-widget .avatar-circle.speaking {
                animation: speakingBounce 0.5s infinite alternate !important;
            }
            
            #armosa-widget .avatar-circle.thinking {
                animation: thinkingSpin 2s infinite linear !important;
                background: linear-gradient(135deg, #FFB800 0%, #FF8A00 100%) !important;
            }

            @keyframes listeningPulse {
                0% {
                    transform: scale(1);
                    box-shadow: 0 0 0 0 rgba(0, 200, 150, 0.6);
                }
                70% {
                    transform: scale(1.1);
                    box-shadow: 0 0 0 20px rgba(0, 200, 150, 0);
                }
                100% {
                    transform: scale(1);
                    box-shadow: 0 0 0 0 rgba(0, 200, 150, 0);
                }
            }

            @keyframes speakingBounce {
                from { transform: scale(1); }
                to { transform: scale(1.05); }
            }
            
            @keyframes thinkingSpin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }

            #armosa-widget .avatar-status-text {
                margin-top: 24px !important;
                font-size: 14px !important;
                font-weight: 600 !important;
                color: #71717A !important;
                text-align: center !important;
                min-height: 20px !important;
            }

            /* Waveforms behind avatar */
            #armosa-widget .avatar-wave {
                position: absolute !important;
                top: 50% !important;
                left: 50% !important;
                transform: translate(-50%, -50%) !important;
                border-radius: 50% !important;
                border: 2px solid rgba(0, 200, 150, 0.12) !important;
                z-index: 1 !important;
            }

            #armosa-widget .avatar-wave:nth-child(1) { width: 160px; height: 160px; animation-delay: 0s; }
            #armosa-widget .avatar-wave:nth-child(2) { width: 200px; height: 200px; animation-delay: 0.2s; }
            #armosa-widget .avatar-wave:nth-child(3) { width: 240px; height: 240px; animation-delay: 0.4s; }

            /* ==================== TYPING INDICATOR ==================== */
            #armosa-widget .typing-indicator {
                display: flex !important;
                gap: 4px !important;
                padding: 10px 14px !important;
                background: #f4f4f5 !important;
                border-radius: 18px !important;
                width: fit-content !important;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06) !important;
            }

            #armosa-widget .typing-dot {
                width: 7px !important;
                height: 7px !important;
                border-radius: 50% !important;
                background: #00C896 !important;
                animation: typingBounce 1.4s infinite !important;
            }

            #armosa-widget .typing-dot:nth-child(2) { animation-delay: 0.2s !important; }
            #armosa-widget .typing-dot:nth-child(3) { animation-delay: 0.4s !important; }

            @keyframes typingBounce {
                0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
                30% { transform: translateY(-8px); opacity: 1; }
            }

            /* ==================== INPUT AREA ==================== */
            #armosa-widget .armosa-input-container {
                background: #ffffff !important;
                border-radius: 0 !important;
                border-top: 1px solid #e8e8e8 !important;
                display: flex !important;
                align-items: center !important;
                padding: 12px 16px !important;
                gap: 8px !important;
                flex-shrink: 0 !important;
            }

            #armosa-widget .action-btn {
                all: unset !important;
                width: 36px !important;
                height: 36px !important;
                border-radius: 8px !important;
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

            #armosa-widget .action-btn.recording {
                background: #ef4444 !important;
                border-color: #ef4444 !important;
                color: #ffffff !important;
                animation: recordPulse 1s infinite !important;
            }

            @keyframes recordPulse {
                0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
                50% { box-shadow: 0 0 0 10px rgba(239, 68, 68, 0); }
            }

            #armosa-widget #armosa-input {
                all: unset !important;
                flex: 1 !important;
                min-height: 36px !important;
                max-height: 120px !important;
                padding: 8px 12px !important;
                font-size: 14px !important;
                color: #18181b !important;
                background: #fafafa !important;
                border: 1px solid #e5e5e5 !important;
                border-radius: 10px !important;
                transition: border-color 0.15s ease, background 0.15s ease !important;
                resize: none !important;
            }

            #armosa-widget #armosa-input:focus {
                border-color: #00C896 !important;
                background: #ffffff !important;
                box-shadow: 0 0 0 2px rgba(0, 200, 150, 0.1) !important;
            }

            #armosa-widget #armosa-input::placeholder {
                color: #a1a1aa !important;
            }

            #armosa-widget .send-btn {
                all: unset !important;
                width: 36px !important;
                height: 36px !important;
                border-radius: 8px !important;
                background: #00C896 !important;
                cursor: pointer !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                color: #ffffff !important;
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

            /* ==================== FILE PREVIEW ==================== */
            #armosa-widget .file-preview {
                display: none !important;
                background: #f4f4f5 !important;
                border: 1px solid #e5e5e5 !important;
                border-radius: 10px !important;
                padding: 8px 12px !important;
                margin-bottom: 8px !important;
                font-size: 12px !important;
                color: #3f3f46 !important;
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

            /* ==================== USER AUTH STATUS ==================== */
            #armosa-widget .armosa-user-status {
                flex: 1 !important;
                display: flex !important;
                justify-content: center !important;
                align-items: center !important;
            }

            #armosa-widget .armosa-user-badge {
                display: flex !important;
                align-items: center !important;
                gap: 6px !important;
                background: #f4f4f5 !important;
                border-radius: 20px !important;
                padding: 4px 10px 4px 4px !important;
            }

            #armosa-widget .armosa-user-avatar {
                width: 24px !important;
                height: 24px !important;
                border-radius: 50% !important;
                background: #00C896 !important;
                color: white !important;
                font-size: 11px !important;
                font-weight: 700 !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                flex-shrink: 0 !important;
            }

            #armosa-widget .armosa-user-name {
                font-size: 12px !important;
                font-weight: 500 !important;
                color: #3f3f46 !important;
                max-width: 70px !important;
                overflow: hidden !important;
                text-overflow: ellipsis !important;
                white-space: nowrap !important;
            }

            #armosa-widget .armosa-logout-btn {
                all: unset !important;
                cursor: pointer !important;
                color: #71717A !important;
                display: flex !important;
                align-items: center !important;
                transition: color 0.2s ease !important;
            }

            #armosa-widget .armosa-logout-btn:hover {
                color: #EF4444 !important;
            }

            #armosa-widget .armosa-login-btn {
                all: unset !important;
                display: flex !important;
                align-items: center !important;
                gap: 4px !important;
                padding: 5px 10px !important;
                border-radius: 20px !important;
                background: #00C896 !important;
                color: white !important;
                font-size: 12px !important;
                font-weight: 600 !important;
                cursor: pointer !important;
                transition: background 0.15s ease !important;
            }

            #armosa-widget .armosa-login-btn:hover {
                background: #009977 !important;
            }

            /* ==================== AVATAR SELECTOR ==================== */
            #armosa-widget .avatar-selector {
                position: relative !important;
            }

            #armosa-widget .avatar-selector-toggle {
                all: unset !important;
                width: 32px !important;
                height: 32px !important;
                border-radius: 8px !important;
                background: transparent !important;
                color: #71717a !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                cursor: pointer !important;
                font-size: 18px !important;
                transition: background 0.15s ease !important;
            }

            #armosa-widget .avatar-selector-toggle:hover {
                background: #f4f4f5 !important;
                color: #18181b !important;
            }

            #armosa-widget .avatar-selector-dropdown {
                display: none !important;
                position: absolute !important;
                top: calc(100% + 6px) !important;
                right: 0 !important;
                background: #ffffff !important;
                border: 1px solid #e5e5e5 !important;
                border-radius: 12px !important;
                padding: 4px !important;
                box-shadow: 0 4px 24px rgba(0,0,0,0.12) !important;
                z-index: 9999 !important;
                min-width: 160px !important;
                flex-direction: column !important;
                gap: 1px !important;
            }

            #armosa-widget .avatar-selector-dropdown.open {
                display: flex !important;
            }

            #armosa-widget .avatar-option {
                all: unset !important;
                display: flex !important;
                align-items: center !important;
                gap: 8px !important;
                padding: 8px 10px !important;
                border-radius: 8px !important;
                cursor: pointer !important;
                transition: background 0.15s ease !important;
                font-size: 13px !important;
                color: #18181b !important;
                width: 100% !important;
                box-sizing: border-box !important;
            }

            #armosa-widget .avatar-option:hover {
                background: #f4f4f5 !important;
            }

            #armosa-widget .avatar-option.selected {
                background: rgba(0, 200, 150, 0.08) !important;
                border-left: 2px solid #00C896 !important;
            }

            #armosa-widget .avatar-option-thumb {
                font-size: 18px !important;
                line-height: 1 !important;
            }

            #armosa-widget .avatar-option-check {
                margin-left: auto !important;
                color: #00C896 !important;
                display: none !important;
            }

            #armosa-widget .avatar-option.selected .avatar-option-check {
                display: block !important;
            }

            /* ==================== RESPONSIVE ==================== */
            @media (max-width: 420px) {
                #armosa-widget {
                    width: 100% !important;
                    height: 100% !important;
                    border-radius: 0 !important;
                    bottom: 0 !important;
                    right: 0 !important;
                }

                #armosa-widget .widget-inner {
                    border-radius: 0 !important;
                }
            }
        `;
        
        document.head.appendChild(style);
    }

    createWidget() {
        // FAB
        const fab = document.createElement('button');
        fab.id = 'armosa-fab';
        fab.innerHTML = `<iconify-icon icon="mdi:chat-processing-outline" style="font-size: 28px; color: white;"></iconify-icon>`;
        fab.title = 'Chat with MasterProDev AI';
        document.body.appendChild(fab);
        this.fab = fab;

        
        const widget = document.createElement('div');
        widget.id = 'armosa-widget';
        widget.classList.add('hidden');
        widget.innerHTML = `
            <div class="widget-inner">
                <!-- HEADER ISLAND -->
                <div class="armosa-header">
                    <!-- Top Row: Logo, Title, Close -->
                    <div class="header-row-top">
                        <div class="header-left">
                            <div class="armosa-logo">
                                <iconify-icon icon="mdi:robot-happy-outline" style="font-size: 22px; color: white;"></iconify-icon>
                            </div>
                            <span class="armosa-title">MasterProDev</span>
                        </div>
                        <div id="armosa-user-status" class="armosa-user-status"></div>
                        <div class="header-right">
                             <div class="avatar-selector">
                                <button class="avatar-selector-toggle" id="avatar-selector-toggle" title="Change Avatar">
                                    <iconify-icon icon="mdi:account-convert-outline"></iconify-icon>
                                </button>
                                <div class="avatar-selector-dropdown" id="avatar-selector-dropdown">
                                    <!-- Options will be populated by JS -->
                                </div>
                            </div>
                             <button class="close-btn" id="close-widget" title="Close">
                                <iconify-icon icon="mdi:close" style="font-size: 18px;"></iconify-icon>
                            </button>
                        </div>
                    </div>
                    
                    <!-- Bottom Row: Navigation Tabs -->
                    <div class="header-row-bottom">
                        <button class="tab-btn active" data-mode="chat" title="Chat Mode">
                             <iconify-icon icon="mdi:chat-outline" style="font-size: 16px;"></iconify-icon>
                             Chat
                        </button>
                        <button class="tab-btn" data-mode="voice" title="Voice Mode">
                             <iconify-icon icon="mdi:microphone-outline" style="font-size: 16px;"></iconify-icon>
                             Voice
                        </button>
                        <button class="tab-btn" data-mode="avatar" title="Avatar Mode">
                             <iconify-icon icon="mdi:face-man-shimmer-outline" style="font-size: 16px;"></iconify-icon>
                             Avatar
                        </button>
                    </div>
                </div>

                <!-- CHAT ISLAND (Default View) -->
                <div class="armosa-messages" id="armosa-messages"></div>

                <!-- VOICE ISLAND (Hidden by default) -->
                <div class="voice-view" id="armosa-voice-view">
                    <div class="voice-orb" id="voice-orb">
                        <iconify-icon icon="mdi:microphone" style="font-size: 48px; color: white;"></iconify-icon>
                    </div>
                    <div class="voice-status-text" id="voice-status-text">Tap to speak</div>
                </div>

                <!-- AVATAR ISLAND (Hidden by default) -->
                <div class="avatar-view" id="armosa-avatar-view">
                    <div class="avatar-wave"></div>
                    <div class="avatar-wave"></div>
                    <div class="avatar-wave"></div>
                    <!-- 3D canvas - shown when Three.js loads -->
                    <canvas id="armosa-avatar-canvas"></canvas>
                    <!-- 2D fallback circle - shown while loading or if no GLB URL -->
                    <div class="avatar-circle" id="avatar-circle">
                         <iconify-icon icon="mdi:robot-happy" style="font-size: 64px;"></iconify-icon>
                    </div>
                    <div class="avatar-status-text" id="avatar-status-text">Tap to speak</div>
                </div>

                <!-- INPUT ISLAND -->
                <div class="armosa-input-container" id="armosa-input-container">
                    <input type="file" id="file-input" accept="audio/*,video/*,image/*,.pdf,.docx,.doc,.txt" style="display: none;">
                    <button class="action-btn" id="file-btn" title="Attach file">
                        <iconify-icon icon="mdi:paperclip" style="font-size: 20px;"></iconify-icon>
                    </button>
                    <button class="action-btn" id="voice-btn" title="Record voice">
                        <iconify-icon icon="mdi:microphone" style="font-size: 20px;"></iconify-icon>
                    </button>
                    <textarea id="armosa-input" placeholder="Message Armosa..." rows="1"></textarea>
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
        
        // Avatar View Elements
        this.avatarView = widget.querySelector('#armosa-avatar-view');
        this.avatarCircle = widget.querySelector('#avatar-circle');
        this.avatarStatusText = widget.querySelector('#avatar-status-text');

        // Voice View Elements
        this.voiceView = widget.querySelector('#armosa-voice-view');
        this.voiceOrb = widget.querySelector('#voice-orb');

        this.inputContainer = widget.querySelector('#armosa-input-container');
        
        this.isOpen = false;
        
        // Default state
        this.setAvatarState('idle');
    }

    toggleWidget() {
        this.isOpen = !this.isOpen;
        this.widget.classList.toggle('hidden', !this.isOpen);
        this.fab.classList.toggle('hidden', this.isOpen);
    }

    attachEventListeners() {
        this.fab.addEventListener('click', () => this.toggleWidget());
        this.widget.querySelector('#close-widget').addEventListener('click', () => this.toggleWidget());

        this.widget.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchMode(e.target.closest('.tab-btn').dataset.mode));
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
    }

    switchMode(mode) {
        this.currentMode = mode;

        // Update Tabs
        this.widget.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });

        // Hide all views first
        this.messagesContainer.style.display = 'none';
        this.inputContainer.style.display = 'none';
        this.avatarView.classList.remove('active');
        this.voiceView.classList.remove('active');
        this.stopRecording();

        if (mode === 'chat') {
            this.messagesContainer.style.display = 'flex';
            this.inputContainer.style.display = 'flex';
        } else if (mode === 'voice') {
            this.voiceView.classList.add('active');
            this.voiceOrb.onclick = () => this.toggleRecording();
            this.widget.querySelector('#voice-status-text').textContent = 'Tap to speak';
        } else if (mode === 'avatar') {
            this.avatarView.classList.add('active');
            this.setAvatarState('idle');
            this.avatarCircle.onclick = () => this.toggleRecording();
            // Lazy-init 3D engine on first visit to avatar tab
            this.init3DAvatar();
        }
    }

    setAvatarState(state) {
        // States: 'idle', 'listening', 'thinking', 'speaking'
        this.avatarCircle.classList.remove('idle', 'listening', 'thinking', 'speaking');
        this.avatarCircle.classList.add(state);
        
        const statusMap = {
            'idle': 'Tap to speak',
            'listening': 'Listening...',
            'thinking': 'Thinking...',
            'speaking': 'Speaking...'
        };
        
        this.avatarStatusText.textContent = statusMap[state] || 'Ready';
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
                    if (this.currentMode === 'avatar') {
                        this.setAvatarState('listening');
                    } else if (this.currentMode === 'voice') {
                        this.voiceOrb.classList.add('listening');
                        this.widget.querySelector('#voice-status-text').textContent = 'Listening... tap to stop';
                    }
                };

                this.mediaRecorder.onstop = () => {
                    this.isRecording = false;
                    this.widget.querySelector('#voice-btn').classList.remove('recording');
                    if (this.currentMode === 'voice') {
                        this.voiceOrb.classList.remove('listening');
                        this.widget.querySelector('#voice-status-text').textContent = 'Processing...';
                    }
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
        if (this.currentMode === 'avatar') this.setAvatarState('thinking');
        if (this.currentMode === 'voice') this.widget.querySelector('#voice-status-text').textContent = 'Thinking...';
        
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
                    } else {
                        // Text only response in avatar mode?
                         if (this.currentMode === 'avatar') this.setAvatarState('idle');
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

                if (this.currentMode === 'avatar') this.setAvatarState('speaking');
                if (this.currentMode === 'voice') {
                    this.voiceOrb.classList.add('speaking');
                    this.widget.querySelector('#voice-status-text').textContent = 'Speaking...';
                }

                // Start lip sync once we know the audio duration
                audio.addEventListener('loadedmetadata', () => {
                    if (this.three.loaded) {
                        const durationMs = (audio.duration || 3) * 1000;
                        const spokenText = responseText ? decodeURIComponent(responseText) : '';
                        if (spokenText && Object.keys(this.three.visemeInfluences).length > 0) {
                            this.startTextLipSync(spokenText, durationMs);
                        } else {
                            this.startSimulatedLipSync();
                        }
                    }
                });

                audio.play();
                audio.onended = () => {
                    this.stopLipSync();
                    URL.revokeObjectURL(audioUrl);
                    if (this.currentMode === 'avatar') this.setAvatarState('idle');
                    if (this.currentMode === 'voice') {
                        this.voiceOrb.classList.remove('speaking');
                        this.widget.querySelector('#voice-status-text').textContent = 'Tap to speak';
                    }
                };
            }
        })
        .catch(err => {
            this.addBotMessage('Sorry, there was an error processing your voice message.');
            console.error('Voice error:', err);
            if (this.currentMode === 'avatar') this.setAvatarState('idle');
            if (this.currentMode === 'voice') {
                this.voiceOrb.classList.remove('listening', 'speaking');
                this.widget.querySelector('#voice-status-text').textContent = 'Tap to speak';
            }
        })
        .finally(() => this.removeTypingIndicator());
    }

    speakText(text) {
        if ('speechSynthesis' in window) {
            speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = 'en-US';
            utterance.rate = 1.0;

            utterance.onstart = () => {
                if (this.currentMode === 'avatar') this.setAvatarState('speaking');
                if (this.currentMode === 'voice') {
                    this.voiceOrb.classList.add('speaking');
                    this.widget.querySelector('#voice-status-text').textContent = 'Speaking...';
                }
                // Estimate ~120 wpm → ~500ms/word; use text-based lip sync
                const wordCount = text.split(/\s+/).length;
                const estimatedMs = (wordCount / 120) * 60 * 1000;
                if (this.three.loaded && Object.keys(this.three.visemeInfluences).length > 0) {
                    this.startTextLipSync(text, estimatedMs);
                } else if (this.three.loaded) {
                    this.startSimulatedLipSync();
                }
            };

            utterance.onend = () => {
                this.stopLipSync();
                if (this.currentMode === 'avatar') this.setAvatarState('idle');
                if (this.currentMode === 'voice') {
                    this.voiceOrb.classList.remove('speaking');
                    this.widget.querySelector('#voice-status-text').textContent = 'Tap to speak';
                }
            };

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
            
            // Handle pending authentication
            if (data.pending_auth && data.auth_url) {
                const authMsg = `🔐 **Authorization Required**\n\nPlease [click here to authorize](${data.auth_url}) access to your external account.`;
                this.addBotMessage(authMsg);
            }
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
function initializeArmosaWidget() {
    if (!window.armosaChatWidget) {
        window.armosaChatWidget = new ArmosaChatWidget();
    }
}

// Handle various loading scenarios
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeArmosaWidget);
} else {
    // DOMContentLoaded has already fired
    initializeArmosaWidget();
}

// ES Module export
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ArmosaChatWidget;
}
