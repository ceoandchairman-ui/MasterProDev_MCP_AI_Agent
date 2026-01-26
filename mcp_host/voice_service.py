"""Voice Processing Service - STT and TTS with Multiple Fallbacks"""

import logging
import io
import asyncio
from typing import Optional, Tuple
from openai import OpenAI
import os
import httpx

# Edge TTS (Free, High Quality)
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

logger = logging.getLogger(__name__)


class VoiceService:
    """Handles speech-to-text and text-to-speech conversion with multiple fallbacks"""
    
    # Edge TTS voice options (natural-sounding, free)
    EDGE_VOICES = {
        "female_us": "en-US-JennyNeural",
        "male_us": "en-US-GuyNeural",
        "female_uk": "en-GB-SoniaNeural",
        "male_uk": "en-GB-RyanNeural",
        "female_au": "en-AU-NatashaNeural",
    }
    
    def __init__(self):
        # OpenAI (Primary - best quality, costs money)
        self.openai_key = os.environ.get("OPENAI_API_KEY")
        if not self.openai_key:
            logger.warning("⚠️ OPENAI_API_KEY not set - using free alternatives")
            self.client = None
        else:
            self.client = OpenAI(api_key=self.openai_key)
            logger.info("✓ Voice service initialized with OpenAI (primary)")
        
        # Edge TTS (Free, high quality - recommended fallback)
        if EDGE_TTS_AVAILABLE:
            logger.info("✓ Edge TTS available (free, high quality)")
        else:
            logger.warning("⚠️ Edge TTS not installed (pip install edge-tts)")
        
        # Hugging Face Inference API (Fallback for STT)
        self.hf_token = os.environ.get("HUGGINGFACE_API_KEY") or os.environ.get("HF_TOKEN")
        if self.hf_token:
            logger.info("✓ Hugging Face API token found (STT fallback enabled)")
        elif not self.client:
            logger.warning("⚠️ No OPENAI_API_KEY or HUGGINGFACE_API_KEY - STT limited")
        
        # Hugging Face model endpoints
        self.hf_stt_model = os.environ.get("HF_STT_MODEL", "openai/whisper-large-v3-turbo")
        self.hf_api_base = "https://router.huggingface.co/hf-inference/models"
        
        # Alternative STT models
        self.hf_stt_alternatives = [
            "openai/whisper-large-v3",
        ]
        
        # Default Edge voice
        self.default_edge_voice = os.environ.get("EDGE_TTS_VOICE", "en-US-JennyNeural")
    
    async def speech_to_text(self, audio_data: bytes, filename: str = "audio.webm") -> str:
        """
        Convert audio to text using OpenAI Whisper (primary) or Hugging Face (fallback)
        
        Args:
            audio_data: Raw audio bytes
            filename: Original filename (for format detection)
            
        Returns:
            Transcribed text
        """
        # Try OpenAI first
        if self.client:
            try:
                audio_file = io.BytesIO(audio_data)
                audio_file.name = filename
                
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )
                
                logger.info(f"🎤 STT (OpenAI): '{transcript[:50]}...'")
                return transcript
                
            except Exception as e:
                logger.error(f"❌ OpenAI STT Error: {e}")
                if not self.hf_token:
                    raise Exception(f"Speech-to-text failed: {str(e)}")
                logger.info("Falling back to Hugging Face...")
        
        # Fallback to Hugging Face Inference API
        if self.hf_token:
            # Try primary model first, then alternatives
            models_to_try = [self.hf_stt_model] + self.hf_stt_alternatives
            last_error = None
            
            # Determine content type from filename
            content_type = "audio/webm"
            ext = filename.lower().split('.')[-1] if '.' in filename else 'webm'
            content_types = {
                'webm': 'audio/webm',
                'mp3': 'audio/mpeg',
                'wav': 'audio/wav',
                'flac': 'audio/flac',
                'm4a': 'audio/m4a',
                'ogg': 'audio/ogg',
            }
            content_type = content_types.get(ext, 'audio/webm')
            
            for model in models_to_try:
                try:
                    headers = {
                        "Authorization": f"Bearer {self.hf_token}",
                        "Content-Type": content_type
                    }
                    url = f"{self.hf_api_base}/{model}"
                    
                    logger.info(f"🎤 Trying STT model {model} with {content_type}...")
                    
                    async with httpx.AsyncClient(timeout=60.0) as client:
                        response = await client.post(url, headers=headers, content=audio_data)
                        
                        # Check for model loading (503) or unsupported format
                        if response.status_code == 503:
                            logger.warning(f"⚠️ Model {model} is loading, trying next...")
                            continue
                        
                        if response.status_code == 400:
                            error_detail = response.text
                            logger.warning(f"⚠️ Model {model} rejected audio: {error_detail[:100]}")
                            continue
                            
                        response.raise_for_status()
                        result = response.json()
                        
                        transcript = result.get("text", "")
                        if transcript:
                            logger.info(f"🎤 STT (HuggingFace/{model}): '{transcript[:50]}...'")
                            return transcript
                        else:
                            logger.warning(f"⚠️ Model {model} returned empty transcription")
                            continue
                    
                except Exception as e:
                    logger.warning(f"⚠️ HF model {model} failed: {e}")
                    last_error = e
                    continue
            
            raise Exception(f"Speech-to-text failed (tried {len(models_to_try)} models): {str(last_error)}")
        
        raise Exception("No STT service available - set OPENAI_API_KEY or HUGGINGFACE_API_KEY")
    
    async def text_to_speech(
        self, 
        text: str, 
        voice: str = "alloy",
        model: str = "tts-1"
    ) -> Tuple[Optional[bytes], Optional[str]]:
        """
        Convert text to speech with multiple fallbacks.
        
        Priority:
        1. OpenAI TTS (best quality, paid)
        2. Edge TTS (free, high quality)
        3. Return None → browser speechSynthesis
        
        Args:
            text: Text to convert
            voice: Voice preference
            model: TTS model (OpenAI only)
            
        Returns:
            Tuple of (audio_bytes, audio_format) or (None, None) for browser fallback
        """
        # Clean text for TTS
        clean_text = text[:4096].strip()
        if not clean_text:
            return None, None
        
        # 1. Try OpenAI first (best quality)
        if self.client:
            try:
                response = self.client.audio.speech.create(
                    model=model,
                    voice=voice,
                    input=clean_text
                )
                audio_bytes = response.content
                logger.info(f"🔊 TTS (OpenAI): Generated {len(audio_bytes)} bytes")
                return audio_bytes, "audio/mpeg"
                
            except Exception as e:
                logger.warning(f"⚠️ OpenAI TTS failed: {e}")
        
        # 2. Try Edge TTS (free, high quality)
        if EDGE_TTS_AVAILABLE:
            try:
                audio_bytes = await self._edge_tts(clean_text)
                if audio_bytes:
                    logger.info(f"🔊 TTS (Edge): Generated {len(audio_bytes)} bytes")
                    return audio_bytes, "audio/mpeg"
            except Exception as e:
                logger.warning(f"⚠️ Edge TTS failed: {e}")
        
        # 3. Return None - frontend will use browser speechSynthesis
        logger.info("ℹ️ Using browser TTS fallback")
        return None, None
    
    async def _edge_tts(self, text: str) -> Optional[bytes]:
        """Generate speech using Edge TTS (Microsoft's free TTS)"""
        try:
            communicate = edge_tts.Communicate(text, self.default_edge_voice)
            
            # Collect audio chunks
            audio_chunks = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])
            
            if audio_chunks:
                return b"".join(audio_chunks)
            return None
            
        except Exception as e:
            logger.error(f"Edge TTS error: {e}")
            raise
        
        # No TTS available - return None for browser fallback
        logger.warning("⚠️ No TTS service configured, returning None for browser fallback")
        return None


# Singleton instance
voice_service = VoiceService()
