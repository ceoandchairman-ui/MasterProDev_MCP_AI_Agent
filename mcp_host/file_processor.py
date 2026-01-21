"""File processing service for handling various file types"""

import logging
import io
import os
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
import httpx

logger = logging.getLogger(__name__)

# Try importing optional dependencies
try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    logger.info("PyPDF2 not available - PDF processing disabled")

try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    logger.info("python-docx not available - Word processing disabled")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.info("Pillow not available - image processing limited")

try:
    import moviepy.editor as mp
    MOVIEPY_AVAILABLE = True
except ImportError:
    MOVIEPY_AVAILABLE = False
    logger.info("moviepy not available - video processing disabled")


class FileProcessor:
    """Handles processing of various file types"""
    
    def __init__(self, openai_client=None, voice_service=None):
        self.openai_client = openai_client
        self.voice_service = voice_service
        
        # Supported file types
        self.audio_types = {'.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac'}
        self.video_types = {'.mp4', '.avi', '.mov', '.mkv', '.webm'}
        self.image_types = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        self.doc_types = {'.pdf', '.docx', '.doc', '.txt'}
    
    async def process_file(self, file_data: bytes, filename: str) -> Tuple[str, Optional[str]]:
        """
        Process uploaded file and extract content
        
        Args:
            file_data: Raw file bytes
            filename: Original filename
            
        Returns:
            Tuple of (extracted_text, file_type)
        """
        ext = Path(filename).suffix.lower()
        
        logger.info(f"📁 Processing file: {filename} ({len(file_data)} bytes)")
        
        # Audio files → STT
        if ext in self.audio_types:
            return await self._process_audio(file_data, filename), "audio"
        
        # Video files → Extract audio → STT
        elif ext in self.video_types:
            return await self._process_video(file_data, filename), "video"
        
        # Images → Vision analysis
        elif ext in self.image_types:
            return await self._process_image(file_data, filename), "image"
        
        # Documents → Text extraction
        elif ext == '.pdf':
            return self._process_pdf(file_data), "pdf"
        elif ext in {'.docx', '.doc'}:
            return self._process_docx(file_data), "docx"
        elif ext == '.txt':
            return file_data.decode('utf-8', errors='ignore'), "text"
        
        else:
            raise ValueError(f"Unsupported file type: {ext}")
    
    async def _process_audio(self, audio_data: bytes, filename: str) -> str:
        """Extract text from audio using STT"""
        if not self.voice_service:
            raise Exception("Voice service not initialized")
        
        try:
            transcript = await self.voice_service.speech_to_text(audio_data, filename)
            logger.info(f"🎤 Audio transcribed: {len(transcript)} chars")
            return f"[Audio transcription]\n{transcript}"
        except Exception as e:
            logger.error(f"Audio processing failed: {e}")
            raise
    
    async def _process_video(self, video_data: bytes, filename: str) -> str:
        """Extract audio from video and transcribe"""
        if not MOVIEPY_AVAILABLE:
            return "[Video uploaded - moviepy not installed, cannot process]"
        
        if not self.voice_service:
            raise Exception("Voice service not initialized")
        
        try:
            # Save video temporarily
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp_video:
                tmp_video.write(video_data)
                video_path = tmp_video.name
            
            # Extract audio
            video = mp.VideoFileClip(video_path)
            audio_path = video_path + ".mp3"
            video.audio.write_audiofile(audio_path, logger=None)
            video.close()
            
            # Read audio and transcribe
            with open(audio_path, 'rb') as f:
                audio_data = f.read()
            
            transcript = await self.voice_service.speech_to_text(audio_data, "audio.mp3")
            
            # Cleanup
            os.remove(video_path)
            os.remove(audio_path)
            
            logger.info(f"🎬 Video audio transcribed: {len(transcript)} chars")
            return f"[Video audio transcription]\n{transcript}"
            
        except Exception as e:
            logger.error(f"Video processing failed: {e}")
            return f"[Video uploaded - processing failed: {str(e)}]"
    
    async def _process_image(self, image_data: bytes, filename: str) -> str:
        """Analyze image using vision model"""
        if not self.openai_client:
            return "[Image uploaded - OpenAI API not configured for vision analysis]"
        
        try:
            import base64
            
            # Convert to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            # Use GPT-4 Vision
            response = self.openai_client.chat.completions.create(
                model="gpt-4-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Describe this image in detail. What do you see?"},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=500
            )
            
            description = response.choices[0].message.content
            logger.info(f"🖼️ Image analyzed: {len(description)} chars")
            return f"[Image analysis]\n{description}"
            
        except Exception as e:
            logger.error(f"Image processing failed: {e}")
            return f"[Image uploaded - analysis failed: {str(e)}]"
    
    def _process_pdf(self, pdf_data: bytes) -> str:
        """Extract text from PDF"""
        if not PDF_AVAILABLE:
            return "[PDF uploaded - PyPDF2 not installed, cannot extract text]"
        
        try:
            pdf_file = io.BytesIO(pdf_data)
            reader = PyPDF2.PdfReader(pdf_file)
            
            text_parts = []
            for page_num, page in enumerate(reader.pages):
                text = page.extract_text()
                if text.strip():
                    text_parts.append(f"Page {page_num + 1}:\n{text}")
            
            extracted_text = "\n\n".join(text_parts)
            logger.info(f"📄 PDF extracted: {len(extracted_text)} chars from {len(reader.pages)} pages")
            return f"[PDF content - {len(reader.pages)} pages]\n{extracted_text[:5000]}"  # Limit to 5000 chars
            
        except Exception as e:
            logger.error(f"PDF processing failed: {e}")
            return f"[PDF uploaded - extraction failed: {str(e)}]"
    
    def _process_docx(self, docx_data: bytes) -> str:
        """Extract text from Word document"""
        if not DOCX_AVAILABLE:
            return "[Word document uploaded - python-docx not installed, cannot extract text]"
        
        try:
            docx_file = io.BytesIO(docx_data)
            doc = Document(docx_file)
            
            text_parts = [paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()]
            extracted_text = "\n\n".join(text_parts)
            
            logger.info(f"📝 Word doc extracted: {len(extracted_text)} chars from {len(doc.paragraphs)} paragraphs")
            return f"[Word document content]\n{extracted_text[:5000]}"  # Limit to 5000 chars
            
        except Exception as e:
            logger.error(f"Word doc processing failed: {e}")
            return f"[Word document uploaded - extraction failed: {str(e)}]"


# Singleton instance
file_processor = None

def initialize_file_processor(openai_client=None, voice_service=None):
    """Initialize file processor with dependencies"""
    global file_processor
    file_processor = FileProcessor(openai_client, voice_service)
    return file_processor
