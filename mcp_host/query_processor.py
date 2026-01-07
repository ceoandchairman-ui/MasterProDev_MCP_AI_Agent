import pkg_resources
from symspellpy import SymSpell, Verbosity
import yaml
from fuzzywuzzy import process
import re
import logging
from typing import Dict, List, Any
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AliasManager:
    """Manages and resolves entity aliases."""
    def __init__(self, alias_config: Dict[str, List[str]]):
        self.alias_map = {}
        if alias_config:
            for canonical, aliases in alias_config.items():
                for alias in aliases:
                    self.alias_map[alias.lower()] = canonical
        logging.info(f"AliasManager initialized with {len(self.alias_map)} aliases.")

    def expand_aliases(self, text: str) -> str:
        """Expands known aliases in the text to their canonical form."""
        if not self.alias_map:
            return text
            
        # A simple implementation using regex to match whole words to avoid replacing parts of words.
        for alias, canonical in self.alias_map.items():
            text = re.sub(r'\b' + re.escape(alias) + r'\b', canonical, text, flags=re.IGNORECASE)
        return text

class SpellingCorrector:
    """Handles spelling correction for queries."""
    def __init__(self, max_edit_distance=2):
        self.sym_spell = SymSpell(max_dictionary_edit_distance=max_edit_distance, prefix_length=7)
        dictionary_path = pkg_resources.resource_filename("symspellpy", "frequency_dictionary_en_82_765.txt")
        # term_index is the column of the term and count_index is the column of the term frequency
        self.sym_spell.load_dictionary(dictionary_path, term_index=0, count_index=1)
        logging.info("SpellingCorrector initialized with default dictionary.")

    def correct(self, text: str) -> str:
        """Corrects spelling in the given text."""
        suggestions = self.sym_spell.lookup_compound(text, max_edit_distance=2)
        if suggestions:
            corrected_text = suggestions[0].term
            logging.info(f"Spelling correction: '{text}' -> '{corrected_text}'")
            return corrected_text
        return text

class QueryProcessor:
    """
    A service to preprocess user queries before they are sent to the RAG pipeline.
    Handles normalization, alias expansion, and spelling correction.
    """
    def __init__(self, alias_config_path: str = None):
        self.alias_manager = None
        self.spelling_corrector = SpellingCorrector()
        
        # Resolve alias config path
        if alias_config_path is None:
            # Try to find aliases.yaml in the same directory as this file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            alias_config_path = os.path.join(current_dir, 'aliases.yaml')
        
        try:
            with open(alias_config_path, 'r') as f:
                alias_config = yaml.safe_load(f).get('aliases', {})
                self.alias_manager = AliasManager(alias_config)
        except FileNotFoundError:
            logging.warning(f"Alias config file not found at {alias_config_path}. No aliases will be used.")
            self.alias_manager = AliasManager({})
        except Exception as e:
            logging.error(f"Error loading alias config: {e}")
            self.alias_manager = AliasManager({})

    def process_query(self, query: str) -> str:
        """
        Processes a raw query through preprocessing steps.
        Step 1: Expand aliases (case-insensitive matching)
        Step 2: Lowercase for search
        Step 3: Light spelling correction only if needed
        """
        # Step 1: Expand aliases BEFORE lowercasing to preserve canonical forms
        processed_query = self.alias_manager.expand_aliases(query)
        
        # Step 2: Lowercase for consistent search
        processed_query = processed_query.lower()
        
        # Step 3: ONLY apply spelling correction to short, obvious typos
        # Skip if query looks reasonable (contains mostly valid words)
        words = processed_query.split()
        if len(words) <= 3 and any(len(word) > 2 for word in words):
            # Only correct if it's a short query with potentially misspelled words
            corrected = self.spelling_corrector.correct(processed_query)
            if corrected != processed_query:
                logging.info(f"Spelling correction: '{processed_query}' -> '{corrected}'")
                processed_query = corrected
        
        logging.info(f"Original Query: '{query}' | Processed Query: '{processed_query}'")
        return processed_query

# Example usage:
if __name__ == '__main__':
    processor = QueryProcessor()
    
    test_queries = [
        "tell me about masterprodev",
        "what is lang chain?",
        "how does weav8 work?",
        "explain mpd architecture"
    ]
    
    for q in test_queries:
        processor.process_query(q)
