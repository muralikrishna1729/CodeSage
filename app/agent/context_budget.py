try:
    import tiktoken
    _encoder = tiktoken.get_encoding("cl100k_base")
    _HAS_TIKTOKEN = True
except ImportError:
    _encoder = None
    _HAS_TIKTOKEN = False

MAX_CONTEXT_TOKENS = 4000       # tune against your actual Groq model's limit
MAX_CHUNK_CHARS = 1500 

def _count_tokens(text: str) -> int:
    if _HAS_TIKTOKEN:
        return len(_encoder.encode(text))
    # rough fallback: ~4 chars/token is the standard approximation for English/code
    return len(text) // 4

def build_context_text(kb_results: list[dict], max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
    parts = []
    total_tokens = 0
    for r in kb_results:
        content = r.get("content", "")[:MAX_CHUNK_CHARS]  # per-chunk cap first
        chunk_text = f"{r['file_path']}:{r['start_line']}-{r['end_line']}\n{content}"
        chunk_tokens = _count_tokens(chunk_text)
        if total_tokens + chunk_tokens > max_tokens:
            break
        parts.append(chunk_text)
        total_tokens += chunk_tokens
    return "\n\n".join(parts)

print(f"[context_budget] Using {'tiktoken' if _HAS_TIKTOKEN else 'char-based fallback'} for token counting")

if __name__ == "__main__":
    fake_results = [
        {"file_path": "a.py", "start_line": 1, "end_line": 50, "content": "x" * 3000},
        {"file_path": "b.py", "start_line": 1, "end_line": 10, "content": "y" * 200},
    ]
    text = build_context_text(fake_results, max_tokens=500)
    print("Result length (chars):", len(text))
    print("Contains a.py:", "a.py" in text)
    print("Contains b.py:", "b.py" in text)