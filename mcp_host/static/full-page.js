/**
 * MasterProDev AI Agent - Full Page Chat with 3D Avatar
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

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
let userEmail = null;

// 3D Avatar State
let scene, camera, renderer, avatar3D, mixer, clock;
let audioContext, analyser, dataArray;
let avatar3DLoaded = false;
let mouthMorphTarget = null;

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
const avatar3DContainer = document.getElementById('avatar-3d-container');
const avatar3DStatus = document.getElementById('avatar-3d-status');
const avatarCanvas = document.getElementById('avatar-canvas');
const modeBtns = document.querySelectorAll('.mode-btn');
const userInfo = document.getElementById('user-info');
const headerLogin = document.getElementById('header-login');
const headerLogout = document.getElementById('header-logout');

// Initialize
async function init() {
    checkAuth();
    attachEventListeners();
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

function loadAvatar() {
    const loader = new GLTFLoader();
    
    // Use a sample avatar URL - this is a free CC0 model
    // You can replace with your own GLB file at /static/avatars/avatar.glb
    const avatarUrl = 'https://models.readyplayer.me/64bfa15f0e72c63d7c3934a6.glb?morphTargets=ARKit,Oculus+Visemes&textureAtlas=1024';
    
    avatar3DStatus.textContent = 'Loading 3D Avatar...';
    
    loader.load(
        avatarUrl,
        (gltf) => {
            avatar3D = gltf.scene;
            avatar3D.position.set(0, 0, 0);
            avatar3D.scale.set(1, 1, 1);
            scene.add(avatar3D);
            
            // Find mesh with morph targets for lip sync
            avatar3D.traverse((child) => {
                if (child.isMesh && child.morphTargetInfluences) {
                    mouthMorphTarget = child;
                    console.log('Found morph targets:', child.morphTargetDictionary);
                }
            });
            
            // Setup animations if available
            if (gltf.animations && gltf.animations.length > 0) {
                mixer = new THREE.AnimationMixer(avatar3D);
                const idleAction = mixer.clipAction(gltf.animations[0]);
                idleAction.play();
            }
            
            avatar3DStatus.textContent = 'Click microphone to speak';
            console.log('Avatar loaded successfully');
        },
        (progress) => {
            const percent = Math.round((progress.loaded / progress.total) * 100);
            avatar3DStatus.textContent = `Loading... ${percent}%`;
        },
        (error) => {
            console.error('Error loading avatar:', error);
            avatar3DStatus.textContent = 'Using fallback avatar';
            createFallbackAvatar();
        }
    );
}

function createFallbackAvatar() {
    // Create a simple geometric avatar as fallback
    const group = new THREE.Group();
    
    // Head
    const headGeometry = new THREE.SphereGeometry(0.3, 32, 32);
    const headMaterial = new THREE.MeshStandardMaterial({ color: 0x00C896 });
    const head = new THREE.Mesh(headGeometry, headMaterial);
    head.position.y = 1.5;
    group.add(head);
    
    // Eyes
    const eyeGeometry = new THREE.SphereGeometry(0.05, 16, 16);
    const eyeMaterial = new THREE.MeshStandardMaterial({ color: 0xffffff });
    
    const leftEye = new THREE.Mesh(eyeGeometry, eyeMaterial);
    leftEye.position.set(-0.1, 1.55, 0.25);
    group.add(leftEye);
    
    const rightEye = new THREE.Mesh(eyeGeometry, eyeMaterial);
    rightEye.position.set(0.1, 1.55, 0.25);
    group.add(rightEye);
    
    // Pupils
    const pupilGeometry = new THREE.SphereGeometry(0.02, 16, 16);
    const pupilMaterial = new THREE.MeshStandardMaterial({ color: 0x000000 });
    
    const leftPupil = new THREE.Mesh(pupilGeometry, pupilMaterial);
    leftPupil.position.set(-0.1, 1.55, 0.29);
    group.add(leftPupil);
    
    const rightPupil = new THREE.Mesh(pupilGeometry, pupilMaterial);
    rightPupil.position.set(0.1, 1.55, 0.29);
    group.add(rightPupil);
    
    // Mouth (will be animated)
    const mouthGeometry = new THREE.BoxGeometry(0.15, 0.03, 0.05);
    const mouthMaterial = new THREE.MeshStandardMaterial({ color: 0x6B5CE7 });
    const mouth = new THREE.Mesh(mouthGeometry, mouthMaterial);
    mouth.position.set(0, 1.4, 0.27);
    mouth.name = 'mouth';
    group.add(mouth);
    
    // Body
    const bodyGeometry = new THREE.CylinderGeometry(0.25, 0.3, 0.8, 32);
    const bodyMaterial = new THREE.MeshStandardMaterial({ color: 0x6B5CE7 });
    const body = new THREE.Mesh(bodyGeometry, bodyMaterial);
    body.position.y = 0.9;
    group.add(body);
    
    avatar3D = group;
    scene.add(avatar3D);
    
    avatar3DStatus.textContent = 'Click microphone to speak';
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
    
    // Audio-driven lip sync
    if (analyser && dataArray && avatar3D) {
        analyser.getByteFrequencyData(dataArray);
        const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
        const mouthOpenAmount = Math.min(average / 128, 1);
        
        // Animate mouth based on audio
        if (mouthMorphTarget && mouthMorphTarget.morphTargetDictionary) {
            // Try different morph target names
            const mouthTargets = ['jawOpen', 'viseme_aa', 'mouthOpen', 'jawForward'];
            for (const targetName of mouthTargets) {
                if (mouthMorphTarget.morphTargetDictionary[targetName] !== undefined) {
                    const index = mouthMorphTarget.morphTargetDictionary[targetName];
                    mouthMorphTarget.morphTargetInfluences[index] = mouthOpenAmount;
                    break;
                }
            }
        } else {
            // Fallback: scale the mouth mesh
            const mouth = avatar3D.getObjectByName('mouth');
            if (mouth) {
                mouth.scale.y = 1 + mouthOpenAmount * 3;
            }
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

// ==================== Audio Analysis ====================

function setupAudioAnalyser(audioElement) {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    
    const source = audioContext.createMediaElementSource(audioElement);
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 256;
    
    source.connect(analyser);
    analyser.connect(audioContext.destination);
    
    dataArray = new Uint8Array(analyser.frequencyBinCount);
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

        // Play audio response with lip sync
        const audioUrl = URL.createObjectURL(audioResponse);
        const audio = new Audio(audioUrl);
        
        // Setup audio analyser for 3D avatar lip sync
        if (currentMode === 'avatar') {
            audio.crossOrigin = 'anonymous';
            audio.addEventListener('canplaythrough', () => {
                setupAudioAnalyser(audio);
            }, { once: true });
            avatar3DStatus.textContent = 'Speaking...';
        } else {
            avatar.className = 'avatar speaking';
            avatarStatus.textContent = 'Speaking...';
        }
        
        audio.play();
        
        audio.onended = () => {
            if (currentMode === 'voice') {
                avatar.className = 'avatar idle';
                avatarStatus.textContent = 'Click the microphone to speak';
            } else if (currentMode === 'avatar') {
                avatar3DStatus.textContent = 'Click microphone to speak';
                // Reset mouth
                if (analyser) {
                    dataArray.fill(0);
                }
            }
            URL.revokeObjectURL(audioUrl);
        };

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
