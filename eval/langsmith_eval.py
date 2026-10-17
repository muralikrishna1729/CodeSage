"""
LangSmith Regression Evaluation & Tracing Suite for Codebase RAG Agent (CodeSage).

Features:
1. Prevents Self-Grading Bias by avoiding using the same LLM for generation & judging.
2. Uses Deterministic & Heuristic Evaluators (Citation presence, Router accuracy, Embedding Similarity).
3. Uses Independent Judge (e.g. Gemini 2.0 Flash / OpenAI) distinct from Agent's Groq Llama 3.3.
4. Uploads traces & benchmark regression scores directly to LangSmith UI.

Prerequisites:
  LANGCHAIN_TRACING_V2=true
  LANGCHAIN_API_KEY=your_langsmith_api_key
  LANGCHAIN_PROJECT=CodeSage-Agent

Usage:
  python -m eval.langsmith_eval
"""

import os
import sys
import argparse
from dotenv import load_dotenv

load_dotenv()

from langsmith import Client, evaluate
from app.agent.graph import agent_graph

# Initialize LangSmith Client
client = Client()

DATASET_NAME = "codesage-codebase-regression-v1"

# Sample regression queries from real engineering usage
REGRESSION_EXAMPLES = [
    {
        "inputs": {"question": "How does the AST chunker split code files in chunker.py?", "repo_name": "CodeSage"},
        "outputs": {
            "expected_route": "kb",
            "expected_file_citation": "chunker.py",
            "reference_answer": "The AST chunker uses tree-sitter to split code along function and class AST nodes preserving syntax boundaries up to max_chunk_size."
        }
    },
    {
        "inputs": {"question": "How is network isolation configured for sandboxed code execution?", "repo_name": "CodeSage"},
        "outputs": {
            "expected_route": "kb",
            "expected_file_citation": "code_exec.py",
            "reference_answer": "Network isolation is enforced using the '--network none' flag in Docker during sandboxed python execution."
        }
    },
    {
        "inputs": {"question": "What is the stock price of Apple today?", "repo_name": "CodeSage"},
        "outputs": {
            "expected_route": "web",
            "expected_file_citation": None,
            "reference_answer": "Out of scope for codebase KB; routed to web search."
        }
    }
]

def ensure_langsmith_dataset():
    """Create or load the regression dataset in LangSmith UI."""
    if client.has_dataset(dataset_name=DATASET_NAME):
        print(f"📄 Found existing LangSmith dataset: '{DATASET_NAME}'")
        dataset = client.read_dataset(dataset_name=DATASET_NAME)
    else:
        print(f"✨ Creating new LangSmith dataset: '{DATASET_NAME}'")
        dataset = client.create_dataset(
            dataset_name=DATASET_NAME,
            description="Regression eval dataset for CodeSage Agentic RAG"
        )
        for example in REGRESSION_EXAMPLES:
            client.create_example(
                inputs=example["inputs"],
                outputs=example["outputs"],
                dataset_id=dataset.id
            )
        print(f"✅ Added {len(REGRESSION_EXAMPLES)} regression examples to LangSmith dataset.")
    return dataset

# -------------------------------------------------------------------
# DETERMINISTIC & HEURISTIC EVALUATORS (Zero LLM Bias)
# -------------------------------------------------------------------

def eval_router_accuracy(run, example) -> dict:
    """Evaluates if the LangGraph router selected the correct path (kb vs web vs direct)."""
    expected_route = example.outputs.get("expected_route")
    actual_route = run.outputs.get("route") or run.outputs.get("source")
    
    score = 1.0 if actual_route == expected_route else 0.0
    return {
        "key": "router_accuracy",
        "score": score,
        "comment": f"Expected '{expected_route}', got '{actual_route}'"
    }

def eval_citation_presence(run, example) -> dict:
    """Evaluates if the answer contains expected file citations without LLM bias."""
    expected_citation = example.outputs.get("expected_file_citation")
    if not expected_citation:
        return {"key": "citation_presence", "score": 1.0, "comment": "No citation required for this query."}
        
    answer = run.outputs.get("answer", "")
    score = 1.0 if expected_citation.lower() in answer.lower() else 0.0
    return {
        "key": "citation_presence",
        "score": score,
        "comment": f"Looked for '{expected_citation}' in answer."
    }

def eval_embedding_similarity(run, example) -> dict:
    """Computes cosine similarity between reference answer & generated answer using sentence-transformers."""
    try:
        from sentence_transformers import SentenceTransformer, util
        model = SentenceTransformer("all-MiniLM-L6-v2")
        
        ref_ans = example.outputs.get("reference_answer", "")
        gen_ans = run.outputs.get("answer", "")
        
        emb1 = model.encode(ref_ans, convert_to_tensor=True)
        emb2 = model.encode(gen_ans, convert_to_tensor=True)
        sim = float(util.cos_sim(emb1, emb2)[0][0])
        
        return {"key": "semantic_similarity", "score": sim, "comment": f"Cosine similarity: {sim:.3f}"}
    except Exception as e:
        return {"key": "semantic_similarity", "score": 0.0, "comment": f"Embedding error: {e}"}

# -------------------------------------------------------------------
# INDEPENDENT JUDGE EVALUATOR (Using a Different Model Family, e.g. Gemini)
# -------------------------------------------------------------------

def eval_independent_judge(run, example) -> dict:
    """Uses a DIFFERENT model family (Google Gemini / OpenAI) as judge to avoid self-grading bias."""
    google_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    
    if not google_api_key and not openai_api_key:
        return {
            "key": "independent_judge_correctness",
            "score": None,
            "comment": "Skipped: Add GOOGLE_API_KEY or OPENAI_API_KEY to test independent judge (distinct from Groq Llama agent)."
        }
        
    try:
        if google_api_key:
            from langchain_google_genai import ChatGoogleGenerativeAI
            judge_llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", temperature=0)
        else:
            from langchain_openai import ChatOpenAI
            judge_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
            
        prompt = f"""You are an unbiased AI evaluator. Compare the Generated Answer against the Reference Answer for the given Question.

Question: {run.inputs.get('question')}
Reference Answer: {example.outputs.get('reference_answer')}
Generated Answer: {run.outputs.get('answer')}

Rate correctness from 0.0 to 1.0. Output ONLY a valid JSON: {{"score": float, "reason": "brief explanation"}}"""

        res = judge_llm.invoke(prompt)
        import json
        text = res.content.strip()
        if text.startswith("```json"): text = text[7:]
        if text.startswith("```"): text = text[3:]
        if text.endswith("```"): text = text[:-3]
        
        data = json.loads(text)
        return {
            "key": "independent_judge_correctness",
            "score": float(data.get("score", 0.0)),
            "comment": data.get("reason", "")
        }
    except Exception as e:
        return {"key": "independent_judge_correctness", "score": 0.0, "comment": f"Judge Error: {e}"}

# -------------------------------------------------------------------
# AGENT TARGET FUNCTION
# -------------------------------------------------------------------

def predict_agent(inputs: dict) -> dict:
    """Target function for LangSmith evaluate harness."""
    question = inputs["question"]
    repo_name = inputs.get("repo_name", "CodeSage")
    result = agent_graph.invoke({"question": question, "repo_name": repo_name})
    return {
        "answer": result.get("answer", ""),
        "route": result.get("route") or result.get("source"),
        "kb_results": result.get("kb_results")
    }

def run_langsmith_evaluation():
    if not os.getenv("LANGCHAIN_API_KEY"):
        print("❌ Error: LANGCHAIN_API_KEY is required to run LangSmith evaluation.")
        print("Please set LANGCHAIN_API_KEY in your .env file.")
        return
        
    print("🚀 Initializing LangSmith Evaluation Suite for CodeSage...")
    ensure_langsmith_dataset()
    
    print("\n⚡ Running LangSmith evaluation harness (Uploading traces to LangSmith UI)...")
    eval_results = evaluate(
        predict_agent,
        data=DATASET_NAME,
        evaluators=[
            eval_router_accuracy,
            eval_citation_presence,
            eval_embedding_similarity,
            eval_independent_judge,
        ],
        experiment_prefix="codesage-regression",
        max_concurrency=2
    )
    
    print("\n✅ LangSmith Evaluation Complete!")
    print(f"📊 View interactive traces and breakdown on LangSmith UI: https://smith.langchain.com")

if __name__ == "__main__":
    run_langsmith_evaluation()
