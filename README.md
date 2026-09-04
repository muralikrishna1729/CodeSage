# Agentic Codebase RAG Assistant

An agentic RAG system that answers natural-language questions about any
GitHub repository — architecture, specific functions, error messages — with
citations to exact files and lines. Falls back to live web search for
things the codebase itself can't explain, and is honest when neither source
has good evidence.

Built entirely on free/open-source tooling — no paid API keys required.

---

## Why this project

Every engineering org runs internal codebase onboarding and support at
scale — new engineers spend weeks reading unfamiliar code, asking seniors
"why does this work this way," and Googling stack traces. This compresses
that process into a chat interface, grounded in the actual repo rather than
guesswork.

It's also designed to be more than "RAG with extra steps": a router decides
*where* to look, a grading step self-corrects when retrieval comes back
weak, and a sandboxed code-execution tool lets the agent verify its own
explanations against real runtime behavior rather than just describing code.

---

## Architecture

```
User Question
   │
   ▼
Router (LLM) ── classifies: KB / Web / Direct
   │
   ▼
Retrieve from Qdrant (KB) ── semantic search + structural repo context
   │
   ▼
Grade KB Evidence (LLM) ── good enough? / weak?
   │              │
  good           weak
   │              │
   ▼              ▼
Generate      Web Search (Tavily → DuckDuckGo fallback)
from KB            │
   │                ▼
   │          Grade Web Evidence (LLM)
   │            │           │
   │           good        weak
   │            │           │
   │            ▼           ▼
   │       Generate    Fallback Answer
   │       from Web    (honest "insufficient info")
   │            │           │
   └────────────┴───────────┘
                │
                ▼
         Final Answer to User
```

**How the agent understands a codebase — 3 layers:**
1. **File-level chunking** — tree-sitter parses each file's AST and extracts
   function/class boundaries with exact `file_path:start_line-end_line`
   metadata, so every chunk is a complete, citable unit of code.
2. **Structural understanding** — a directory-tree summary, import graph,
   and README/config ingestion give the agent the shape of the whole
   project, not just isolated functions — needed for "how does X work"
   questions that span multiple files.
3. **Retrieval-time context assembly** — the stored repo-map chunk is
   included alongside normal top-k code chunks so architecture-flavored
   questions get both the big picture and the specific detail.

---

## Tech stack (100% free / open-source)

| Layer | Tool | Notes |
|---|---|---|
| LLM (primary) | Groq — `openai/gpt-oss-120b` | Free tier, no card required |
| LLM (fallback 1) | OpenRouter free pool (`:free` models) | Kicks in on Groq rate limit |
| LLM (fallback 2) | Gemini free tier | Also used as RAGAS eval judge |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2` | Local, no API needed |
| Vector DB | Qdrant (self-hosted via Docker) | Free, production-grade |
| Web search (primary) | Tavily | Free: 1,000 queries/month |
| Web search (fallback) | `duckduckgo-search` | Free, no key |
| Code parsing | tree-sitter | AST-aware chunking (Python, JS/TS) |
| Orchestration | LangGraph | Router → grade → generate state machine |
| Backend | FastAPI | `/ingest`, `/chat`, `/chat/debug` endpoints |
| Frontend | Chainlit | Chat UI with visible agent reasoning steps |
| Code execution sandbox | Docker (network-isolated, resource-capped) | Verifies agent's code explanations |
| Eval | RAGAS | Faithfulness + answer relevancy scoring |

---

## Project structure

```
codebase-rag-agent/
├── requirements.txt
├── docker-compose.yml
├── .env.example
├── app/
│   ├── config.py
│   ├── ingestion/
│   │   ├── clone.py
│   │   ├── chunker.py
│   │   ├── repo_map.py
│   │   └── embed_store.py
│   ├── agent/
│   │   ├── state.py
│   │   ├── llm_client.py
│   │   ├── nodes.py
│   │   └── graph.py
│   ├── tools/
│   │   ├── web_search.py
│   │   └── code_exec.py
│   ├── api/
│   │   └── routes.py
│   └── frontend/
│       └── chainlit_app.py
└── eval/
    ├── eval_dataset.py
    └── run_eval.py
```

---

## Setup

### Prerequisites
- Python 3.11+
- Docker (for Qdrant and the code-execution sandbox)
- Free API keys: [Groq](https://console.groq.com), [OpenRouter](https://openrouter.ai),
  [Google AI Studio / Gemini](https://aistudio.google.com), [Tavily](https://tavily.com)

### Install
```bash
git clone <this-repo-url>
cd codebase-rag-agent

docker compose up -d              # starts Qdrant on localhost:6333
pip install -r requirements.txt
cp .env.example .env              # fill in your free API keys
```

### Run
```bash
uvicorn app.api.routes:app --reload            # terminal 1 — backend
chainlit run app/frontend/chainlit_app.py -w   # terminal 2 — frontend
```

Open the Chainlit UI (usually `http://localhost:8000` for the app, check
terminal output for the exact URL) and paste a public GitHub repo URL to
begin.

---

## Demo script

1. **Ingest a repo** — paste a public GitHub URL in the chat. Watch the
   "Ingesting repo" step complete with a chunk count.
2. **Ask a KB-eligible question** — e.g. "How does the router decide where
   to send a question?" (if you've ingested this repo itself). Confirm the
   answer cites a real `file_path:line`.
3. **Ask a web-eligible question** — e.g. "What does ECONNREFUSED mean?"
   Watch it route to web search rather than the codebase.
4. **Ask a nonsense question** — confirm it lands on the honest fallback
   answer rather than confidently hallucinating.
5. Point out the visible reasoning steps (routing decision, grading
   verdicts) in the Chainlit UI throughout — this transparency is the core
   differentiator from a plain RAG chatbot.

---

## Evaluation

RAGAS scores (faithfulness, answer relevancy) across a hand-curated
question set spanning KB, web-fallback, and no-evidence-fallback paths:

```
[Paste your run_eval.py output here once Phase 3 eval is complete]
```

A lower faithfulness score on fallback-sourced answers is expected and
correct — those answers are explicitly not grounded, so a lower score there
validates the fallback node is being honest rather than indicating a bug.
A low faithfulness score on a KB-sourced answer is the one worth
investigating.

---

## Design decisions worth defending

- **AST-aware chunking over fixed-size chunking** — every chunk is a
  complete function/class, preserving semantic boundaries that naive
  character-count chunking would cut through.
- **Corrective RAG (grading step)** — retrieval isn't trusted blindly; an
  LLM-as-judge checks whether retrieved context actually answers the
  question before generating, falling back to web search when it doesn't.
- **Free-tier provider fallback cascades** — both the LLM client and web
  search tool try a primary free provider and fall through to a secondary
  on rate-limit or failure, keeping the whole stack at zero cost without
  sacrificing demo reliability.
- **Docker-sandboxed code execution** — network-isolated, resource-capped,
  read-only mounted — lets the agent verify its own explanations against
  real runtime output instead of only describing code from static context.

---

## Known limitations / next steps

- Multi-turn conversation context is not yet wired end-to-end — verify
  whether `/chat` uses prior message history or treats every question
  statelessly before claiming this in an interview.
- The ingest-vs-chat routing in the Chainlit frontend uses a crude
  URL-prefix heuristic rather than a dedicated ingest flow.
- Class-level chunking captures an entire class as one chunk rather than
  per-method — worth revisiting if large classes hurt retrieval precision.