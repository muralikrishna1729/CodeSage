# 🛡️ LangSmith Evaluation & Tracing Guide for CodeSage

This guide explains how to build a **real-world, bias-free regression evaluation pipeline** using **LangSmith** and **LangGraph**, avoiding the self-grading confirmation bias of using the same LLM for both generation and evaluation.

---

## 🛑 The Self-Grading Bias Problem

> **"If Llama 3.3 / Groq generates the answer AND grades the answer, evaluations look 99% perfect, but real-world users get wrong answers."**

This is known as **LLM Confirmation Bias (Sycophancy)**:
1. An LLM tends to rate its own style, tone, and reasoning higher.
2. It fails to notice its own subtle hallucinations because it holds the same parametric blind spots as judge and generator.

---

## 💡 The Solution: LangSmith + LangGraph 4-Layer Evaluator

Instead of relying on a single LLM judge, our LangSmith evaluation suite ([`eval/langsmith_eval.py`](file:///c:/Users/Lenovo/Music/Projects/Codebase-RAG-Agent/eval/langsmith_eval.py)) uses **4 independent evaluation layers**:

```
                               ┌────────────────────────────────────────────────────────┐
                               │             LangSmith Evaluator Pipeline               │
                               └────────────────────────────────────────────────────────┘
                                                           │
        ┌───────────────────────────┬──────────────────────┴────┬───────────────────────────┐
        ▼                           ▼                           ▼                           ▼
1️⃣ Router Accuracy          2️⃣ Citation Presence        3️⃣ Embedding Distance        4️⃣ Independent Judge
   (Deterministic)             (Deterministic)             (SentenceTransformers)      (Different LLM Family)
   Validates if LangGraph       Checks if answer contains   Measures semantic cosine    Uses Google Gemini Flash or
   routed query to 'kb'         exact file citations        similarity to reference     OpenAI (NOT the Groq agent)
   vs 'web' vs 'direct'.        (e.g., `chunker.py`).       truth without LLM bias.     to grade correctness.
```

---

## 🚀 Step-by-Step Walkthrough

### Step 1: Enable LangSmith Tracing in `.env`

Make sure your `.env` file contains your LangSmith credentials:
```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
LANGCHAIN_API_KEY=your_langsmith_api_key_here
LANGCHAIN_PROJECT=CodeSage-Agent
```

When you run your Streamlit UI or FastAPI backend, **every single user request and LangGraph state transition is automatically logged to your LangSmith Dashboard**.

---

### Step 2: Build a Dataset from Real User Traces in LangSmith UI

1. Open [smith.langchain.com](https://smith.langchain.com) and go to your **CodeSage-Agent** project.
2. Filter for real user traces that failed or received negative feedback.
3. Click **"Add to Dataset"** ➔ Select/Create **`codesage-codebase-regression-v1`**.
4. Edit the reference output to set the correct ground-truth answer.

---

### Step 3: Run the LangSmith Evaluation Harness

Run the evaluation script to execute your LangGraph agent on the regression dataset and upload metrics directly to LangSmith:

```bash
python -m eval.langsmith_eval
```

---

## 📈 Viewing Experiment Results in LangSmith

Once completed, open your [LangSmith Dashboard](https://smith.langchain.com):

1. Navigate to **Datasets & Testing** ➔ **`codesage-codebase-regression-v1`**.
2. Compare experiments side-by-side (e.g. `codesage-regression-v1` vs `codesage-regression-v2`).
3. Inspect metric scores across:
   - **`router_accuracy`**: Fraction of queries routed to the correct node.
   - **`citation_presence`**: Exact match for code file citations.
   - **`semantic_similarity`**: Cosine distance via `all-MiniLM-L6-v2`.
   - **`independent_judge_correctness`**: Score from distinct judge model family (Gemini / OpenAI).

---

## 🛠️ Code Reference

- **Harness Code**: [`eval/langsmith_eval.py`](file:///c:/Users/Lenovo/Music/Projects/Codebase-RAG-Agent/eval/langsmith_eval.py)
- **Agent Graph**: [`app/agent/graph.py`](file:///c:/Users/Lenovo/Music/Projects/Codebase-RAG-Agent/app/agent/graph.py)
