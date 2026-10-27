"""
Smart Document Q&A Agent - Streamlit Web Application.

This is the main entry point for the RAG system. It coordinates:
- Multi-document upload (PDF, DOCX, TXT)
- In-memory parsing, recursive chunking, and embedding generation
- FAISS vector store indexing and persistence in session state
- Interactive natural language Q&A with grounded citations
- Cloud LLM inference backend powered exclusively by OpenRouter (Free Tier Models)
- "Minimal Modern SaaS" visual theme with teal accent
"""

import os
import glob
import html
from typing import List, Dict, Any
import streamlit as st
from dotenv import load_dotenv

# Import local pipeline modules
from ingestion import load_document, DocumentParsingError
from chunking import chunk_documents
from embeddings import get_embedding_model
from vector_store import FaissVectorStore
from qa_chain import answer_question, LLMInferenceError

# Expose top-level WSGI/ASGI 'app' for Vercel Serverless runtime detection
try:
    from api.index import app  # noqa: F401
except Exception:
    app = None

# Load environment configuration
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Smart Document Q&A Agent",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)


def load_css(css_filename: str = "style.css") -> None:
    """
    Loads external CSS stylesheet into Streamlit app for clean modular styling.
    """
    css_path = os.path.join(os.path.dirname(__file__), css_filename)
    if os.path.exists(css_path):
        with open(css_path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Loading all-MiniLM-L6-v2 embedding model...")
def load_cached_embedder():
    """
    Caches the SentenceTransformer embedding model across Streamlit reruns.
    """
    return get_embedding_model("all-MiniLM-L6-v2")


def init_session_state():
    """
    Initializes required state variables in Streamlit session_state.
    """
    if "vector_store" not in st.session_state:
        st.session_state.vector_store = FaissVectorStore()
    if "processed_filenames" not in st.session_state:
        st.session_state.processed_filenames = set()
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []


def index_files(files_to_process: List[Any], embedder: Any) -> None:
    """
    Parses, chunks, embeds, and indexes a batch of uploaded files.

    Args:
        files_to_process: List of Streamlit UploadedFile objects or file path strings.
        embedder: EmbeddingModel instance.
    """
    new_files_count = 0
    all_new_chunks: List[Dict[str, Any]] = []

    progress_bar = st.progress(0, text="Starting document ingestion...")

    for i, file_obj in enumerate(files_to_process):
        # Determine filename and source
        if isinstance(file_obj, str):
            filename = os.path.basename(file_obj)
            source_input = file_obj
        else:
            filename = file_obj.name
            source_input = file_obj

        # Avoid re-indexing already indexed files
        if filename in st.session_state.processed_filenames:
            continue

        progress_text = f"Parsing [{i+1}/{len(files_to_process)}]: {filename}"
        progress_bar.progress(int(((i + 0.3) / len(files_to_process)) * 100), text=progress_text)

        try:
            # 1. Parse document
            doc_units = load_document(source_input, filename)

            # 2. Chunk document (chunk_size=512, chunk_overlap=64)
            chunks = chunk_documents(doc_units, chunk_size=512, chunk_overlap=64)

            all_new_chunks.extend(chunks)
            st.session_state.processed_filenames.add(filename)
            new_files_count += 1

        except DocumentParsingError as exc:
            st.error(f"❌ Ingestion Error: {str(exc)}")
        except Exception as exc:
            st.error(f"❌ Unexpected Error parsing '{filename}': {str(exc)}")

    # 3. Generate embeddings and index in FAISS
    if all_new_chunks:
        progress_bar.progress(85, text=f"Generating dense embeddings for {len(all_new_chunks)} chunks...")
        texts_to_embed = [chunk["text"] for chunk in all_new_chunks]
        embeddings = embedder.embed_texts(texts_to_embed)

        progress_bar.progress(95, text="Populating FAISS IndexFlatL2...")
        st.session_state.vector_store.add_documents(all_new_chunks, embeddings)

    progress_bar.progress(100, text="Indexing complete!")
    progress_bar.empty()

    if new_files_count > 0:
        st.success(f" Successfully indexed {new_files_count} new file(s) ({len(all_new_chunks)} total chunks).")


def render_sidebar(embedder: Any) -> Dict[str, Any]:
    """
    Renders the sidebar with statistics, configuration, and controls.

    Returns:
        Dictionary containing selected LLM configuration.
    """
    with st.sidebar:
        st.title("⚙️ System Control")

        # Section 1: Knowledge Base Statistics
        stats = st.session_state.vector_store.get_stats()
        st.subheader("📊 Indexed Knowledge Base")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Documents", stats["total_documents"])
        with col2:
            st.metric("Chunks", stats["total_chunks"])

        if stats["sources"]:
            with st.expander("📄 Indexed Files List", expanded=False):
                for src in stats["sources"]:
                    st.write(f"- `{src}`")

        # Quick action: Load sample docs
        if st.button("📁 Load Built-in Sample Docs", use_container_width=True, help="Index sample documents from sample_docs/ folder"):
            sample_dir = os.path.join(os.path.dirname(__file__), "sample_docs")
            sample_files = glob.glob(os.path.join(sample_dir, "*.txt"))
            if sample_files:
                index_files(sample_files, embedder)
                st.rerun()
            else:
                st.warning("No sample files found in sample_docs/ directory.")

        # Reset button
        if st.button("🗑️ Clear Vector Index", use_container_width=True):
            st.session_state.vector_store.clear()
            st.session_state.processed_filenames.clear()
            st.session_state.chat_history.clear()
            st.success("Vector index cleared!")
            st.rerun()

        st.divider()

        # Section 2: LLM Configuration (OpenRouter Only)
        st.subheader("🌐 OpenRouter LLM")
        st.caption("Using **OpenRouter** free models (zero local GPU needed)")

        free_models = [
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.1-8b-instruct:free",
            "qwen/qwen-2.5-7b-instruct:free",
            "mistralai/mistral-7b-instruct:free",
            "deepseek/deepseek-r1:free",
            "Custom Model ID..."
        ]

        selected_model = st.selectbox(
            "Select Free Model:",
            options=free_models,
            index=0,
            help="Free models hosted on OpenRouter. No credit card or usage fee required."
        )

        if selected_model == "Custom Model ID...":
            model_name = st.text_input(
                "Custom OpenRouter Model ID:",
                value="meta-llama/llama-3.3-70b-instruct:free",
                help="Type any valid model ID from openrouter.ai/models"
            )
        else:
            model_name = selected_model

        env_key = os.getenv("OPENROUTER_API_KEY", "")
        openrouter_api_key = st.text_input(
            "OpenRouter API Key:",
            value=env_key,
            type="password",
            placeholder="sk-or-v1-...",
            help="Reads automatically from OPENROUTER_API_KEY in .env if set. Get a free key at openrouter.ai/keys."
        )

        if not openrouter_api_key:
            st.info("🔑 **Enter your OpenRouter API key above** to start asking questions. Get a free key at [openrouter.ai/keys](https://openrouter.ai/keys).")

        config: Dict[str, Any] = {
            "model_name": model_name,
            "openrouter_api_key": openrouter_api_key
        }

        st.divider()
        st.caption("🎓 **Smart Document Q&A Agent**  \nCS Academic Project Review Edition  \nOpenRouter • FAISS • MiniLM-L6-v2")

        return config


def main():
    """
    Main Streamlit application layout and event loop.
    """
    # Load external stylesheet
    load_css("style.css")

    init_session_state()
    embedder = load_cached_embedder()

    # Render sidebar and capture LLM configuration
    llm_config = render_sidebar(embedder)

    # Main UI Header
    st.title("Smart Document Q&A Agent")
    st.markdown(
        """
        <div style="margin-top: -12px; margin-bottom: 22px;">
            <div style="font-size: 0.95rem; color: #64748B; line-height: 1.55;">
                A <strong>Retrieval-Augmented Generation (RAG)</strong> system that indexes local documents
                (<strong>PDF</strong>, <strong>DOCX</strong>, <strong>TXT</strong>) into FAISS and answers questions strictly grounded in their content with verified source citations.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Document Upload Section
    st.subheader("1. Upload Documents")
    uploaded_files = st.file_uploader(
        "Drag and drop documents to build or expand your vector index:",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
        help="Upload one or multiple PDF, DOCX, or TXT documents."
    )

    if uploaded_files:
        # Check if there are newly added files
        new_files = [f for f in uploaded_files if f.name not in st.session_state.processed_filenames]
        if new_files:
            if st.button(f"📥 Process & Index {len(new_files)} Uploaded Document(s)", type="primary"):
                index_files(new_files, embedder)
                st.rerun()
        else:
            st.caption("✅ All uploaded documents are indexed in the vector store.")

    st.divider()

    # Question & Answer Section
    st.subheader("2. Ask a Question")

    stats = st.session_state.vector_store.get_stats()
    if stats["total_chunks"] == 0:
        st.markdown(
            """
            <div class="custom-info-card">
                <div class="custom-info-icon">💡</div>
                <div class="custom-info-text">
                    <strong>No documents indexed yet.</strong> Upload documents above or click <strong>'📁 Load Built-in Sample Docs'</strong> in the sidebar to get started.
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    user_question = st.text_input(
        "Enter your question regarding the indexed documents:",
        placeholder="e.g., What are the rules regarding AI use in exams? or How many items can an undergrad borrow?",
        disabled=(stats["total_chunks"] == 0)
    )

    ask_button = st.button("🔍 Get Answer with Citations", type="primary", disabled=(stats["total_chunks"] == 0 or not user_question.strip()))

    if ask_button and user_question.strip():
        with st.spinner(f"Retrieving relevant passages and querying {llm_config['model_name']}..."):
            try:
                result = answer_question(
                    question=user_question.strip(),
                    vector_store=st.session_state.vector_store,
                    embedder=embedder,
                    model_name=llm_config["model_name"],
                    openrouter_api_key=llm_config["openrouter_api_key"],
                    top_k=5
                )

                # Record in chat history
                st.session_state.chat_history.insert(0, {
                    "question": user_question.strip(),
                    "answer": result["answer"],
                    "sources": result["sources"]
                })

            except LLMInferenceError as exc:
                st.error(f"⚠️ {str(exc)}")
                if not llm_config["openrouter_api_key"]:
                    st.info(
                        "💡 **How to get your OpenRouter API Key (Free):**  \n"
                        "1. Go to [openrouter.ai/keys](https://openrouter.ai/keys) and sign in.  \n"
                        "2. Click **Create Key** (it is free, no credit card required).  \n"
                        "3. Paste the key into the **OpenRouter API Key** field in the left sidebar."
                    )
            except Exception as exc:
                st.error(f"❌ Unexpected Error: {str(exc)}")

    # Display Recent Q&A Results
    if st.session_state.chat_history:
        st.subheader("3. Answer & Source Citations")

        for item in st.session_state.chat_history:
            st.markdown(f"#### ❓ Question: *{item['question']}*")

            # Format citation chips
            chips_html = ""
            if item.get("sources"):
                chips_list = []
                for chunk in item["sources"]:
                    src_name = chunk.get("source", "Unknown")
                    page_num = chunk.get("page", 1)
                    sim_score = chunk.get("similarity", 0.0)
                    chips_list.append(
                        f'<span class="citation-chip">📄 {html.escape(src_name)} · P.{page_num} '
                        f'<span class="citation-chip-score">{sim_score:.2f}</span></span>'
                    )
                chips_html = f"""
                <div class="citation-chips-wrapper">
                    <div class="citation-chips-label">📚 Verified Source Citations</div>
                    <div class="citation-chips-container">
                        {''.join(chips_list)}
                    </div>
                </div>
                """

            clean_answer = html.escape(item["answer"]).replace("\n", "<br>")

            # Stylish elevated answer card with fade-in animation
            st.markdown(
                f"""
                <div class="answer-display-card">
                    <div class="answer-header">
                        <span>✨</span> Generated Grounded Answer
                    </div>
                    <div class="answer-body">
                        {clean_answer}
                    </div>
                    {chips_html}
                </div>
                """,
                unsafe_allow_html=True
            )

            # Collapsible detailed source passages
            with st.expander(f"📖 Detailed Source Passages ({len(item['sources'])} chunks)", expanded=False):
                if not item["sources"]:
                    st.write("No source passages retrieved.")
                else:
                    for idx, chunk in enumerate(item["sources"], 1):
                        st.markdown(
                            f"**Passage #{idx}** | 📄 **Source:** `{chunk['source']}` | 📑 **Page:** `{chunk['page']}` | 🎯 **Cosine Similarity:** `{chunk['similarity']}`"
                        )
                        st.code(chunk["text"], language=None)
                        st.divider()


if __name__ == "__main__":
    main()
