# Smart Document Q&A Agent (RAG System)

A modular, production-ready Retrieval-Augmented Generation (RAG) system built with **Python 3.11**, **Streamlit**, **FAISS**, **Sentence-Transformers**, and **Ollama / OpenAI**.

The application allows users to upload local documents (**PDF**, **DOCX**, **TXT**), semantically indexes their contents in a vector store, and answers natural-language questions strictly using the retrieved context—citing the exact file and page/chunk for every statement.

---

## Architecture Overview

Retrieval-Augmented Generation (RAG) combines the search capabilities of dense vector representations with the natural language reasoning of large language models. The system is split into two distinct pipelines:

```
=============================================================================
                      1. OFFLINE INDEXING PIPELINE
=============================================================================
 [User Documents] (PDF, DOCX, TXT)
        │
        ▼
 [Document Ingestion] (PyMuPDF `fitz`, python-docx, UTF-8 text reader)
        │  Extracts text while preserving source metadata & page numbers
        ▼
 [Text Chunking] (RecursiveCharacterTextSplitter: size=512, overlap=64)
        │  Splits text hierarchically into semantically coherent segments
        ▼
 [Dense Embeddings] (Sentence-Transformers: 'all-MiniLM-L6-v2')
        │  Generates 384-dimensional L2-normalized dense vector embeddings
        ▼
 [Vector Store] (FAISS IndexFlatL2 + In-Memory Metadata Map)
        │  Stores vector indices mapped to {text, source, page, chunk_id}

=============================================================================
                       2. ONLINE QUERY PIPELINE
=============================================================================
 [User Query] ("What is the borrowing limit for undergraduates?")
        │
        ▼
 [Query Embedding] (Embed query using 'all-MiniLM-L6-v2' with L2 normalization)
        │
        ▼
 [Cosine Similarity Search] (FAISS IndexFlatL2: Top 5 most similar chunks)
        │  d^2 = ||u - v||^2 = 2 - 2*cos(theta)  ==>  cos(theta) = 1 - (d^2 / 2)
        ▼
 [Grounded Prompt Construction]
        │  Combines system guardrails + retrieved source excerpts + user query
        ▼
 [LLM Inference] (Local Ollama 'llama3' OR Cloud OpenAI 'gpt-4o-mini')
        │  Generates answer strictly bounded by context or admits lack of info
        ▼
 [Streamlit UI Presentation]
        │  Renders generated answer + collapsible source citations & similarity
```

### Why this design? (Key Defense Points for Project Review)
1. **Zero Hallucination Guardrail**: The LLM prompt explicitly constrains the model: *"Base your answer EXCLUSIVELY on the provided context excerpts... If the answer cannot be deduced, respond with 'I don't have enough information in the provided documents.' Never invent or hallucinate facts or citations."*
2. **Offline-First & Zero Cost**: By using `sentence-transformers` locally and FAISS in-memory, embedding generation and retrieval require no internet and zero API costs.
3. **Exact Cosine Similarity via L2 Normalization**: By normalizing all vector embeddings ($\|\vec{v}\| = 1$), the squared Euclidean distance computed by `faiss.IndexFlatL2` corresponds mathematically to Cosine Similarity ($d_{L2}^2 = 2 - 2\cos(\theta)$).
4. **Recursive Chunking with Overlap**: Splitting by `["\n\n", "\n", " ", ""]` prevents splitting in the middle of sentences or words, while 64 characters of overlap ensure that context spanning chunk boundaries is preserved.

---

## Project Structure

```
smart-doc-qa/
├── app.py                  # Streamlit UI, session state, and user interaction
├── ingestion.py            # File loading & text extraction (PDF, DOCX, TXT)
├── chunking.py             # LangChain RecursiveCharacterTextSplitter logic
├── embeddings.py           # SentenceTransformer wrapper ('all-MiniLM-L6-v2')
├── vector_store.py         # FAISS IndexFlatL2 store & metadata mapping
├── qa_chain.py             # Context formatting, grounded prompts & LLM dispatch
├── requirements.txt        # Pinned Python package dependencies
├── README.md               # Documentation and academic review guide
└── sample_docs/            # Pre-packaged sample documents for immediate testing
    ├── artificial_intelligence_policy.txt
    ├── campus_library_guide.txt
    └── quantum_computing_primer.txt
```

---

## Installation & Setup

### Prerequisites
- Python 3.11 installed
- Git (optional)

### 1. Clone or Navigate to the Project Directory
```powershell
cd C:\Users\Shiva\.gemini\antigravity\scratch\smart-doc-qa
```

### 2. Create and Activate Virtual Environment
Using Python's built-in `venv`:
```powershell
python -m venv .venv
.\.venv\Scripts\activate
```
*(Or if using `uv`: `uv venv .venv --python 3.11`)*

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
```

---

## Configuring the LLM

The application supports **two** interchangeable LLM backends:

### Option A: Local Ollama (Default, 100% Free & Offline)
1. Download and install Ollama from [ollama.com](https://ollama.com).
2. Pull the default `llama3` model (or `llama3.2` / `mistral`):
   ```bash
   ollama pull llama3
   ```
3. Ensure the Ollama background daemon is running:
   ```bash
   ollama serve
   ```
4. In the Streamlit sidebar, verify that **"Ollama (Local / Free)"** is selected.

### Option B: OpenAI API (Optional Alternative)
1. Create a `.env` file in the `smart-doc-qa/` folder:
   ```env
   OPENAI_API_KEY=your_actual_openai_api_key_here
   ```
2. In the Streamlit sidebar, select **"OpenAI (API Key)"**. You can also enter or override your API key directly in the sidebar input field.

---

## Running the Application

Launch the Streamlit web interface:
```powershell
streamlit run app.py
```
Streamlit will automatically open your default browser at `http://localhost:8501`.

---

## How to Test the Application

1. **Quick Test using Sample Documents**:
   - In the sidebar under **"Indexed Knowledge Base"**, click **"📁 Load Built-in Sample Docs"**.
   - Notice the document counter updates to 3 documents and the total chunk count is displayed.
2. **Ask Questions**:
   - *Question 1:* `"What is the borrowing period and limit for undergraduate students?"`
     - **Expected Answer:** Undergraduates may borrow up to 25 items concurrently for a 21-day loan period.
     - **Citation:** `campus_library_guide.txt`, Page 1.
   - *Question 2:* `"What is the penalty for a first-time violation of the AI academic policy?"`
     - **Expected Answer:** Automatic grade of zero on the assessment and mandatory completion of an Academic Integrity Workshop.
     - **Citation:** `artificial_intelligence_policy.txt`, Page 1.
   - *Question 3:* `"What is Shor's algorithm and who developed it?"`
     - **Expected Answer:** Developed by Peter Shor in 1994, it solves integer prime factorization in polynomial time.
     - **Citation:** `quantum_computing_primer.txt`, Page 1.
   - *Question 4 (Out-of-domain / Hallucination Test):* `"What is the recipe for chocolate chip cookies?"`
     - **Expected Answer:** *"I don't have enough information in the provided documents."*
3. **Verify Citations**:
   - Expand the collapsible **"📚 Retrieved Source Passages & Citations"** panel under each answer to inspect the exact chunk text, source filename, page, and cosine similarity score.

---

## Module-by-Module Technical Reference

| Module | Core Classes / Functions | Primary Responsibility |
| :--- | :--- | :--- |
| `ingestion.py` | `load_pdf`, `load_docx`, `load_txt`, `load_document` | Extracts clean text page-by-page from raw files; handles stream bytes or disk files. |
| `chunking.py` | `chunk_documents`, `get_text_splitter` | Splits text into 512-character chunks with 64-character overlap while tracking source and page. |
| `embeddings.py` | `EmbeddingModel`, `get_embedding_model` | Caches `all-MiniLM-L6-v2` SentenceTransformer; yields 384-dim L2-normalized float32 vectors. |
| `vector_store.py` | `FaissVectorStore` | Wraps FAISS `IndexFlatL2`; maps internal IDs to metadata and calculates exact cosine similarity. |
| `qa_chain.py` | `build_grounded_prompt`, `answer_question`, `query_ollama`, `query_openai` | Formats context passages, builds hallucination-resistant prompts, and executes LLM queries. |
| `app.py` | `main`, `index_files`, `render_sidebar` | Streamlit reactive web application, file uploader, chat history, and visualization. |
