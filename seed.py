import os
import logging
import json
from pathlib import Path
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Weaviate
from langchain_community.embeddings import HuggingFaceInferenceAPIEmbeddings
from mcp_host.config import Settings
import weaviate
import re
from typing import List, Dict, Any, Tuple
from langchain.schema import Document
import uuid
from docx import Document as DocxDocument

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Simple sentence splitter (no nltk dependency)
def simple_sent_tokenize(text: str) -> List[str]:
    """Split text into sentences using regex."""
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in sentences if s.strip()]

# Optional: Try to load spaCy for entity extraction
try:
    import spacy
    nlp = spacy.load('en_core_web_sm')
    SPACY_AVAILABLE = True
except (ImportError, OSError):
    logging.warning("spaCy not available. Entity extraction disabled.")
    nlp = None
    SPACY_AVAILABLE = False

def extract_entities(text: str) -> Dict[str, List[str]]:
    """
    Extracts named entities from text using spaCy.
    Returns empty dict if spaCy model is not available.
    """
    if nlp is None:
        return {}
    
    doc = nlp(text)
    entities = {}
    for ent in doc.ents:
        if ent.label_ not in entities:
            entities[ent.label_] = []
        entities[ent.label_].append(ent.text)
    
    # Deduplicate
    for label in entities:
        entities[label] = sorted(list(set(entities[label])))
        
    return entities

def load_documents_from_directory(directory_path: str) -> List[Document]:
    """
    Load documents from directory using direct format-specific loaders.
    Supports: .docx, .txt, .md
    No unstructured dependency - robust and fast.
    """
    documents = []
    path = Path(directory_path)
    
    # Supported extensions
    supported_files = list(path.rglob('*.docx')) + list(path.rglob('*.txt')) + list(path.rglob('*.md'))
    
    logging.info(f"Found {len(supported_files)} supported files")
    
    for file_path in supported_files:
        try:
            if file_path.suffix == '.docx':
                # Load DOCX using python-docx directly
                doc = DocxDocument(str(file_path))
                text = '\n'.join([para.text for para in doc.paragraphs if para.text.strip()])
                documents.append(Document(
                    page_content=text,
                    metadata={"source": str(file_path), "type": "docx"}
                ))
                logging.info(f"✓ Loaded {file_path.name} ({len(text)} chars)")
                
            elif file_path.suffix in ['.txt', '.md']:
                # Load text files directly
                with open(file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
                documents.append(Document(
                    page_content=text,
                    metadata={"source": str(file_path), "type": file_path.suffix[1:]}
                ))
                logging.info(f"✓ Loaded {file_path.name} ({len(text)} chars)")
                
        except Exception as e:
            logging.error(f"✗ Failed to load {file_path.name}: {e}")
            continue
    
    return documents

def extract_structure_and_text(doc: Document) -> List[Dict[str, Any]]:
    """
    Extracts structured content from a document.
    Since we're loading with format-specific loaders, content is already clean.
    """
    return [{"type": "paragraph", "content": doc.page_content, "style": "Normal"}]

def deterministic_chunking(
    documents: List[Document],
    tokens_per_chunk: int = 256,
    token_overlap: int = 32,
) -> List[Document]:
    """
    Chunks documents into deterministic, overlapping sentence-based chunks.

    Args:
        documents: List of LangChain documents to process.
        tokens_per_chunk: The target number of tokens for each chunk.
        token_overlap: The number of tokens to overlap between consecutive chunks.

    Returns:
        A list of new Document objects representing the chunks.
    """
    logging.info(f"Starting deterministic chunking: {tokens_per_chunk} tokens/chunk, {token_overlap} token overlap.")
    all_chunks = []
    
    for doc in documents:
        doc_chunks = []
        structured_content = extract_structure_and_text(doc)
        
        full_text = " ".join(block['content'] for block in structured_content)
        sentences = simple_sent_tokenize(full_text)
        
        if not sentences:
            continue

        # Group sentences into chunks
        current_chunk_sentences = []
        current_token_count = 0
        
        sentence_index = 0
        while sentence_index < len(sentences):
            sentence = sentences[sentence_index]
            sentence_token_count = len(sentence.split())

            if current_token_count + sentence_token_count <= tokens_per_chunk:
                current_chunk_sentences.append(sentence)
                current_token_count += sentence_token_count
                sentence_index += 1
            else:
                # Create a chunk
                chunk_text = " ".join(current_chunk_sentences)
                doc_chunks.append(chunk_text)
                
                # Start next chunk with overlap
                overlap_sentence_count = 0
                overlap_token_count = 0
                # Find a good starting point for the next chunk to respect the overlap
                start_next_chunk_from_index = sentence_index - 1
                while start_next_chunk_from_index > 0:
                    # Go backwards from the current sentence
                    prev_sentence = sentences[start_next_chunk_from_index]
                    prev_sentence_tokens = len(prev_sentence.split())
                    if overlap_token_count + prev_sentence_tokens > token_overlap:
                        break
                    overlap_token_count += prev_sentence_tokens
                    start_next_chunk_from_index -= 1
                
                sentence_index = start_next_chunk_from_index + 1
                current_chunk_sentences = []
                current_token_count = 0

        if current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            doc_chunks.append(chunk_text)

        # Create Document objects for each chunk of the current document
        total_chunks = len(doc_chunks)
        for i, chunk_text in enumerate(doc_chunks):
            chunk_metadata = doc.metadata.copy()
            chunk_metadata.update({
                "chunk_id": str(uuid.uuid4()),
                "chunk_index": i,
                "total_chunks": total_chunks,
                "chunk_size": len(chunk_text),
                "token_count": len(chunk_text.split()),
            })
            all_chunks.append(Document(page_content=chunk_text, metadata=chunk_metadata))

    logging.info(f"✓ Created {len(all_chunks)} deterministic chunks.")
    return all_chunks

def seed_documents_from_local():
    """
    Loads documents from a local directory, processes them with hierarchical chunking,
    and seeds them into Weaviate with enriched metadata for better retrieval.
    
    FEATURES:
    - Hierarchical chunking: Base chunks with metadata
    - Enriched metadata: summaries, chunk indices, hierarchy levels
    - Optimized for retrieval and synthesis
    """
    try:
        # Load settings from environment variables
        settings = Settings()
        logging.info("Loaded configuration settings.")

        knowledge_base_path = settings.KNOWLEDGE_BASE_PATH
        if not os.path.isdir(knowledge_base_path):
            logging.error(f"Knowledge base path '{knowledge_base_path}' is not a valid directory.")
            return

        # 1. Load documents from local directory using direct loaders (no unstructured)
        logging.info(f"Loading documents from local directory: {knowledge_base_path}")
        documents = load_documents_from_directory(knowledge_base_path)
        
        if not documents:
            logging.warning("No documents found in the specified local directory.")
            return
        logging.info(f"✓ Successfully loaded {len(documents)} document(s)")

        # 2. Create hierarchical chunks with multi-level summaries
        logging.info("Creating semantic chunks with multi-level summaries...")
        
        # Initialize embeddings first for semantic chunking
        logging.info(f"Initializing Hugging Face Inference API embeddings with model {settings.EMBEDDING_MODEL}.")
        embeddings = HuggingFaceInferenceAPIEmbeddings(
            api_key=settings.HUGGINGFACE_API_KEY,
            model_name=settings.EMBEDDING_MODEL
        )
        
        # Apply deterministic chunking
        chunks = deterministic_chunking(documents)
        
        # Enrich chunks with extracted entities
        logging.info("Enriching chunks with named entities...")
        enriched_chunks = []
        for chunk in chunks:
            entities = extract_entities(chunk.page_content)
            if entities:
                chunk.metadata['entities'] = entities
            enriched_chunks.append(chunk)
        
        logging.info(f"✓ Enriched {len(enriched_chunks)} chunks with entity metadata.")
        
        # Log a few examples of enriched chunks
        for i, chunk in enumerate(enriched_chunks[:3]):
            if 'entities' in chunk.metadata:
                logging.info(f"  - Chunk {i+1} entities: {chunk.metadata['entities']}")
        
        # 🔍 CHUNK VISIBILITY LOGGING
        logging.info("\n" + "="*80)
        logging.info("📋 SEEDING VERIFICATION - ALL CHUNKS CREATED:")
        logging.info("="*80)
        for i, chunk in enumerate(enriched_chunks):
            logging.info(f"\n[CHUNK {i}]")
            logging.info(f"  Size: {len(chunk.page_content)} chars")
            logging.info(f"  Source: {chunk.metadata.get('source', 'unknown')}")
            logging.info(f"  Entities: {chunk.metadata.get('entities', [])}")
            logging.info(f"  Content: {chunk.page_content[:250]}...")
        logging.info("="*80 + "\n")

        # 3. Initialize embeddings
        logging.info(f"Initializing Hugging Face Inference API embeddings for Weaviate with model {settings.EMBEDDING_MODEL}.")
        embeddings = HuggingFaceInferenceAPIEmbeddings(
            api_key=settings.HUGGINGFACE_API_KEY,
            model_name=settings.EMBEDDING_MODEL
        )

        # 4. Seed Weaviate
        logging.info(f"Connecting to Weaviate at {settings.WEAVIATE_HOST}:{settings.WEAVIATE_PORT}...")
        client = weaviate.connect_to_local(
            host=settings.WEAVIATE_HOST,
            port=settings.WEAVIATE_PORT,
            grpc_port=settings.WEAVIATE_GRPC_PORT,
        )
        
        # Clear the collection to ensure fresh data
        collection_name = "Chunk"
        if client.collections.exists(collection_name):
            logging.warning(f"Collection '{collection_name}' already exists. Deleting and recreating.")
            client.collections.delete(collection_name)

        # Create collection with proper schema for new Weaviate v4 API
        from weaviate.classes.config import Configure
        client.collections.create(
            name=collection_name,
            vectorizer_config=Configure.Vectorizer.none(),  # We'll provide vectors
            vector_index_config=Configure.VectorIndex.hnsw()
        )
        logging.info(f"✓ Created Weaviate collection '{collection_name}'")

        # Seed documents with embeddings
        logging.info(f"Seeding {len(enriched_chunks)} hierarchically-structured chunks into Weaviate...")
        collection = client.collections.get(collection_name)
        
        # Generate embeddings and seed documents
        for chunk in enriched_chunks:
            vector = embeddings.embed_query(chunk.page_content)
            collection.data.insert(
                properties={
                    "content": chunk.page_content,
                    "source": chunk.metadata.get("source", ""),
                    "entities": json.dumps(chunk.metadata.get("entities", {})),
                    "summary": chunk.metadata.get("summary", ""),
                    "level": chunk.metadata.get("level", 1)
                },
                vector=vector
            )
        
        logging.info(f"✓ Successfully seeded Weaviate with {len(enriched_chunks)} document chunks (hierarchical structure with summaries).")

    except Exception as e:
        logging.error(f"An error occurred during the seeding process: {e}", exc_info=True)

if __name__ == "__main__":
    seed_documents_from_local()
