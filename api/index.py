"""
Vercel Serverless Entrypoint for Smart Document Q&A Agent.

This module provides a FastAPI backend exporting the top-level `app` variable
required by Vercel's Python runtime. It integrates the complete RAG pipeline
(ingestion, chunking, embeddings, vector store, QA chain) and serves an interactive,
stylish Cream & Stylish frontend UI.
"""

import os
import sys
import glob
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Ensure parent directory is in Python path to import existing RAG modules
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ingestion import load_document, DocumentParsingError
from chunking import chunk_documents
from embeddings import get_embedding_model
from vector_store import FaissVectorStore
from qa_chain import answer_question, LLMInferenceError

# --- VERCEL REQUIRED TOP-LEVEL APP OBJECT ---
app = FastAPI(
    title="Smart Document Q&A Agent",
    description="Retrieval-Augmented Generation (RAG) System deployed on Vercel"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory Vector Store and Embeddings
vector_store = FaissVectorStore(dimension=384)
embedder = get_embedding_model("all-MiniLM-L6-v2")
processed_files = set()


class QuestionRequest(BaseModel):
    question: str
    api_key: Optional[str] = None
    model_name: Optional[str] = "meta-llama/llama-3.3-70b-instruct:free"


@app.get("/", response_class=HTMLResponse)
def serve_ui():
    """Serves the complete Cream & Stylish responsive web application."""
    stats = vector_store.get_stats()
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Smart Document Q&A Agent</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-base: #FBF6EF;
      --bg-sidebar: #F3EAD8;
      --bg-card: #FFFDF9;
      --text-main: #3B2F2F;
      --text-muted: #7A6961;
      --accent: #B5651D;
      --accent-light: #F5E8D7;
      --accent-hover: #984E12;
      --accent-gold: #C9852B;
      --border-subtle: #EADDC9;
      --border-hover: #D8C3A8;
      --shadow-sm: 0 2px 8px rgba(59, 47, 47, 0.04);
      --shadow-md: 0 4px 16px rgba(59, 47, 47, 0.06);
      --radius-sm: 8px;
      --radius-md: 12px;
      --radius-lg: 16px;
      --radius-pill: 9999px;
      --transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      background-color: var(--bg-base);
      color: var(--text-main);
      line-height: 1.6;
      padding: 0;
    }}

    .layout-container {{
      display: flex;
      min-height: 100vh;
    }}

    /* --- Sidebar --- */
    .sidebar {{
      width: 320px;
      background-color: var(--bg-sidebar);
      border-right: 1px solid var(--border-subtle);
      padding: 24px 20px;
      flex-shrink: 0;
    }}

    .sidebar-title {{
      font-size: 1.25rem;
      font-weight: 800;
      color: var(--text-main);
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .sidebar-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 16px;
      margin-bottom: 18px;
      box-shadow: var(--shadow-sm);
    }}

    .sidebar-heading {{
      font-size: 0.8rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--accent);
      margin-bottom: 12px;
    }}

    .stat-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-bottom: 14px;
    }}

    .stat-card {{
      background: var(--bg-base);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 10px 12px;
      text-align: center;
    }}

    .stat-value {{
      font-size: 1.6rem;
      font-weight: 800;
      color: var(--accent);
    }}

    .stat-label {{
      font-size: 0.72rem;
      font-weight: 600;
      text-transform: uppercase;
      color: var(--text-muted);
    }}

    /* --- Main Content --- */
    .main-content {{
      flex-grow: 1;
      padding: 32px 48px;
      max-width: 960px;
      margin: 0 auto;
    }}

    .hero-header {{
      display: flex;
      align-items: center;
      gap: 16px;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 2px solid var(--border-subtle);
    }}

    .hero-badge {{
      width: 52px;
      height: 52px;
      background: var(--accent-light);
      border: 1.5px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 26px;
      box-shadow: var(--shadow-sm);
    }}

    .hero-title {{
      font-size: 2rem;
      font-weight: 800;
      color: var(--text-main);
      letter-spacing: -0.02em;
    }}

    .hero-subtitle {{
      font-size: 0.95rem;
      color: var(--text-muted);
    }}

    .section-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: var(--radius-lg);
      padding: 24px;
      margin-bottom: 24px;
      box-shadow: var(--shadow-sm);
      transition: var(--transition);
    }}

    .section-title {{
      font-size: 1.15rem;
      font-weight: 700;
      margin-bottom: 14px;
      color: var(--text-main);
    }}

    /* --- File Upload Dropzone --- */
    .dropzone {{
      border: 2px dashed var(--border-subtle);
      border-radius: var(--radius-md);
      padding: 28px;
      text-align: center;
      background: var(--bg-base);
      cursor: pointer;
      transition: var(--transition);
    }}

    .dropzone:hover {{
      border-color: var(--accent);
      background: var(--accent-light);
    }}

    /* --- Inputs & Buttons --- */
    input[type="text"], input[type="password"] {{
      width: 100%;
      padding: 12px 16px;
      background: var(--bg-card);
      border: 1.5px solid var(--border-subtle);
      border-radius: var(--radius-md);
      font-size: 0.95rem;
      font-family: inherit;
      color: var(--text-main);
      margin-bottom: 12px;
      transition: var(--transition);
    }}

    input[type="text"]:focus, input[type="password"]:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(181, 101, 29, 0.16);
      outline: none;
    }}

    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 10px 20px;
      font-size: 0.95rem;
      font-weight: 600;
      font-family: inherit;
      border-radius: var(--radius-md);
      cursor: pointer;
      border: 1px solid var(--border-subtle);
      background: var(--bg-card);
      color: var(--text-main);
      transition: var(--transition);
      box-shadow: var(--shadow-sm);
    }}

    .btn:hover {{
      transform: translateY(-2px);
      border-color: var(--accent);
      color: var(--accent);
      box-shadow: var(--shadow-md);
    }}

    .btn:active {{
      transform: translateY(1px);
    }}

    .btn-primary {{
      background: linear-gradient(135deg, var(--accent-gold), var(--accent));
      color: white;
      border: none;
      box-shadow: 0 4px 14px rgba(181, 101, 29, 0.25);
    }}

    .btn-primary:hover {{
      background: linear-gradient(135deg, var(--accent), var(--accent-hover));
      color: white;
      box-shadow: 0 6px 20px rgba(181, 101, 29, 0.35);
    }}

    .btn-full {{
      width: 100%;
      margin-bottom: 10px;
    }}

    /* --- Info Card --- */
    .info-card {{
      display: flex;
      align-items: center;
      gap: 12px;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-left: 5px solid var(--accent);
      border-radius: var(--radius-md);
      padding: 14px 18px;
      margin: 14px 0 20px 0;
    }}

    /* --- Answer Display --- */
    .answer-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-left: 6px solid var(--accent);
      border-radius: var(--radius-lg);
      padding: 22px 26px;
      box-shadow: var(--shadow-md);
      margin-top: 20px;
      animation: fadeIn 0.4s ease-out;
    }}

    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(10px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    .answer-header {{
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--accent);
      margin-bottom: 12px;
    }}

    .citation-chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 16px;
      padding-top: 14px;
      border-top: 1px dashed var(--border-subtle);
    }}

    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: var(--accent-light);
      color: #783C08;
      border: 1px solid rgba(181, 101, 29, 0.22);
      border-radius: var(--radius-pill);
      padding: 5px 12px;
      font-size: 0.82rem;
      font-weight: 600;
    }}

    .chip-score {{
      background: var(--bg-card);
      padding: 2px 7px;
      border-radius: var(--radius-pill);
      font-size: 0.74rem;
      color: var(--accent);
    }}

    .status-toast {{
      font-size: 0.9rem;
      margin-top: 10px;
      padding: 8px 12px;
      border-radius: var(--radius-sm);
      display: none;
    }}

    .status-success {{ background: #E6F4EA; color: #137333; border: 1px solid #CEEAD6; display: block; }}
    .status-error {{ background: #FCE8E6; color: #C5221F; border: 1px solid #FAD2CF; display: block; }}

    /* Responsive */
    @media (max-width: 800px) {{
      .layout-container {{ flex-direction: column; }}
      .sidebar {{ width: 100%; border-right: none; border-bottom: 1px solid var(--border-subtle); }}
      .main-content {{ padding: 20px 16px; }}
    }}
  </style>
</head>
<body>
  <div class="layout-container">
    
    <!-- Sidebar -->
    <div class="sidebar">
      <div class="sidebar-title">⚙️ System Control</div>

      <div class="sidebar-card">
        <div class="sidebar-heading">📊 Indexed Knowledge Base</div>
        <div class="stat-grid">
          <div class="stat-card">
            <div class="stat-value" id="docCount">{stats['total_documents']}</div>
            <div class="stat-label">Documents</div>
          </div>
          <div class="stat-card">
            <div class="stat-value" id="chunkCount">{stats['total_chunks']}</div>
            <div class="stat-label">Chunks</div>
          </div>
        </div>
        <button class="btn btn-full" onclick="loadSampleDocs()">📁 Load Built-in Samples</button>
        <button class="btn btn-full" onclick="clearIndex()">🗑️ Clear Vector Index</button>
        <div id="sidebarToast" class="status-toast"></div>
      </div>

      <div class="sidebar-card">
        <div class="sidebar-heading">🌐 OpenRouter LLM</div>
        <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 10px;">
          Using OpenRouter free models. Enter your OpenRouter API key below (or set OPENROUTER_API_KEY in environment variables).
        </p>
        <input type="password" id="sidebarApiKey" placeholder="sk-or-v1-..." />
      </div>

      <div style="font-size: 0.78rem; color: var(--text-muted); text-align: center; margin-top: 20px;">
        🎓 <strong>Smart Document Q&A Agent</strong><br>
        Vercel Serverless Edition • MiniLM-L6-v2 • FAISS
      </div>
    </div>

    <!-- Main Content -->
    <div class="main-content">
      <div class="hero-header">
        <div class="hero-badge">📄</div>
        <div>
          <div class="hero-title">Smart Document Q&A Agent</div>
          <div class="hero-subtitle">
            A <strong>Retrieval-Augmented Generation (RAG)</strong> system that indexes local documents (PDF, DOCX, TXT) and generates cited answers.
          </div>
        </div>
      </div>

      <!-- Upload Section -->
      <div class="section-card">
        <div class="section-title">1. Upload Documents</div>
        <div class="dropzone" onclick="document.getElementById('fileUploadInput').click()">
          <div style="font-size: 2rem; margin-bottom: 8px;">📥</div>
          <strong>Click to select documents</strong> (PDF, DOCX, TXT)
          <div style="font-size: 0.85rem; color: var(--text-muted); margin-top: 4px;">Supports multiple files</div>
          <input type="file" id="fileUploadInput" multiple accept=".pdf,.docx,.txt" style="display:none;" onchange="handleFileUpload(event)">
        </div>
        <div id="uploadToast" class="status-toast"></div>
      </div>

      <!-- Question Section -->
      <div class="section-card">
        <div class="section-title">2. Ask a Question</div>
        
        <div class="info-card" id="emptyNotice" style="display: {'none' if stats['total_chunks'] > 0 else 'flex'};">
          <div style="font-size: 1.3rem;">💡</div>
          <div>
            <strong>No documents indexed yet.</strong> Upload documents above or click <strong>'📁 Load Built-in Samples'</strong> in the sidebar.
          </div>
        </div>

        <input type="text" id="userQuestion" placeholder="e.g. What is the borrowing limit for undergraduate students?" />
        <button class="btn btn-primary" id="askBtn" onclick="askQuestion()">🔍 Get Answer with Citations</button>
        
        <div id="askLoading" style="display:none; margin-top:14px; font-weight:600; color:var(--accent);">
          ⏳ Retrieving relevant passages & generating grounded answer...
        </div>

        <div id="answerContainer"></div>
      </div>

    </div>
  </div>

  <script>
    async function updateStats() {{
      try {{
        const res = await fetch('/api/stats');
        const data = await res.json();
        document.getElementById('docCount').innerText = data.total_documents;
        document.getElementById('chunkCount').innerText = data.total_chunks;
        document.getElementById('emptyNotice').style.display = data.total_chunks > 0 ? 'none' : 'flex';
      }} catch (e) {{}}
    }}

    async function loadSampleDocs() {{
      const toast = document.getElementById('sidebarToast');
      toast.className = 'status-toast status-success';
      toast.innerText = 'Indexing built-in sample docs...';
      try {{
        const res = await fetch('/api/load-samples', {{ method: 'POST' }});
        const data = await res.json();
        toast.innerText = data.message;
        updateStats();
      }} catch (e) {{
        toast.className = 'status-toast status-error';
        toast.innerText = 'Failed to load samples: ' + e;
      }}
    }}

    async function clearIndex() {{
      await fetch('/api/clear', {{ method: 'POST' }});
      updateStats();
      document.getElementById('answerContainer').innerHTML = '';
      const toast = document.getElementById('sidebarToast');
      toast.className = 'status-toast status-success';
      toast.innerText = 'Index cleared!';
      setTimeout(() => toast.style.display = 'none', 3000);
    }}

    async function handleFileUpload(event) {{
      const files = event.target.files;
      if (!files.length) return;
      const toast = document.getElementById('uploadToast');
      toast.className = 'status-toast status-success';
      toast.innerText = `Parsing and embedding ${{files.length}} file(s)...`;

      const formData = new FormData();
      for (let f of files) formData.append('files', f);

      try {{
        const res = await fetch('/api/upload', {{ method: 'POST', body: formData }});
        const data = await res.json();
        toast.innerText = data.message;
        updateStats();
      }} catch (e) {{
        toast.className = 'status-toast status-error';
        toast.innerText = 'Upload failed: ' + e;
      }}
    }}

    async function askQuestion() {{
      const q = document.getElementById('userQuestion').value.trim();
      const key = document.getElementById('sidebarApiKey').value.trim();
      if (!q) return alert('Please enter a question!');

      document.getElementById('askLoading').style.display = 'block';
      const container = document.getElementById('answerContainer');

      try {{
        const res = await fetch('/api/ask', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ question: q, api_key: key }})
        }});

        const data = await res.json();
        document.getElementById('askLoading').style.display = 'none';

        if (!res.ok) {{
          container.innerHTML = `<div class="status-toast status-error" style="display:block; margin-top:14px;">❌ Error: ${{data.detail || 'Inference failed'}}</div>`;
          return;
        }}

        let chipsHtml = '';
        if (data.sources && data.sources.length) {{
          chipsHtml = '<div class="citation-chips">' + data.sources.map(s => `
            <div class="chip">
              📄 ${{s.source}} · P.${{s.page}}
              <span class="chip-score">${{s.similarity.toFixed(2)}}</span>
            </div>
          `).join('') + '</div>';
        }}

        container.innerHTML = `
          <div class="answer-card">
            <div class="answer-header">✨ Generated Grounded Answer</div>
            <div style="font-size:1.05rem; line-height:1.7;">${{data.answer.replace(/\\n/g, '<br>')}}</div>
            ${{chipsHtml}}
          </div>
        `;
      }} catch (e) {{
        document.getElementById('askLoading').style.display = 'none';
        container.innerHTML = `<div class="status-toast status-error" style="display:block; margin-top:14px;">❌ Error: ${{e}}</div>`;
      }}
    }}
  </script>
</body>
</html>
"""


@app.get("/api/stats")
def get_stats():
    return vector_store.get_stats()


@app.post("/api/load-samples")
def load_sample_documents():
    """Loads and indexes the 3 built-in sample docs."""
    sample_dir = os.path.join(BASE_DIR, "sample_docs")
    sample_files = glob.glob(os.path.join(sample_dir, "*.txt"))
    if not sample_files:
        raise HTTPException(status_code=404, detail="No sample documents found.")

    all_chunks = []
    new_files_count = 0

    for path in sample_files:
        filename = os.path.basename(path)
        if filename in processed_files:
            continue
        try:
            docs = load_document(path, filename)
            chunks = chunk_documents(docs, chunk_size=512, chunk_overlap=64)
            all_chunks.extend(chunks)
            processed_files.add(filename)
            new_files_count += 1
        except Exception as e:
            continue

    if all_chunks:
        texts = [c["text"] for c in all_chunks]
        embeddings = embedder.embed_texts(texts)
        vector_store.add_documents(all_chunks, embeddings)

    return {
        "message": f"Successfully indexed {new_files_count} sample files ({len(all_chunks)} chunks)!",
        "stats": vector_store.get_stats()
    }


@app.post("/api/upload")
async def upload_documents(files: List[UploadFile] = File(...)):
    """Handles multi-file document upload and vector indexing."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    all_chunks = []
    indexed_count = 0

    for file in files:
        filename = file.filename
        if filename in processed_files:
            continue
        try:
            contents = await file.read()
            docs = load_document(contents, filename)
            chunks = chunk_documents(docs, chunk_size=512, chunk_overlap=64)
            all_chunks.extend(chunks)
            processed_files.add(filename)
            indexed_count += 1
        except DocumentParsingError as e:
            raise HTTPException(status_code=400, detail=f"Parsing error on {filename}: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to process {filename}: {str(e)}")

    if all_chunks:
        texts = [c["text"] for c in all_chunks]
        embeddings = embedder.embed_texts(texts)
        vector_store.add_documents(all_chunks, embeddings)

    return {
        "message": f"Successfully indexed {indexed_count} file(s) ({len(all_chunks)} total chunks)!",
        "stats": vector_store.get_stats()
    }


@app.post("/api/ask")
def query_qa(payload: QuestionRequest):
    """Executes grounded retrieval and LLM answering."""
    q = payload.question.strip()
    if not q:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    stats = vector_store.get_stats()
    if stats["total_chunks"] == 0:
        return {
            "answer": "No documents have been indexed yet. Please upload files or load the sample docs.",
            "sources": []
        }

    api_key = payload.api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="OpenRouter API Key is required. Enter your key in the sidebar (openrouter.ai/keys)."
        )

    try:
        result = answer_question(
            question=q,
            vector_store=vector_store,
            embedder=embedder,
            model_name=payload.model_name or "meta-llama/llama-3.3-70b-instruct:free",
            openrouter_api_key=api_key,
            top_k=5
        )
        return result
    except LLMInferenceError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clear")
def clear_vector_store():
    vector_store.clear()
    processed_files.clear()
    return {"message": "Vector store and document history cleared!"}
