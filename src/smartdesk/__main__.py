"""Minimal CLI for smoke-testing the workflow: `python -m smartdesk`."""

import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from smartdesk import observability
from smartdesk.config import get_settings
from smartdesk.graph import build_graph
from smartdesk.llm import get_chat_model


def main() -> None:
    settings = get_settings()
    graph = build_graph(get_chat_model(settings), checkpointer=InMemorySaver())
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
            print(f"[intent: {result['intent']}]")
            print(f"SmartDesk: {result['messages'][-1].content}")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        observability.flush()


if __name__ == "__main__":
    main()
