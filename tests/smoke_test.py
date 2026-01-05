import asyncio
import logging
import os
import sys

# Add the project root to the Python path to allow for absolute imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from mcp_host.query_processor import QueryProcessor
from mcp_host.intent_router import IntentRouter, Intent
from mcp_host.rag_service import rag_service

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SmokeTest:
    """
    A suite of smoke tests to validate the core components of the new RAG pipeline.
    This should be run after the seeder has populated the Weaviate database.
    """

    def __init__(self):
        self.query_processor = QueryProcessor()
        self.intent_router = IntentRouter()
        # The rag_service is a singleton, so we just need to initialize it
        rag_service.initialize()

    async def run_all_tests(self):
        """Runs all smoke tests in sequence."""
        logging.info("🚀 Starting RAG Pipeline Smoke Tests...")
        
        await self.test_query_processing()
        await self.test_intent_routing()
        await self.test_hybrid_search()
        # The filter test is commented out as it depends on specific data being seeded.
        # await self.test_filtered_search()
        
        logging.info("✅ All smoke tests passed successfully!")
        rag_service.close()

    async def test_query_processing(self):
        """Tests the query normalization, alias, and spelling correction."""
        logging.info("--- Running Test: Query Processing ---")
        
        test_query = "tell me abut masterprodev"
        expected_output = "tell me about master pro dev"
        
        processed_query = self.query_processor.process_query(test_query)
        
        assert processed_query == expected_output, f"Expected '{expected_output}', but got '{processed_query}'"
        logging.info(f"✓ Query processing test passed: '{test_query}' -> '{processed_query}'")

    async def test_intent_routing(self):
        """Tests the rule-based intent router."""
        logging.info("--- Running Test: Intent Routing ---")
        
        # Test Case 1: Knowledge Base Query
        kb_query = "what is the architecture of mpd?"
        intent = self.intent_router.detect_intent(kb_query)
        assert intent == Intent.KNOWLEDGE_BASE_QUERY, f"Expected KNOWLEDGE_BASE_QUERY, got {intent}"
        logging.info(f"✓ Intent routing test passed for: '{kb_query}' -> {intent.value}")

        # Test Case 2: Greeting
        greeting_query = "hello there"
        intent = self.intent_router.detect_intent(greeting_query)
        assert intent == Intent.GREETING_OR_CONVERSATION, f"Expected GREETING_OR_CONVERSATION, got {intent}"
        logging.info(f"✓ Intent routing test passed for: '{greeting_query}' -> {intent.value}")

    async def test_hybrid_search(self):
        """Tests the RAG service's hybrid search functionality."""
        logging.info("--- Running Test: Hybrid Search ---")
        
        # This query should be processed correctly and find relevant documents
        query = "what is master pro dev"
        
        results = rag_service.search(query, limit=3)
        
        assert isinstance(results, list), "Search should return a list."
        # We expect results, but can't guarantee how many. Just check that it doesn't crash.
        logging.info(f"✓ Hybrid search test ran successfully and returned {len(results)} results.")
        if results:
            logging.info(f"  - Top result preview: {results[0]['page_content'][:100]}...")

    async def test_filtered_search(self):
        """
        Tests the RAG service's ability to filter search by metadata.
        NOTE: This test's success depends on the content of your 'Company_Documents'
        and the entities extracted by spaCy. It might fail if the specific
        entities/documents do not exist.
        """
        logging.info("--- Running Test: Filtered Search ---")
        
        query = "architecture"
        # This filter assumes that 'Master Pro Dev' will be extracted as an ORG entity.
        filters = {"entities.ORG": "Master Pro Dev"}
        
        results = rag_service.search(query, limit=3, filters=filters)
        
        assert isinstance(results, list), "Filtered search should return a list."
        logging.info(f"✓ Filtered search test ran successfully and returned {len(results)} results.")
        if results:
            logging.info(f"  - Top filtered result preview: {results[0]['page_content'][:100]}...")
            # You could add stronger assertions here if you know your data
            # e.g., assert all(r['metadata']['entities']['ORG'] == 'Master Pro Dev' for r in results)


async def main():
    """Main function to run the smoke tests."""
    smoke_tester = SmokeTest()
    await smoke_tester.run_all_tests()


if __name__ == "__main__":
    # To run this script:
    # 1. Make sure the Docker containers (especially Weaviate and the seeder) have run successfully.
    # 2. From the root directory 'AI_Agent_MCP', run:
    #    python tests/smoke_test.py
    asyncio.run(main())
