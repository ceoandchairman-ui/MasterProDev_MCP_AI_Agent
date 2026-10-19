"""OCR engines behind one interface: Tesseract (local binary) or a vision-capable model. Used for uploaded images,
scanned PDFs in uploads, and scanned documents in the knowledge-base indexer."""

import asyncio
import base64
import io
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import httpx

logger = logging.getLogger(__name__)

MAX_OCR_CHARS = 20000


class OcrError(RuntimeError):
    pass


@dataclass
class OcrResult:
    text: str
    confidence: Optional[float] = None  # 0-1 when the engine reports it
    engine: str = ""


class OcrEngine(Protocol):
    async def read(self, image_bytes: bytes, languages: str = "eng+fra") -> OcrResult: ...


def strip_metadata(image_bytes: bytes) -> bytes:
    """Re-encode the pixels only, dropping EXIF (location, device) and other metadata. Returns PNG bytes."""
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        img.load()
        clean = Image.new(img.mode, img.size)
        clean.putdata(list(img.getdata()))
        out = io.BytesIO()
        clean.convert("RGB" if clean.mode not in ("RGB", "L") else clean.mode).save(out, format="PNG")
        return out.getvalue()


class TesseractOcr:
    """Needs `pytesseract` and the tesseract binary with the eng and fra language packs."""

    async def read(self, image_bytes: bytes, languages: str = "eng+fra") -> OcrResult:
        def run() -> OcrResult:
            try:
                import pytesseract
                from PIL import Image
            except ImportError as exc:
                raise OcrError("Tesseract OCR is not installed") from exc
            with Image.open(io.BytesIO(image_bytes)) as img:
                data = pytesseract.image_to_data(img, lang=languages, output_type=pytesseract.Output.DICT)
            words = [w for w in data.get("text", []) if w.strip()]
            confs = [float(c) for c, w in zip(data.get("conf", []), data.get("text", []), strict=False) if w.strip() and float(c) >= 0]
            text = " ".join(words)[:MAX_OCR_CHARS]
            return OcrResult(text, (sum(confs) / len(confs) / 100) if confs else None, "tesseract")

        try:
            return await asyncio.to_thread(run)
        except OcrError:
            raise
        except Exception as exc:
            raise OcrError(f"OCR failed: {type(exc).__name__}") from exc


class VisionModelOcr:
    """Any OpenAI-compatible chat endpoint with image input. The image goes to that vendor: configure per policy D13."""

    def __init__(self, base_url: str, api_key: str, model: str, client: Optional[httpx.AsyncClient] = None, timeout: float = 60.0):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key, self._model, self._client, self._timeout = api_key, model, client, timeout

    async def _ask(self, image_bytes: bytes, instruction: str, max_tokens: int) -> str:
        data_uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
        payload = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "messages": [{"role": "user", "content": [{"type": "text", "text": instruction}, {"type": "image_url", "image_url": {"url": data_uri}}]}],
        }
        headers = {"Authorization": f"Bearer {self._key}"}
        try:
            if self._client:
                resp = await self._client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            else:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(self._url, json=payload, headers=headers, timeout=self._timeout)
            resp.raise_for_status()
            return (resp.json()["choices"][0]["message"]["content"] or "").strip()
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise OcrError(f"Vision call failed: {type(exc).__name__}") from exc

    async def read(self, image_bytes: bytes, languages: str = "eng+fra") -> OcrResult:
        text = await self._ask(image_bytes, "Transcribe all text in this image exactly. Output only the text, nothing else.", 2000)
        return OcrResult(text[:MAX_OCR_CHARS], None, "vision")

    async def describe(self, image_bytes: bytes) -> str:
        """Short factual description for images that are not documents (screenshots, diagrams, photos)."""
        return (await self._ask(image_bytes, "Describe this image factually in at most 120 words. Include any visible text.", 300))[:2000]


__all__ = ["OcrEngine", "OcrError", "OcrResult", "TesseractOcr", "VisionModelOcr", "strip_metadata"]
