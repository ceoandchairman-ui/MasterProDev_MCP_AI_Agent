"""LangChain Agent Orchestrator for MCP System"""

import logging
import os
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
import json

from langchain.tools import BaseTool
from dateutil import parser as date_parser

from .mcp_tools import get_all_mcp_tools
from .llm_provider import llm_manager

logger = logging.getLogger(__name__)


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
        self.initialized = False
    
    async def initialize(self):
        """Initialize the agent with LLM and tools"""
        if self.initialized:
            logger.info("⚠ Agent already initialized")
            return
        
        try:
            logger.info("🤖 Initializing MCP Agent...")
            
            # Initialize LLM manager
            await llm_manager.initialize()
            self.llm_manager = llm_manager
            logger.info("✓ LLM manager initialized")
            
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
        """High-level orchestration entrypoint.

        Executes a plan loop: plan → act (tools) → synthesize.
        Returns the final message plus tool call telemetry.
        """
        logger.info(f"[DEBUG] MCPAgent.process_message called. self.llm_manager={self.llm_manager}")
        if not self.initialized:
            logger.warning("⚠ Agent not initialized, initializing now...")
            await self.initialize()

        try:
            logger.info(f"📥 Processing message: {message[:100]}...")
            start_time = datetime.utcnow()

            history_text = self._format_history(conversation_history)
            plan = await self._plan_actions(message, history_text)
            logger.info(f"🧭 Planner output: {plan.get('actions', [])}")

            tool_runs: List[Dict[str, Any]] = []
            final_response: Optional[str] = None

            if plan.get("actions"):
                tool_runs = await self._execute_plan(plan["actions"], message)
                had_errors = any("error" in run for run in tool_runs)
                planner_hint = None if had_errors else plan.get("final_response")
                final_response = await self._synthesize_response(
                    user_message=message,
                    history_text=history_text,
                    tool_runs=tool_runs,
                    planner_hint=planner_hint,
                    had_errors=had_errors,
                )
            else:
                final_response = plan.get("final_response")
                if not final_response:
                    direct_prompt = self._build_direct_prompt(message, history_text)
                    final_response = await self.llm_manager.generate(
                        prompt=direct_prompt,
                        max_tokens=500,
                        temperature=0.3
                    )

            final_response = (final_response or "I couldn't craft a response.").strip()

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
                "llm_provider": llm_manager.get_active_provider_info(),
            }

            logger.info(f"✓ Message processed in {execution_time:.2f}s")
            return response

        except Exception as e:
            logger.error(f"✗ Agent processing error: {e}")
            return {
                "response": f"I encountered an error: {str(e)}. Please try again.",
                "tool_calls": [],
                "execution_time": 0,
                "success": False,
                "error": str(e),
            }

    async def _plan_actions(self, message: str, history_text: str) -> Dict[str, Any]:
        """Ask the LLM planner to decide which tools to use."""
        tool_catalog = self._format_tool_catalog()
        planner_prompt = f"""
You are the planning module for an AI assistant with calendar and email tools. Your task is to decide what the agent should do before it responds to the user.

TOOLS (JSON schema):
{tool_catalog}

CONTEXT:
{history_text or "(no prior turns)"}

USER MESSAGE:
{message}

PLANNING RULES:
1. When the user asks to check, schedule, cancel, or update meetings, you MUST call the appropriate calendar tool.
     - IMPORTANT: Always include explicit start_time and end_time in ISO8601 format.
     - If the user specifies times (e.g., "8:00 am to 9:00 pm"), parse both the start and end times exactly as stated.
     - If only a date is provided with NO time, create an all-day event (start_time at 00:00Z and end_time at 23:59Z).
     - If a time is mentioned but no end time, default to 1 hour duration from start time.
     - Remember prior context: if the user previously said "8:00 am to 9:00 pm" and later says "same time", reuse those exact times.
2. When the user asks about email inbox or wants to send a message, select the corresponding Gmail tool.
3. The "actions" array lists steps IN ORDER. Each arguments object must include every required field named exactly as in the tool schema.
4. For time parsing: interpret times in 24-hour format (e.g., "8:00 am" = 08:00, "9:00 pm" = 21:00). Include date context when available.
5. Ask for clarification instead of guessing only when critical details are missing and no reasonable default exists.
6. The final_response should be a short hint for the responder (e.g., summary of expected outcome). Do NOT tell the user the task is already complete.

Respond with strict JSON matching this template (no additional text):
{{
    "actions": [
        {{"tool": "tool_name", "arguments": {{...}} }}
    ],
    "final_response": "string"
}}

Limit to {self.MAX_TOOL_STEPS} actions. Use [] only when NO tool is needed.
"""

        planner_output = await self.llm_manager.generate(
            prompt=planner_prompt,
            max_tokens=400,
            temperature=0.2
        )

        plan = self._parse_plan_output(planner_output)
        plan["raw"] = planner_output
        return plan

    def _parse_plan_output(self, planner_output: str) -> Dict[str, Any]:
        """Best-effort JSON extraction from planner output."""
        try:
            json_start = planner_output.find("{")
            json_end = planner_output.rfind("}")
            if json_start == -1 or json_end == -1:
                raise ValueError("No JSON object found")
            plan_json = planner_output[json_start:json_end + 1]
            parsed = json.loads(plan_json)
            actions = parsed.get("actions") or []
            if not isinstance(actions, list):
                actions = []
            final_response = parsed.get("final_response") or ""
            return {"actions": actions, "final_response": final_response}
        except Exception as exc:
            logger.warning(f"⚠ Planner output parsing failed: {exc}. Raw: {planner_output[:200]}")
            return {"actions": [], "final_response": planner_output.strip()}

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

        synthesis_prompt = f"""
You are a factual reporting agent. Your ONLY job is to report exactly what the tools returned—nothing more, nothing less.

Tool execution summary:
{os.linesep.join(tool_log_snippets) if tool_log_snippets else "(no tools executed)"}

Planner guidance:
{planner_hint or "(none)"}

CRITICAL RULES:
1. Report ONLY facts from the tool outputs above. Do NOT add details, assume, or fabricate.
2. If a tool returned a "status": "success", say it succeeded and cite the exact fields it returned.
3. If a tool returned a "status": "pending_auth" or "error", report that clearly.
4. Do NOT say "your calendar is empty" unless the tool explicitly said so.
5. Do NOT invent email details, calendar events, or other data not in the tool output.
6. Keep response brief and factual. Be helpful but honest about limitations.

User's request: {user_message}

Based strictly on the tool outputs above, provide a factual summary:
"""

        return await self.llm_manager.generate(
            prompt=synthesis_prompt,
            max_tokens=400,
            temperature=0.1
        )

    def _build_direct_prompt(self, message: str, history_text: str) -> str:
        """Prompt template when the planner chooses not to act."""
        return f"""
You are a helpful assistant with no tool usage required.

Conversation so far:
{history_text or "(no prior turns)"}

User message:
{message}

Reply with a clear, actionable answer.
"""

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
            "llm_provider": llm_manager.get_active_provider_info() if self.initialized else None,
        }


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

# Global agent instance - initialized on startup
mcp_agent = MCPAgent()
