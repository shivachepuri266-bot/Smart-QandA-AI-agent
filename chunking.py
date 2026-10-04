"""
Text Chunking Module for Smart Document Q&A Agent.

This module splits extracted document text into coherent segments (chunks)
using LangChain's RecursiveCharacterTextSplitter.

Why Chunking is Critical for RAG (Project Review Note):
1. LLM Context Window & Efficiency: Passing entire documents wastes tokens and
   leads to the "lost in the middle" phenomenon where LLMs overlook relevant facts.
2. Embedding Granularity: Embedding an entire document washes out specific nuances.
   A 512-character chunk captures a distinct semantic idea, producing dense,
   discriminative vector embeddings.
3. Recursive Splitting Strategy:
   Unlike naive fixed-length slicing, RecursiveCharacterTextSplitter attempts splits
   in a hierarchy of natural boundaries: paragraphs ("\n\n"), sentences ("\n"),
   words (" "), and characters (""). This preserves syntactic and semantic coherence.
4. Overlap (64 characters):
   Guarantees that context spanning across chunk boundaries is not severed,
   allowing complete sentence comprehension during retrieval.
"""

from typing import Any, Dict, List

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    # Fallback if installed through legacy langchain package
    from langchain.text_splitter import RecursiveCharacterTextSplitter


def get_text_splitter(
    chunk_size: int = 512,
    chunk_overlap: int = 64
) -> RecursiveCharacterTextSplitter:
    """
    Initializes and returns a configured RecursiveCharacterTextSplitter instance.

    Args:
        chunk_size: Target maximum character length for each chunk (default: 512).
        chunk_overlap: Number of overlapping characters between consecutive chunks (default: 64).

    Returns:
        Configured RecursiveCharacterTextSplitter instance.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
        length_function=len,
        is_separator_regex=False
    )


def chunk_documents(
    documents: List[Dict[str, Any]],
    chunk_size: int = 512,
    chunk_overlap: int = 64
) -> List[Dict[str, Any]]:
    """
    Splits a list of document units (e.g. pages or single files) into smaller chunks
    while preserving source tracking metadata.

    Args:
        documents: List of dicts, each with {"text": str, "source": str, "page": int}.
        chunk_size: Maximum character length per chunk (default: 512).
        chunk_overlap: Overlapping character count (default: 64).

    Returns:
        List of chunk dictionaries:
        [
            {
                "chunk_id": int,       # Global sequential index
                "text": str,           # Segment text
                "source": str,         # Original file name
                "page": int,           # Page number (1-indexed)
                "chunk_index": int     # Relative chunk index within this page/file
            },
            ...
        ]
    """
    splitter = get_text_splitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    all_chunks: List[Dict[str, Any]] = []
    global_chunk_id = 0

    for doc in documents:
        text = doc.get("text", "")
        source = doc.get("source", "unknown")
        page = doc.get("page", 1)

        if not text.strip():
            continue

        # Split text into overlapping segments
        split_texts = splitter.split_text(text)

        for relative_idx, chunk_text in enumerate(split_texts):
            clean_chunk = chunk_text.strip()
            if not clean_chunk:
                continue

            all_chunks.append({
                "chunk_id": global_chunk_id,
                "text": clean_chunk,
                "source": source,
                "page": page,
                "chunk_index": relative_idx + 1
            })
            global_chunk_id += 1

    return all_chunks
