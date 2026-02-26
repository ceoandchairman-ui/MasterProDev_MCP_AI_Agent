import weaviate
from weaviate.classes.init import Auth, AdditionalConfig, Timeout
from weaviate.classes.query import MetadataQuery, Filter
from mcp_host.config import settings
from mcp_host.embeddings import MultiFallbackEmbeddings
import logging
from typing import List, Dict, Any, Optional
import json
import os
import asyncio

logger = logging.getLogger(__name__)

class RAGService:
    def __init__(self):
        self.client = None
        self.embeddings = None
        self.hf_api_key = settings.HUGGINGFACE_API_KEY
        self.embedding_model = settings.EMBEDDING_MODEL
     
    def _sync_connect(self):
        """
        Synchronous connection logic to be run in a background thread.
        This ensures we don't block the main asyncio loop during startup.
        """
        if not self.embedding_model:
            logger.error("Embedding model is not configured. RAG service will be disabled.")
            return

        # 1. Connect to Weaviate
        try:
            logger.info(f"Connecting to Weaviate at {settings.WEAVIATE_HOST}:{settings.WEAVIATE_PORT}...")
            
            # Use short timeout (5s) + skip_init_checks to be fast
            self.client = weaviate.connect_to_custom(
                http_host=settings.WEAVIATE_HOST,
                http_port=settings.WEAVIATE_PORT,
                http_secure=False,
                grpc_host=settings.WEAVIATE_HOST,
                grpc_port=settings.WEAVIATE_GRPC_PORT,
                grpc_secure=False,
                additional_config=AdditionalConfig(
                    timeout=Timeout(init=5, query=30, insert=60),
                    skip_init_checks=True
                )
            )

            # Check liveness
            if self.client.is_live():
                logger.info("✓ Successfully connected to Weaviate.")
            else:
                logger.warning("⚠️ Connected to Weaviate object, but service is not live yet.")

        except Exception as e:
            logger.error(f"⚠️ Initial connection to Weaviate failed: {e}")
            logger.warning("Continuing without RAG. Search will be unavailable.")
            self.client = None

        try:
            # 2. Initialize embeddings (shared MultiFallbackEmbeddings class)
            logger.info(f"Initializing embeddings with model {self.embedding_model}...")
            self.embeddings = MultiFallbackEmbeddings(
                api_key=self.hf_api_key, model_name=self.embedding_model
            )

        except Exception as e:
            logger.error(f"Failed to initialize RAG service: {e}", exc_info=True)
            self.client = None
            self.embeddings = None

    async def initialize(self):
        """Deprecated: Use initialize_async instead."""
        await self.initialize_async()

    async def initialize_async(self):
        """
        Initializes the Weaviate client and embeddings in a background thread.
        This is non-blocking and safe for startup.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_connect)

    def _rerank_results(self, query: str, results: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Rerank results using semantic relevance scoring.
        Prioritises section-level (L1) chunks, boosts results with summaries,
        and applies query-keyword matching.
        """
        if not results:
            return []
        
        scored_results = []
        for result in results:
            # Base score: invert distance so CLOSER = HIGHER score
            distance = result.get('distance', 0.5)
            score = max(0, 1.0 - distance)
            
            # Hierarchy boost:
            #   L1 (section) = best for most queries  +0.3
            #   L2 (sub-chunk) = good for detail       +0.15
            #   L0 (doc summary) = broad context only  +0.0
            hierarchy_level = result.get('level', 1)
            if hierarchy_level == 1:
                score += 0.3
            elif hierarchy_level == 2:
                score += 0.15
            
            # Boost results with meaningful summaries
            summary = result.get('summary', '')
            if summary and len(summary) > 50:
                score += 0.2
            
            # Query keyword matching boost
            query_terms = set(query.lower().split())
            content_lower = result.get('content', '').lower()
            section_lower = result.get('section_title', '').lower()
            matches = sum(1 for term in query_terms if term in content_lower or term in section_lower)
            score += min(0.3, matches * 0.05)
            
            scored_results.append({
                'result': result,
                'score': score
            })
        
        # Sort by score and return top-k
        scored_results.sort(key=lambda x: x['score'], reverse=True)
        return scored_results[:top_k]

    def _fetch_parent_texts(self, collection, parent_ids: set) -> Dict[str, str]:
        """
        MultiVector pattern: given a set of parent chunk_ids, fetch their
        full_text from Weaviate so the retriever can return full section
        context alongside matched sub-chunks.
        """
        parent_texts: Dict[str, str] = {}
        for pid in parent_ids:
            try:
                response = collection.query.fetch_objects(
                    filters=Filter.by_property("chunk_id").equal(pid),
                    limit=1,
                )
                if response.objects:
                    obj = response.objects[0]
                    ft = obj.properties.get('full_text', '')
                    if ft:
                        parent_texts[pid] = ft
                    else:
                        # Fallback: use parent's content if no full_text
                        parent_texts[pid] = obj.properties.get('content', '')
            except Exception as e:
                logger.warning(f"Failed to fetch parent chunk {pid}: {e}")
        return parent_texts

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
                return_metadata=MetadataQuery(distance=True)
            )
            
            # Extract results (now includes chunk_id, parent_id, full_text)
            raw_results = []
            for item in response.objects:
                raw_results.append({
                    'id': item.uuid,
                    'chunk_id': item.properties.get('chunk_id', ''),
                    'content': item.properties.get('content', ''),
                    'source': item.properties.get('source', 'Unknown'),
                    'summary': item.properties.get('summary', ''),
                    'level': item.properties.get('level', 1),
                    'section_title': item.properties.get('section_title', ''),
                    'parent_id': item.properties.get('parent_id', ''),
                    'full_text': item.properties.get('full_text', ''),
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
                logger.info(f"  Section: {result.get('section_title', 'N/A')}")
                logger.info(f"  Level: {result['level']}")
                logger.info(f"  Entities: {result['entities']}")
                logger.info(f"  Content: {result['content'][:300]}...")
            
            # Rerank results
            reranked = self._rerank_results(query, raw_results, top_k=limit)
            
            # ── MultiVector pattern: fetch parent full_text for L2 sub-chunks ──
            parent_ids_needed = set()
            for ranked_item in reranked:
                r = ranked_item['result']
                if r['level'] == 2 and r.get('parent_id'):
                    parent_ids_needed.add(r['parent_id'])
            
            parent_texts = {}
            if parent_ids_needed:
                parent_texts = self._fetch_parent_texts(collection, parent_ids_needed)
            
            # Format results
            formatted_results = []
            for ranked_item in reranked:
                result = ranked_item['result']
                
                # Determine best text to return:
                #  - L1 with full_text → use full_text (complete section)
                #  - L2 sub-chunk     → attach parent full_text if available
                #  - Otherwise        → use content as-is
                best_text = result['content']
                parent_context = ""
                
                if result.get('full_text'):
                    # L1 summary-only chunk: return the full section text
                    best_text = result['full_text']
                elif result['level'] == 2 and result.get('parent_id') in parent_texts:
                    # L2 sub-chunk: attach parent section context
                    parent_context = parent_texts[result['parent_id']]
                
                formatted_result = {
                    "text": best_text,
                    "source": result['source'],
                    "summary": result['summary'] or result['content'][:150],
                    "section_title": result.get('section_title', ''),
                    "hierarchy_level": result['level'],
                    "relevance_score": round(ranked_item['score'], 3),
                    "chunk_type": ["document_summary", "section", "sub_chunk"][min(result['level'], 2)]
                }
                if parent_context:
                    formatted_result["parent_context"] = parent_context
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
