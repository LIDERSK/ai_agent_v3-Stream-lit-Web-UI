"""Describe an image with the vision model (used by the agent and the describe_image tool)."""
import base64

from core.media import prepare_image
from core.ollama_client import chat_once
from core.router import resolve_target

DEFAULT_QUESTION = ("Popíš podrobne, čo je na obrázku. Ak je na ňom text alebo kód, presne ho prepíš. "
                    "Odpovedz po slovensky.")


def describe_bytes(node_name: str, data: bytes, question: str = DEFAULT_QUESTION) -> str:
    """May raise RoutingError / OllamaError."""
    target = resolve_target(node_name, needs_vision=True)
    b64 = base64.b64encode(prepare_image(data)).decode("ascii")
    return chat_once(target.url, target.model,
                     [{"role": "user", "content": question or DEFAULT_QUESTION, "images": [b64]}], 0.2)
