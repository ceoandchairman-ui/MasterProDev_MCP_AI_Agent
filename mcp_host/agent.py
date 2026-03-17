"""LangChain Agent Orchestrator for MCP System"""

import logging
import os
import uuid
from typing import Optional, List, Dict, Any, AsyncGenerator
from datetime import datetime, timedelta, timezone
import json

from fastapi import UploadFile
from langchain.tools import BaseTool
from dateutil import parser as date_parser

from mcp_host.llm_provider import LLMProvider
from mcp_host.state import state_manager, ConversationState
from mcp_host.mcp_tools import get_all_mcp_tools
from mcp_host.rag_service import rag_service
from mcp_host.prompt_service import prompt_library
from mcp_host.multi_turn_processor import multi_turn_processor, initialize_multi_turn_processor
from mcp_host.query_processor import QueryProcessor
from mcp_host.intent_router import IntentRouter, Intent
from mcp_host.evaluator import evaluator  # Task evaluation metrics
from mcp_host.pii_scanner import pii_scanner

try:
    from langdetect import detect as _detect_lang, LangDetectException
    _LANGDETECT_AVAILABLE = True
except ImportError:
    _LANGDETECT_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================================
# TOKEN BUDGETING FOR CONTEXT MANAGEMENT
# ============================================================================

class TokenBudget:
    """Manages token allocation across different components."""
    
    def __init__(self, total_tokens: int = 4000):
        self.total_tokens = total_tokens
        # Token allocation percentages
        self.context_percentage = 0.50   # 50% for context/conversation
        self.planner_percentage = 0.20   # 20% for planner/planning
        self.synthesis_percentage = 0.20 # 20% for synthesis/response
        self.tools_percentage = 0.10     # 10% for tool execution
    
    def get_context_tokens(self) -> int:
        """Tokens available for conversation context."""
        return int(self.total_tokens * self.context_percentage)
    
    def get_planner_tokens(self) -> int:
        """Tokens for planner LLM call."""
        return int(self.total_tokens * self.planner_percentage)
    
    def get_synthesis_tokens(self) -> int:
        """Tokens for response synthesis."""
        return int(self.total_tokens * self.synthesis_percentage)
    
    def get_tools_tokens(self) -> int:
        """Tokens for tool execution."""
        return int(self.total_tokens * self.tools_percentage)
    
    def trim_context(self, history: str) -> str:
        """Trim conversation history to fit token budget."""
        max_chars = self.get_context_tokens() * 3  # Rough estimate: 1 token ≈ 3-4 chars
        if len(history) <= max_chars:
            return history
        # Keep recent context
        lines = history.split('\n')
        trimmed = []
        char_count = 0
        for line in reversed(lines):
            char_count += len(line) + 1
            if char_count > max_chars:
                break
            trimmed.insert(0, line)
        return '\n'.join(trimmed)

# ============================================================================
# AGENT ORCHESTRATOR
# ============================================================================

class MCPAgent:
    """
    Simple agent orchestrator for MCP system.
    Coordinates tool execution across Calendar and Gmail MCP servers.
    """
    
    MAX_TOOL_STEPS = 3

    # Tier-0: deterministic responses — no LLM call, zero tokens
    _DETERMINISTIC_RESPONSES = [
        (['hello', 'hi', 'hey', 'howdy', 'greetings'],
         "Hi! I'm MasterProDev's AI Assistant. What can I help you with today?"),
        (['good morning'],
         "Good morning! I'm MasterProDev's AI Assistant. How can I help you today?"),
        (['good afternoon'],
         "Good afternoon! I'm MasterProDev's AI Assistant. How can I help you today?"),
        (['good evening', 'good night'],
         "Good evening! I'm MasterProDev's AI Assistant. How can I help you today?"),
        (['thank you', 'thanks', 'thx', 'cheers'],
         "You're welcome! Is there anything else I can help you with?"),
        (['bye', 'goodbye', 'see you', 'take care', 'cya', 'ttyl'],
         "Goodbye! Feel free to reach out whenever you need help."),
        (['how are you', 'how are things', "what's up", 'whats up'],
         "I'm doing well, thanks for asking! How can I assist you today?"),
    ]

    # Tier-0a: FAQ bank — zero LLM tokens. Mirrored in prompts.yaml for reference.
    _FAQS = [
        {
            "id": "faq_identity",
            "keywords": ["masterprodev", "master pro dev", "your company", "about the company", "about your company", "about masterprodev", "what does masterprodev", "what does master pro dev", "what do you do", "what masterprodev does", "what master pro dev does"],
            "min_score": 1,
            "answer": "\U0001f3e2 **MasterProDev** is a professional software consulting firm based in Toronto, Canada. We specialise in AI-powered applications, custom software development, and digital transformation.",
        },
        {
            "id": "faq_services",
            "keywords": ["services", "offer", "expertise", "solutions", "provide"],
            "min_score": 2,
            "answer": "\U0001f680 We offer: **AI & Machine Learning**, **Custom Software Development**, **Cloud Solutions**, **Mobile & Web Apps**, and **Digital Strategy Consulting**.",
        },
        {
            "id": "faq_location",
            "keywords": ["located", "location", "your address", "toronto", "your office"],
            "min_score": 2,
            "answer": "\U0001f4cd MasterProDev is headquartered in **Toronto, Canada**. We serve clients globally and operate remotely worldwide.",
        },
        {
            "id": "faq_contact",
            "keywords": ["contact", "get in touch", "reach us", "email address", "phone number"],
            "min_score": 2,
            "answer": "\U0001f4ec You can reach our team via the contact form on our website, or I can help you send an email directly \u2014 just say the word!",
        },
        {
            "id": "faq_hours",
            "keywords": ["hours", "business hours", "working hours", "office hours", "opening time"],
            "min_score": 2,
            "answer": "\U0001f550 Our team is available **Monday\u2013Friday, 9 AM\u20136 PM EST**. I\u2019m available 24/7 to assist you! \U0001f60a",
        },
        {
            "id": "faq_booking",
            "keywords": ["book a meeting", "book a call", "schedule a meeting", "schedule a call", "book an appointment", "discovery call"],
            "min_score": 1,
            "answer": "\U0001f4c5 I can book that for you right now! Just tell me your preferred date and time and I\u2019ll get it on the calendar. \u2705",
        },
        {
            "id": "faq_capabilities",
            "keywords": ["capabilities", "what can you do", "what can you help", "what you offer", "your features"],
            "min_score": 1,
            "answer": "\U0001f916 I can help you with: **\U0001f4c5 Calendar & scheduling**, **\U0001f4e7 Email management**, **\U0001f4da Company knowledge**, and **\U0001f4c1 File analysis**. What do you need?",
        },
        {
            "id": "faq_privacy",
            "keywords": ["data privacy", "personal data", "secure data", "store my data", "privacy policy"],
            "min_score": 1,
            "answer": "\U0001f512 Your data is securely stored and never shared with third parties. We comply with standard data privacy regulations.",
        },
        {
            "id": "faq_onboarding",
            "keywords": ["get started", "getting started", "onboarding", "first step", "how do i start"],
            "min_score": 2,
            "answer": "\U0001f44b Great to have you here! Tell me what you need \u2014 schedule a meeting, ask about our services, or send an email. I\u2019ll guide you! \U0001f680",
        },
        {
            "id": "faq_team",
            "keywords": ["your team", "your staff", "your engineers", "your employees", "who works"],
            "min_score": 1,
            "answer": "\U0001f465 MasterProDev has a talented team of engineers, designers, and consultants. Want me to connect you with the right person? Just describe what you need!",
        },
    ]

    def __init__(self):
        self.tools = []
        self.tool_map: Dict[str, BaseTool] = {}
        self.llm_manager = None
        self.token_budget = TokenBudget(total_tokens=4000)  # Default 4k token budget
        self.query_processor = QueryProcessor()
        self.intent_router = IntentRouter()
        self.state_manager = state_manager
        self.initialized = False

    @property
    def file_processor(self):
        """Lazily resolve the file_processor singleton (initialized after startup)."""
        from mcp_host.file_processor import file_processor
        return file_processor
    
    async def initialize(self):
        """Initialize the agent with LLM and tools"""
        if self.initialized:
            logger.info("⚠ Agent already initialized")
            return
        
        try:
            logger.info("🤖 Initializing MCP Agent...")
            
            # Initialize LLM manager
            from mcp_host.llm_provider import LLMManager
            self.llm_manager = LLMManager()
            await self.llm_manager.initialize()
            logger.info("✓ LLM manager initialized")
            
            # Initialize multi-turn processor
            initialize_multi_turn_processor(self.llm_manager)
            logger.info("✓ Multi-turn processor initialized")
            
            # Load all MCP tools
            self.tools = get_all_mcp_tools()
            self.tool_map = {tool.name: tool for tool in self.tools}
            logger.info(f"✓ Loaded {len(self.tools)} MCP tools")
            
            self.initialized = True
            logger.info("🎯 MCP Agent fully initialized and ready!")
            
        except Exception as e:
            logger.error(f"✗ Agent initialization failed: {e}")
            raise
    
    async def process_message(
        self,
        message: str,
        session_id: str,  # Add session_id for state management
        conversation_history: Optional[List[Dict[str, str]]] = None,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        UNIFIED Orchestration Entrypoint - Single ReAct Loop.
        All tools (calendar, email, knowledge search) available.
        LLM decides intelligently which tools to use.
        
        Uses token budgeting to optimize context allocation.
        Supports multi-turn processing for complex requests.
        """
        trace_id = trace_id or str(uuid.uuid4())
        
        # PII SCANNING: Redact sensitive info from user message before logging/processing
        redacted_message = pii_scanner.scan_and_redact(message, "USER_MESSAGE")
        
        logger.info(f"[{trace_id}] 📥 Processing message: {redacted_message[:100]}...")
        if not self.initialized:
            logger.warning(f"[{trace_id}] ⚠ Agent not initialized, initializing now...")
            await self.initialize()

        start_time = datetime.utcnow()

        # First, check for and handle any pending actions for this session
        # check_and_handle_pending_action will return the result directly if a pending action exists
        pending_result = await self.query_processor.check_and_handle_pending_action(message, session_id, trace_id=trace_id)
        if pending_result is not None and isinstance(pending_result, dict):
            # A pending action was successfully resumed
            pending_result["execution_time"] = (datetime.utcnow() - start_time).total_seconds()
            pending_result["llm_provider"] = self.llm_manager.get_active_provider_info() if self.initialized else None
            return pending_result
        
        # If no pending action was handled, process the query normally
        processed_query = await self.query_processor.process_query(message, session_id, trace_id=trace_id)

        # ── Normalise for routing (LLM always receives the original text) ─────
        norm_message = self._normalize_message(message)
        logger.info(f"[{trace_id}] 📝 Normalised: '{norm_message}'")

        # ── Tier 0a: FAQ keyword match — zero LLM tokens ─────────────────────
        faq_answer = self._match_faq(norm_message, history_len=len(conversation_history or []))
        if faq_answer:
            logger.info(f"[{trace_id}] \U0001f4da Tier-0a FAQ match \u2014 no LLM call")
            return {
                "response": faq_answer,
                "tool_calls": [],
                "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                "success": True,
                "llm_provider": "faq",
            }

        # ── Tier 0: hardcoded template — zero LLM tokens ──────────────────────
        det_response = self._get_deterministic_response(norm_message)
        if det_response:
            logger.info(f"[{trace_id}] ⚡ Tier-0 deterministic response — no LLM call")
            return {
                "response": det_response,
                "tool_calls": [],
                "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                "success": True,
                "llm_provider": "deterministic",
            }

        # Format and trim history to fit token budget
        history_text = self._format_history(conversation_history)
        history_text = self.token_budget.trim_context(history_text)
        logger.info(f"[{trace_id}] 📊 Context tokens budgeted: {self.token_budget.get_context_tokens()} tokens")
        
        # ── Tier 1a: elaboration follow-up — RAG search on previous topic ────
        if self._is_elaboration(norm_message) and conversation_history:
            logger.info(f"[{trace_id}] 🔍 Elaboration detected — routing to RAG for richer answer")
            last_answer = self._get_last_assistant_turn(conversation_history)
            # Guard: if last answer is a greeting/name-ack there's no real topic to elaborate on
            if last_answer and self._is_trivial_turn(last_answer):
                logger.info(f"[{trace_id}] ⚠ Last turn is trivial (greeting/name-ack) — returning clarifying prompt")
                clarify = "Sure! What would you like to know more about? I can tell you about our **services**, **team**, **location**, or how to **get started**. 😊"
                return {
                    "response": clarify,
                    "tool_calls": [],
                    "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                    "success": True,
                    "llm_provider": "deterministic",
                }
            if last_answer:
                try:
                    forced_actions = [{"tool": "search_knowledge_base", "arguments": {"query": last_answer[:300]}}]
                    tool_runs = await self._execute_plan(forced_actions, session_id, trace_id=trace_id)
                    rag_output = str(tool_runs[0].get("output", "")) if tool_runs else ""
                    has_content = (
                        bool(rag_output)
                        and "no results" not in rag_output.lower()
                        and "error" not in rag_output.lower()
                        and len(rag_output.strip()) > 30
                    )
                    if has_content:
                        final_response = await self._synthesize_response(
                            user_message=message,
                            history_text=history_text,
                            tool_runs=tool_runs,
                            planner_hint="The user asked for elaboration on the previous answer. Expand meaningfully using the search results. Do not repeat what was already said.",
                            had_errors=False,
                            trace_id=trace_id
                        )
                        execution_time = (datetime.utcnow() - start_time).total_seconds()
                        
                        # PII SCANNING: Redact final response before returning
                        final_response = pii_scanner.scan_and_redact(final_response, "AGENT_RESPONSE")

                        return {
                            "response": (final_response or "I couldn't craft a response.").strip(),
                            "tool_calls": [],
                            "execution_time": execution_time,
                            "success": True,
                            "llm_provider": self.llm_manager.get_active_provider_info(),
                        }
                    logger.info(f"[{trace_id}] ⚠ RAG returned no useful content for elaboration — falling back to Tier-1")
                except Exception as _elab_err:
                    logger.warning(f"[{trace_id}] ⚠ Elaboration RAG failed: {_elab_err} — falling back to Tier-1")

        # ── Tier 1: pure conversation — LLM, capped at 400 tokens for elaborations
        if self._is_pure_conversation(norm_message):
            is_elab = self._is_elaboration(norm_message)
            tier1_tokens = 400 if is_elab else 150
            logger.info(f"[{trace_id}] 💬 Tier-1 conversation — direct LLM response ({tier1_tokens} tokens)")
            direct_prompt = self._build_direct_prompt(message, history_text)
            final_response = await self.llm_manager.generate(
                prompt=direct_prompt,
                max_tokens=tier1_tokens,
                temperature=0.1,
                trace_id=trace_id
            )
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            
            # PII SCANNING: Redact final response before returning and logging
            final_response = pii_scanner.scan_and_redact(final_response, "AGENT_RESPONSE")
            
            return {
                "response": (final_response or "I couldn't craft a response.").strip(),
                "tool_calls": [],
                "execution_time": execution_time,
                "success": True,
                "llm_provider": self.llm_manager.get_active_provider_info(),
            }
        
        # Check if multi-turn processing should be used for complex requests
        message_complexity = self._calculate_message_complexity(norm_message)
        if multi_turn_processor and multi_turn_processor.should_use_multi_turn(message, message_complexity):
            logger.info(f"[{trace_id}] 🔄 Complex request detected - using multi-turn processing...")
            try:
                multi_turn_result = await multi_turn_processor.process_multi_turn(
                    message,
                    llm_generate_fn=self.llm_manager.generate,
                    history_text=history_text,
                    trace_id=trace_id
                )
                
                if multi_turn_result['turns'] > 1:
                    execution_time = (datetime.utcnow() - start_time).total_seconds()
                    return {
                        "response": multi_turn_result['synthesis'],
                        "tool_calls": [],
                        "execution_time": execution_time,
                        "success": True,
                        "llm_provider": self.llm_manager.get_active_provider_info(),
                        "multi_turn": multi_turn_result
                    }
            except Exception as e:
                logger.warning(f"[{trace_id}] Multi-turn processing failed, falling back to standard flow: {e}")
        
        logger.info(f"[{trace_id}] 🎯 UNIFIED AGENT LOOP: Planning actions with all available tools...")
        try:
            # SINGLE FLOW: Plan actions using ALL tools (calendar, email, knowledge)
            plan = await self._plan_actions(message, history_text, norm_message=norm_message, trace_id=trace_id)
            logger.info(f"[{trace_id}] 🧭 Planner decided on actions: {[a.get('tool') for a in plan.get('actions', [])]}")

            tool_runs: List[Dict[str, Any]] = []
            final_response: Optional[str] = None

            if plan.get("actions"):
                # Execute the planned tools
                tool_runs = await self._execute_plan(plan["actions"], session_id, trace_id=trace_id) # Pass session_id
                had_errors = any("error" in run for run in tool_runs)
                planner_hint = None if had_errors else plan.get("final_response")
                
                # Synthesize final response from tool outputs
                final_response = await self._synthesize_response(
                    user_message=message,
                    history_text=history_text,
                    tool_runs=tool_runs,
                    planner_hint=planner_hint,
                    had_errors=had_errors,
                    trace_id=trace_id
                )
            else:
                # No tools needed - use planner's hint or generate direct response
                final_response = plan.get("final_response")
                if not final_response:
                    logger.info(f"[{trace_id}] 📝 No tools needed - generating direct response...")
                    direct_prompt = self._build_direct_prompt(message, history_text)
                    final_response = await self.llm_manager.generate(
                        prompt=direct_prompt,
                        max_tokens=500,
                        temperature=0.3,
                        trace_id=trace_id
                    )

            final_response = (final_response or "I couldn't craft a response.").strip()

            # PII SCANNING: Redact final response before returning and logging
            final_response = pii_scanner.scan_and_redact(final_response, "AGENT_RESPONSE")

            # Format response
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            tool_calls_payload = []
            for run in tool_runs:
                if "error" in run:
                    output_text = f"ERROR: {run.get('error')}"
                else:
                    output_text = self._stringify_tool_output(run.get("output"))
                
                # If the output is a dict with 'status': 'pending_auth', handle authorization flow
                if isinstance(run.get("output"), dict) and run["output"].get("status") == "pending_auth":
                    auth_url = run["output"].get("auth_url")
                    return {
                        "response": "Please authorize the required service to continue.",
                        "tool_calls": [],
                        "execution_time": execution_time,
                        "success": True,
                        "pending_auth": True,
                        "auth_url": auth_url,
                        "llm_provider": self.llm_manager.get_active_provider_info(),
                    }

                tool_calls_payload.append(
                    {
                        "tool": run.get("tool"),
                        "input": run.get("arguments", {}),
                        "output": output_text,
                    }
                )

            response = {
                "response": final_response,
                "tool_calls": tool_calls_payload,
                "execution_time": execution_time,
                "success": True,
                "llm_provider": self.llm_manager.get_active_provider_info(),
            }

            # ===== EVALUATION: Log task results (non-blocking) =====
            try:
                await self._evaluate_task(
                    session_id=session_id,
                    user_message=message,
                    tool_runs=tool_runs,
                    final_response=final_response,
                    elapsed_time=execution_time,
                    trace_id=trace_id
                )
            except Exception as e:
                logger.error(f"[{trace_id}] ❌ Failed to log evaluation task: {e}", exc_info=True)

            return response
        except Exception as e:
            logger.error(f"[{trace_id}] ❌ UNIFIED AGENT LOOP FAILED: {e}", exc_info=True)
            return {
                "response": "I'm sorry, but I encountered a critical error and couldn't complete your request.",
                "tool_calls": [],
                "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                "success": False,
                "llm_provider": self.llm_manager.get_active_provider_info() if self.initialized else "N/A",
            }

    async def process_message_stream(
        self,
        message: str,
        session_id: str,
        file: Optional[UploadFile] = None,
        user_id: Optional[str] = None,
        trace_id: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Processes a chat message and streams the response back chunk by chunk.
        This is the primary method for real-time, interactive chat.
        """
        trace_id = trace_id or str(uuid.uuid4())
        
        # PII SCANNING: Redact sensitive info from user message before logging/processing
        redacted_message = pii_scanner.scan_and_redact(message, "USER_MESSAGE")
        
        logger.info(f"[{trace_id}] 📥 Streaming message: {redacted_message[:100]}...")
        if not self.initialized:
            logger.warning(f"[{trace_id}] ⚠ Agent not initialized, initializing now...")
            await self.initialize()

        start_time = datetime.utcnow()
        user_id = user_id or "guest"

        try:
            # 1 & 2. Handle file upload and combine with message
            full_message = message
            file_context_for_history = ""
            
            if file:
                try:
                    file_data = await file.read()
                    logger.info(f"[{trace_id}] 📎 File received: '{file.filename}' ({len(file_data):,} bytes)")
                    yield {"type": "status", "text": f"Processing file: {file.filename}"}

                    extracted_text, file_type = await self.file_processor.process_file(
                        file_data, file.filename, user_query=message
                    )
                    logger.info(f"[{trace_id}] ✓ File processed ({file_type}): {len(extracted_text):,} chars")
                    yield {"type": "status", "text": "File analysis complete."}
                    
                    if extracted_text:
                        full_message += f"\n\n{extracted_text}"
                        file_context_for_history = f"\n\n[User uploaded file '{file.filename}' ({file_type})]"
                        await self.state_manager.set_file_context(session_id, file.filename, file_type, extracted_text)
                except ValueError as e:
                    logger.warning(f"[{trace_id}] ⚠️ File rejected: {e}")
                    yield {"type": "error", "text": f"File Error: {e}"}
                except Exception as e:
                    logger.error(f"[{trace_id}] ❌ File processing error: {e}", exc_info=True)
                    yield {"type": "error", "text": f"File upload failed: {e}"}

            # Add context from previous files if no new file is uploaded
            if not file:
                stored_fc = await self.state_manager.get_file_context(session_id)
                if stored_fc:
                    full_message += (
                        f"\n\n[Context from previously uploaded file '{stored_fc['filename']}' "
                        f"({stored_fc['file_type']}) is available for reference.]"
                    )

            # 3. Get conversation history
            conversation_history = await self.state_manager.get_conversation_history(session_id)
            history_text = self._format_history(conversation_history)
            history_text = self.token_budget.trim_context(history_text)
            logger.info(f"[{trace_id}] 📊 Context tokens budgeted: {self.token_budget.get_context_tokens()} tokens")

            # 3a. Apply same Tier-0a/Tier-0 routing used in non-streaming mode
            norm_message = self._normalize_message(message)

            faq_answer = self._match_faq(norm_message, history_len=len(conversation_history or []))
            if faq_answer:
                yield {"type": "status", "text": "Formulating response..."}
                final_response_text = ""
                for token in faq_answer.split():
                    chunk = token + " "
                    final_response_text += chunk
                    yield {"type": "text_chunk", "text": chunk}

                redacted_user_turn = pii_scanner.scan_and_redact(message, "USER_MESSAGE")
                redacted_final_response = pii_scanner.scan_and_redact(final_response_text.strip(), "AGENT_RESPONSE")
                await self.state_manager.save_conversation_turn(
                    session_id, user_id, session_id, redacted_user_turn, redacted_final_response
                )

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                yield {
                    "type": "done",
                    "execution_time": round(execution_time, 2),
                    "llm_provider": "faq",
                    "trace_id": trace_id
                }
                return

            det_response = self._get_deterministic_response(norm_message)
            if det_response:
                yield {"type": "status", "text": "Formulating response..."}
                final_response_text = ""
                for token in det_response.split():
                    chunk = token + " "
                    final_response_text += chunk
                    yield {"type": "text_chunk", "text": chunk}

                redacted_user_turn = pii_scanner.scan_and_redact(message, "USER_MESSAGE")
                redacted_final_response = pii_scanner.scan_and_redact(final_response_text.strip(), "AGENT_RESPONSE")
                await self.state_manager.save_conversation_turn(
                    session_id, user_id, session_id, redacted_user_turn, redacted_final_response
                )

                execution_time = (datetime.utcnow() - start_time).total_seconds()
                yield {
                    "type": "done",
                    "execution_time": round(execution_time, 2),
                    "llm_provider": "deterministic",
                    "trace_id": trace_id
                }
                return

            # 4. Plan actions
            yield {"type": "status", "text": "Thinking..."}
            plan = await self._plan_actions(full_message, history_text, trace_id=trace_id)
            actions = plan.get("actions", [])
            logger.info(f"[{trace_id}] 🧭 Planner decided on actions: {[a.get('tool') for a in actions]}")

            # 5. Execute tools and stream results
            tool_runs = []
            if actions:
                async for tool_chunk in self._execute_plan_stream(actions, session_id, trace_id=trace_id):
                    yield tool_chunk
                    if tool_chunk.get("type") == "tool_result":
                        tool_runs.append(tool_chunk["data"])
            else:
                yield {"type": "status", "text": "Formulating response..."}

            # 6. Synthesize final response and stream it
            yield {"type": "status", "text": "Creating final response..."}
            final_response_text = ""
            had_errors = any("error" in run for run in tool_runs)
            planner_hint = None if had_errors else plan.get("final_response")

            synthesis_gen = self._synthesize_response_stream(
                user_message=full_message,
                history_text=history_text,
                tool_runs=tool_runs,
                planner_hint=planner_hint,
                had_errors=had_errors,
                trace_id=trace_id
            )

            async for chunk in synthesis_gen:
                yield {"type": "text_chunk", "text": chunk}
                final_response_text += chunk

            # 7. Save conversation turn
            # PII SCANNING: Redact user message and agent response before saving to history
            redacted_user_turn = pii_scanner.scan_and_redact(message, "USER_MESSAGE")
            redacted_final_response = pii_scanner.scan_and_redact(final_response_text, "AGENT_RESPONSE")
            
            await self.state_manager.save_conversation_turn(
                session_id, user_id, session_id, redacted_user_turn, redacted_final_response
            )
            logger.info(f"[{trace_id}] ✔️ Streamed response finished and saved.")

            # 8. Final "done" message
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            yield {
                "type": "done",
                "execution_time": round(execution_time, 2),
                "llm_provider": self.llm_manager.get_active_provider_info(),
                "trace_id": trace_id
            }

        except Exception as e:
            logger.error(f"[{trace_id}] ❌ Stream processing error: {e}", exc_info=True)
            yield {
                "type": "error",
                "text": "An unexpected error occurred during streaming.",
                "trace_id": trace_id
            }

    async def _plan_actions(self, user_message: str, history_text: str, norm_message: Optional[str] = None, trace_id: Optional[str] = None) -> Dict[str, Any]:
        """Generates a plan of actions (tool calls) for the LLM to execute."""
        trace_id = trace_id or str(uuid.uuid4())
        
        # Build planner prompt using prompt_library
        tool_catalog = self._format_tool_catalog()
        nm = norm_message or user_message.lower()
        knowledge_intent = any(kw in nm for kw in ['company', 'policy', 'info', 'document', 'knowledge', 'about', 'services'])
        calendar_intent = any(kw in nm for kw in ['calendar', 'schedule', 'meeting', 'event', 'appointment', 'book'])
        email_intent = any(kw in nm for kw in ['email', 'send', 'inbox', 'mail', 'compose'])
        
        prompt = prompt_library.get_prompt(
            'sys_planner',
            tool_catalog=tool_catalog,
            history=history_text,
            message=user_message,
            knowledge_intent=knowledge_intent,
            calendar_intent=calendar_intent,
            email_intent=email_intent
        )
        if not prompt:
            prompt = f"Plan actions for: {user_message}"
        
        raw_response = await self.llm_manager.generate(
            prompt=prompt,
            max_tokens=1024,
            temperature=0.0,
            stop_sequences=["<observation>"],
            trace_id=trace_id
        )
        
        return self._parse_planner_response(raw_response)

    async def _execute_plan(self, actions: List[Dict[str, Any]], session_id: str, trace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Executes a list of tool actions."""
        trace_id = trace_id or str(uuid.uuid4())
        results = []
        for action in actions:
            tool_name = action.get("tool")
            arguments = action.get("arguments", {})
            
            if tool_name in self.tool_map:
                tool = self.tool_map[tool_name]
                logger.info(f"[{trace_id}] 🛠️ Executing tool: {tool_name} with args: {arguments}")
                try:
                    # Pass session_id to tools that need it
                    if tool_name in ["search_calendar", "create_calendar_event", "delete_calendar_event", "search_emails", "send_email"]:
                        arguments["session_id"] = session_id

                    output = await tool.arun(**arguments)
                    results.append({"tool": tool_name, "arguments": arguments, "output": output})
                except Exception as e:
                    logger.error(f"[{trace_id}] ❌ Tool '{tool_name}' execution failed: {e}", exc_info=True)
                    results.append({"tool": tool_name, "arguments": arguments, "error": str(e)})
            else:
                logger.warning(f"[{trace_id}] ⚠️ Tool '{tool_name}' not found.")
                results.append({"tool": tool_name, "arguments": arguments, "error": "Tool not found"})
        
        return results

    async def _execute_plan_stream(self, actions: List[Dict[str, Any]], session_id: str, trace_id: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Executes a list of tool actions and streams the progress."""
        trace_id = trace_id or str(uuid.uuid4())
        for action in actions:
            tool_name = action.get("tool")
            arguments = action.get("arguments", {})

            if tool_name in self.tool_map:
                tool = self.tool_map[tool_name]
                yield {
                    "type": "tool_call",
                    "data": {"tool_name": tool_name, "tool_input": arguments}
                }
                logger.info(f"[{trace_id}] 🛠️ Streaming tool execution: {tool_name} with args: {arguments}")
                try:
                    if tool_name in ["search_calendar", "create_calendar_event", "delete_calendar_event", "search_emails", "send_email"]:
                        arguments["session_id"] = session_id

                    output = await tool.arun(**arguments)
                    result_data = {"tool": tool_name, "arguments": arguments, "output": output}
                    yield {"type": "tool_result", "data": result_data}
                except Exception as e:
                    logger.error(f"[{trace_id}] ❌ Tool '{tool_name}' execution failed: {e}", exc_info=True)
                    error_data = {"tool": tool_name, "arguments": arguments, "error": str(e)}
                    yield {"type": "tool_result", "data": error_data}
            else:
                logger.warning(f"[{trace_id}] ⚠️ Tool '{tool_name}' not found.")
                error_data = {"tool": tool_name, "arguments": arguments, "error": "Tool not found"}
                yield {"type": "tool_result", "data": error_data}


    async def _synthesize_response(
        self,
        user_message: str,
        history_text: str,
        tool_runs: List[Dict[str, Any]],
        planner_hint: Optional[str] = None,
        had_errors: bool = False,
        trace_id: Optional[str] = None
    ) -> Optional[str]:
        """Synthesizes a final response from tool outputs."""
        trace_id = trace_id or str(uuid.uuid4())
        prompt = self._build_synthesis_prompt(
            user_message=user_message,
            history=history_text,
            tool_runs=tool_runs,
            planner_hint=planner_hint,
            had_errors=had_errors
        )
        
        return await self.llm_manager.generate(
            prompt=prompt,
            max_tokens=1500,
            temperature=0.2,
            trace_id=trace_id
        )

    async def _synthesize_response_stream(
        self,
        user_message: str,
        history_text: str,
        tool_runs: List[Dict[str, Any]],
        planner_hint: Optional[str] = None,
        had_errors: bool = False,
        trace_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Synthesizes a final response and streams it chunk by chunk."""
        trace_id = trace_id or str(uuid.uuid4())
        prompt = self._build_synthesis_prompt(
            user_message=user_message,
            history=history_text,
            tool_runs=tool_runs,
            planner_hint=planner_hint,
            had_errors=had_errors
        )

        async for chunk in self.llm_manager.generate_stream(
            prompt=prompt,
            max_tokens=1500,
            temperature=0.2,
            trace_id=trace_id
        ):
            yield chunk

    def _build_direct_prompt(self, user_message: str, history_text: str) -> str:
        """Build a direct response prompt using smart semantic selection."""
        # Use intelligent prompt selection instead of simple keyword matching
        prompt_id = self._select_best_prompt(user_message)
        
        # Retrieve and format the prompt
        prompt = prompt_library.get_prompt(
            prompt_id,
            message=user_message,
            history=history_text or "(no prior turns)"
        )
        
        if not prompt:
            # Fallback to a simple prompt if library lookup fails
            logger.warning(f"⚠ Prompt not found in library: {prompt_id}, using fallback")
            prompt = f"You are MasterProDev's AI Assistant.\n\nUser message: {user_message}\n\nRespond helpfully."
        
        return prompt

    def _format_history(self, conversation_history: Optional[List[Dict[str, str]]]) -> str:
        """Collapse recent turns to a readable block. Handles both old and new history formats."""
        if not conversation_history:
            return ""
        trimmed = conversation_history[-10:]  # Keep last 10 turns for better context
        lines = []
        for msg in trimmed:
            # New format: {"user": "...", "assistant": "..."}
            if "user" in msg and "assistant" in msg:
                lines.append(f"User: {msg['user']}")
                lines.append(f"Assistant: {msg['assistant']}")
            # LangChain/OpenAI format: {"role": "user"/"assistant", "content": "..."}
            elif "role" in msg and "content" in msg:
                label = "User" if msg["role"] == "user" else "Assistant"
                lines.append(f"{label}: {msg['content']}")
        return "\n".join(lines)

    def _stringify_tool_output(self, payload: Any) -> str:
        """Convert tool output to a compact printable string."""
        try:
            text = json.dumps(payload, indent=2)
        except Exception:
            text = str(payload)
        if len(text) > 500:
            text = text[:497] + "..."
        return text

    def _normalize_tool_arguments(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        user_message: str,
    ) -> Dict[str, Any]:
        """Apply defaults and heuristics to LLM-provided arguments."""
        normalized = dict(arguments or {})

        if tool_name == "create_calendar_event":
            normalized.setdefault("title", normalized.get("summary") or "New event")

            start_dt = self._parse_datetime(
                normalized.get("start_time")
                or normalized.get("date_time")
                or normalized.get("date")
                or normalized.get("day"),
                fallback=user_message,
            )

            all_day = self._looks_date_only(normalized.get("start_time") or normalized.get("date") or normalized.get("day"))

            if not start_dt:
                start_dt = datetime.utcnow().replace(minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
                all_day = False

            normalized["start_time"] = self._to_iso(start_dt)

            if all_day:
                end_dt = start_dt.replace(hour=23, minute=59)
            else:
                end_dt = self._parse_datetime(
                    normalized.get("end_time")
                    or normalized.get("end_date")
                    or normalized.get("end")
                    or None,
                    fallback=None,
                )
                if not end_dt:
                    duration = normalized.get("duration_minutes")
                    if duration:
                        try:
                            minutes = int(duration)
                        except Exception:
                            minutes = 60
                        end_dt = start_dt + timedelta(minutes=minutes)
                    else:
                        end_dt = start_dt + timedelta(hours=1)

            normalized["end_time"] = self._to_iso(end_dt)

            # Clean intermediary fields
            for key in ("summary", "date", "day", "date_time", "end_date", "end", "duration_minutes"):
                normalized.pop(key, None)

        return normalized

    def _parse_datetime(self, value: Optional[str], fallback: Optional[str]) -> Optional[datetime]:
        """Parse a datetime from value or fallback text with support for time ranges."""
        candidates = [value, fallback]
        for candidate in candidates:
            if not candidate:
                continue
            try:
                candidate_str = str(candidate).strip()
                
                # Handle explicit ISO8601 timestamps
                if "T" in candidate_str or "Z" in candidate_str:
                    dt = date_parser.parse(candidate_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                
                # CRITICAL: Normalize AM/PM to uppercase before parsing
                # This handles common mistakes like "10:00Am" or "10:00aM"
                candidate_normalized = candidate_str.upper()
                
                # Try parsing with proper dateutil settings (NOT fuzzy mode - it causes errors)
                # fuzzy=False ensures we don't accidentally parse wrong times
                dt = date_parser.parse(candidate_normalized, fuzzy=False, dayfirst=False)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                logger.info(f"✓ Parsed datetime: '{candidate_str}' → {dt.isoformat()}")
                return dt
            except Exception as e:
                logger.debug(f"⚠ Failed to parse '{candidate}': {e}")
                continue
        return None

    def _looks_date_only(self, value: Optional[str]) -> bool:
        if not value:
            return False
        text = str(value).strip().lower()
        return "t" not in text and any(char.isdigit() for char in text)

    def _to_iso(self, dt: datetime) -> str:
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _format_tool_catalog(self) -> str:
        """Formatted tool metadata for planner prompts."""
        catalog = []
        for tool in self.tools:
            args_schema = {}
            schema_model = getattr(tool, "args_schema", None)
            if schema_model:
                if hasattr(schema_model, "model_json_schema"):
                    args_schema = schema_model.model_json_schema()
                elif hasattr(schema_model, "schema"):
                    args_schema = schema_model.schema()
            catalog.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "args": args_schema,
                }
            )
        return json.dumps(catalog, indent=2)

    def _parse_planner_response(self, raw_response: str) -> Dict[str, Any]:
        """Parse the planner LLM response into a structured plan."""
        if not raw_response:
            return {"actions": [], "final_response": None}
        try:
            # Try to extract JSON from the response
            text = raw_response.strip()
            # Handle markdown-wrapped JSON
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            
            plan = json.loads(text)
            actions = plan.get("actions", [])
            final_response = plan.get("final_response", None)
            return {"actions": actions, "final_response": final_response}
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"⚠ Failed to parse planner response as JSON: {e}")
            return {"actions": [], "final_response": raw_response}

    def _build_synthesis_prompt(
        self,
        user_message: str,
        history: str,
        tool_runs: List[Dict[str, Any]],
        planner_hint: Optional[str] = None,
        had_errors: bool = False
    ) -> str:
        """Build the synthesis prompt from tool outputs."""
        # Format tool outputs
        tool_outputs_text = ""
        for run in tool_runs:
            tool_name = run.get("tool", "unknown")
            if "error" in run:
                tool_outputs_text += f"\n[{tool_name}] ERROR: {run['error']}\n"
            else:
                output = self._stringify_tool_output(run.get("output"))
                tool_outputs_text += f"\n[{tool_name}] Result:\n{output}\n"

        hint = planner_hint or "(none)"
        resolution = "Explain clearly if any tool returned an error." if had_errors else "Synthesize a concise, helpful response."

        prompt = prompt_library.get_prompt(
            'sys_synthesis',
            history=history or "(no prior turns)",
            tool_outputs=tool_outputs_text or "(no tool output)",
            planner_hint=hint,
            user_message=user_message,
            resolution_instruction=resolution
        )
        if not prompt:
            prompt = f"Synthesize a response for: {user_message}\nTool outputs: {tool_outputs_text}"
        return prompt

    def _select_best_prompt(self, user_message: str) -> str:
        """Select the best prompt ID based on message content."""
        msg = user_message.lower().strip()

        # Meta questions about the assistant
        if any(kw in msg for kw in ['who are you', 'what are you', 'what can you do', 'your name']):
            return 'conv_meta'

        # Company info questions
        if any(kw in msg for kw in ['company', 'masterprodev', 'services', 'about us', 'your team']):
            return 'conv_company_info'

        # Greeting patterns
        if any(kw in msg for kw in ['hello', 'hi', 'hey', 'good morning', 'good afternoon', 'good evening']):
            return 'conv_greeting'

        # Default: general conversation
        return 'conv_general'

    def _calculate_message_complexity(self, message: str) -> str:
        """Estimate message complexity for multi-turn routing."""
        word_count = len(message.split())
        question_marks = message.count('?')
        conjunctions = sum(1 for w in ['and', 'also', 'then', 'after', 'before', 'while', 'additionally']
                          if w in message.lower().split())
        if word_count > 100 or question_marks > 2 or conjunctions > 2:
            return 'complex'
        if word_count > 40 or question_marks > 1 or conjunctions > 0:
            return 'moderate'
        return 'simple'

    async def _evaluate_task(
        self,
        session_id: str,
        user_message: str,
        tool_runs: List[Dict[str, Any]],
        final_response: str,
        elapsed_time: float,
        trace_id: Optional[str] = None
    ):
        """Delegate task evaluation to the evaluator service."""
        try:
            await evaluator.evaluate_task(
                session_id=session_id,
                user_message=user_message,
                tool_runs=tool_runs,
                final_response=final_response,
                elapsed_time=elapsed_time,
                trace_id=trace_id
            )
        except Exception as e:
            logger.warning(f"[{trace_id}] ⚠ Evaluation failed (non-blocking): {e}")
    
    async def get_available_tools(self) -> List[Dict[str, str]]:
        """Get list of available tools with descriptions"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
            }
            for tool in self.tools
        ]
    
    def get_status(self) -> Dict[str, Any]:
        """Get agent status and configuration"""
        return {
            "initialized": self.initialized,
            "tools_count": len(self.tools),
            "tools": [tool.name for tool in self.tools],
            "llm_provider": self.llm_manager.get_active_provider_info() if self.initialized else None,
        }

    def _get_deterministic_response(self, message: str) -> Optional[str]:
        """Tier-0: return a hardcoded reply for simple greetings/closings — zero LLM tokens."""
        msg = message.lower().strip().rstrip('!?., ')
        for patterns, response in self._DETERMINISTIC_RESPONSES:
            for pattern in patterns:
                if msg == pattern or msg.startswith(pattern + ' ') or msg.startswith(pattern + ','):
                    return response
        return None

    def _match_faq(self, message: str, history_len: int = 0) -> Optional[str]:
        """Tier-0a: fuzzy keyword FAQ match.

        Uses per-FAQ min_score thresholds. No history penalty — min_score values
        are calibrated to be selective enough on their own.
        """
        msg = message.lower()
        best_score = 0
        best_answer: Optional[str] = None
        for faq in self._FAQS:
            min_s = faq.get("min_score", 2)
            score = sum(1 for kw in faq["keywords"] if self._fuzzy_keyword_match(kw, msg))
            if score >= min_s and score > best_score:
                best_score = score
                best_answer = faq["answer"]
        return best_answer

    @staticmethod
    def _normalize_message(text: str) -> str:
        """
        Normalise raw user input for reliable routing and matching.
        Expands abbreviations, fixes common typos, collapses whitespace.
        The ORIGINAL text is still sent to the LLM — this is only for
        internal routing (FAQ, Tier-0, intent keywords, elaboration).
        """
        import re
        t = text.strip().lower()

        # ── 1. SMS / casual abbreviations ────────────────────────────────────
        _abbrev = [
            (r'\bu\b',    'you'),    (r'\bur\b',   'your'),
            (r'\br\b',    'are'),    (r'\bpls\b',  'please'),
            (r'\bplz\b',  'please'), (r'\bthx\b',  'thank you'),
            (r'\bty\b',   'thank you'), (r'\basap\b', 'as soon as possible'),
            (r'\bfyi\b',  'for your information'),
            (r'\bbtw\b',  'by the way'), (r'\bnvm\b',  'never mind'),
            (r'\bomw\b',  'on my way'),  (r'\bsup\b',  "what's up"),
            (r'\bngl\b',  'not going to lie'), (r'\btbh\b', 'to be honest'),
            (r'\bwdym\b', 'what do you mean'), (r'\bimo\b',  'in my opinion'),
            (r'\bhbu\b',  'how about you'),    (r'\bwbu\b',  'what about you'),
            (r'\bgm\b',   'good morning'),     (r'\bgn\b',   'good night'),
        ]
        for pattern, replacement in _abbrev:
            t = re.sub(pattern, replacement, t)

        # ── 2. Domain name variants → canonical ──────────────────────────────
        t = re.sub(r'\bmaster\s*pro\s*dev\b', 'masterprodev', t)
        t = re.sub(r'\bmpd\b', 'masterprodev', t)

        # ── 3. Common typos that break routing ───────────────────────────────
        _typos = [
            (r'\beloborate\w*', 'elaborate'), (r'\belabrate\w*',   'elaborate'),
            (r'\belaborrate\w*','elaborate'),  (r'\bdescirbe\b',    'describe'),
            (r'\bdescibe\b',    'describe'),   (r'\bsummarise\b',   'summarize'),
            (r'\bsummaize\b',   'summarize'),  (r'\bscheudle\b',    'schedule'),
            (r'\bscheule\b',    'schedule'),   (r'\bcalander\b',    'calendar'),
            (r'\bcalender\b',   'calendar'),   (r'\bkalender\b',    'calendar'),
            (r'\bappoinment\b', 'appointment'),(r'\bappointmnt\b',  'appointment'),
            (r'\bmeetnig\b',    'meeting'),    (r'\bmeeing\b',      'meeting'),
            (r'\bemial\b',      'email'),      (r'\bemayl\b',       'email'),
            (r'\belaborate more\b', 'elaborate more'),
        ]
        for pattern, replacement in _typos:
            t = re.sub(pattern, replacement, t)

        # ── 4. Repeated punctuation (??? → ?) ────────────────────────────────
        t = re.sub(r'([!?.])\1+', r'\1', t)

        # ── 5. Collapse whitespace ────────────────────────────────────────────
        t = re.sub(r'\s+', ' ', t).strip()
        return t

    @staticmethod
    def _fuzzy_keyword_match(keyword: str, text: str, threshold: float = 0.82) -> bool:
        """
        Return True if `keyword` matches any same-length token window in `text`
        with SequenceMatcher ratio >= threshold.  Falls back to plain substring
        for single-word keywords (fast path).
        """
        from difflib import SequenceMatcher
        if keyword in text:
            return True
        kw_words = keyword.split()
        text_words = text.split()
        n = len(kw_words)
        if n == 1:
            # Single word — try character-level fuzzy on every token
            for token in text_words:
                if SequenceMatcher(None, keyword, token).ratio() >= threshold:
                    return True
            return False
        # Multi-word — sliding window
        for i in range(max(1, len(text_words) - n + 1)):
            window = " ".join(text_words[i:i + n])
            if SequenceMatcher(None, keyword, window).ratio() >= threshold:
                return True
        return False

    @staticmethod
    def _looks_like_name(text: str) -> bool:
        """Returns True if text looks like a personal name (1-3 words, no question markers)."""
        if not text or len(text) > 40:
            return False
        if "?" in text or "@" in text or "." in text:
            return False
        _q = {"what", "who", "where", "when", "how", "why", "is", "are", "can",
              "do", "does", "my", "the", "i", "a", "an", "it", "yes", "no", "ok", "okay",
              "hello", "hi", "hey", "thanks", "thank", "sure", "great", "cool", "fine",
              "nice", "good", "bye", "please", "sorry", "help", "tell", "there",
              "more", "this", "that", "about", "us", "you", "your", "our", "we"}
        words = text.split()
        if not (1 <= len(words) <= 3):
            return False
        return words[0].lower() not in _q

    @staticmethod
    def _extract_name_from_message(text: str, require_explicit: bool = False) -> Optional[str]:
        """Extract a first name from natural language.

        Handles:
          'My name is Srivardhan Muthyala' -> 'Srivardhan'
          'I'm John'  -> 'John'
          'Call me Emma' -> 'Emma'
          'John' (direct short reply, only when require_explicit=False)

        require_explicit=True: only match intro-phrase patterns (safe for open turns).
        require_explicit=False: also accept direct 1-3 word name replies.
        """
        import re
        # Hard-block list — these must NEVER be treated as names
        _hard_block = {
            "hello", "hi", "hey", "howdy", "greetings",
            "yes", "no", "ok", "okay", "sure", "fine", "cool", "great", "nice",
            "thanks", "thank", "bye", "goodbye", "please", "sorry", "help",
            "more", "tell", "there", "this", "that", "about", "us", "you", "your", "our", "we"}
        t = text.strip().rstrip("!?., ")
        tl = t.lower()

        # Hard-block single-word greetings/fillers before anything else
        if tl in _hard_block:
            return None

        m = re.search(
            r"\b(?:my name is|i am|i'm|name's|my name's|call me|it is|it's)\s+([a-z]+)",
            tl
        )
        if m:
            idx = tl.find(m.group(1), m.start())
            raw = t[idx:].split()[0]
            _stop = {"the", "a", "an", "there", "here", "ok", "okay", "just", "not"} | _hard_block
            if raw.lower() not in _stop and raw.isalpha():
                return raw.capitalize()
        if require_explicit:
            return None
        if MCPAgent._looks_like_name(t):
            return t.split()[0].capitalize()
        return None

    @staticmethod
    def _is_trivial_turn(text: str) -> bool:
        """Return True if the assistant turn has no real topic (greeting, name-ack, etc.)."""
        t = text.lower().strip()
        trivial_phrases = [
            "nice to meet you", "i'm here to help", "what can i assist",
            "how can i help", "what can i help", "i'm masterprodev",
            "hi!", "hello!", "good morning", "good afternoon", "good evening",
            "you're welcome", "is there anything else",
        ]
        # Also treat very short turns as trivial (< 80 chars, no sentence of substance)
        if len(t) < 80:
            return True
        return any(p in t for p in trivial_phrases)

    @staticmethod
    def _is_elaboration(message: str) -> bool:
        """Return True if message is a follow-up elaboration request with no new topic."""
        msg = message.lower().strip()
        elaboration_patterns = [
            'tell me more', 'can you elaborate', 'can u elaborate', 'elaborate more',
            'elaborate on', 'can you expand', 'can u expand', 'expand on',
            'more details', 'more detail', 'more info', 'tell me more about that',
            'explain more', 'explain further', 'go on', 'continue', 'and then',
            'what else', 'anything else', 'say more', 'keep going',
        ]
        return any(p in msg for p in elaboration_patterns)

    @staticmethod
    def _get_last_assistant_turn(conversation_history: List[Dict[str, Any]]) -> Optional[str]:
        """Return the most recent assistant response text from history, or None."""
        for turn in reversed(conversation_history):
            # {user, assistant} format
            if "assistant" in turn and turn["assistant"]:
                return turn["assistant"]
            # {role, content} format
            if turn.get("role") == "assistant" and turn.get("content"):
                return turn["content"]
        return None

    def _is_pure_conversation(self, message: str) -> bool:
        """
        Detect if this is a purely conversational message that doesn't need any tools.
        Returns True if message is greeting, small talk, meta-question, etc.
        """
        msg_lower = message.lower().strip()
        
        # Greetings & closing
        greetings = ['hello', 'hi', 'hey', 'howdy', 'greetings', 'good morning', 
                     'good afternoon', 'good evening', 'good night', 'thanks', 
                     'thank you', 'thanks!', 'bye', 'goodbye', 'see you', 'take care']
        
        # Meta-questions about the assistant itself
        meta_questions = ['who are you', 'what are you', 'what can you', 
                         'what can i', 'help me', 'can you help', 'tell me a joke',
                         'what is mcp', 'what tools do you', 'how do you work']
        
        # Generic conversation (no specific request)
        conversation_patterns = ['how are you', 'how are things', "what's up", 'whats up']

        # Follow-up elaboration — refer back to previous answer, no new tool needed
        elaboration_patterns = [
            'tell me more', 'can you elaborate', 'can u elaborate', 'elaborate more',
            'elaborate on', 'can you expand', 'can u expand', 'expand on',
            'more details', 'more detail', 'more info', 'tell me more about that',
            'explain more', 'explain further', 'go on', 'continue', 'and then',
            'what else', 'anything else', 'say more', 'keep going',
        ]
        
        # Greetings / meta / conversation: match at word boundary (startswith prevents
        # 'hello world company info' from short-circuiting a real query)
        for pattern in greetings + meta_questions + conversation_patterns:
            if msg_lower.startswith(pattern) or msg_lower == pattern:
                logger.info(f"✓ Detected pure conversation pattern: '{pattern}'")
                return True

        # Elaboration patterns: match anywhere in the message so "can you PLEASE elaborate"
        # and "could you give me more details" are caught even with filler words.
        for pattern in elaboration_patterns:
            if pattern in msg_lower:
                logger.info(f"✓ Detected elaboration pattern: '{pattern}'")
                return True

        # Single word greetings
        if msg_lower in greetings:
            return True

        return False


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Global agent instance - initialized on startup
mcp_agent = MCPAgent()
