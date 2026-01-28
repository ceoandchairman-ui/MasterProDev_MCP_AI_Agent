/**
 * MasterProDev AI Agent - Full Page Chat with 3D Avatar
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const API_URL = window.location.origin;

// State
let currentMode = 'avatar';  // Default to avatar mode for talking experience
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let selectedFile = null;
let conversationId = null;
let authToken = null;
let isAuthenticated = false;
let userEmail = null;

// 3D Avatar State
let scene, camera, renderer, avatar3D, mixer, clock;
let audioContext, analyser, dataArray;
let avatar3DLoaded = false;
let mouthMorphTarget = null;
let visemeInfluences = {};  // Store all viseme morph target indices

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

// Lip sync state
let lipSyncQueue = [];
let lipSyncInterval = null;
let currentViseme = 'viseme_sil';
let targetViseme = 'viseme_sil';
let visemeBlendFactor = 0;

// Avatar Gallery - Diverse, high-quality business avatars
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
        description: 'Friendly male support agent',
        url: 'https://models.readyplayer.me/6479c6c52e7c2c3d3c2b8f1b.glb?morphTargets=ARKit,Oculus+Visemes&textureAtlas=1024',
        thumbnail: '🧑‍💻',
        gender: 'male'
    }
];

let currentAvatarId = localStorage.getItem('selectedAvatar') || 'sophia';

// Elements (initialized in init())
let chatMessages, chatInput, sendBtn, attachBtn, voiceBtn;
let fileInput, filePreview, fileName, removeFileBtn;
let typingIndicator, avatar, avatarContainer, avatarStatus;
let avatar3DContainer, avatar3DStatus, avatarCanvas;
let modeBtns, userInfo, headerLogin, headerLogout;
let avatarSelector;

// Initialize
async function init() {
    // Get DOM elements
    chatMessages = document.getElementById('chat-messages');
    chatInput = document.getElementById('chat-input');
    sendBtn = document.getElementById('send-btn');
    attachBtn = document.getElementById('attach-btn');
    voiceBtn = document.getElementById('voice-btn');
    fileInput = document.getElementById('file-input');
    filePreview = document.getElementById('file-preview');
    fileName = document.getElementById('file-name');
    removeFileBtn = document.getElementById('remove-file');
    typingIndicator = document.getElementById('typing-indicator');
    avatar = document.getElementById('avatar');
    avatarContainer = document.getElementById('avatar-container');
    avatarStatus = document.getElementById('avatar-status');
    avatar3DContainer = document.getElementById('avatar-3d-container');
    avatar3DStatus = document.getElementById('avatar-3d-status');
    avatarCanvas = document.getElementById('avatar-canvas');
    modeBtns = document.querySelectorAll('.mode-btn');
    userInfo = document.getElementById('user-info');
    headerLogin = document.getElementById('header-login');
    headerLogout = document.getElementById('header-logout');
    
    checkAuth();
    attachEventListeners();
    createAvatarSelector();  // Add avatar selection UI
    
    // Auto-start avatar mode
    avatar3DContainer.classList.add('active');
    init3DAvatar();
    
    // Mark avatar button as active
    modeBtns.forEach(btn => {
        if (btn.dataset.mode === 'avatar') {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
}

// Check if user is authenticated (but don't require it - guests allowed)
function checkAuth() {
    const savedToken = localStorage.getItem('mcp_auth_token');
    const savedEmail = localStorage.getItem('mcp_user_email');
    
    if (savedToken) {
        authToken = savedToken;
        isAuthenticated = true;
        userEmail = savedEmail || 'User';
    } else {
        // Guest mode - no token needed, chat is public
        isAuthenticated = false;
        userEmail = 'Guest';
    }
    updateUserUI();
}

// Update user info in header
function updateUserUI() {
    if (isAuthenticated && userEmail && userEmail !== 'Guest') {
        // Logged in user - show logout
        const displayName = userEmail.includes('guest_') ? '👤 Guest' : `👤 ${userEmail.split('@')[0]}`;
        userInfo.textContent = displayName;
        userInfo.style.display = 'inline';
        headerLogout.style.display = 'inline';
        headerLogin.style.display = 'none';
    } else {
        // Guest mode - show login option
        userInfo.textContent = '👤 Guest';
        userInfo.style.display = 'inline';
        headerLogout.style.display = 'none';
        headerLogin.style.display = 'inline';
    }
}

// Logout function
function logout() {
    localStorage.removeItem('mcp_auth_token');
    localStorage.removeItem('mcp_user_email');
    authToken = null;
    isAuthenticated = false;
    userEmail = null;
    window.location.href = '/';  // Stay on chat as guest after logout
}

// ==================== 3D Avatar Setup ====================

function init3DAvatar() {
    if (avatar3DLoaded) return;
    
    const container = avatar3DContainer;
    const canvas = avatarCanvas;
    
    // Scene
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);
    
    // Camera
    camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 100);
    camera.position.set(0, 1.5, 2);
    
    // Renderer
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    
    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
    scene.add(ambientLight);
    
    const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
    directionalLight.position.set(5, 10, 7.5);
    scene.add(directionalLight);
    
    const fillLight = new THREE.DirectionalLight(0x00C896, 0.3);
    fillLight.position.set(-5, 5, -5);
    scene.add(fillLight);
    
    // Controls
    const controls = new OrbitControls(camera, canvas);
    controls.target.set(0, 1.2, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.minDistance = 1;
    controls.maxDistance = 5;
    controls.update();
    
    // Clock for animations
    clock = new THREE.Clock();
    
    // Load avatar
    loadAvatar();
    
    // Handle resize
    window.addEventListener('resize', onWindowResize);
    
    // Start animation loop
    animate();
    
    avatar3DLoaded = true;
}

function loadAvatar(avatarId = null) {
    const loader = new GLTFLoader();
    
    // Get avatar from gallery or use default
    const selectedId = avatarId || currentAvatarId;
    const avatarData = AVATAR_GALLERY.find(a => a.id === selectedId) || AVATAR_GALLERY[0];
    const avatarUrl = avatarData.url;
    
    // Clear existing avatar if any
    if (avatar3D) {
        scene.remove(avatar3D);
        avatar3D = null;
        mouthMorphTarget = null;
        visemeInfluences = {};
    }
    
    avatar3DStatus.textContent = `Loading ${avatarData.name}...`;
    loader.load(
        avatarUrl,
        (gltf) => {
            avatar3D = gltf.scene;
            avatar3D.position.set(0, 0, 0);
            avatar3D.scale.set(1, 1, 1);
            scene.add(avatar3D);
            // Find mesh with morph targets for lip sync
            avatar3D.traverse((child) => {
                if (child.isMesh && child.morphTargetInfluences && child.morphTargetDictionary) {
                    mouthMorphTarget = child;
                    // Map all viseme morph targets
                    for (const visemeName of VISEME_NAMES) {
                        if (child.morphTargetDictionary[visemeName] !== undefined) {
                            visemeInfluences[visemeName] = child.morphTargetDictionary[visemeName];
                        }
                    }
                    console.log('Found viseme morph targets:', Object.keys(visemeInfluences));
                }
            });
            // Setup animations if available
            if (gltf.animations && gltf.animations.length > 0) {
                mixer = new THREE.AnimationMixer(avatar3D);
                const idleAction = mixer.clipAction(gltf.animations[0]);
                idleAction.play();
            }
            avatar3DStatus.textContent = `${avatarData.name} - Click microphone to speak`;
            console.log(`Avatar ${avatarData.name} loaded successfully`);
        },
        (progress) => {
            const percent = Math.round((progress.loaded / progress.total) * 100);
            avatar3DStatus.textContent = `Loading ${avatarData.name}... ${percent}%`;
        },
        (error) => {
            console.error('Error loading avatar:', error);
            avatar3DStatus.textContent = 'Failed to load avatar. Please check your network or choose another avatar.';
        }
    );
}



// Avatar Selection
function createAvatarSelector() {
    const selectorHTML = `
        <div class="avatar-selector" id="avatar-selector">
            <button class="avatar-selector-toggle" id="avatar-selector-toggle" title="Change Avatar">
                👤 Change Avatar
            </button>
            <div class="avatar-selector-dropdown" id="avatar-selector-dropdown">
                <div class="avatar-selector-title">Choose Your Assistant</div>
                ${AVATAR_GALLERY.map(av => `
                    <div class="avatar-option ${av.id === currentAvatarId ? 'selected' : ''}" 
                         data-avatar-id="${av.id}">
                        <span class="avatar-option-thumb">${av.thumbnail}</span>
                        <div class="avatar-option-info">
                            <div class="avatar-option-name">${av.name}</div>
                            <div class="avatar-option-desc">${av.description}</div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
    
    // Insert into header
    const headerRight = document.querySelector('.header-right');
    if (headerRight) {
        headerRight.insertAdjacentHTML('afterbegin', selectorHTML);
        
        // Attach events
        const toggle = document.getElementById('avatar-selector-toggle');
        const dropdown = document.getElementById('avatar-selector-dropdown');
        
        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('show');
        });
        
        // Close when clicking outside
        document.addEventListener('click', () => {
            dropdown.classList.remove('show');
        });
        
        // Avatar selection
        document.querySelectorAll('.avatar-option').forEach(option => {
            option.addEventListener('click', (e) => {
                e.stopPropagation();
                const avatarId = option.dataset.avatarId;
                selectAvatar(avatarId);
                dropdown.classList.remove('show');
            });
        });
    }
}

function selectAvatar(avatarId) {
    currentAvatarId = avatarId;
    localStorage.setItem('selectedAvatar', avatarId);
    
    // Update selected state in UI
    document.querySelectorAll('.avatar-option').forEach(opt => {
        opt.classList.toggle('selected', opt.dataset.avatarId === avatarId);
    });
    
    // Reload avatar
    if (avatar3DLoaded) {
        loadAvatar(avatarId);
    }
    
    const avatarData = AVATAR_GALLERY.find(a => a.id === avatarId);
    console.log(`Switched to avatar: ${avatarData?.name}`);
}

function onWindowResize() {
    if (!avatar3DContainer || !camera || !renderer) return;
    
    camera.aspect = avatar3DContainer.clientWidth / avatar3DContainer.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(avatar3DContainer.clientWidth, avatar3DContainer.clientHeight);
}

function animate() {
    requestAnimationFrame(animate);
    
    const delta = clock ? clock.getDelta() : 0.016;
    
    if (mixer) {
        mixer.update(delta);
    }
    
    // Viseme-based lip sync
    if (mouthMorphTarget && Object.keys(visemeInfluences).length > 0) {
        // Smooth transition between visemes
        visemeBlendFactor = Math.min(visemeBlendFactor + delta * 12, 1);
        
        // Reset all visemes first (with smooth decay)
        for (const visemeName of VISEME_NAMES) {
            if (visemeInfluences[visemeName] !== undefined) {
                const index = visemeInfluences[visemeName];
                const currentValue = mouthMorphTarget.morphTargetInfluences[index];
                
                if (visemeName === targetViseme) {
                    // Blend towards target viseme
                    const targetValue = 0.7;  // Max mouth open amount (0.7 = natural)
                    mouthMorphTarget.morphTargetInfluences[index] = 
                        currentValue + (targetValue - currentValue) * visemeBlendFactor;
                } else {
                    // Decay other visemes
                    mouthMorphTarget.morphTargetInfluences[index] = currentValue * 0.85;
                }
            }
        }
    } else if (avatar3D) {
        // Fallback avatar: scale the mouth mesh
        const mouth = avatar3D.getObjectByName('mouth');
        if (mouth && targetViseme !== 'viseme_sil') {
            mouth.scale.y = 1 + Math.sin(Date.now() * 0.02) * 0.5;
        } else if (mouth) {
            mouth.scale.y = 1;
        }
    }
    
    // Idle animation for fallback avatar
    if (avatar3D && !mixer) {
        avatar3D.rotation.y = Math.sin(Date.now() * 0.001) * 0.1;
    }
    
    if (renderer && scene && camera) {
        renderer.render(scene, camera);
    }
}

// ==================== Text-to-Viseme Lip Sync ====================

function textToVisemes(text) {
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
}

function startTextLipSync(text, durationMs) {
    stopLipSync();
    
    const visemes = textToVisemes(text);
    if (visemes.length === 0) return;
    
    // Calculate timing - spread visemes over speech duration
    const msPerViseme = durationMs / visemes.length;
    let visemeIndex = 0;
    
    lipSyncInterval = setInterval(() => {
        if (visemeIndex >= visemes.length) {
            stopLipSync();
            return;
        }
        
        targetViseme = visemes[visemeIndex];
        visemeBlendFactor = 0;  // Reset blend for smooth transition
        visemeIndex++;
    }, msPerViseme);
}

function stopLipSync() {
    if (lipSyncInterval) {
        clearInterval(lipSyncInterval);
        lipSyncInterval = null;
    }
    targetViseme = 'viseme_sil';
    visemeBlendFactor = 0;
    
    // Reset all visemes
    if (mouthMorphTarget && Object.keys(visemeInfluences).length > 0) {
        for (const visemeName of VISEME_NAMES) {
            if (visemeInfluences[visemeName] !== undefined) {
                const index = visemeInfluences[visemeName];
                mouthMorphTarget.morphTargetInfluences[index] = 0;
            }
        }
    }
}

// ==================== Audio Analysis (Legacy Fallback) ====================

let currentAudioSource = null;

function setupAudioAnalyser(audioElement) {
    try {
        if (!audioContext) {
            audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }
        
        // Resume context if suspended (browser autoplay policy)
        if (audioContext.state === 'suspended') {
            audioContext.resume();
        }
        
        // Disconnect previous source if exists
        if (currentAudioSource) {
            try {
                currentAudioSource.disconnect();
            } catch (e) { /* ignore */ }
        }
        
        currentAudioSource = audioContext.createMediaElementSource(audioElement);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        
        currentAudioSource.connect(analyser);
        analyser.connect(audioContext.destination);
        
        dataArray = new Uint8Array(analyser.frequencyBinCount);
        console.log('Audio analyser setup for lip sync');
    } catch (e) {
        console.warn('Could not setup audio analyser:', e);
        // Fall back to simulated lip sync
        startSimulatedLipSync();
    }
}

// Simulated lip sync for browser TTS (speechSynthesis can't be analyzed)
function startSimulatedLipSync() {
    if (lipSyncInterval) clearInterval(lipSyncInterval);
    
    // Create fake audio data that simulates talking
    if (!dataArray) {
        dataArray = new Uint8Array(128);
    }
    
    lipSyncInterval = setInterval(() => {
        // Generate random mouth movement to simulate talking
        const baseLevel = 60 + Math.random() * 80;
        for (let i = 0; i < dataArray.length; i++) {
            dataArray[i] = baseLevel + Math.random() * 40;
        }
    }, 50); // Update every 50ms
}

function stopSimulatedLipSync() {
    if (lipSyncInterval) {
        clearInterval(lipSyncInterval);
        lipSyncInterval = null;
    }
    // Reset mouth
    if (dataArray) {
        dataArray.fill(0);
    }
}

// ==================== Event Listeners ====================

function attachEventListeners() {
    // Header auth buttons
    if (headerLogout) {
        headerLogout.addEventListener('click', logout);
    }
    if (headerLogin) {
        headerLogin.addEventListener('click', () => {
            window.location.href = '/login';
        });
    }

    // Mode toggle
    modeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            modeBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentMode = btn.dataset.mode;
            
            // Hide all avatar containers
            avatarContainer.classList.remove('active');
            avatar3DContainer.classList.remove('active');
            
            if (currentMode === 'voice') {
                avatarContainer.classList.add('active');
                avatar.className = 'avatar idle';
                avatarStatus.textContent = 'Click the microphone to speak';
            } else if (currentMode === 'avatar') {
                avatar3DContainer.classList.add('active');
                init3DAvatar();
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
            
            if (currentMode === 'voice') {
                avatar.className = 'avatar listening';
                avatarStatus.textContent = 'Recording... Click to stop';
            } else if (currentMode === 'avatar') {
                avatar3DStatus.textContent = 'Recording... Click to stop';
            }
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
    if (currentMode === 'voice') {
        avatar.className = 'avatar thinking';
        avatarStatus.textContent = 'Processing...';
    } else if (currentMode === 'avatar') {
        avatar3DStatus.textContent = 'Processing...';
    }
    
    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
    const formData = new FormData();
    formData.append('audio', audioBlob, 'recording.webm');

    try {
        typingIndicator.classList.add('active');
        scrollToBottom();

        const response = await fetch(`${API_URL}/voice`, {
            method: 'POST',
            headers: authToken ? { 'Authorization': `Bearer ${authToken}` } : {},
            body: formData
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Voice request failed (${response.status})`);
        }

        // Check content type - could be audio or JSON (for browser TTS fallback)
        const contentType = response.headers.get('Content-Type');
        
        if (contentType && contentType.includes('application/json')) {
            // Server returned JSON - use browser TTS
            const data = await response.json();
            
            // Show user transcription
            if (data.transcription) {
                addMessage(data.transcription, 'user');
            }
            
            // Show bot response
            if (data.response) {
                addMessage(data.response, 'bot');
            }
            
            // Use browser's speechSynthesis for TTS with proper lip sync
            if (data.use_browser_tts && data.response && 'speechSynthesis' in window) {
                speakText(data.response);  // Use centralized speakText with viseme lip sync
            }
        } else {
            // Server returned audio
            const audioResponse = await response.blob();
            const transcription = response.headers.get('X-Transcription');
            const responseText = response.headers.get('X-Response-Text');
            const decodedResponseText = responseText ? decodeURIComponent(responseText) : '';

            // Show user transcription
            if (transcription) {
                addMessage(transcription, 'user');
            }

            // Show bot response text
            if (decodedResponseText) {
                addMessage(decodedResponseText, 'bot');
            }

            // Play audio response with viseme lip sync
            const audioUrl = URL.createObjectURL(audioResponse);
            const audio = new Audio(audioUrl);
            
            // Start text-to-viseme lip sync based on response text
            if (currentMode === 'avatar' && decodedResponseText) {
                avatar3DStatus.textContent = 'Speaking...';
                
                // Estimate audio duration (will be more accurate than TTS estimation)
                audio.addEventListener('loadedmetadata', () => {
                    const durationMs = audio.duration * 1000;
                    startTextLipSync(decodedResponseText, durationMs);
                }, { once: true });
            } else if (currentMode === 'voice') {
                avatar.className = 'avatar speaking';
                avatarStatus.textContent = 'Speaking...';
            }
            
            audio.play();
            
            audio.onended = () => {
                stopLipSync();
                if (currentMode === 'voice') {
                    avatar.className = 'avatar idle';
                    avatarStatus.textContent = 'Click the microphone to speak';
                } else if (currentMode === 'avatar') {
                    avatar3DStatus.textContent = 'Click microphone to speak';
                }
                URL.revokeObjectURL(audioUrl);
            };
        }

    } catch (error) {
        console.error('Voice error:', error);
        const errorMsg = error.message || 'Unknown error';
        addMessage(`Sorry, voice processing failed: ${errorMsg}`, 'bot');
        if (currentMode === 'voice') {
            avatar.className = 'avatar idle';
            avatarStatus.textContent = 'Click the microphone to speak';
        } else if (currentMode === 'avatar') {
            avatar3DStatus.textContent = 'Click microphone to speak';
        }
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
        const response = await fetch(`${API_URL}/chat`, {
            method: 'POST',
            headers: authToken ? { 'Authorization': `Bearer ${authToken}` } : {},
            body: formData
        });

        if (!response.ok) {
            throw new Error('Chat request failed');
        }

        const data = await response.json();
        conversationId = data.conversation_id;
        addMessage(data.response, 'bot');

        // Auto-speak response in voice/avatar modes
        if ((currentMode === 'voice' || currentMode === 'avatar') && data.response && 'speechSynthesis' in window) {
            speakText(data.response);
        }

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

// Speak text using browser TTS with viseme lip sync
function speakText(text) {
    // Cancel any ongoing speech
    speechSynthesis.cancel();
    stopLipSync();
    
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-US';
    utterance.rate = 1.0;
    
    // Estimate speech duration (~150 words per minute for TTS)
    const wordCount = text.split(/\s+/).length;
    const estimatedDurationMs = (wordCount / 150) * 60 * 1000;
    const minDuration = 1000;  // At least 1 second
    const durationMs = Math.max(estimatedDurationMs, minDuration);
    
    // Start text-to-viseme lip sync
    if (currentMode === 'avatar') {
        avatar3DStatus.textContent = 'Speaking...';
        startTextLipSync(text, durationMs);
        
        utterance.onend = () => {
            stopLipSync();
            avatar3DStatus.textContent = 'Click microphone to speak';
        };
        utterance.onerror = () => {
            stopLipSync();
            avatar3DStatus.textContent = 'Ready';
        };
    } else if (currentMode === 'voice') {
        avatar.className = 'avatar speaking';
        avatarStatus.textContent = 'Speaking...';
        utterance.onend = () => {
            avatar.className = 'avatar idle';
            avatarStatus.textContent = 'Click the microphone to speak';
        };
    }
    
    speechSynthesis.speak(utterance);
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
