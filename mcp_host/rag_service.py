import weaviate
from mcp_host.config import settings
import logging
from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
from typing import List, Dict, Any, Optional
import json

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self):
        self.client = None
        self.embeddings = None
        self.hf_api_key = settings.HUGGINGFACE_API_KEY
        self.embedding_model = settings.EMBEDDING_MODEL
     
    def initialize(self):
        """Initializes the Weaviate client and embeddings."""
        if not self.hf_api_key or not self.embedding_model:
            logger.error("Hugging Face API key or embedding model is not configured. RAG service will be disabled.")
            return
        try:
            # 1. Initialize Weaviate client
            self.client = weaviate.connect_to_local(
                host=settings.WEAVIATE_HOST,
                port=settings.WEAVIATE_PORT,
                grpc_port=settings.WEAVIATE_GRPC_PORT,
            )
            logger.info("✓ Successfully connected to Weaviate.")

            # 2. Initialize Hugging Face embeddings for Inference API
            self.embeddings = HuggingFaceInferenceAPIEmbeddings(
                api_key=self.hf_api_key, model_name=self.embedding_model
            )
            logger.info(f"✓ Hugging Face Inference API embeddings initialized with model {self.embedding_model}.")

        except Exception as e:
            logger.error(f"Failed to initialize RAG service: {e}", exc_info=True)
            self.client = None
            self.embeddings = None

    def _rerank_results(self, query: str, results: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Rerank results using semantic relevance scoring.
        Prioritizes results with good summaries and hierarchy levels.
        """
        if not results:
            return []
        
        # Score each result based on:
        # 1. Content relevance (already filtered by vector search)
        # 2. Summary quality (if available)
        # 3. Hierarchy level (base chunks > grouped chunks)
        scored_results = []
        for result in results:
            score = result.get('distance', 0.5)  # Use Weaviate distance
            
            # Boost base-level chunks (hierarchy level 1)
            hierarchy_level = result.get('level', 1)
            if hierarchy_level == 1:
                score += 0.3
            
            # Boost results with good summaries
            summary = result.get('summary', '')
            if summary and len(summary) > 50:
                score += 0.2
            
            # Query keyword matching boost
            query_terms = set(query.lower().split())
            content_lower = result.get('content', '').lower()
            matches = sum(1 for term in query_terms if term in content_lower)
            score += min(0.3, matches * 0.05)
            
            scored_results.append({
                'result': result,
                'score': score
            })
        
        # Sort by score and return top-k
        scored_results.sort(key=lambda x: x['score'], reverse=True)
        return scored_results[:top_k]

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """
        Performs semantic search using Weaviate with vector embeddings.
        """
        if not self.client or not self.embeddings:
            logger.error("Vector store not initialized. Cannot perform search.")
            return []

        try:
            # Get collection
            collection_name = "Chunk"
            if not self.client.collections.exists(collection_name):
                logger.warning(f"Collection '{collection_name}' does not exist. No data to search.")
                return []
            
            collection = self.client.collections.get(collection_name)
            
            # Generate query embedding
            query_vector = self.embeddings.embed_query(query)
            
            # Perform vector search
            raw_limit = min(limit * 2, 10)
            response = collection.query.near_vector(
                near_vector=query_vector,
                limit=raw_limit,
                return_metadata=weaviate.classes.query.MetadataQuery(distance=True)
            )
            
            # Extract results
            raw_results = []
            for item in response.objects:
                raw_results.append({
                    'id': item.uuid,
                    'content': item.properties.get('content', ''),
                    'source': item.properties.get('source', 'Unknown'),
                    'summary': item.properties.get('summary', ''),
                    'level': item.properties.get('level', 1),
                    'entities': json.loads(item.properties.get('entities', '{}')),
                    'distance': item.metadata.distance
                })
            
            # 🔍 RETRIEVAL VISIBILITY LOGGING
            logger.info("\n" + "="*80)
            logger.info(f"🔎 RAG SEARCH OPERATION")
            logger.info("="*80)
            logger.info(f"Query: '{query}'")
            logger.info(f"Raw results found: {len(raw_results)}")
            
            if not raw_results:
                logger.warning(f"No results found for query: '{query}'")
                logger.info("="*80 + "\n")
                return []
            
            for i, result in enumerate(raw_results):
                logger.info(f"\n[RETRIEVED CHUNK {i}]")
                logger.info(f"  Distance: {result['distance']}")
                logger.info(f"  Source: {result['source']}")
                logger.info(f"  Entities: {result['entities']}")
                logger.info(f"  Content: {result['content'][:300]}...")
            
            # Rerank results
            reranked = self._rerank_results(query, raw_results, top_k=limit)
            
            # Format results
            formatted_results = []
            for ranked_item in reranked:
                result = ranked_item['result']
                formatted_result = {
                    "text": result['content'],
                    "source": result['source'],
                    "summary": result['summary'] or result['content'][:150],
                    "hierarchy_level": result['level'],
                    "relevance_score": round(1 - ranked_item['score'], 2),
                    "chunk_type": "standard"
                }
                formatted_results.append(formatted_result)
            
            logger.info(f"✓ Search for '{query}' returned {len(formatted_results)} reranked results.")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Failed to perform search for '{query}': {e}", exc_info=True)
            return []

    def search_with_summary(self, query: str, limit: int = 3) -> Dict[str, Any]:
        """
        Search and return results organized by relevance with summary headers.
        Better for synthesis and context building.
        """
        results = self.search(query, limit=limit)
        
        if not results:
            return {
                "query": query,
                "found": False,
                "results": [],
                "summary": "No relevant documents found in knowledge base."
            }
        
        # Create a grouped summary
        summary_text = f"Found {len(results)} relevant document(s) for '{query}':\n\n"
        for i, result in enumerate(results, 1):
            summary_text += f"{i}. {result['summary']}\n   Source: {result['source']}\n\n"
        return {
            "query": query,
            "found": True,
            "result_count": len(results),
            "results": results,
            "summary": summary_text,
            "context": "\n---\n".join([r['text'] for r in results])
        }

# Singleton instance
rag_service = RAGService()

# Singleton instance
rag_service = RAGService()
