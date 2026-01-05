from enum import Enum
import re
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class Intent(Enum):
    """Enumeration for user intents."""
    KNOWLEDGE_BASE_QUERY = "knowledge_base_query"
    DATABASE_QUERY = "database_query"
    GREETING_OR_CONVERSATION = "greeting_or_conversation"
    UNSUPPORTED = "unsupported"

class IntentRouter:
    """
    A rule-based router to determine the user's intent from a query.
    """
    def __init__(self):
        # Define keywords and patterns for each intent
        self.intent_patterns = {
            Intent.KNOWLEDGE_BASE_QUERY: [
                r'\b(tell me about|what is|explain|how does|who is|describe)\b',
                r'\b(master ?pro ?dev|mpd|langchain|weaviate)\b', # Keywords specific to your domain
            ],
            Intent.DATABASE_QUERY: [
                r'\b(find|search|get|list)\b.*\b(users|orders|products|customers)\b',
                r'\b(database|query|table|records)\b',
            ],
            Intent.GREETING_OR_CONVERSATION: [
                r'^\s*(hi|hello|hey|good morning|good afternoon|how are you)\b',
                r'^\s*(thanks|thank you|ok|sounds good|great)\b',
                r'^\s*\?$', # A single question mark
            ]
        }
        logging.info("IntentRouter initialized with rule-based patterns.")

    def detect_intent(self, query: str) -> Intent:
        """
        Detects the intent of the query using predefined rules.
        """
        normalized_query = query.lower().strip()

        # Check for greetings first as they are often simple and clear
        for pattern in self.intent_patterns[Intent.GREETING_OR_CONVERSATION]:
            if re.search(pattern, normalized_query, re.IGNORECASE):
                logging.info(f"Intent detected: GREETING_OR_CONVERSATION for query: '{query}'")
                return Intent.GREETING_OR_CONVERSATION

        # Check for database queries
        for pattern in self.intent_patterns[Intent.DATABASE_QUERY]:
            if re.search(pattern, normalized_query, re.IGNORECASE):
                logging.info(f"Intent detected: DATABASE_QUERY for query: '{query}'")
                return Intent.DATABASE_QUERY

        # Check for knowledge base queries
        for pattern in self.intent_patterns[Intent.KNOWLEDGE_BASE_QUERY]:
            if re.search(pattern, normalized_query, re.IGNORECASE):
                logging.info(f"Intent detected: KNOWLEDGE_BASE_QUERY for query: '{query}'")
                return Intent.KNOWLEDGE_BASE_QUERY
        
        # If no specific intent is matched, default to a knowledge base query
        # This is a safe default for a RAG-focused system.
        logging.info(f"No specific intent matched. Defaulting to KNOWLEDGE_BASE_QUERY for query: '{query}'")
        return Intent.KNOWLEDGE_BASE_QUERY

# Example usage:
if __name__ == '__main__':
    router = IntentRouter()
    
    test_queries = [
        "hello there",
        "tell me about master pro dev",
        "what is the architecture?",
        "find all users in the database",
        "thanks!",
        "how are you doing?"
    ]
    
    for q in test_queries:
        intent = router.detect_intent(q)
        print(f"Query: '{q}' -> Intent: {intent.value}")
