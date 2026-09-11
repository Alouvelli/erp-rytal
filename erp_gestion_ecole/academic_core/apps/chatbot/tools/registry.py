TOOL_REGISTRY = {}


def register_tool(name, schema):
    """Enregistre un outil RYTAL : nom -> {schema Anthropic tool-use, handler(user, request, **kwargs)}."""
    def decorator(fn):
        TOOL_REGISTRY[name] = {'schema': schema, 'handler': fn}
        return fn
    return decorator
