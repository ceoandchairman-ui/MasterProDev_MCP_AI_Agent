"""Prompt Library Service - Dynamic Prompt Management"""

import yaml
import logging
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class PromptLibrary:
    """Manages prompts stored in a YAML file."""
    
    def __init__(self, prompts_file: str = "prompts.yaml"):
        self.prompts_file = Path(prompts_file)
        self.prompts: Dict[str, Dict[str, Any]] = {}
        self._load_prompts()
    
    def _load_prompts(self):
        """Load prompts from YAML file and index by ID."""
        try:
            if not self.prompts_file.exists():
                logger.error(f"Prompts file not found: {self.prompts_file}")
                return
            
            with open(self.prompts_file, 'r') as f:
                data = yaml.safe_load(f)
            
            # Index prompts by their 'id' field, not by YAML key
            yaml_prompts = data.get('prompts', {})
            self.prompts = {}
            for yaml_key, prompt_data in yaml_prompts.items():
                prompt_id = prompt_data.get('id', yaml_key)  # Use 'id' field, fallback to YAML key
                self.prompts[prompt_id] = prompt_data
            
            logger.info(f"✓ Loaded {len(self.prompts)} prompts from {self.prompts_file}")
            logger.debug(f"  Available prompt IDs: {list(self.prompts.keys())}")
            
        except Exception as e:
            logger.error(f"Failed to load prompts: {e}")
            self.prompts = {}
    
    def get_prompt(self, prompt_id: str, **format_args) -> Optional[str]:
        """
        Get a prompt by ID and format it with provided arguments.
        
        Args:
            prompt_id: ID of the prompt (e.g., 'sys_masterprodev', 'conv_general')
            **format_args: Arguments to format into the prompt (e.g., message="hello", history="...")
        
        Returns:
            Formatted prompt string, or None if not found
        """
        if prompt_id not in self.prompts:
            logger.warning(f"Prompt not found: {prompt_id}")
            return None
        
        prompt_data = self.prompts[prompt_id]
        content = prompt_data.get('content', '')
        
        try:
            # Format the prompt with provided arguments
            formatted = content.format(**format_args)
            logger.info(f"✓ Retrieved and formatted prompt: {prompt_id}")
            return formatted
        except KeyError as e:
            logger.error(f"Missing format argument for prompt {prompt_id}: {e}")
            return content  # Return unformatted if format fails
    
    def get_prompt_by_category(self, category: str, prompt_type: str = "conversation") -> Optional[str]:
        """
        Get a prompt by category and type.
        
        Args:
            category: Category of prompt (e.g., 'meta_questions', 'general')
            prompt_type: Type of prompt (e.g., 'conversation', 'system', 'synthesis')
        
        Returns:
            Prompt ID matching the criteria, or None if not found
        """
        for prompt_id, prompt_data in self.prompts.items():
            if (prompt_data.get('category') == category and 
                prompt_data.get('type') == prompt_type):
                return prompt_id
        
        logger.warning(f"No prompt found for category={category}, type={prompt_type}")
        return None
    
    def list_prompts(self) -> Dict[str, Dict[str, Any]]:
        """Return all available prompts."""
        return self.prompts
    
    def reload_prompts(self):
        """Reload prompts from file (useful for hot-reloading)."""
        logger.info("Reloading prompts from file...")
        self._load_prompts()


# Singleton instance
prompt_library = PromptLibrary()
