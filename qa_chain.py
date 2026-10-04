"""
QA Chain and Retrieval Generation Module for Smart Document Q&A Agent.

This module orchestrates:
1. Question embedding and top-k nearest neighbor retrieval.
2. Context preparation with explicit source and page citations.
3. Grounded prompt assembly preventing hallucinations.
4. LLM querying supporting both Ollama (offline local model) and OpenAI API.

Key Concepts for Project Defense:
- Grounded Prompting: The LLM is strictly constrained to the retrieved context.
  If the provided passages do not contain the answer, it is instructed to explicitly
  state: "I don't have enough information in the provided documents."
- Decoupled Retrieval & Generation: The vector similarity engine is completely
  independent of the LLM provider, allowing zero-friction model swapping.
"""

import os
from typing import Any, Dict, List, Optional
import requests
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()


class LLMInferenceError(Exception):
    """Custom exception raised when an LLM provider fails to generate a response."""
    pass


def format_retrieval_context(chunks: List[Dict[str, Any]]) -> str:
    """
    Formats retrieved chunks into a structured context string with clear citation headers.

    Args:
        chunks: List of chunk metadata dictionaries from the vector store.

    Returns:
        Formatted context string with source and page annotations.
    """
    if not chunks:
        return "No relevant context found."

    context_blocks = []
    for idx, chunk in enumerate(chunks, 1):
        source = chunk.get("source", "Unknown Document")
        page = chunk.get("page", 1)
        chunk_id = chunk.get("chunk_id", idx)
        text = chunk.get("text", "").strip()

        header = f"[Source {idx}: {source} | Page: {page} | Chunk ID: {chunk_id}]"
        context_blocks.append(f"{header}\n{text}")

    return "\n\n".join(context_blocks)


def build_grounded_prompt(question: str, context: str) -> str:
    """
    Constructs a strictly grounded prompt instructing the LLM to answer only
    using the provided context and cite its sources.

    Args:
        question: User's natural language question.
        context: Formatted context passages.

    Returns:
        The complete prompt string ready for LLM consumption.
    """
    prompt = f"""You are an accurate, reliable, and honest Document Question Answering assistant.
Your task is to answer the user's question using ONLY the factual information in the context excerpts below.

Strict Operational Guidelines:
1. Base your answer EXCLUSIVELY on the provided context excerpts. Do not speculate, extrapolate, or utilize outside knowledge.
2. Whenever you provide a fact or statement, cite the source filename and page number from the context headers (for example: [Source: artificial_intelligence_policy.txt, Page 1]).
3. If the answer CANNOT be deduced from the provided context, respond EXACTLY with:
   "I don't have enough information in the provided documents."
4. Never invent or hallucinate facts or citations.

Context Excerpts:
---------------------
{context}
---------------------

User Question:
{question}

Answer:"""
    return prompt


def query_ollama(
    prompt: str,
    model: str = "llama-3-groq-8b-tool-use",
    base_url: str = "http://localhost:1234",
    timeout: int = 120
) -> str:
    """
    Sends the prompt to a locally running LLM server via the OpenAI-compatible
    Chat Completions API (served by LM Studio on port 1234).

    The function is named 'query_ollama' to match the UI label shown to users,
    but it communicates with any OpenAI-compatible local server.

    Args:
        prompt: Assembled prompt text.
        model: Model identifier as listed in the local server (e.g. "llama-3-groq-8b-tool-use").
        base_url: Local LLM server URL (default: "http://localhost:1234").
        timeout: HTTP request timeout in seconds.

    Returns:
        LLM response text.

    Raises:
        LLMInferenceError: If the local server is unreachable or returns an error.
    """
    endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a precise document Q&A assistant. "
                    "Answer only using the supplied context and never fabricate citations."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 512
    }

    try:
        response = requests.post(endpoint, json=payload, timeout=timeout)
        if response.status_code == 404:
            raise LLMInferenceError(
                f"Model '{model}' not found on the local server at {base_url}. "
                "Please ensure the model is loaded in LM Studio."
            )
        response.raise_for_status()
        data = response.json()

        # Parse the OpenAI-compatible response format
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            return content.strip()
        return ""

    except requests.exceptions.ConnectionError as exc:
        raise LLMInferenceError(
            f"Could not connect to the local LLM server at {base_url}. "
            "Please ensure LM Studio is running and its local server is started, "
            "or switch to OpenAI in the sidebar."
        ) from exc
    except requests.exceptions.Timeout as exc:
        raise LLMInferenceError(
            f"Request timed out after {timeout} seconds. The local model may be overloaded."
        ) from exc
    except Exception as exc:
        raise LLMInferenceError(f"Ollama generation failed: {str(exc)}") from exc


def query_openai(
    prompt: str,
    model: str = "gpt-4o-mini",
    api_key: Optional[str] = None
) -> str:
    """
    Sends the prompt to the OpenAI Chat Completions API.

    Args:
        prompt: Assembled prompt text.
        model: OpenAI model name (e.g. "gpt-4o-mini", "gpt-3.5-turbo").
        api_key: OpenAI API key (reads from OPENAI_API_KEY environment variable if not provided).

    Returns:
        LLM response text.

    Raises:
        LLMInferenceError: If the API key is missing or the API returns an error.
    """
    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key or not key.strip():
        raise LLMInferenceError(
            "OpenAI API Key is missing. Please provide it in the sidebar or set OPENAI_API_KEY in your .env file."
        )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=key.strip())

        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a precise document Q&A assistant that answers only using supplied context and never fabricates citations."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=600
        )

        content = response.choices[0].message.content
        return content.strip() if content else ""

    except Exception as exc:
        raise LLMInferenceError(f"OpenAI API call failed: {str(exc)}") from exc


def answer_question(
    question: str,
    vector_store: Any,
    embedder: Any,
    provider: str = "ollama",
    model_name: str = "llama3",
    openai_api_key: Optional[str] = None,
    ollama_url: str = "http://localhost:11434",
    top_k: int = 5
) -> Dict[str, Any]:
    """
    High-level pipeline function executing retrieval, prompt assembly, and LLM inference.

    Args:
        question: User query string.
        vector_store: Instantiated FaissVectorStore.
        embedder: Instantiated EmbeddingModel.
        provider: 'ollama' or 'openai'.
        model_name: LLM identifier (e.g. 'llama3' or 'gpt-4o-mini').
        openai_api_key: Optional OpenAI API key.
        ollama_url: Base URL for Ollama daemon.
        top_k: Number of most similar chunks to retrieve (default: 5).

    Returns:
        Dictionary containing:
        {
            "answer": str,
            "sources": List[Dict[str, Any]],
            "prompt": str
        }
    """
    stats = vector_store.get_stats()
    if stats["total_chunks"] == 0:
        return {
            "answer": "No documents have been indexed yet. Please upload one or more PDF, DOCX, or TXT documents first.",
            "sources": [],
            "prompt": ""
        }

    # Step 1: Embed the user's natural language query
    query_vector = embedder.embed_query(question)

    # Step 2: Retrieve top-k nearest chunks via cosine similarity
    retrieved_chunks = vector_store.similarity_search(query_vector, top_k=top_k)

    # Step 3: Format context passages with citations
    context_text = format_retrieval_context(retrieved_chunks)

    # Step 4: Construct the grounded prompt
    prompt = build_grounded_prompt(question, context_text)

    # Step 5: Dispatch to selected LLM provider
    if provider.lower() == "openai":
        answer = query_openai(prompt=prompt, model=model_name, api_key=openai_api_key)
    else:
        answer = query_ollama(prompt=prompt, model=model_name, base_url=ollama_url)

    return {
        "answer": answer,
        "sources": retrieved_chunks,
        "prompt": prompt
    }
