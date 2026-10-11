"""Lesson 01: LangChain Runnables with no model/API key.

pip install -r requirements-learning.txt
python examples/learning/langchain_01_runnables.py
"""
from langchain_core.runnables import RunnableLambda


def normalize(question: str) -> dict[str, str]:
    return {"text": question.strip().lower()}


def route(value: dict[str, str]) -> dict[str, str]:
    q = value["text"]
    if "memory" in q or "记忆" in q:
        topic = "agent memory"
    elif "mcp" in q:
        topic = "mcp"
    else:
        topic = "other"
    return {"question": q, "topic": topic}


def render(value: dict[str, str]) -> str:
    return f"Topic={value['topic']} | Question={value['question']}"


def build_chain():
    return RunnableLambda(normalize) | RunnableLambda(route) | RunnableLambda(render)


if __name__ == "__main__":
    for question in ["Agent memory checkpoint", "MCP tool schema", "Browser agent"]:
        print(build_chain().invoke(question))
