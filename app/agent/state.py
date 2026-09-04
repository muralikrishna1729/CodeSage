from typing import TypedDict, Optional


class AgentState(TypedDict):
    question: str
    route: Optional[str]              # "kb" | "web" | "direct"
    kb_results: Optional[list[dict]]
    kb_grade: Optional[str]           # "good" | "weak"
    web_results: Optional[list[dict]]
    web_grade: Optional[str]          # "good" | "weak"
    answer: Optional[str]
    source: Optional[str]             # "kb" | "web" | "fallback" | "direct"

if __name__ == "__main__":
    sample: AgentState = {
        "question": "how does auth work?",
        "route": None, "kb_results": None, "kb_grade": None,
        "web_results": None, "web_grade": None, "answer": None, "source": None,
    }
    print(sample)