"""LLM Provider - Multi-model abstraction layer with fallback and mock support"""

import logging
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod
from enum import Enum
import json
import httpx
from mcp_host.config import settings

logger = logging.getLogger(__name__)


class LLMType(Enum):
    """Available LLM providers"""
    CLAUDE = "claude"  # Anthropic Claude (proprietary)
    BEDROCK = "bedrock"  # AWS Bedrock (proprietary)
    HUGGINGFACE = "huggingface"  # Hugging Face Inference API (open source)
    OLLAMA = "ollama"  # Ollama local (open source)


class LLMProvider(ABC):
    """Base class for LLM providers"""
    
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.available = False
    
    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize provider and check availability"""
        pass
    
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None
    ) -> str:
        """Generate text from prompt"""
        pass
    
    @abstractmethod
    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """Generate with tool calling capability"""
        pass


class HuggingFaceModelHandler(ABC):
    """Base class for handling different Hugging Face model capabilities."""
    
    @abstractmethod
    def prepare_tool_payload(self, payload: Dict[str, Any], tools: List[Dict[str, Any]]):
        """Modifies the payload to include tools in the model-specific format."""
        pass

    @abstractmethod
    def parse_tool_response(
        self, choice: Dict[str, Any], tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Parses the model's response to extract text and tool calls."""
        pass


class KimiModelHandler(HuggingFaceModelHandler):
    """Handler for Kimi-K2 native tool calling."""

    def prepare_tool_payload(self, payload: Dict[str, Any], tools: List[Dict[str, Any]]):
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

    def parse_tool_response(
        self, choice: Dict[str, Any], tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        message = choice.get("message", {})
        tool_calls = []

        if choice.get("finish_reason") == "tool_calls" and "tool_calls" in message:
            for tc in message.get("tool_calls", []):
                try:
                    arguments = json.loads(tc.get("function", {}).get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}
                
                tool_calls.append({
                    "id": tc.get("id"),
                    "function": tc.get("function", {}).get("name"),
                    "arguments": arguments,
                })
        
        return {
            "text": message.get("content", ""),
            "tool_calls": tool_calls,
            "finish_reason": choice.get("finish_reason", "stop"),
        }


class LlamaModelHandler(HuggingFaceModelHandler):
    """Fallback handler for Llama and other models without native tool calling."""

    def prepare_tool_payload(self, payload: Dict[str, Any], tools: List[Dict[str, Any]]):
        # Llama doesn't have a native tool format, so we don't modify the payload.
        # The agent must rely on text parsing of the response.
        pass

    def parse_tool_response(
        self, choice: Dict[str, Any], tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        message = choice.get("message", {})
        text_response = message.get("content", "")
        tool_calls = []

        # Fallback: very basic text search for tool names.
        if tools and text_response:
            for tool in tools:
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name and tool_name.lower() in text_response.lower():
                    tool_calls.append({
                        "id": f"fallback_{tool_name}",
                        "function": tool_name,
                        "arguments": {},  # Cannot reliably parse args from text
                    })

        return {
            "text": text_response,
            "tool_calls": tool_calls,
            "finish_reason": choice.get("finish_reason", "stop"),
        }


class BedrockProvider(LLMProvider):
    """AWS Bedrock LLM Provider (Proprietary)"""
    
    def __init__(self, model_name: str = "amazon.nova-pro-v1:0"):
        super().__init__(model_name)
        self.client = None
    
    async def initialize(self) -> bool:
        """Initialize Bedrock client"""
        try:
            import boto3
            from botocore.exceptions import NoCredentialsError, ClientError
            
            # Use bedrock-runtime client for text generation
            self.client = boto3.client(
                'bedrock-runtime',
                region_name='us-east-1'
            )
            
            # Test with a simple check (no list_foundation_models in runtime client)
            self.available = True
            logger.info(f"✓ AWS Bedrock initialized: {self.model_name}")
            return True
            
        except (NoCredentialsError, ClientError, ImportError) as e:
            logger.warning(f"⚠ AWS Bedrock unavailable: {e}")
            self.available = False
            return False
    
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None
    ) -> str:
        """Generate text using Bedrock"""
        if not self.available:
            raise RuntimeError("Bedrock provider not available")
        
        import json
        
        # Use invoke_model (works with older boto3)
        body = json.dumps({
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": max_tokens,
                "temperature": temperature
            }
        })
        
        response = self.client.invoke_model(
            modelId=self.model_name,
            body=body
        )
        
        response_body = json.loads(response.get('body').read())
        return response_body.get('results')[0].get('outputText', '')
    
    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """Generate with tool calling"""
        import json
        tool_prompt = f"{prompt}\n\nAvailable tools:\n{json.dumps(tools, indent=2)}"
        response = await self.generate(tool_prompt, max_tokens, temperature)
        
        return {
            "text": response,
            "tool_calls": []
        }


class HuggingFaceProvider(LLMProvider):
    """Hugging Face Inference API Provider using a factory for model-specific handlers."""
    
    # Fallback models in order of preference (free inference models)
    FALLBACK_MODELS = [
        "moonshotai/Kimi-K2-Instruct",  # Primary
        "meta-llama/Meta-Llama-3-8B-Instruct",
        "mistralai/Mistral-7B-Instruct-v0.2",
        "microsoft/Phi-3-mini-4k-instruct",
        "google/gemma-2-9b-it",
        "Qwen/Qwen2.5-7B-Instruct",
    ]
    
    def __init__(self, model_name: str = "moonshotai/Kimi-K2-Instruct"):
        super().__init__(model_name)
        self.api_key = None
        self.api_url = "https://router.huggingface.co/v1/chat/completions"
        self.handler = self._get_model_handler(model_name)
        self.current_model_index = 0
    
    def _get_model_handler(self, model_name: str) -> HuggingFaceModelHandler:
        """Factory to select the appropriate model handler."""
        model_name_lower = model_name.lower()
        if "kimi" in model_name_lower:
            logger.info("Instantiating KimiModelHandler.")
            return KimiModelHandler()
        else:
            logger.info("Instantiating LlamaModelHandler as fallback.")
            return LlamaModelHandler()

    async def initialize(self) -> bool:
        """Initialize Hugging Face client."""
        try:
            self.api_key = settings.HUGGINGFACE_API_KEY
            if not self.api_key:
                logger.warning("⚠ HUGGINGFACE_API_KEY not found")
                self.available = False
                return False
            
            self.available = True
            logger.info(f"✓ Hugging Face initialized: {self.model_name} (Handler: {self.handler.__class__.__name__})")
            return True
            
        except Exception as e:
            logger.warning(f"⚠ Hugging Face unavailable: {e}")
            self.available = False
            return False
    
    async def _try_model(self, model_name: str, messages: List[Dict], max_tokens: int, temperature: float) -> str:
        """Try a single model and return response or raise exception"""
        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.api_url, json=payload, headers=headers)

        if response.status_code >= 400:
            raise RuntimeError(f"Model {model_name} error: {response.status_code}")

        data = response.json()
        if not data.get("choices"):
            raise RuntimeError(f"Model {model_name} response missing choices")

        return data["choices"][0]["message"]["content"]
    
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None
    ) -> str:
        """Generate text using Hugging Face with automatic model fallback"""
        if not self.available:
            raise RuntimeError("Hugging Face provider not available")
        
        # Build messages for chat completion
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        # Try primary model first, then fallbacks
        models_to_try = [self.model_name] + [m for m in self.FALLBACK_MODELS if m != self.model_name]
        last_error = None
        
        for model in models_to_try:
            try:
                result = await self._try_model(model, messages, max_tokens, temperature)
                if model != self.model_name:
                    logger.info(f"✓ LLM fallback succeeded with {model}")
                return result
            except Exception as e:
                logger.warning(f"⚠️ LLM model {model} failed: {e}")
                last_error = e
                continue
        
        raise RuntimeError(f"All LLM models failed. Last error: {last_error}")
    
    async def _try_model_with_tools(self, model_name: str, messages: List[Dict], tools: List[Dict], max_tokens: int, temperature: float) -> Dict[str, Any]:
        """Try a single model with tools and return response or raise exception"""
        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        
        # Get handler for this model
        handler = self._get_model_handler(model_name)
        handler.prepare_tool_payload(payload, tools)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.api_url, json=payload, headers=headers)
        
        if response.status_code >= 400:
            raise RuntimeError(f"Model {model_name} error: {response.status_code}")
        
        data = response.json()
        if not data.get("choices"):
            raise RuntimeError(f"Model {model_name} response missing choices")
        
        return handler.parse_tool_response(data["choices"][0], tools)
    
    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """Generate with tool calling with automatic model fallback."""
        if not self.available:
            raise RuntimeError("Hugging Face provider not available")
        
        messages = [{"role": "user", "content": prompt}]
        
        # Try primary model first, then fallbacks
        models_to_try = [self.model_name] + [m for m in self.FALLBACK_MODELS if m != self.model_name]
        last_error = None
        
        for model in models_to_try:
            try:
                result = await self._try_model_with_tools(model, messages, tools, max_tokens, temperature)
                if model != self.model_name:
                    logger.info(f"✓ LLM tool-call fallback succeeded with {model}")
                return result
            except Exception as e:
                logger.warning(f"⚠️ LLM model {model} (tools) failed: {e}")
                last_error = e
                continue
        
        raise RuntimeError(f"All LLM models failed for tool calling. Last error: {last_error}")


class OllamaProvider(LLMProvider):
    """Ollama Local LLM Provider (Open Source)"""
    
    def __init__(self, model_name: str = "llama3.1:8b"):
        super().__init__(model_name)
        self.base_url = "http://localhost:11434"
    
    async def initialize(self) -> bool:
        """Initialize Ollama client"""
        try:
            import httpx
            
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/api/tags")
                
                if response.status_code == 200:
                    models = response.json().get('models', [])
                    model_names = [m['name'] for m in models]
                    
                    if self.model_name not in model_names:
                        logger.warning(f"⚠ Model {self.model_name} not found. Available: {model_names}")
                        return False
                    
                    self.available = True
                    logger.info(f"✓ Ollama initialized: {self.model_name}")
                    return True
                
                return False
                
        except Exception as e:
            logger.warning(f"⚠ Ollama unavailable: {e}")
            self.available = False
            return False
    
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None
    ) -> str:
        """Generate text using Ollama"""
        if not self.available:
            raise RuntimeError("Ollama provider not available")
        
        import httpx
        import json
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload
            )
            
            if response.status_code == 200:
                return response.json().get('response', '')
            
            raise RuntimeError(f"Ollama error: {response.status_code}")
    
    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """Generate with tool calling"""
        import json
        tool_prompt = f"{prompt}\n\nAvailable tools:\n{json.dumps(tools, indent=2)}\n\nRespond with the tool to use and parameters."
        response = await self.generate(tool_prompt, max_tokens, temperature)
        
        return {
            "text": response,
            "tool_calls": []
        }


class LLMManager:
    """Manages multiple LLM providers with automatic fallback and mock mode"""
    
    def __init__(self):
        self.providers: Dict[LLMType, LLMProvider] = {}
        self.active_provider: Optional[LLMProvider] = None
        self.mock_mode = False  # Fallback to mock responses if no providers available
        
        # MAIN: Kimi-K2-Instruct (via HuggingFace Inference API)
        # FALLBACK: Llama-3-8B-Instruct (via HuggingFace Inference API)
        # OTHER: Bedrock, Ollama
        active_provider = (settings.ACTIVE_LLM_PROVIDER or 'huggingface').lower()
        # Set priority based on environment variable
        if active_provider == 'huggingface':
            self.priority = [LLMType.HUGGINGFACE, LLMType.BEDROCK, LLMType.OLLAMA]
        elif active_provider == 'bedrock':
            self.priority = [LLMType.BEDROCK, LLMType.HUGGINGFACE, LLMType.OLLAMA]
        elif active_provider == 'ollama':
            self.priority = [LLMType.OLLAMA, LLMType.HUGGINGFACE, LLMType.BEDROCK]
        else:
            self.priority = [LLMType.HUGGINGFACE, LLMType.BEDROCK, LLMType.OLLAMA]

    async def initialize(self):
        """Initialize all providers - Kimi-K2 as main, Llama-3-8B as fallback"""
        # AWS Bedrock (Proprietary)
        bedrock = BedrockProvider()
        await bedrock.initialize()
        self.providers[LLMType.BEDROCK] = bedrock
        
        # Hugging Face (Open Source)
        # MAIN: Kimi-K2-Instruct (via HuggingFace Inference API, no local download)
        # FALLBACK: meta-llama/Meta-Llama-3-8B-Instruct
        hf_model = settings.HUGGINGFACE_MODEL or 'moonshotai/Kimi-K2-Instruct'
        huggingface = HuggingFaceProvider(model_name=hf_model)
        await huggingface.initialize()
        self.providers[LLMType.HUGGINGFACE] = huggingface
        
        # Ollama (Open Source Local)
        ollama = OllamaProvider()
        await ollama.initialize()
        self.providers[LLMType.OLLAMA] = ollama
        
        # Set active provider (first available in priority order)
        for llm_type in self.priority:
            if self.providers[llm_type].available:
                self.active_provider = self.providers[llm_type]
                logger.info(f"✓ Active LLM: {llm_type.value} ({self.active_provider.model_name})")
                break
        
        if not self.active_provider:
            logger.warning("⚠ No LLM providers available! Using mock mode for testing.")
            self.mock_mode = True
    
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None
    ) -> str:
        """Generate text with automatic fallback"""
        # Debug log for runtime state
        logger.info(f"[DEBUG] LLMManager.generate: mock_mode={self.mock_mode}, active_provider={self.active_provider}")

        # Mock mode fallback when no providers available
        if self.mock_mode:
            logger.info("🤖 Using mock LLM response (no providers configured)")
            return self._generate_mock_response(prompt)

        for llm_type in self.priority:
            provider = self.providers.get(llm_type)

            if provider and provider.available:
                try:
                    return await provider.generate(prompt, max_tokens, temperature, system_prompt)
                except Exception as e:
                    logger.warning(f"⚠ {llm_type.value} failed: {e}, trying next provider...")
                    continue

        # All providers failed, use mock
        logger.warning("⚠ All LLM providers failed, using mock response")
        return self._generate_mock_response(prompt)
    
    def _generate_mock_response(self, prompt: str) -> str:
        """Generate a mock response when no LLM is available"""
        # Simple rule-based responses for testing
        prompt_lower = prompt.lower()
        
        if "calendar" in prompt_lower or "meeting" in prompt_lower or "schedule" in prompt_lower:
            if "get" in prompt_lower or "show" in prompt_lower or "what" in prompt_lower:
                return "TOOL: get_calendar_events | PARAMS: {\"days\": 7}"
            elif "create" in prompt_lower or "schedule" in prompt_lower or "book" in prompt_lower:
                return "TOOL: create_calendar_event | PARAMS: {\"title\": \"Meeting\", \"start_time\": \"2025-12-14T14:00:00\", \"end_time\": \"2025-12-14T15:00:00\"}"
        
        elif "email" in prompt_lower or "mail" in prompt_lower:
            if "get" in prompt_lower or "show" in prompt_lower or "check" in prompt_lower or "read" in prompt_lower:
                return "TOOL: get_emails | PARAMS: {\"limit\": 10}"
            elif "send" in prompt_lower:
                return "TOOL: send_email | PARAMS: {\"to\": \"example@email.com\", \"subject\": \"Test\", \"body\": \"Message\"}"
        
        # Default response
        return "I'm running in mock mode. Please configure an LLM provider (AWS Bedrock, HuggingFace, or Ollama) to get intelligent responses."
    
    async def generate_with_tools(
        self,
        prompt: str,
        tools: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.7
    ) -> Dict[str, Any]:
        """Generate with tool calling and automatic fallback"""
        
        # Mock mode fallback
        if self.mock_mode:
            logger.info("🤖 Using mock tool calling response")
            return {
                "text": self._generate_mock_response(prompt),
                "tool_calls": []
            }
        
        for llm_type in self.priority:
            provider = self.providers.get(llm_type)
            
            if provider and provider.available:
                try:
                    return await provider.generate_with_tools(prompt, tools, max_tokens, temperature)
                except Exception as e:
                    logger.warning(f"⚠ {llm_type.value} failed: {e}, trying next provider...")
                    continue
        
        # Fallback to mock
        return {
            "text": self._generate_mock_response(prompt),
            "tool_calls": []
        }
    
    def get_active_provider_info(self) -> Dict[str, str]:
        """Get info about active provider"""
        if self.mock_mode:
            return {
                "provider": "mock",
                "model": "rule-based-mock",
                "status": "mock_mode"
            }
        
        if not self.active_provider:
            return {"provider": "none", "model": "none", "status": "unavailable"}
        
        for llm_type, provider in self.providers.items():
            if provider == self.active_provider:
                return {
                    "provider": llm_type.value,
                    "model": provider.model_name,
                    "status": "available"
                }
        
        return {"provider": "unknown", "model": "unknown", "status": "unknown"}


# Global LLM manager instance
llm_manager = LLMManager()
