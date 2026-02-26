"""
Multi-turn Processing Framework for Complex Requests

Handles breaking down long or complex user requests into manageable
LLM calls with state persistence across turns.
"""

import logging
from typing import Dict, List, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class ProcessingStrategy(Enum):
    """Strategies for breaking down complex requests."""
    SEQUENTIAL = "sequential"      # Process in strict order
    PARALLEL = "parallel"          # Process independent subtasks in parallel
    HIERARCHICAL = "hierarchical"  # Process with dependencies
    ITERATIVE = "iterative"        # Refine based on previous outputs


class MultiTurnProcessor:
    """
    Breaks down complex requests into multiple turns with state persistence.
    
    Example use cases:
    - Long research queries with multiple document searches
    - Multi-step process descriptions requiring verification at each step
    - Complex questions requiring gathering multiple pieces of information
    """
    
    def __init__(self, llm_manager):
        self.llm_manager = llm_manager
        self.max_turns = 3
        self.turn_history: List[Dict[str, Any]] = []
    
    def should_use_multi_turn(self, message: str, message_complexity: str) -> bool:
        """
        Determine if a message should use multi-turn processing.
        Multi-turn is beneficial for:
        - Long messages (>150 words)
        - Complex messages with multiple questions
        - Requests requiring verification or refinement
        """
        word_count = len(message.split())
        question_count = message.count('?')
        refinement_keywords = ['also', 'furthermore', 'additionally', 'can you', 'explain more', 'go deeper']
        has_refinement = any(kw in message.lower() for kw in refinement_keywords)
        
        use_multi_turn = (
            (word_count > 150 and message_complexity == 'complex') or
            (question_count > 2) or
            has_refinement
        )
        
        if use_multi_turn:
            logger.info(f"📋 Multi-turn processing recommended: {word_count} words, {question_count} questions")
        
        return use_multi_turn
    
    def break_down_request(self, message: str, num_turns: int = 2) -> List[Dict[str, Any]]:
        """
        Break down a complex message into sub-tasks for sequential processing.
        
        Returns list of sub-tasks with:
        - task_id: unique identifier
        - query: the specific question or request
        - depends_on: list of task_ids that must complete first
        - priority: execution priority
        """
        # Analyze message for natural breaking points
        subtasks = []
        
        # Simple heuristic: Split on "also", "furthermore", etc.
        refinement_markers = [' also ', ' furthermore ', ' additionally ', ' and ']
        parts = message
        
        for marker in refinement_markers:
            if marker in message.lower():
                parts_list = message.split(marker)
                if len(parts_list) <= num_turns:
                    for i, part in enumerate(parts_list):
                        subtasks.append({
                            'task_id': f'sub_{i+1}',
                            'query': part.strip(),
                            'depends_on': [f'sub_{i}'] if i > 0 else [],  # Sequential dependency
                            'priority': len(parts_list) - i  # Earlier parts higher priority
                        })
                    break
        
        # If no natural breaking points, create single task
        if not subtasks:
            subtasks = [{
                'task_id': 'main_1',
                'query': message,
                'depends_on': [],
                'priority': 1
            }]
        
        logger.info(f"📋 Broke down request into {len(subtasks)} sub-tasks")
        for task in subtasks:
            logger.debug(f"  - Task {task['task_id']}: {task['query'][:60]}...")
        
        return subtasks
    
    def extract_key_information(self, response: str) -> Dict[str, Any]:
        """
        Extract and structure key information from an LLM response
        for use in subsequent turns.
        """
        return {
            'response': response,
            'length': len(response),
            'has_questions': '?' in response,
            'has_actionables': any(kw in response.lower() for kw in ['should', 'need to', 'must', 'action'])
        }
    
    async def process_multi_turn(
        self,
        original_message: str,
        llm_generate_fn,
        strategy: ProcessingStrategy = ProcessingStrategy.SEQUENTIAL,
        history_text: str = ""
    ) -> Dict[str, Any]:
        """
        Execute multi-turn processing for complex requests.
        
        Args:
            original_message: The full user message
            llm_generate_fn: Async function to call LLM (await llm_generate_fn(...))
            strategy: How to break down and process the request
        
        Returns:
            Aggregated result with all turns and final synthesis
        """
        self.turn_history = []
        
        # Break down the request
        subtasks = self.break_down_request(original_message, num_turns=self.max_turns)
        
        if len(subtasks) == 1:
            logger.info("Single task - no multi-turn needed")
            return {
                'strategy': 'single',
                'turns': 1,
                'result': None  # Will be processed normally
            }
        
        logger.info(f"🔄 Starting multi-turn processing with strategy: {strategy.value}")
        
        turn_results = {}
        
        # Process tasks based on strategy
        if strategy == ProcessingStrategy.SEQUENTIAL:
            for task in subtasks:
                result = await self._execute_task(task, turn_results, llm_generate_fn, history_text=history_text)
                turn_results[task['task_id']] = result
        
        # Synthesize multi-turn results
        final_synthesis = await self._synthesize_multi_turn(turn_results, llm_generate_fn)
        
        self.turn_history.append({
            'strategy': strategy.value,
            'num_subtasks': len(subtasks),
            'results': turn_results,
            'synthesis': final_synthesis
        })
        
        logger.info(f"✓ Multi-turn processing completed in {len(subtasks)} turns")
        
        return {
            'strategy': strategy.value,
            'turns': len(subtasks),
            'turn_results': turn_results,
            'synthesis': final_synthesis,
            'original_message': original_message
        }
    
    async def _execute_task(
        self,
        task: Dict[str, Any],
        previous_results: Dict[str, Any],
        llm_generate_fn,
        history_text: str = ""
    ) -> str:
        """Execute a single sub-task with context from previous results."""
        task_query = task['query']
        task_id = task['task_id']
        
        # Build context from dependencies
        context_text = ""
        if task['depends_on']:
            for dep_id in task['depends_on']:
                if dep_id in previous_results:
                    context_text += f"\nPrevious result ({dep_id}):\n{previous_results[dep_id][:200]}...\n"
        
        # Build conversation history block
        history_block = f"\nConversation so far:\n{history_text}\n" if history_text else ""

        # Construct task prompt
        task_prompt = f"""You are processing part of a larger user request. 
Here is your specific sub-task:

{task_query}
{history_block}
{f"Context from previous step:{context_text}" if context_text else ""}

Answer this sub-task specifically and concisely. Your response will feed into the next part of the request."""
        
        logger.info(f"▶️ Executing task {task_id}: {task_query[:50]}...")
        
        result = await llm_generate_fn(
            prompt=task_prompt,
            max_tokens=300,
            temperature=0.3
        )
        
        logger.info(f"✓ Task {task_id} completed")
        return result
    
    async def _synthesize_multi_turn(
        self,
        turn_results: Dict[str, str],
        llm_generate_fn
    ) -> str:
        """Synthesize results from multiple turns into a cohesive response."""
        combined_results = "\n".join([
            f"Part {i+1}:\n{result}\n"
            for i, (task_id, result) in enumerate(turn_results.items())
        ])
        
        synthesis_prompt = f"""Synthesize these multi-part responses into a single, cohesive answer:

{combined_results}

Combine them naturally without repeating information. Maintain the logical flow and ensure the response reads as a unified answer to the original request."""
        
        logger.info("📝 Synthesizing multi-turn results...")
        
        synthesis = await llm_generate_fn(
            prompt=synthesis_prompt,
            max_tokens=400,
            temperature=0.2
        )
        
        logger.info("✓ Synthesis completed")
        return synthesis
    
    def get_turn_history(self) -> List[Dict[str, Any]]:
        """Retrieve history of multi-turn processing for debugging."""
        return self.turn_history


# Singleton instance (will be initialized with LLM manager)
multi_turn_processor: Optional[MultiTurnProcessor] = None


def initialize_multi_turn_processor(llm_manager):
    """Initialize the multi-turn processor with LLM manager."""
    global multi_turn_processor
    multi_turn_processor = MultiTurnProcessor(llm_manager)
    logger.info("✓ Multi-turn processor initialized")
