"""LangChain Agent Orchestrator for MCP System"""

import logging
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import json

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
        session_id: str,  # Add session_id for state management
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

        # First, check for and handle any pending actions for this session
        # check_and_handle_pending_action will return the result directly if a pending action exists
        pending_result = await self.query_processor.check_and_handle_pending_action(message, session_id)
        if pending_result is not None and isinstance(pending_result, dict):
            # A pending action was successfully resumed
            pending_result["execution_time"] = (datetime.utcnow() - start_time).total_seconds()
            pending_result["llm_provider"] = self.llm_manager.get_active_provider_info() if self.initialized else None
            return pending_result
        
        # If no pending action was handled, process the query normally
        processed_query = await self.query_processor.process_query(message, session_id)

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
                tool_runs = await self._execute_plan(plan["actions"], session_id) # Pass session_id
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
                    elapsed_time=execution_time
                )
            except Exception as eval_error:
                logger.warning(f"⚠️ Evaluation failed (non-critical): {eval_error}")
                # Continue - evaluator is for monitoring only, not core chat logic

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
                            'delete', 'reschedule', 'move the', 'time slot', 'remove event', 'drop meeting',
                            'unscheduled', 'no longer need', 'cancel that', 'remove that']
        
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
        
        # INTENT-BASED VALIDATION: Ensure selected tools match detected intent
        plan = self._validate_plan_by_intent(
            plan, 
            has_knowledge_intent, 
            has_calendar_intent, 
            has_email_intent,
            message
        )
        
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

    def _validate_plan_by_intent(
        self, 
        plan: Dict[str, Any], 
        has_knowledge_intent: bool, 
        has_calendar_intent: bool, 
        has_email_intent: bool,
        message: str
    ) -> Dict[str, Any]:
        """
        Validate that selected tools match the detected intent.
        Prevent calendar tools from being used for knowledge queries, etc.
        """
        actions = plan.get("actions", [])
        if not actions:
            return plan  # No tools, nothing to validate
        
        # Tool categories
        knowledge_tools = ["search_knowledge_base"]
        calendar_tools = ["get_calendar_events", "create_calendar_event", "delete_calendar_event"]
        email_tools = ["send_email", "get_emails", "read_email"]
        
        # Check each action
        for action in actions:
            tool_name = action.get("tool")
            
            # CRITICAL: Prevent mismatched tool usage
            if tool_name in calendar_tools and has_knowledge_intent and not has_calendar_intent:
                logger.error(f"❌ TOOL MISMATCH: Message detected as knowledge query but '{tool_name}' (calendar tool) was selected")
                logger.error(f"   Message: '{message}'")
                logger.error(f"   Intents: knowledge={has_knowledge_intent}, calendar={has_calendar_intent}, email={has_email_intent}")
                return {"actions": [{"tool": "search_knowledge_base", "arguments": {"query": message}}], "final_response": None}
            
            if tool_name in email_tools and has_knowledge_intent and not has_email_intent:
                logger.error(f"❌ TOOL MISMATCH: Message detected as knowledge query but '{tool_name}' (email tool) was selected")
                return {"actions": [{"tool": "search_knowledge_base", "arguments": {"query": message}}], "final_response": None}
            
            if tool_name in knowledge_tools and has_calendar_intent and not has_knowledge_intent:
                logger.error(f"❌ TOOL MISMATCH: Message detected as calendar query but '{tool_name}' (knowledge tool) was selected")
                return {"actions": [{"tool": "get_calendar_events", "arguments": {"days": 7}}], "final_response": None}
        
        # CRITICAL: Validate delete operations have proper workflow
        for i, action in enumerate(actions):
            if action.get("tool") == "delete_calendar_event":
                event_id = action.get("arguments", {}).get("event_id")
                
                # Check if event_id is missing or placeholder
                if not event_id or event_id == "[REQUIRES_ID_FROM_ABOVE]":
                    logger.error("❌ CALENDAR DELETE VALIDATION: delete_calendar_event missing valid event_id")
                    logger.error("   Deletion requires: 1) get_calendar_events to fetch events, 2) delete_calendar_event with event_id")
                    
                    # Check if a preceding get_calendar_events exists
                    has_preceding_get = any(
                        act.get("tool") == "get_calendar_events" 
                        for act in actions[:i]
                    )
                    
                    if not has_preceding_get:
                        logger.info("📋 Enforcing two-step deletion workflow: inserting get_calendar_events")
                        # Force the proper workflow
                        return {
                            "actions": [
                                {"tool": "get_calendar_events", "arguments": {"days": 30, "days_back": 90}},
                                action
                            ],
                            "final_response": None
                        }
        
        return plan

    async def _identify_event_from_description(
        self, 
        description: str, 
        calendar_events: List[Dict[str, Any]]
    ) -> Optional[str]:
        """
        FIX 4: Use LLM to match user's event description to actual calendar event.
        
        Args:
            description: User's event description (e.g., "that January 24 meeting")
            calendar_events: List of calendar events from get_calendar_events
        
        Returns:
            Event ID if match found, None otherwise
        """
        if not calendar_events:
            logger.warning("⚠ No calendar events available for matching")
            return None
        
        # Build event summaries for LLM matching
        event_summaries = []
        for event in calendar_events:
            summary = {
                "id": event.get("id"),
                "title": event.get("summary", "Untitled"),
                "start": event.get("start", {}).get("dateTime", event.get("start", {}).get("date")),
                "description": event.get("description", "")
            }
            event_summaries.append(summary)
        
        # Use LLM to match description to event
        matching_prompt = f"""Given the user's event description: "{description}"
        
Available calendar events:
{json.dumps(event_summaries, indent=2)}

Which event ID best matches the user's description? 
Return ONLY the event ID (e.g., "abc123") or "NONE" if no match found.
Consider date, time, title, and any details mentioned."""
        
        try:
            match_result = await self.llm_manager.generate(
                prompt=matching_prompt,
                max_tokens=50,
                temperature=0.3  # Low temperature for deterministic matching
            )
            
            matched_id = match_result.strip().upper() if match_result else "NONE"
            
            if matched_id != "NONE":
                logger.info(f"✓ Event matched: {matched_id} for description '{description}'")
                return matched_id
            else:
                logger.warning(f"⚠ No event matched for description: {description}")
                return None
                
        except Exception as e:
            logger.error(f"✗ Event matching failed: {e}")
            return None

    async def _execute_plan(self, actions: List[Dict[str, Any]], session_id: str) -> List[Dict[str, Any]]:
        """Execute each planned tool step sequentially."""
        results: List[Dict[str, Any]] = []
        calendar_events_cache = None  # Cache calendar events for event identification
        
        for step, action in enumerate(actions[: self.MAX_TOOL_STEPS], start=1):
            tool_name = action.get("tool")
            arguments = action.get("arguments") or {}
            record = {
                "step": step,
                "tool": tool_name,
                "arguments": arguments,
            }

            # FIX 5: Pre-execution validation for delete operations
            if tool_name == "delete_calendar_event":
                event_id = arguments.get("event_id")
                if not event_id or event_id == "[REQUIRES_ID_FROM_ABOVE]":
                    logger.error("❌ Cannot execute delete: event_id not provided or is placeholder")
                    record["error"] = "Missing event_id - cannot delete without valid event identifier"
                    results.append(record)
                    continue

            tool = self.tool_map.get(tool_name)
            if not tool:
                record["error"] = "Unknown tool"
                logger.warning(f"⚠ Planner selected unknown tool: {tool_name}")
                results.append(record)
                continue

            try:
                normalized_args = self._normalize_tool_arguments(tool_name, arguments, "") # user_message no longer available
                record["arguments"] = normalized_args
                logger.info(f"🔧 Executing tool step {step}: {tool_name} with args {normalized_args}")
                
                # Execute the tool
                output = await tool._arun(**normalized_args)

                # Check if the tool requires user to authenticate
                if isinstance(output, dict) and output.get("status") == "pending_auth":
                    logger.info(f"Tool {tool_name} requires authentication. Saving pending action.")
                    
                    # Get current state
                    state = await state_manager.get_conversation_state(session_id)
                    if not state:
                        state = ConversationState(session_id=session_id, conversation_id=session_id)

                    # Save the pending action
                    pending_action_data = {"tool_name": tool_name, "params": normalized_args}
                    state.pending_action = json.dumps(pending_action_data)
                    
                    # Update the state
                    await state_manager.update_conversation_state(session_id, state)
                
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
        logger.info(f"📋 FINAL PROMPT BEING SENT TO LLM:\n{'='*80}\n{synthesis_prompt}\n{'='*80}")
        return await self.llm_manager.generate(
            prompt=synthesis_prompt,
            max_tokens=self.token_budget.get_synthesis_tokens(),
            temperature=0.1
        )

    async def _evaluate_task(
        self,
        session_id: str,
        user_message: str,
        tool_runs: List[Dict[str, Any]],
        final_response: str,
        elapsed_time: float = 0.0
    ) -> None:
        """
        Evaluate task completion and log metrics.
        Determines task category and calls appropriate evaluator method.
        """
        import uuid
        task_id = f"{session_id}_{uuid.uuid4().hex[:8]}"
        
        # Extract tool names from tool_runs
        tool_names = [run.get("tool") for run in tool_runs]
        tool_outputs = {run.get("tool"): run.get("output") for run in tool_runs}
        
        # Determine task category based on tools used
        msg_lower = user_message.lower()
        task_category = "unknown"
        task_success = True  # Default to True; specific evaluators may override
        
        # Calendar tasks
        if any(t in tool_names for t in ["get_calendar_events", "create_calendar_event", "delete_calendar_event"]):
            task_category = "calendar"
            if "delete" in msg_lower or "remove" in msg_lower or "cancel" in msg_lower:
                evaluator.evaluate_delete_calendar_event(tool_names, tool_outputs, task_id)
            elif "create" in msg_lower or "schedule" in msg_lower or "book" in msg_lower:
                evaluator.evaluate_create_calendar_event(tool_names, tool_outputs, task_id)
            else:
                evaluator.evaluate_get_calendar_events(tool_names, tool_outputs, task_id)
        
        # Knowledge base tasks
        elif "search_knowledge_base" in tool_names:
            task_category = "knowledge"
            evaluator.evaluate_knowledge_search(tool_names, tool_outputs, final_response, task_id)
        
        # Email tasks
        elif "send_email" in tool_names:
            task_category = "email"
            evaluator.evaluate_send_email(tool_names, tool_outputs, task_id)
        elif "get_emails" in tool_names:
            task_category = "email"
            evaluator.evaluate_get_emails(tool_names, tool_outputs, task_id)
        
        # Conversation (no tools)
        else:
            if tool_names:  # Tools were used but we didn't categorize
                logger.debug(f"Unknown tool combination: {tool_names}")
            else:
                task_category = "conversation"
                evaluator.evaluate_conversation(final_response, task_id)
        
        # ====================================================================
        # NEW: Evaluate Tool Usage, Trajectory, and Cost
        # ====================================================================
        
        # Tool Usage Accuracy
        await evaluator.evaluate_tool_usage(tool_runs, task_id, task_category)
        
        # Task Trajectory (completion rate and efficiency)
        await evaluator.evaluate_trajectory(tool_runs, task_id, task_success)
        
        # Cost Tracking (LLM tokens)
        # Extract token counts from LLM manager if available
        prompt_tokens = getattr(self, '_last_prompt_tokens', 0)
        completion_tokens = getattr(self, '_last_completion_tokens', 0)
        total_tokens = prompt_tokens + completion_tokens
        
        await evaluator.evaluate_cost(task_id, prompt_tokens, completion_tokens, total_tokens)
        
        # ====================================================================
        # NEW: Evaluate Reliability & Performance Metrics
        # ====================================================================
        
        # State Consistency (does agent maintain context?)
        conversation_history = getattr(self, f'_session_history_{session_id}', [])
        await evaluator.evaluate_state_consistency(
            session_id=session_id,
            user_message=user_message,
            final_response=final_response,
            conversation_history=conversation_history,
            task_id=task_id
        )
        
        # Robustness (can it handle edge cases?)
        await evaluator.evaluate_robustness(user_message, final_response, task_id)
        
        # Adversarial Safety (can it resist malicious inputs?)
        await evaluator.evaluate_adversarial(user_message, final_response, task_id)
        
        # Verification Behavior (does it double-check?)
        await evaluator.evaluate_verifier(user_message, tool_runs, final_response, task_id)
        
        # Latency (how fast?)
        await evaluator.evaluate_latency(task_id, elapsed_time)
        
        # End-to-End Completion (multi-step workflows)
        await evaluator.evaluate_end_to_end(user_message, tool_runs, final_response, task_id)
        
        # Log aggregated metrics every 10 tasks
        if len(evaluator.results) % 10 == 0:
            evaluator.print_report()

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
        """Collapse recent turns to a readable block. Handles both old and new history formats."""
        if not conversation_history:
            return ""
        trimmed = conversation_history[-10:]  # Keep last 10 turns for better context
        return "\n".join(
            # Try new format first ("user"/"assistant"), fall back to old format ("role"/"content")
            f"{msg.get('role') or 'user'}: {msg.get('content') or msg.get('assistant', '')}" for msg in trimmed
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
