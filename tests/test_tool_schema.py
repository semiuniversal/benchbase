"""BFCL tool schemas must be JSON Schema before they hit llama.cpp."""

from benchbase.runners.tool_calling import _openai_tools


def test_nested_bfcl_types_become_json_schema():
    tools = _openai_tools(
        [
            {
                "name": "calculate_area_under_curve",
                "description": "area",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "interval": {
                            "type": "array",
                            "items": {"type": "float"},
                        },
                        "where": {"type": "city"},
                    },
                    "required": ["interval"],
                },
            }
        ]
    )
    params = tools[0]["function"]["parameters"]
    assert params["type"] == "object"
    assert params["properties"]["interval"]["items"]["type"] == "number"
    assert params["properties"]["where"]["type"] == "string"
