import os
import logging
import json
from pathlib import Path
from mcp_host.config import Settings
import weaviate
import re
from typing import List, Dict, Any, Optional, Tuple
import uuid

# ── LangChain imports ─────────────────────────────────────────────────────
from langchain.schema import Document
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
)
from langchain_community.document_loaders import DirectoryLoader, TextLoader

# python-docx for heading-aware .docx parsing (LangChain's Docx2txtLoader
# strips heading structure, so we keep python-docx for that one task)
from docx import Document as DocxDocument

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ============================================================================
# EMBEDDINGS — imported from shared module (single source of truth)
# ============================================================================
from mcp_host.embeddings import MultiFallbackEmbeddings


# Simple sentence splitter — used ONLY for extractive summaries.
# All chunking is handled by LangChain splitters.
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
    Load documents using LangChain DirectoryLoader (for .txt/.md) and
    custom python-docx loader (for .docx — preserves heading structure).

    LangChain handles file discovery, encoding, and Document creation.
    """
    documents = []
    path = Path(directory_path)

    # ── Stage 1: .txt and .md via LangChain DirectoryLoader ────────────
    for ext, label in [("*.txt", "txt"), ("*.md", "md")]:
        try:
            loader = DirectoryLoader(
                str(path),
                glob=f"**/{ext}",
                loader_cls=TextLoader,
                loader_kwargs={"encoding": "utf-8"},
                show_progress=False,
                use_multithreading=True,
            )
            text_docs = loader.load()
            for doc in text_docs:
                file_source = doc.metadata.get("source", "")
                suffix = Path(file_source).suffix if file_source else f".{label}"
                sections = _detect_sections_text(doc.page_content, suffix)
                doc.metadata.update({"type": label, "sections": sections})
                documents.append(doc)
                logging.info(
                    f"✓ Loaded {Path(file_source).name} "
                    f"({len(doc.page_content)} chars, {len(sections)} sections) [LangChain DirectoryLoader]"
                )
        except Exception as e:
            logging.warning(f"DirectoryLoader for {ext} failed: {e}")

    # ── Stage 2: .docx via python-docx (heading-aware) ─────────────────
    for file_path in path.rglob("*.docx"):
        try:
            full_text, sections = _detect_sections_docx(file_path)
            documents.append(Document(
                page_content=full_text,
                metadata={"source": str(file_path), "type": "docx", "sections": sections},
            ))
            logging.info(f"✓ Loaded {file_path.name} ({len(full_text)} chars, {len(sections)} sections)")
        except Exception as e:
            logging.error(f"✗ Failed to load {file_path.name}: {e}")

    logging.info(f"Total: {len(documents)} documents loaded")
    return documents


# ============================================================================
# SECTION DETECTION — 2-stage LangChain pipeline
#   Stage 1: MarkdownHeaderTextSplitter  → structure-aware section splitting
#   Stage 2: RecursiveCharacterTextSplitter → sub-chunk large sections
# ============================================================================

# LangChain Stage 1 splitter — splits by heading hierarchy.
# .docx and .txt are first converted to markdown format, then split here.
_md_header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[
        ("#", "Header 1"),
        ("##", "Header 2"),
        ("###", "Header 3"),
        ("####", "Header 4"),
    ],
)


def _is_heading_by_heuristic(para) -> bool:
    """
    Auto-detect whether a python-docx paragraph is a heading using
    multiple heuristics — works even if the document has no formal
    Heading styles applied.

    Checks (any one is enough):
      1. Word style name starts with "Heading" or equals "Title" / "Subtitle"
      2. Entire paragraph is bold and ≤ 120 chars
      3. Font size ≥ 14 pt and ≤ 120 chars
      4. Text is ALL CAPS, has ≥ 2 words, and ≤ 120 chars
      5. Text matches common numbered-heading patterns
         ("1.", "1.1", "A.", "I.", "Chapter 3", "Section 2", etc.)
    """
    text = para.text.strip()
    if not text or len(text) > 120:
        return False

    # 1. Formal Word style
    style = (para.style.name or "") if para.style else ""
    if style.startswith("Heading") or style in ("Title", "Subtitle"):
        return True

    word_count = len(text.split())
    if word_count < 1 or word_count > 15:
        return False            # Too long for a heading

    # 2. All runs bold
    runs = [r for r in para.runs if r.text.strip()]
    if runs and all(r.bold for r in runs):
        return True

    # 3. Large font (≥ 14pt)
    sizes = {r.font.size.pt for r in runs if r.font and r.font.size}
    if sizes and min(sizes) >= 14:
        return True

    # 4. ALL CAPS with at least 2 words (rules out acronyms like "AI")
    if text == text.upper() and word_count >= 2 and any(c.isalpha() for c in text):
        return True

    # 5. Numbered heading patterns
    if re.match(
        r'^(?:'
        r'\d{1,3}(?:\.\d{1,3}){0,3}\.?\s+'
        r'|[A-Z]\.\s+'
        r'|[IVXLC]+\.\s+'
        r'|(?:Chapter|Section|Part|Appendix|Annex|Module|Unit|Phase|Pillar|Pillar\s*\d)'
        r')'
        , text, re.IGNORECASE
    ):
        return True

    return False


def _infer_heading_level(para) -> int:
    """
    Infer markdown heading level from a python-docx paragraph.

    Priority:
      1. Formal Word styles (Heading 1–4, Title, Subtitle)
      2. Numbered patterns: depth of dot-separated numbers
         "1. Topic" → 1, "1.1 Sub" → 2, "1.1.1 Detail" → 3
      3. Everything else (bold, ALL CAPS) → level 1
    """
    style = (para.style.name or "") if para.style else ""
    if style == "Title":
        return 1
    if style == "Subtitle":
        return 2
    if style.startswith("Heading"):
        try:
            return min(int(style.replace("Heading", "").strip()), 4)
        except (ValueError, IndexError):
            return 1

    # Infer level from numbered-heading depth: "1." → 1, "1.2" → 2, "1.2.3" → 3
    text = para.text.strip()
    m = re.match(r'^(\d{1,3}(?:\.\d{1,3}){0,3})\.?\s+', text)
    if m:
        depth = m.group(1).count('.') + 1      # "1" → 1, "1.2" → 2, "1.2.3" → 3
        return min(depth, 4)

    # Chapter/Section/Part keywords → level 1
    return 1


def _docx_to_markdown(file_path) -> Tuple[str, str]:
    """
    Convert a .docx to markdown-formatted text so LangChain's
    MarkdownHeaderTextSplitter can do structure-aware splitting.

    Returns (markdown_text, plain_full_text).
    """
    doc = DocxDocument(str(file_path))
    md_lines: List[str] = []
    plain_lines: List[str] = []

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        plain_lines.append(text)

        if _is_heading_by_heuristic(para):
            level = _infer_heading_level(para)
            md_lines.append(f"\n{'#' * level} {text}\n")
        else:
            md_lines.append(text)

    return '\n'.join(md_lines), '\n'.join(plain_lines)


def _detect_sections_docx(file_path) -> Tuple[str, List[Dict[str, str]]]:
    """
    Parse .docx → convert to markdown → split with LangChain's
    MarkdownHeaderTextSplitter for automatic structure-aware sections.

    Two LangChain splitters work in a pipeline:
      Stage 1: MarkdownHeaderTextSplitter  → sections by heading
      Stage 2: RecursiveCharacterTextSplitter → sub-chunks (in _build_sub_chunks)
    """
    md_text, full_text = _docx_to_markdown(file_path)
    section_docs = _md_header_splitter.split_text(md_text)

    sections: List[Dict[str, str]] = []
    for doc in section_docs:
        # Pick the most specific (deepest) heading level
        heading = (doc.metadata.get("Header 4") or doc.metadata.get("Header 3")
                   or doc.metadata.get("Header 2") or doc.metadata.get("Header 1")
                   or Path(file_path).stem)
        body = doc.page_content.strip()
        if body:
            sections.append({"heading": heading, "text": body})

    # Fallback: entire document as a single section
    if not sections:
        sections.append({"heading": Path(file_path).stem, "text": full_text})

    logging.info(f"  → Detected {len(sections)} sections in {Path(file_path).name}: "
                 f"{[s['heading'][:50] for s in sections]}")
    return full_text, sections


def _is_text_heading(line: str) -> bool:
    """
    Auto-detect heading lines in plain text / markdown.
    Matches: # headings, ALL CAPS lines, numbered headings, underline patterns.
    """
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False

    # Markdown # heading
    if re.match(r'^#{1,4}\s+', stripped):
        return True

    word_count = len(stripped.split())
    if word_count < 1 or word_count > 15:
        return False

    # ALL CAPS (at least 2 words)
    if stripped == stripped.upper() and word_count >= 2 and any(c.isalpha() for c in stripped):
        return True

    # Numbered heading
    if re.match(
        r'^(?:'
        r'\d{1,3}(?:\.\d{1,3}){0,3}\.?\s+'
        r'|[A-Z]\.\s+'
        r'|[IVXLC]+\.\s+'
        r'|(?:Chapter|Section|Part|Appendix|Annex|Module|Unit|Phase)'
        r')'
        , stripped, re.IGNORECASE
    ):
        return True

    return False


def _detect_sections_text(text: str, file_suffix: str = ".md") -> List[Dict[str, str]]:
    """
    Split .md / .txt into sections using LangChain's MarkdownHeaderTextSplitter.

    - .md files  → fed directly to the splitter (already has # headings).
    - .txt files → auto-detected headings converted to # format first,
                    then split by LangChain.
    """
    if file_suffix == ".md":
        md_text = text
    else:
        # Convert plain-text headings to markdown # format
        lines = text.split('\n')
        md_lines: List[str] = []
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()

            # Underline-style heading: "Title\n=====" → "# Title"
            if stripped and i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and len(next_line) >= 3:
                    if set(next_line) <= {'='}:
                        md_lines.append(f"\n# {stripped}\n")
                        i += 2
                        continue
                    elif set(next_line) <= {'-'}:
                        md_lines.append(f"\n## {stripped}\n")
                        i += 2
                        continue

            # Other heading patterns (ALL CAPS, numbered, etc.)
            if stripped and _is_text_heading(stripped) and not stripped.startswith('#'):
                md_lines.append(f"\n# {stripped}\n")
            else:
                md_lines.append(lines[i])
            i += 1
        md_text = '\n'.join(md_lines)

    section_docs = _md_header_splitter.split_text(md_text)

    sections: List[Dict[str, str]] = []
    for doc in section_docs:
        heading = (doc.metadata.get("Header 4") or doc.metadata.get("Header 3")
                   or doc.metadata.get("Header 2") or doc.metadata.get("Header 1")
                   or "Content")
        body = doc.page_content.strip()
        if body:
            sections.append({"heading": heading, "text": body})

    if not sections:
        sections.append({"heading": "Content", "text": text})

    return sections


# ============================================================================
# EXTRACTIVE SUMMARIES
# ============================================================================

def generate_extractive_summary(
    text: str, max_sentences: int = 3, max_tokens: int = 150
) -> str:
    """Create an extractive summary from the first N sentences, capped at max_tokens."""
    sentences = simple_sent_tokenize(text)
    parts: List[str] = []
    token_count = 0
    for sent in sentences[:max_sentences]:
        sent_tokens = len(sent.split())
        if token_count + sent_tokens > max_tokens and parts:
            break
        parts.append(sent)
        token_count += sent_tokens
    return ' '.join(parts) if parts else text[:400]


# ============================================================================
# SEMANTIC HIERARCHICAL CHUNKING
# ============================================================================

# ── LangChain Stage 2 splitter ─────────────────────────────────────────
# RecursiveCharacterTextSplitter — the recommended default for generic text.
# Tries to split on paragraphs → sentences → words, keeping semantic units.
_sub_chunk_splitter = RecursiveCharacterTextSplitter(
    chunk_size=1024,          # ~256 tokens × 4 chars/token
    chunk_overlap=256,        # ~64 tokens overlap
    separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
    length_function=len,
    is_separator_regex=False,
)


def semantic_hierarchical_chunking(
    documents: List[Document],
    section_max_chars: int = 2048,
    sub_chunk_size: int = 1024,
    sub_chunk_overlap: int = 256,
) -> List[Document]:
    """
    Semantic hierarchical chunking with three levels:

    Level 0 — One document-summary chunk per file (extractive summary).
    Level 1 — One chunk per auto-detected section (kept whole if ≤ section_max_chars).
    Level 2 — Sub-chunks via LangChain RecursiveCharacterTextSplitter when section is large.

    Every chunk carries an extractive summary and parent_id so the retriever
    can walk the hierarchy (child → section → document).

    Works with ANY document — headings are auto-detected from formatting,
    bold, font size, ALL CAPS, or numbered patterns.
    """
    logging.info(
        f"Starting semantic hierarchical chunking: "
        f"section_max={section_max_chars} chars, sub_chunk={sub_chunk_size} chars, overlap={sub_chunk_overlap} chars"
    )
    all_chunks: List[Document] = []

    for doc in documents:
        full_text = doc.page_content
        source = doc.metadata.get("source", "unknown")
        sections = doc.metadata.get("sections", [])

        # ── Level 0: Document summary ───────────────────────────────────────
        doc_summary = generate_extractive_summary(full_text, max_sentences=5, max_tokens=200)
        doc_chunk_id = str(uuid.uuid4())
        all_chunks.append(Document(
            page_content=doc_summary,
            metadata={
                "chunk_id": doc_chunk_id,
                "source": source,
                "level": 0,
                "section_title": "Document Summary",
                "summary": doc_summary,
                "parent_id": "",
                "chunk_index": 0,
                "total_chunks": 1,
                "chunk_size": len(doc_summary),
                "token_count": len(doc_summary.split()),
            }
        ))

        # Fall back to whole-document-as-one-section if no headings detected
        if not sections:
            sections = [{"heading": "Content", "text": full_text}]

        # ── Level 1 + Level 2 ──────────────────────────────────────────────
        for sec_idx, section in enumerate(sections):
            heading = section["heading"]
            sec_text = section["text"].strip()
            if not sec_text:
                continue

            sec_tokens = len(sec_text.split())
            sec_chars  = len(sec_text)
            sec_summary = generate_extractive_summary(sec_text, max_sentences=3, max_tokens=120)
            section_chunk_id = str(uuid.uuid4())

            if sec_chars <= section_max_chars:
                # Section fits in one chunk → Level 1 (full text)
                all_chunks.append(Document(
                    page_content=sec_text,
                    metadata={
                        "chunk_id": section_chunk_id,
                        "source": source,
                        "level": 1,
                        "section_title": heading,
                        "summary": sec_summary,
                        "parent_id": doc_chunk_id,
                        "chunk_index": sec_idx,
                        "total_chunks": 1,
                        "chunk_size": len(sec_text),
                        "token_count": sec_tokens,
                    }
                ))
            else:
                # Section too large → Level 1 summary-only + Level 2 sub-chunks
                # Store full section text in full_text so the retriever can
                # "search on summaries, return full parents" (MultiVector pattern)
                all_chunks.append(Document(
                    page_content=sec_summary,
                    metadata={
                        "chunk_id": section_chunk_id,
                        "source": source,
                        "level": 1,
                        "section_title": heading,
                        "summary": sec_summary,
                        "full_text": sec_text,
                        "parent_id": doc_chunk_id,
                        "chunk_index": sec_idx,
                        "total_chunks": 0,
                        "chunk_size": len(sec_summary),
                        "token_count": len(sec_summary.split()),
                    }
                ))

                # ── Level 2: sub-chunk via LangChain create_documents() ──
                # create_documents() returns Document objects directly,
                # propagating the base metadata to every sub-chunk.
                if sub_chunk_size == 1024 and sub_chunk_overlap == 256:
                    splitter = _sub_chunk_splitter
                else:
                    splitter = RecursiveCharacterTextSplitter(
                        chunk_size=sub_chunk_size,
                        chunk_overlap=sub_chunk_overlap,
                        separators=["\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ", ""],
                        length_function=len,
                        is_separator_regex=False,
                    )

                sub_docs = splitter.create_documents(
                    [sec_text],
                    metadatas=[{
                        "source": source,
                        "level": 2,
                        "section_title": heading,
                        "parent_id": section_chunk_id,
                    }],
                )

                for sub_idx, sub_doc in enumerate(sub_docs):
                    sub_summary = generate_extractive_summary(
                        sub_doc.page_content, max_sentences=2, max_tokens=80
                    )
                    sub_doc.metadata.update({
                        "chunk_id": str(uuid.uuid4()),
                        "summary": sub_summary,
                        "chunk_index": sub_idx,
                        "total_chunks": len(sub_docs),
                        "chunk_size": len(sub_doc.page_content),
                        "token_count": len(sub_doc.page_content.split()),
                    })
                    all_chunks.append(sub_doc)

    l0 = sum(1 for c in all_chunks if c.metadata['level'] == 0)
    l1 = sum(1 for c in all_chunks if c.metadata['level'] == 1)
    l2 = sum(1 for c in all_chunks if c.metadata['level'] == 2)
    logging.info(f"✓ Created {len(all_chunks)} hierarchical chunks (L0={l0}, L1={l1}, L2={l2})")
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
        
        # Initialize embeddings
        logging.info(f"Initializing embeddings with model {settings.EMBEDDING_MODEL}...")
        embeddings = MultiFallbackEmbeddings(
            api_key=settings.HUGGINGFACE_API_KEY,
            model_name=settings.EMBEDDING_MODEL,
        )
        
        # Apply semantic hierarchical chunking
        chunks = semantic_hierarchical_chunking(documents)
        
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
        
        # Chunk summary table (concise production-friendly logging)
        from collections import Counter
        level_counts = Counter(c.metadata.get('level', '?') for c in enriched_chunks)
        source_counts = Counter(
            Path(c.metadata.get('source', 'unknown')).name for c in enriched_chunks
        )
        logging.info("\n" + "="*60)
        logging.info("SEEDING SUMMARY")
        logging.info(f"  Total chunks: {len(enriched_chunks)}")
        logging.info(f"  By level: L0={level_counts.get(0,0)}, L1={level_counts.get(1,0)}, L2={level_counts.get(2,0)}")
        logging.info(f"  By source:")
        for fname, cnt in source_counts.most_common():
            logging.info(f"    {fname}: {cnt} chunks")
        avg_size = sum(len(c.page_content) for c in enriched_chunks) // max(len(enriched_chunks), 1)
        logging.info(f"  Avg chunk size: {avg_size} chars")
        logging.info("="*60 + "\n")

        # 3. Seed Weaviate
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

        # Create collection with explicit property schema
        from weaviate.classes.config import Configure, Property, DataType
        client.collections.create(
            name=collection_name,
            vectorizer_config=Configure.Vectorizer.none(),
            vector_index_config=Configure.VectorIndex.hnsw(),
            properties=[
                Property(name="chunk_id",      data_type=DataType.TEXT),
                Property(name="content",       data_type=DataType.TEXT),
                Property(name="full_text",     data_type=DataType.TEXT),
                Property(name="source",        data_type=DataType.TEXT),
                Property(name="summary",       data_type=DataType.TEXT),
                Property(name="level",         data_type=DataType.INT),
                Property(name="section_title", data_type=DataType.TEXT),
                Property(name="parent_id",     data_type=DataType.TEXT),
                Property(name="entities",      data_type=DataType.TEXT),
                Property(name="chunk_index",   data_type=DataType.INT),
                Property(name="total_chunks",  data_type=DataType.INT),
            ],
        )
        logging.info(f"✓ Created Weaviate collection '{collection_name}' with explicit schema")

        # Seed documents with embeddings
        logging.info(f"Seeding {len(enriched_chunks)} hierarchically-structured chunks into Weaviate...")
        collection = client.collections.get(collection_name)
        
        # Generate embeddings and seed documents with better error handling
        for i, chunk in enumerate(enriched_chunks):
            try:
                logging.info(f"Embedding chunk {i+1}/{len(enriched_chunks)}...")
                vector = embeddings.embed_query(chunk.page_content)
                
                if not vector or len(vector) == 0:
                    logging.error(f"✗ Empty embedding returned for chunk {i}")
                    continue
                    
                collection.data.insert(
                    properties={
                        "chunk_id": chunk.metadata.get("chunk_id", ""),
                        "content": chunk.page_content,
                        "full_text": chunk.metadata.get("full_text", ""),
                        "source": chunk.metadata.get("source", ""),
                        "summary": chunk.metadata.get("summary", ""),
                        "level": chunk.metadata.get("level", 1),
                        "section_title": chunk.metadata.get("section_title", ""),
                        "parent_id": chunk.metadata.get("parent_id", ""),
                        "entities": json.dumps(chunk.metadata.get("entities", {})),
                        "chunk_index": chunk.metadata.get("chunk_index", 0),
                        "total_chunks": chunk.metadata.get("total_chunks", 1),
                    },
                    vector=vector
                )
                logging.info(f"✓ Seeded chunk {i+1} successfully")
            except Exception as e:
                logging.error(f"✗ Failed to seed chunk {i}: {e}")
                continue
        
        logging.info(f"✓ Successfully seeded Weaviate with {len(enriched_chunks)} document chunks (hierarchical structure with summaries).")

    except Exception as e:
        logging.error(f"An error occurred during the seeding process: {e}", exc_info=True)

if __name__ == "__main__":
    seed_documents_from_local()
