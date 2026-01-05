"""LangChain Agent Orchestrator for MCP System"""

import logging
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import json

from langchain.tools import BaseTool
from dateutil import parser as date_parser

from mcp_host.llm_provider import LLMProvider
from mcp_host.state import state_manager
from mcp_host.mcp_tools import get_all_mcp_tools
from mcp_host.rag_service import rag_service
from mcp_host.prompt_service import prompt_library
from mcp_host.multi_turn_processor import multi_turn_processor, initialize_multi_turn_processor
from mcp_host.query_processor import QueryProcessor
from mcp_host.intent_router import IntentRouter, Intent

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

    def __init__(self):
        self.tools = []
        self.tool_map: Dict[str, BaseTool] = {}
        self.llm_manager = None
        self.token_budget = TokenBudget(total_tokens=4000)  # Default 4k token budget
        self.query_processor = QueryProcessor()
        self.intent_router = IntentRouter()
        self.initialized = False
    
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
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        UNIFIED Orchestration Entrypoint - Single ReAct Loop.
        All tools (calendar, email, knowledge search) available.
        LLM decides intelligently which tools to use.
        
        Uses token budgeting to optimize context allocation.
        Supports multi-turn processing for complex requests.
        """
        logger.info(f"📥 Processing message: {message[:100]}...")
        if not self.initialized:
            logger.warning("⚠ Agent not initialized, initializing now...")
            await self.initialize()

        start_time = datetime.utcnow()
        
        # Format and trim history to fit token budget
        history_text = self._format_history(conversation_history)
        history_text = self.token_budget.trim_context(history_text)
        logger.info(f"📊 Context tokens budgeted: {self.token_budget.get_context_tokens()} tokens")
        
        # --- Pre-filter: Detect if this is pure conversation (no tools needed) ---
        # This prevents the planner from wasting resources on greetings, small talk, etc.
        if self._is_pure_conversation(message):
            logger.info("💬 Message is pure conversation - skipping planner, generating direct response...")
            direct_prompt = self._build_direct_prompt(message, history_text)
            final_response = await self.llm_manager.generate(
                prompt=direct_prompt,
                max_tokens=self.token_budget.get_synthesis_tokens(),
                temperature=0.3
            )
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            return {
                "response": (final_response or "I couldn't craft a response.").strip(),
                "tool_calls": [],
                "execution_time": execution_time,
                "success": True,
                "llm_provider": self.llm_manager.get_active_provider_info(),
            }
        
        # Check if multi-turn processing should be used for complex requests
        message_complexity = self._calculate_message_complexity(message)
        if multi_turn_processor and multi_turn_processor.should_use_multi_turn(message, message_complexity):
            logger.info("🔄 Complex request detected - using multi-turn processing...")
            try:
                multi_turn_result = await multi_turn_processor.process_multi_turn(
                    message,
                    llm_generate_fn=self.llm_manager.generate
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
                logger.warning(f"Multi-turn processing failed, falling back to standard flow: {e}")
        
        logger.info("🎯 UNIFIED AGENT LOOP: Planning actions with all available tools...")
        try:
            # SINGLE FLOW: Plan actions using ALL tools (calendar, email, knowledge)
            plan = await self._plan_actions(message, history_text)
            logger.info(f"🧭 Planner decided on actions: {[a.get('tool') for a in plan.get('actions', [])]}")

            tool_runs: List[Dict[str, Any]] = []
            final_response: Optional[str] = None

            if plan.get("actions"):
                # Execute the planned tools
                tool_runs = await self._execute_plan(plan["actions"], message)
                had_errors = any("error" in run for run in tool_runs)
                planner_hint = None if had_errors else plan.get("final_response")
                
                # Synthesize final response from tool outputs
                final_response = await self._synthesize_response(
                    user_message=message,
                    history_text=history_text,
                    tool_runs=tool_runs,
                    planner_hint=planner_hint,
                    had_errors=had_errors,
                )
            else:
                # No tools needed - use planner's hint or generate direct response
                final_response = plan.get("final_response")
                if not final_response:
                    logger.info("📝 No tools needed - generating direct response...")
                    direct_prompt = self._build_direct_prompt(message, history_text)
                    final_response = await self.llm_manager.generate(
                        prompt=direct_prompt,
                        max_tokens=500,
                        temperature=0.3
                    )

            final_response = (final_response or "I couldn't craft a response.").strip()

            # Format response
            execution_time = (datetime.utcnow() - start_time).total_seconds()
            tool_calls_payload = []
            for run in tool_runs:
                if "error" in run:
                    output_text = f"ERROR: {run.get('error')}"
                else:
                    output_text = self._stringify_tool_output(run.get("output"))
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

            logger.info(f"✓ Unified flow completed in {execution_time:.2f}s")
            return response

        except Exception as e:
            logger.error(f"✗ Agent processing error: {e}", exc_info=True)
            return {
                "response": f"I encountered an error: {str(e)}. Please try again.",
                "tool_calls": [],
                "execution_time": (datetime.utcnow() - start_time).total_seconds(),
                "success": False,
                "error": str(e),
            }


    def _calculate_message_complexity(self, message: str) -> str:
        """
        Calculate message complexity to determine routing strategy.
        Returns: 'simple', 'moderate', or 'complex'
        """
        # Simple metrics
        word_count = len(message.split())
        question_count = message.count('?')
        conditional_keywords = ['if', 'but', 'however', 'also', 'and', 'or']
        conditional_count = sum(1 for kw in conditional_keywords if kw in message.lower())
        
        # Scoring
        complexity_score = 0
        if word_count > 30:
            complexity_score += 1
        if question_count > 1:
            complexity_score += 1
        if conditional_count > 2:
            complexity_score += 1
        
        if complexity_score >= 2:
            return 'complex'
        elif complexity_score == 1:
            return 'moderate'
        else:
            return 'simple'

    async def _plan_actions(self, message: str, history_text: str) -> Dict[str, Any]:
        """
        Ask the LLM planner to decide which tools to use with ADAPTIVE SEMANTIC ROUTING.
        Routes based on message complexity and detected intent.
        Uses token budgeting to allocate resources optimally.
        """
        tool_catalog = self._format_tool_catalog()
        
        # Calculate message complexity for adaptive routing
        message_complexity = self._calculate_message_complexity(message)
        logger.info(f"📈 Message complexity: {message_complexity}")
        
        # Semantic routing: Detect intent from message keywords
        msg_lower = message.lower()
        
        # Knowledge/Document intent keywords
        knowledge_keywords = ['policy', 'procedure', 'document', 'documentation', 'handbook', 
                             'guideline', 'standard', 'rule', 'process', 'what is', 'tell me about',
                             'how do we', 'do we have', 'company', 'information about', 'details on',
                             'explain', 'describe', 'background on', 'requirements', 'guidelines']
        
        # Calendar intent keywords
        calendar_keywords = ['schedule', 'meeting', 'calendar', 'event', 'appointment', 'book',
                            'conference', 'call', 'check my', "what's my", 'when am i', 'cancel',
                            'delete', 'reschedule', 'move the', 'time slot']
        
        # Email intent keywords
        email_keywords = ['email', 'send', 'mail', 'message', 'compose', 'inbox', 'check my',
                         'read', 'reply', 'forward', 'unread', 'from', 'to:']
        
        has_knowledge_intent = any(kw in msg_lower for kw in knowledge_keywords)
        has_calendar_intent = any(kw in msg_lower for kw in calendar_keywords)
        has_email_intent = any(kw in msg_lower for kw in email_keywords)
        
        # Adaptive routing: For complex queries, slightly relax knowledge requirements
        if message_complexity == 'complex' and not (has_calendar_intent or has_email_intent):
            logger.info("🎯 Complex query detected - potentially including knowledge search")
            has_knowledge_intent = True
        
        logger.info(f"🧭 Adaptive semantic routing: knowledge={has_knowledge_intent}, calendar={has_calendar_intent}, email={has_email_intent}")
        logger.info(f"📊 Planner tokens allocated: {self.token_budget.get_planner_tokens()} tokens")
        
        # Use prompt library to get the planner prompt with dynamic tool catalog and intent flags
        planner_prompt = prompt_library.get_prompt(
            'sys_planner',
            tool_catalog=tool_catalog,
            history=history_text or "(no prior turns)",
            message=message,
            knowledge_intent=has_knowledge_intent,
            calendar_intent=has_calendar_intent,
            email_intent=has_email_intent
        )

        if not planner_prompt:
            logger.error("❌ Failed to retrieve planner prompt from library")
            return {"actions": [], "final_response": "Error retrieving prompt"}

        # Adaptive token allocation based on complexity
        planner_tokens = self.token_budget.get_planner_tokens()
        if message_complexity == 'complex':
            planner_tokens = int(planner_tokens * 1.2)  # 20% more tokens for complex queries
        
        planner_output = await self.llm_manager.generate(
            prompt=planner_prompt,
            max_tokens=planner_tokens,
            temperature=0.0  # Deterministic: no randomness in tool selection
        )

        plan = self._parse_plan_output(planner_output)
        plan["raw"] = planner_output
        plan["message_complexity"] = message_complexity  # Track for debugging
        return plan

    def _validate_plan_schema(self, parsed: Dict[str, Any]) -> bool:
        """Validate planner output conforms to expected schema."""
        if not isinstance(parsed, dict):
            logger.error("❌ Plan is not a dict")
            return False
        
        if "actions" not in parsed:
            logger.error("❌ Plan missing 'actions' key")
            return False
        
        if not isinstance(parsed["actions"], list):
            logger.error("❌ 'actions' is not a list")
            return False
        
        for action in parsed["actions"]:
            if not isinstance(action, dict):
                logger.error("❌ Action is not a dict")
                return False
            if "tool" not in action or "arguments" not in action:
                logger.error("❌ Action missing 'tool' or 'arguments'")
                return False
        
        return True

    def _validate_tool_arguments(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Validate tool arguments match expected schema."""
        tool = self.tool_map.get(tool_name)
        if not tool:
            logger.error(f"❌ Unknown tool: {tool_name}")
            return False
        
        if not isinstance(arguments, dict):
            logger.error(f"❌ Arguments for {tool_name} not a dict")
            return False
        
        logger.info(f"✓ Tool {tool_name} arguments valid")
        return True

    def _parse_plan_output(self, planner_output: str) -> Dict[str, Any]:
        """Extract and validate JSON from planner output. Safe fallback on failure."""
        try:
            json_start = planner_output.find("{")
            json_end = planner_output.rfind("}")
            if json_start == -1 or json_end == -1:
                raise ValueError("No JSON object found")
            
            plan_json = planner_output[json_start:json_end + 1]
            parsed = json.loads(plan_json)
            
            # Validate schema
            if not self._validate_plan_schema(parsed):
                logger.error("❌ Plan schema validation failed, using safe fallback")
                return {"actions": [], "final_response": ""}
            
            # Validate each tool's arguments
            for action in parsed.get("actions", []):
                if not self._validate_tool_arguments(action["tool"], action.get("arguments", {})):
                    logger.error(f"❌ Argument validation failed for {action['tool']}, using safe fallback")
                    return {"actions": [], "final_response": ""}
            
            final_response = parsed.get("final_response") or ""
            logger.info(f"✓ Plan validated: {len(parsed['actions'])} actions")
            return {"actions": parsed["actions"], "final_response": final_response}
        
        except Exception as exc:
            logger.warning(f"⚠ Planner parsing failed: {exc}")
            return {"actions": [], "final_response": ""}

    async def _execute_plan(self, actions: List[Dict[str, Any]], user_message: str) -> List[Dict[str, Any]]:
        """Execute each planned tool step sequentially."""
        results: List[Dict[str, Any]] = []
        for step, action in enumerate(actions[: self.MAX_TOOL_STEPS], start=1):
            tool_name = action.get("tool")
            arguments = action.get("arguments") or {}
            record = {
                "step": step,
                "tool": tool_name,
                "arguments": arguments,
            }

            tool = self.tool_map.get(tool_name)
            if not tool:
                record["error"] = "Unknown tool"
                logger.warning(f"⚠ Planner selected unknown tool: {tool_name}")
                results.append(record)
                continue

            try:
                normalized_args = self._normalize_tool_arguments(tool_name, arguments, user_message)
                record["arguments"] = normalized_args
                logger.info(f"🔧 Executing tool step {step}: {tool_name} with args {normalized_args}")
                output = await tool._arun(**normalized_args)
                record["output"] = output
            except Exception as exc:
                logger.error(f"✗ Tool {tool_name} failed: {exc}")
                record["error"] = str(exc)

            results.append(record)

        return results

    async def _synthesize_response(
        self,
        user_message: str,
        history_text: str,
        tool_runs: List[Dict[str, Any]],
        planner_hint: Optional[str] = None,
        had_errors: bool = False,
    ) -> str:
        """Convert tool outputs into a final assistant message."""
        tool_log_snippets = []
        for run in tool_runs:
            if "error" in run:
                tool_log_snippets.append(
                    f"Tool {run.get('tool')} failed: {run['error']}"
                )
            else:
                try:
                    pretty_output = json.dumps(run.get("output"), indent=2)
                except Exception:
                    pretty_output = str(run.get("output"))
                tool_log_snippets.append(
                    f"Tool {run.get('tool')} output:\n{pretty_output}"
                )

        resolution_instruction = (
            "Some tool calls failed. Apologize, explain the failure, and tell the user what is still needed."
            if had_errors
            else "Confirm the completed actions and highlight key results."
        )

        # Use prompt library to get synthesis prompt
        synthesis_prompt = prompt_library.get_prompt(
            'sys_synthesis',
            tool_outputs=os.linesep.join(tool_log_snippets) if tool_log_snippets else "(no tools executed)",
            planner_hint=planner_hint or "(none)",
            user_message=user_message,
            resolution_instruction=resolution_instruction
        )
        
        if not synthesis_prompt:
            logger.warning("⚠ Synthesis prompt not found in library, using fallback")
            synthesis_prompt = f"Convert these tool results to a natural response:\n{tool_log_snippets}\n\nUser asked: {user_message}"

        logger.info(f"📊 Synthesis tokens allocated: {self.token_budget.get_synthesis_tokens()} tokens")
        return await self.llm_manager.generate(
            prompt=synthesis_prompt,
            max_tokens=self.token_budget.get_synthesis_tokens(),
            temperature=0.1
        )


    def _score_prompt_match(self, message: str, intent_type: str) -> float:
        """
        Score how well a message matches an intent type (0-100).
        Uses weighted keyword matching for intelligent prompt selection.
        """
        msg_lower = message.lower()
        msg_words = set(msg_lower.split())
        score = 0.0
        
        # Define intent patterns with weighted keywords
        intent_patterns = {
            'meta': {
                'keywords': {
                    ('who', 'are', 'you'): 20,
                    ('what', 'are', 'you'): 20,
                    ('what', 'can', 'you'): 15,
                    ('who', 'owns'): 20,
                    ('whose'): 15,
                    ('creator',): 15,
                    ('built',): 10,
                },
                'base': 5
            },
            'company': {
                'keywords': {
                    ('company',): 20,
                    ('masterprodev',): 25,
                    ('services',): 15,
                    ('expertise',): 15,
                    ('policies',): 15,
                    ('mission',): 15,
                    ('vision',): 15,
                    ('team',): 10,
                    ('about',): 5,
                },
                'base': 5
            },
            'technical': {
                'keywords': {
                    ('how',): 10,
                    ('implement',): 15,
                    ('build',): 15,
                    ('code',): 15,
                    ('development',): 15,
                    ('technical',): 20,
                    ('api',): 15,
                },
                'base': 3
            },
            'greeting': {
                'keywords': {
                    ('hello',): 30,
                    ('hi',): 30,
                    ('hey',): 25,
                    ('good',): 10,
                    ('morning',): 5,
                },
                'base': 10
            }
        }
        
        if intent_type not in intent_patterns:
            return 0.0
        
        pattern = intent_patterns[intent_type]
        score = pattern['base']
        
        # Check keywords (support multi-word patterns)
        for keyword_tuple, weight in pattern['keywords'].items():
            if all(word in msg_lower for word in keyword_tuple):
                score += weight
        
        # Penalty for message length (shorter = clearer intent)
        word_count = len(msg_words)
        if word_count > 30:
            score *= 0.7
        elif word_count < 5:
            score += 10  # Bonus for very short messages
        
        return min(score, 100.0)  # Cap at 100

    def _select_best_prompt(self, message: str) -> str:
        """
        Intelligent prompt selection using semantic intent scoring.
        Returns the best prompt ID for the user message.
        """
        # Score message against all intent types
        intent_scores = {
            'meta': self._score_prompt_match(message, 'meta'),
            'company': self._score_prompt_match(message, 'company'),
            'technical': self._score_prompt_match(message, 'technical'),
            'greeting': self._score_prompt_match(message, 'greeting'),
        }
        
        logger.info(f"🧠 Prompt intent scores: {intent_scores}")
        
        # Map intents to prompts
        intent_to_prompt = {
            'meta': 'conv_meta',
            'company': 'conv_company_info',
            'technical': 'conv_general',  # Could be extended
            'greeting': 'conv_general',
        }
        
        # Find highest scoring intent with threshold
        best_intent = max(intent_scores, key=intent_scores.get)
        best_score = intent_scores[best_intent]
        
        # Only use specialized prompt if score is significant (threshold: 15)
        if best_score >= 15:
            prompt_id = intent_to_prompt[best_intent]
            logger.info(f"✓ Smart selection: intent={best_intent} (score={best_score:.1f}) → prompt={prompt_id}")
        else:
            prompt_id = 'conv_general'
            logger.info(f"⚠ Low confidence intent detection (score={best_score:.1f}), using general prompt")
        
        return prompt_id

    def _build_direct_prompt(self, message: str, history_text: str) -> str:
        """Build a direct response prompt using smart semantic selection."""
        # Use intelligent prompt selection instead of simple keyword matching
        prompt_id = self._select_best_prompt(message)
        
        # Retrieve and format the prompt
        prompt = prompt_library.get_prompt(
            prompt_id,
            message=message,
            history=history_text or "(no prior turns)"
        )
        
        if not prompt:
            # Fallback to a simple prompt if library lookup fails
            logger.warning(f"⚠ Prompt not found in library: {prompt_id}, using fallback")
            prompt = f"You are MasterProDev's AI Assistant.\n\nUser message: {message}\n\nRespond helpfully."
        
        return prompt

    def _format_history(self, conversation_history: Optional[List[Dict[str, str]]]) -> str:
        """Collapse recent turns to a readable block."""
        if not conversation_history:
            return ""
        trimmed = conversation_history[-3:]
        return "\n".join(
            f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in trimmed
        )

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
                
                # Try parsing directly (handles "8:00 am", "3:30 pm", etc.)
                dt = date_parser.parse(candidate_str, fuzzy=True, dayfirst=False)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
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
        
        # Check if message starts with or matches any of these patterns
        for pattern in greetings + meta_questions + conversation_patterns:
            if msg_lower.startswith(pattern):
                logger.info(f"✓ Detected pure conversation pattern: '{pattern}'")
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
