from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes import (
    router_node, retrieve_kb_node, grade_kb_node, generate_kb_node,
    web_search_node, grade_web_node, generate_web_node,
    fallback_node, direct_node,
)

def route_decision(state: dict) -> str:
    return state["route"]

def kb_grade_decision(state:dict)->str:
    return "good" if state["kb_grade"]=="good" else "weak"

def web_grade_decision(state: dict) -> str:
    return "good" if state["web_grade"] == "good" else "weak"

def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("router", router_node)
    graph.add_node("retrieve_kb", retrieve_kb_node)
    graph.add_node("grade_kb", grade_kb_node)
    graph.add_node("generate_kb", generate_kb_node)
    graph.add_node("web_search", web_search_node)
    graph.add_node("grade_web", grade_web_node)
    graph.add_node("generate_web", generate_web_node)
    graph.add_node("fallback", fallback_node)
    graph.add_node("direct", direct_node)

    graph.set_entry_point("router")
    graph.add_conditional_edges("router", route_decision,{
        "kb": "retrieve_kb",
        "web": "web_search",
        "direct": "direct",
    })
    graph.add_edge("retrieve_kb", "grade_kb")
    graph.add_conditional_edges("grade_kb", kb_grade_decision, {
        "good": "generate_kb",
        "weak": "web_search",   # KB insufficient -> fall through to web
    })
    graph.add_edge("web_search", "grade_web")
    graph.add_conditional_edges("grade_web", web_grade_decision, {
        "good": "generate_web",
        "weak": "fallback",
    })

    graph.add_edge("generate_kb", END)
    graph.add_edge("generate_web", END)
    graph.add_edge("fallback", END)
    graph.add_edge("direct", END)

    return graph.compile()


agent_graph = build_graph()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", required=True)
    args = parser.parse_args()
    result = agent_graph.invoke({"question": args.question})
    print(f"\nRoute path led to source: {result['source']}")
    print(f"\nAnswer:\n{result['answer']}")


