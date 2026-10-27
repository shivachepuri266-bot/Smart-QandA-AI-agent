"""
QA Chain and Retrieval Generation Module for Smart Document Q&A Agent.

This module orchestrates:
1. Question embedding and top-k nearest neighbor retrieval.
2. Context preparation with explicit source and page citations.
3. Grounded prompt assembly preventing hallucinations.
4. LLM querying powered exclusively by OpenRouter (supporting free models).

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
    prompt = f"""You are a helpful and accurate Document Question Answering assistant.
Your task is to answer the user's question using the factual information from the context excerpts below.

Strict Operational Guidelines:
1. Base your answer on the provided context excerpts. Explain the details clearly and thoroughly.
2. Whenever you state a key fact or explanation, cite the source filename and page number from the context headers (for example: [Source: filename, Page X]).
3. If the answer cannot be found in the provided context, state clearly:
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


def query_openrouter(
    prompt: str,
    model: str = "openrouter/free",
    api_key: Optional[str] = None,
    timeout: int = 90
) -> str:
    """
    Sends the prompt to OpenRouter's OpenAI-compatible Chat Completions API.

    Args:
        prompt: Assembled prompt text.
        model: OpenRouter model identifier (e.g. 'meta-llama/llama-3.3-70b-instruct:free').
        api_key: OpenRouter API key (defaults to OPENROUTER_API_KEY environment variable).
        timeout: HTTP request timeout in seconds.

    Returns:
        LLM response text.

    Raises:
        LLMInferenceError: If the API key is missing, invalid, or OpenRouter returns an error.
    """
    key = api_key or os.getenv("OPENROUTER_API_KEY")
    if not key:
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "OPENROUTER_API_KEY" in st.secrets:
                key = str(st.secrets["OPENROUTER_API_KEY"])
        except Exception:
            pass

    if not key or not str(key).strip():
        raise LLMInferenceError(
            "OpenRouter API Key is missing. Please enter your API key in the sidebar "
            "or set OPENROUTER_API_KEY in your .env file. (Get a free key at https://openrouter.ai/keys)"
        )

    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key.strip()}",
        "HTTP-Referer": "http://localhost:8501",
        "X-Title": "Smart Document Q&A Agent",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a helpful, accurate, and knowledgeable document Q&A assistant. "
                    "Carefully read the provided context excerpts and answer the user's question with clarity, "
                    "depth, and exact citations."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 1500
    }

    try:
        response = requests.post(endpoint, headers=headers, json=payload, timeout=timeout)

        if response.status_code == 401:
            raise LLMInferenceError(
                "Invalid OpenRouter API Key. Please verify your key at https://openrouter.ai/keys"
            )
        if response.status_code == 402:
            raise LLMInferenceError(
                f"OpenRouter credits exhausted or model '{model}' requires credits. "
                "Please switch to another free model (e.g. meta-llama/llama-3.3-70b-instruct:free) in the sidebar."
            )
        if response.status_code == 429:
            raise LLMInferenceError(
                "OpenRouter rate limit reached for this free model. "
                "Please wait 10 seconds and try again, or switch to a different free model in the sidebar."
            )

        response.raise_for_status()
        data = response.json()

        if "error" in data:
            err_msg = data["error"].get("message", str(data["error"]))
            raise LLMInferenceError(f"OpenRouter error: {err_msg}")

        choices = data.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content") or msg.get("reasoning") or ""
            return content.strip()
        return ""

    except requests.exceptions.Timeout as exc:
        raise LLMInferenceError(
            f"OpenRouter request timed out after {timeout} seconds. The free model may be experiencing high traffic. Please retry."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise LLMInferenceError(
            "Could not connect to OpenRouter (https://openrouter.ai). Please check your internet connection."
        ) from exc
    except LLMInferenceError:
        raise
    except Exception as exc:
        raise LLMInferenceError(f"OpenRouter inference failed: {str(exc)}") from exc


# Backward compatibility aliases for existing tests
query_ollama = query_openrouter
query_openai = query_openrouter


def answer_question(
    question: str,
    vector_store: Any,
    embedder: Any,
    model_name: str = "openrouter/free",
    openrouter_api_key: Optional[str] = None,
    top_k: int = 5,
    **kwargs: Any
) -> Dict[str, Any]:
    """
    High-level pipeline function executing retrieval, prompt assembly, and OpenRouter LLM inference.

    Args:
        question: User query string.
        vector_store: Instantiated FaissVectorStore.
        embedder: Instantiated EmbeddingModel.
        model_name: OpenRouter model identifier (default: 'meta-llama/llama-3.3-70b-instruct:free').
        openrouter_api_key: Optional OpenRouter API key.
        top_k: Number of most similar chunks to retrieve (default: 5).
        **kwargs: Absorbs any legacy arguments (provider, openai_api_key, etc.).

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

    # Step 5: Query OpenRouter
    api_key = openrouter_api_key or kwargs.get("openai_api_key") or os.getenv("OPENROUTER_API_KEY")
    answer = query_openrouter(prompt=prompt, model=model_name, api_key=api_key)

    return {
        "answer": answer,
        "sources": retrieved_chunks,
        "prompt": prompt
    }
