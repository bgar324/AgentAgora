from typing import Any

from agora.config.settings import OpenRouterSettings
from agora.focused.models import ChatReply, ClusterNamings, QuerySuggestions
from agora.llm.providers.openrouter import _request


def _object_schemas(value: Any):
    if isinstance(value, dict):
        if value.get("type") == "object" or "properties" in value:
            yield value
        for child in value.values():
            yield from _object_schemas(child)
    elif isinstance(value, list):
        for child in value:
            yield from _object_schemas(child)


def test_openrouter_uses_strict_json_schema_for_structured_outputs() -> None:
    for schema_type in (QuerySuggestions, ChatReply, ClusterNamings):
        request = _request(
            model="openai/gpt-5.6-luna",
            messages=[{"role": "user", "content": "Draft structured output"}],
            temperature=0.0,
            max_output_tokens=800,
            reasoning_effort=None,
            schema=schema_type,
            settings=OpenRouterSettings(api_key="test"),
        )
        schema = request["response_format"]["json_schema"]["schema"]

        for object_schema in _object_schemas(schema):
            assert object_schema["additionalProperties"] is False
            assert set(object_schema.get("required", [])) == set(
                object_schema.get("properties", {})
            )
