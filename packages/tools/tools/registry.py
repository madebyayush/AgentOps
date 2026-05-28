import logging
import inspect
from functools import wraps
from typing import Callable, Any

logger = logging.getLogger("agentops.tools.registry")

class ToolRegistry:
    """
    Central database containing all registered system-native tools.
    Enables agents to index local Python functionalities with matching schemas.
    """
    def __init__(self):
        self._tools: dict[str, dict[str, Any]] = {}
        logger.info("Local Tool Registry initialized.")

    def register(self, name: str, description: str, func: Callable, schema: dict = None):
        """
        Explicitly adds a function to the registry directory.
        """
        self._tools[name] = {
            "name": name,
            "description": description,
            "callable": func,
            "schema": schema or self._generate_fallback_schema(func)
        }
        logger.info(f"Registered tool: '{name}' | Description: '{description[:50]}...'")

    def get_tool(self, name: str) -> dict[str, Any]:
        """
        Recalls registered tool parameters.
        """
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """
        Returns JSON-compatible tool representations matching LLM tool call signatures.
        """
        return [
            {
                "name": details["name"],
                "description": details["description"],
                "parameters": details["schema"]
            }
            for details in self._tools.values()
        ]

    def _generate_fallback_schema(self, func: Callable) -> dict:
        """
        Basic parameter inspection generating tool call properties.
        """
        sig = inspect.signature(func)
        properties = {}
        required = []
        
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            properties[name] = {
                "type": "string", # Default fallback mapping
                "description": f"Parameter '{name}' signature hook."
            }
            if param.default == inspect.Parameter.empty:
                required.append(name)
                
        return {
            "type": "object",
            "properties": properties,
            "required": required
        }

# Global registry container
global_registry = ToolRegistry()

def tool(name: str, description: str, schema: dict = None):
    """
    Decorator simplifying function registration directly to the global database.
    """
    def decorator(func: Callable):
        global_registry.register(name, description, func, schema)
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator
