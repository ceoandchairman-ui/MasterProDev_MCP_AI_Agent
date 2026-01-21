"""Voice Processing Service - STT and TTS with Hugging Face Fallbacks"""

import logging
import io
from typing import Optional
from openai import OpenAI
import os
import httpx

logger = logging.getLogger(__name__)


class VoiceService:
    """Handles speech-to-text and text-to-speech conversion with Hugging Face fallbacks"""
    
    def __init__(self):
        # OpenAI (Primary)
        self.openai_key = os.environ.get("OPENAI_API_KEY")
        if not self.openai_key:
            logger.warning("⚠️ OPENAI_API_KEY not set - using Hugging Face fallbacks")
            self.client = None
        else:
            self.client = OpenAI(api_key=self.openai_key)
            logger.info("✓ Voice service initialized with OpenAI (primary)")
        
        # Hugging Face Inference API (Fallback)
        self.hf_token = os.environ.get("HUGGINGFACE_API_KEY") or os.environ.get("HF_TOKEN")
        if self.hf_token:
            logger.info("✓ Hugging Face API token found (fallback enabled)")
        elif not self.client:
            logger.warning("⚠️ No OPENAI_API_KEY or HUGGINGFACE_API_KEY - voice features limited")
        
        # Hugging Face model endpoints
        self.hf_stt_model = os.environ.get("HF_STT_MODEL", "openai/whisper-base")
        self.hf_tts_model = os.environ.get("HF_TTS_MODEL", "microsoft/speecht5_tts")
        self.hf_api_base = "https://api-inference.huggingface.co/models"
    
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
            try:
                headers = {"Authorization": f"Bearer {self.hf_token}"}
                url = f"{self.hf_api_base}/{self.hf_stt_model}"
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, headers=headers, content=audio_data)
                    response.raise_for_status()
                    result = response.json()
                    
                    transcript = result.get("text", "")
                    logger.info(f"🎤 STT (HuggingFace): '{transcript[:50]}...'")
                    return transcript
                
            except Exception as e:
                logger.error(f"❌ HuggingFace STT Error: {e}")
                raise Exception(f"Speech-to-text failed: {str(e)}")
        
        raise Exception("No STT service available - set OPENAI_API_KEY or HUGGINGFACE_API_KEY")
    
    async def text_to_speech(
        self, 
        text: str, 
        voice: str = "alloy",
        model: str = "tts-1"
    ) -> bytes:
        """
        Convert text to speech using OpenAI TTS (primary) or Hugging Face (fallback)
        
        Args:
            text: Text to convert
            voice: Voice model (alloy, echo, fable, onyx, nova, shimmer) - OpenAI only
            model: TTS model (tts-1 or tts-1-hd) - OpenAI only
            
        Returns:
            Audio bytes (MP3 or FLAC format)
        """
        # Try OpenAI first
        if self.client:
            try:
                response = self.client.audio.speech.create(
                    model=model,
                    voice=voice,
                    input=text[:4096]  # Max 4096 chars
                )
                
                audio_bytes = response.content
                logger.info(f"🔊 TTS (OpenAI): Generated {len(audio_bytes)} bytes")
                return audio_bytes
                
            except Exception as e:
                logger.error(f"❌ OpenAI TTS Error: {e}")
                if not self.hf_token:
                    raise Exception(f"Text-to-speech failed: {str(e)}")
                logger.info("Falling back to Hugging Face...")
        
        # Fallback to Hugging Face Inference API
        if self.hf_token:
            try:
                headers = {"Authorization": f"Bearer {self.hf_token}"}
                url = f"{self.hf_api_base}/{self.hf_tts_model}"
                payload = {"inputs": text[:1000]}  # HF has smaller limits
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(url, headers=headers, json=payload)
                    response.raise_for_status()
                    
                    audio_bytes = response.content
                    logger.info(f"🔊 TTS (HuggingFace): Generated {len(audio_bytes)} bytes")
                    return audio_bytes
                
            except Exception as e:
                logger.error(f"❌ HuggingFace TTS Error: {e}")
                raise Exception(f"Text-to-speech failed: {str(e)}")
        
        raise Exception("No TTS service available - set OPENAI_API_KEY or HUGGINGFACE_API_KEY")


# Singleton instance
voice_service = VoiceService()
