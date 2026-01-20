"""Voice Processing Service - STT and TTS"""

import logging
import io
from typing import Optional
from openai import OpenAI
import os

logger = logging.getLogger(__name__)


class VoiceService:
    """Handles speech-to-text and text-to-speech conversion"""
    
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.warning("⚠️ OPENAI_API_KEY not set - voice features disabled")
            self.client = None
        else:
            self.client = OpenAI(api_key=api_key)
            logger.info("✓ Voice service initialized with OpenAI")
    
    async def speech_to_text(self, audio_data: bytes, filename: str = "audio.webm") -> str:
        """
        Convert audio to text using OpenAI Whisper
        
        Args:
            audio_data: Raw audio bytes
            filename: Original filename (for format detection)
            
        Returns:
            Transcribed text
        """
        if not self.client:
            raise Exception("Voice service not initialized - missing OPENAI_API_KEY")
        
        try:
            # Create file-like object
            audio_file = io.BytesIO(audio_data)
            audio_file.name = filename
            
            # Call Whisper API
            transcript = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text"
            )
            
            logger.info(f"🎤 STT: Transcribed {len(audio_data)} bytes → '{transcript[:50]}...'")
            return transcript
            
        except Exception as e:
            logger.error(f"❌ STT Error: {e}")
            raise Exception(f"Speech-to-text failed: {str(e)}")
    
    async def text_to_speech(
        self, 
        text: str, 
        voice: str = "alloy",
        model: str = "tts-1"
    ) -> bytes:
        """
        Convert text to speech using OpenAI TTS
        
        Args:
            text: Text to convert
            voice: Voice model (alloy, echo, fable, onyx, nova, shimmer)
            model: TTS model (tts-1 or tts-1-hd)
            
        Returns:
            Audio bytes (MP3 format)
        """
        if not self.client:
            raise Exception("Voice service not initialized - missing OPENAI_API_KEY")
        
        try:
            # Call TTS API
            response = self.client.audio.speech.create(
                model=model,
                voice=voice,
                input=text[:4096]  # Max 4096 chars
            )
            
            audio_bytes = response.content
            logger.info(f"🔊 TTS: Generated {len(audio_bytes)} bytes from '{text[:50]}...'")
            return audio_bytes
            
        except Exception as e:
            logger.error(f"❌ TTS Error: {e}")
            raise Exception(f"Text-to-speech failed: {str(e)}")


# Singleton instance
voice_service = VoiceService()
