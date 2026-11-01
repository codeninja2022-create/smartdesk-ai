"""Minimal CLI for smoke-testing the workflow: `python -m smartdesk`."""

import sys
import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from smartdesk import observability
from smartdesk.config import get_settings
from smartdesk.graph import build_graph
from smartdesk.llm import get_chat_model
from smartdesk.rag.retriever import build_retriever


def main() -> None:
    settings = get_settings()
    retriever = build_retriever(settings)
    if retriever.collection.count() == 0:
        print("The knowledge base index is empty; run `python -m smartdesk.kb.ingest` first.", file=sys.stderr)
        sys.exit(1)
    graph = build_graph(
        get_chat_model(settings),
        retriever,
        min_similarity=settings.rag_min_similarity,
        checkpointer=InMemorySaver(),
    )
    config = {
        "configurable": {"thread_id": str(uuid.uuid4())},
        "callbacks": observability.get_callbacks(settings),
    }
    tracing = "on" if settings.langfuse_enabled else "off"
    print(f"SmartDesk AI (model={settings.llm_model}, tracing={tracing}). Type 'exit' to quit.")
    try:
        while True:
            text = input("\nYou: ").strip()
            if text.lower() in {"exit", "quit"}:
                break
            if not text:
                continue
            result = graph.invoke({"messages": [HumanMessage(content=text)]}, config)
            debug = f"intent: {result['intent']}, domain: {result.get('domain') or '-'}"
            if result.get("retrieved"):
                debug += f", top similarity: {result['retrieved'][0]['similarity']:.3f}"
            if result.get("escalation_reason"):
                debug += f", escalated: {result['escalation_reason']}"
            print(f"[{debug}]")
            print(f"SmartDesk: {result['messages'][-1].content}")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        observability.flush()


if __name__ == "__main__":
    main()
