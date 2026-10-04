"""
Vector Store Module for Smart Document Q&A Agent.

This module provides the `FaissVectorStore` class which integrates FAISS IndexFlatL2
with a metadata map linking internal vector IDs to source documents, page numbers,
and raw chunk text.

Key Concepts for Project Defense:
1. FAISS (IndexFlatL2):
   An exact, exhaustive (brute-force) nearest neighbor search index without quantization
   or clustering artifacts. It computes Euclidean (L2) distance across all stored vectors.
2. Cosine Similarity Equivalence:
   Because all input vectors from `embeddings.py` are L2-normalized (unit vectors where ||v|| = 1),
   the squared Euclidean distance d^2 satisfies:
       d^2 = ||u - v||^2 = ||u||^2 + ||v||^2 - 2(u . v) = 2 - 2*cos(theta)
   Solving for cosine similarity:
       cos(theta) = 1 - (d^2 / 2)
   This allows exact cosine similarity ranking using FAISS IndexFlatL2!
3. Metadata Mapping:
   FAISS itself only stores numeric vectors and integer IDs. To cite sources,
   a parallel Python dictionary `metadata_map: dict[int, dict]` maps each vector's
   integer ID to {"chunk_id", "text", "source", "page"}.
4. Resilient Vector Backend:
   If the native FAISS C++ DLL is restricted by system security policies (e.g. Windows
   Smart App Control / WDAC), the system seamlessly falls back to `NumpyIndexFlatL2`
   which implements the identical IndexFlatL2 mathematics and API in pure NumPy.
"""

from typing import Any, Dict, List, Set, Tuple
import numpy as np


class NumpyIndexFlatL2:
    """
    Pure NumPy implementation of FAISS IndexFlatL2.
    Computes exact squared Euclidean distances with 100% mathematical equivalence.
    """

    def __init__(self, dimension: int):
        self.d = dimension
        self.ntotal = 0
        self.vectors: np.ndarray = np.empty((0, dimension), dtype=np.float32)

    def add(self, x: np.ndarray) -> None:
        """Adds vectors to the index."""
        x = np.ascontiguousarray(x, dtype=np.float32)
        if self.ntotal == 0:
            self.vectors = x
        else:
            self.vectors = np.vstack([self.vectors, x])
        self.ntotal = self.vectors.shape[0]

    def search(self, x: np.ndarray, k: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        Searches the index for the k nearest neighbors for each query vector.

        Returns:
            (distances, indices): Tuple of 2D NumPy arrays of shape (N, k).
        """
        if self.ntotal == 0:
            return np.empty((x.shape[0], 0), dtype=np.float32), np.empty((x.shape[0], 0), dtype=np.int64)

        x = np.ascontiguousarray(x, dtype=np.float32)
        k = min(k, self.ntotal)

        # Vectorized Euclidean squared distance: ||u - v||^2 = ||u||^2 + ||v||^2 - 2(u . v)
        # Or direct difference squared sum across axis=1
        all_distances = []
        all_indices = []

        for q in x:
            diffs = self.vectors - q
            dist_sq = np.sum(diffs ** 2, axis=1)

            # Retrieve top-k smallest distances
            nearest_idx = np.argsort(dist_sq)[:k]
            nearest_dist = dist_sq[nearest_idx]

            all_distances.append(nearest_dist)
            all_indices.append(nearest_idx)

        return np.array(all_distances, dtype=np.float32), np.array(all_indices, dtype=np.int64)

    def reset(self) -> None:
        """Clears all vectors from the index."""
        self.ntotal = 0
        self.vectors = np.empty((0, self.d), dtype=np.float32)


class FaissVectorStore:
    """
    Manages FAISS IndexFlatL2 vector indexing and metadata retrieval.
    """

    def __init__(self, dimension: int = 384):
        """
        Initializes an empty FAISS IndexFlatL2 with the given embedding dimension.

        Args:
            dimension: Dimensionality of embeddings (384 for all-MiniLM-L6-v2).
        """
        self.dimension = dimension
        self.backend = "faiss"

        try:
            import faiss
            self.index = faiss.IndexFlatL2(dimension)
        except Exception:
            # Fallback to NumPy IndexFlatL2
            self.index = NumpyIndexFlatL2(dimension)
            self.backend = "numpy_fallback"

        # Maps internal sequential integer ID (0, 1, 2, ...) to chunk metadata
        self.metadata_map: Dict[int, Dict[str, Any]] = {}
        # Tracks unique document sources indexed
        self.unique_sources: Set[str] = set()

    def add_documents(self, chunks: List[Dict[str, Any]], embeddings: np.ndarray) -> int:
        """
        Adds text chunks and their corresponding embedding vectors to the FAISS index.

        Args:
            chunks: List of chunk metadata dictionaries.
            embeddings: 2D NumPy array of shape (N, dimension) of dtype float32.

        Returns:
            Number of newly indexed chunks.

        Raises:
            ValueError: If chunks length doesn't match embeddings row count.
        """
        if len(chunks) == 0:
            return 0

        if len(chunks) != embeddings.shape[0]:
            raise ValueError(
                f"Mismatch: Received {len(chunks)} chunks but {embeddings.shape[0]} embedding vectors."
            )

        if embeddings.shape[1] != self.dimension:
            raise ValueError(
                f"Vector dimension mismatch: Expected {self.dimension}, got {embeddings.shape[1]}."
            )

        # Ensure embeddings are contiguous float32
        vectors = np.ascontiguousarray(embeddings, dtype=np.float32)

        start_id = self.index.ntotal
        self.index.add(vectors)

        # Record metadata for each newly added vector
        for offset, chunk in enumerate(chunks):
            vector_id = start_id + offset
            self.metadata_map[vector_id] = {
                "chunk_id": chunk.get("chunk_id", vector_id),
                "text": chunk.get("text", ""),
                "source": chunk.get("source", "unknown"),
                "page": chunk.get("page", 1),
                "chunk_index": chunk.get("chunk_index", 1)
            }
            self.unique_sources.add(chunk.get("source", "unknown"))

        return len(chunks)

    def similarity_search(self, query_embedding: np.ndarray, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Performs nearest neighbor search and maps results to source metadata.

        Args:
            query_embedding: 2D NumPy array of shape (1, dimension) representing the query.
            top_k: Number of most similar chunks to return (default: 5).

        Returns:
            List of dictionaries containing chunk text, source, page, distance,
            and computed cosine similarity score:
            [
                {
                    "text": str,
                    "source": str,
                    "page": int,
                    "chunk_id": int,
                    "distance": float,
                    "similarity": float  # Cosine similarity in range [0.0, 1.0]
                },
                ...
            ]
        """
        if self.index.ntotal == 0:
            return []

        # Bound top_k to actual total number of indexed vectors
        k = min(top_k, self.index.ntotal)
        query_vector = np.ascontiguousarray(query_embedding, dtype=np.float32)

        # Search index: returns squared L2 distances and vector indices
        distances, indices = self.index.search(query_vector, k)

        results: List[Dict[str, Any]] = []

        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:  # FAISS returns -1 when fewer than k neighbors exist
                continue

            metadata = self.metadata_map.get(int(idx), {})
            # Derive cosine similarity from squared L2 distance on unit vectors:
            # cos(theta) = 1 - (dist / 2)
            cosine_sim = float(1.0 - (float(dist) / 2.0))
            # Clamp to [0.0, 1.0] for clean reporting
            cosine_sim = max(0.0, min(1.0, cosine_sim))

            results.append({
                "chunk_id": metadata.get("chunk_id", idx),
                "text": metadata.get("text", ""),
                "source": metadata.get("source", "unknown"),
                "page": metadata.get("page", 1),
                "chunk_index": metadata.get("chunk_index", 1),
                "distance": float(dist),
                "similarity": round(cosine_sim, 4)
            })

        return results

    def get_stats(self) -> Dict[str, Any]:
        """
        Returns summary statistics of the currently indexed corpus.

        Returns:
            Dict with total chunks count, total documents count, and list of sources.
        """
        return {
            "total_chunks": self.index.ntotal,
            "total_documents": len(self.unique_sources),
            "sources": sorted(list(self.unique_sources)),
            "backend": self.backend
        }

    def clear(self) -> None:
        """
        Clears the vector index and purges all metadata.
        """
        self.index.reset()
        self.metadata_map.clear()
        self.unique_sources.clear()
