import os
import streamlit as st
import requests

# Backend URL. Port 8000 is contended on this machine, so default to 8010.
# Override with the API_URL env var if the backend moves again.
API_URL = os.getenv("API_URL", "http://localhost:8010")
REQUEST_TIMEOUT = 120  # ingest (clone+chunk+embed) and retrying LLM calls can exceed 30s

st.set_page_config(page_title="Codebase RAG Assistant", layout="wide")
st.title("Agentic Codebase RAG Assistant")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "history" not in st.session_state:
    st.session_state.history = []  # separate from display messages — matches backend's expected shape
if "active_repo" not in st.session_state:
    st.session_state.active_repo = None

with st.sidebar:
    st.subheader("Ingest a repo")
    repo_url = st.text_input("GitHub repo URL")
    if st.button("Ingest") and repo_url:
        with st.spinner("Cloning, chunking, embedding..."):
            try:
                resp = requests.post(
                    f"{API_URL}/ingest", json={"repo_url": repo_url}, timeout=REQUEST_TIMEOUT
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state.active_repo = data["repo_name"]  # remember for questions
                    st.success(f"Indexed {data['chunks_stored']} chunks from {data['repo_name']}")
                else:
                    st.error(f"Ingestion failed ({resp.status_code}): {resp.text}")
            except requests.RequestException as e:
                st.error(f"Could not reach backend at {API_URL}: {e}")

    if st.session_state.active_repo:
        st.caption(f"Active repo: **{st.session_state.active_repo}**")
    else:
        st.caption("No repo ingested yet this session.")

    st.caption(f"Backend: {API_URL}")

# render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg["role"] == "assistant":
            if msg.get("route"):
                st.caption(f"Routed to: {msg['route']}")
            if msg.get("source"):
                st.caption(f"Source: {msg['source']}")

if not st.session_state.active_repo:
    st.info("Ingest a repo first before asking questions.")
elif question := st.chat_input("Ask about the repo..."):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Routing..."):
                resp = requests.post(
                    f"{API_URL}/chat/debug",
                    json={
                        "question": question,
                        "repo_name": st.session_state.active_repo,
                        "history": st.session_state.history,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
            if resp.status_code != 200:
                error_text = f"Backend error ({resp.status_code}): {resp.text}"
                st.error(error_text)
                st.session_state.messages.append({"role": "assistant", "content": error_text})
            else:
                data = resp.json()
                st.write(data["answer"])

                caption_parts = [f"Routed to: {data['route']}"]
                if data.get("kb_grade"):
                    caption_parts.append(f"KB grade: {data['kb_grade']}")
                if data.get("web_grade"):
                    caption_parts.append(f"Web grade: {data['web_grade']}")
                caption_parts.append(f"Source: {data['source']}")
                st.caption(" | ".join(caption_parts))

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": data["answer"],
                    "route": data["route"],
                    "source": data["source"],
                })

                # update history for the next turn — capped to keep prompts small
                st.session_state.history.append({"role": "user", "content": question})
                st.session_state.history.append({"role": "assistant", "content": data["answer"]})
                st.session_state.history = st.session_state.history[-8:]

        except requests.RequestException as e:
            error_text = f"Could not reach backend at {API_URL}: {e}"
            st.error(error_text)
            st.session_state.messages.append({"role": "assistant", "content": error_text})
