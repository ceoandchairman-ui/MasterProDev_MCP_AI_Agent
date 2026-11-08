# Voice Chat with Hugging Face Fallbacks

## Setup Complete ✅

Your voice chat now supports **multiple providers** with automatic fallback:

### STT (Speech-to-Text)
1. **Primary:** OpenAI Whisper API
2. **Fallback:** Hugging Face Inference API

### TTS (Text-to-Speech)
1. **Primary:** OpenAI TTS API  
2. **Fallback:** Hugging Face Inference API

---

## Environment Variables

Add these to Railway:

```bash
# Primary (OpenAI)
OPENAI_API_KEY=sk-...

# Fallback (Hugging Face)
HUGGINGFACE_API_KEY=hf_...
# or
HF_TOKEN=hf_...

# Optional: Override default models
HF_STT_MODEL=openai/whisper-base              # Default
HF_TTS_MODEL=microsoft/speecht5_tts            # Default
```

---

## Recommended Hugging Face Models

### STT Models (Fast to Slow):
- `openai/whisper-tiny` - Fastest, 39M params
- `openai/whisper-base` - **Default**, balanced, 74M params ⭐
- `distil-whisper/distil-small.en` - 6x faster than small
- `openai/whisper-small` - Better quality, 244M params
- `openai/whisper-medium` - High quality, 769M params

### TTS Models (Fast to Quality):
- `microsoft/speecht5_tts` - **Default**, fast, good quality ⭐
- `facebook/mms-tts-eng` - Meta's model
- `suno/bark-small` - Natural with emotions
- `suno/bark` - Best quality, slower

---

## How It Works

1. **With OpenAI API Key:**
   - Uses OpenAI Whisper + TTS (best quality, fastest)
   - Falls back to Hugging Face if OpenAI fails

2. **With Hugging Face API Key only:**
   - Uses Hugging Face Inference API exclusively
   - Free tier: 30,000 requests/month per model

3. **With both keys:**
   - Primary: OpenAI (better quality)
   - Fallback: Hugging Face (if OpenAI down or rate-limited)

---

## Get Hugging Face API Key

1. Go to https://huggingface.co
2. Sign up (free)
3. Settings → Access Tokens
4. Create new token (read permission)
5. Add to Railway as `HUGGINGFACE_API_KEY`

---

## Access Voice Chat

**URL:** `https://masterprodevmcpaiagent-production.up.railway.app/voice-chat`

**Features:**
- 🎙️ Click mic to record
- 🤖 Animated avatar responds
- 📝 See transcription in real-time
- 🔄 Same conversation history as text chat

---

## Cost Comparison

**OpenAI:**
- Whisper: $0.006 per minute
- TTS: $15 per 1M characters (~$0.015 per request)

**Hugging Face:**
- Free tier: 30,000 requests/month
- Pro: $9/month unlimited

**Railway Hosting:**
- Prometheus: ~$2-3/month
- Total: ~$2-3/month with HF free tier ⭐
