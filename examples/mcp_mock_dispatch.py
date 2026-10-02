"""Local tool-interface exercise. This is a simulation, not an MCP server."""
import json


def add(a, b):
    return a + b


def word_count(text):
    return len(text.split())


TOOLS = {
    "add": {"function": add, "schema": {"a": "number", "b": "number"}},
    "word_count": {"function": word_count, "schema": {"text": "string"}},
}


def dispatch(name, arguments):
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": "unknown_tool"}
    if set(arguments) != set(tool["schema"]):
        return {"error": "invalid_parameters"}
    for key, kind in tool["schema"].items():
        value = arguments[key]
        valid = type(value) in (int, float) if kind == "number" else isinstance(value, str)
        if not valid:
            return {"error": "invalid_parameter_type", "parameter": key}
    return {"result": tool["function"](**arguments)}


if __name__ == "__main__":
    calls = [("add", {"a": 2, "b": 3}), ("word_count", {"text": "hello agent"}),
             ("unknown", {}), ("add", {"a": "wrong", "b": 3})]
    for name, arguments in calls:
        print(json.dumps({"tool": name, "parameters": arguments, "output": dispatch(name, arguments)}))
