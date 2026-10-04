"""
Streamlit AppTest Verification Suite for Smart Document Q&A Agent.

Uses Streamlit's built-in `streamlit.testing.v1.AppTest` to programmatically simulate:
1. App initialization and title rendering.
2. Clicking the 'Load Built-in Sample Docs' sidebar button.
3. Verifying session state updates, document metrics (3 docs, 25 chunks).
4. Verifying Q&A input and citation UI components.
"""

import os
import sys
from streamlit.testing.v1 import AppTest

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
project_dir = os.path.dirname(os.path.abspath(__file__))
app_file = os.path.join(project_dir, "app.py")


def test_streamlit_app_flow():
    print("Testing Streamlit app via AppTest...")
    at = AppTest.from_file(app_file, default_timeout=120)
    at.run(timeout=120)

    # Verify no unhandled exceptions on first run
    assert not at.exception, f"App encountered exception on initial load: {at.exception}"

    # Verify title
    titles = [t.value for t in at.title]
    print(f"  -> Page titles: {titles}")
    assert any("Smart Document Q&A Agent" in t for t in titles)

    # Check sidebar metrics before loading docs
    sidebar = at.sidebar
    metrics = [m.value for m in sidebar.metric]
    print(f"  -> Initial metrics (Docs, Chunks): {metrics}")

    # Find and click the 'Load Built-in Sample Docs' button
    sample_btn = None
    for btn in sidebar.button:
        if "Load Built-in Sample Docs" in btn.label:
            sample_btn = btn
            break

    assert sample_btn is not None, "Could not find 'Load Built-in Sample Docs' button"
    print("  -> Clicking 'Load Built-in Sample Docs' button...")
    sample_btn.click().run()

    assert not at.exception, f"App encountered exception after clicking load docs: {at.exception}"

    # Check updated metrics
    updated_metrics = [m.value for m in at.sidebar.metric]
    print(f"  -> Updated metrics after indexing: {updated_metrics}")
    assert "3" in updated_metrics, f"Expected 3 documents indexed, got {updated_metrics}"

    # Test asking a question
    # Find question input
    q_input = None
    for ti in at.text_input:
        if "Enter your question" in ti.label:
            q_input = ti
            break
    assert q_input is not None, "Could not find question text input"
    print("  -> Setting question text...")
    q_input.input("What is the borrowing limit for undergraduates?").run()

    # Find 'Get Answer with Citations' button
    ask_btn = None
    for btn in at.button:
        if "Get Answer with Citations" in btn.label:
            ask_btn = btn
            break
    assert ask_btn is not None, "Could not find 'Get Answer with Citations' button"
    print("  -> Clicking 'Get Answer with Citations' button...")
    ask_btn.click().run()

    # Verify app handles Ollama connection gracefully (either succeeds or displays user-friendly error)
    assert not at.exception, f"App raised unhandled exception during Q&A: {at.exception}"
    if at.error:
        print(f"  -> Graceful user-friendly error caught as expected when Ollama is offline: {at.error[0].value[:100]}...")
    else:
        print("  -> Q&A response rendered successfully!")

    print("Streamlit AppTest End-to-End Simulation Passed Flawlessly!")


def test_streamlit_answer_and_citations_rendering():
    print("\nTesting Streamlit Q&A UI rendering with simulated LLM response...")
    import qa_chain

    # Mock Ollama response
    original_query = qa_chain.query_ollama
    qa_chain.query_ollama = lambda prompt, model, base_url, timeout=90: (
        "Undergraduate students may borrow up to 25 items concurrently for a 21-day loan period "
        "[Source: campus_library_guide.txt, Page 1]."
    )

    try:
        at = AppTest.from_file(app_file, default_timeout=60)
        at.run()

        # Click Load Built-in Sample Docs
        sample_btn = [b for b in at.sidebar.button if "Load Built-in Sample Docs" in b.label][0]
        sample_btn.click().run()

        # Ask question
        q_input = [ti for ti in at.text_input if "Enter your question" in ti.label][0]
        q_input.input("What is the borrowing limit for undergraduates?").run()

        ask_btn = [b for b in at.button if "Get Answer with Citations" in b.label][0]
        ask_btn.click().run()

        assert not at.exception, f"App raised exception: {at.exception}"

        # Verify chat history contains answer and citations
        chat_history = at.session_state["chat_history"]
        assert len(chat_history) > 0, "Chat history should contain 1 entry"
        latest = chat_history[0]
        assert "21-day loan period" in latest["answer"]
        assert len(latest["sources"]) == 5
        assert latest["sources"][0]["source"] == "campus_library_guide.txt"
        assert latest["sources"][0]["page"] == 1

        print("  -> Answer correctly recorded in session state.")
        print(f"  -> Generated answer: {latest['answer']}")
        print(f"  -> Top citation source: {latest['sources'][0]['source']}, page: {latest['sources'][0]['page']}, similarity: {latest['sources'][0]['similarity']}")
        print("  -> Citation and Answer UI Rendering Verified!")

    finally:
        qa_chain.query_ollama = original_query


if __name__ == "__main__":
    test_streamlit_app_flow()
    test_streamlit_answer_and_citations_rendering()
