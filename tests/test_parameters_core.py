import pytest
from ai_exp_app.parameters.validation import parse_number, validate_parameters


@pytest.mark.parametrize("text,value", [("1.5B", 1500000000), ("2k", 2000), ("3M", 3000000)])
def test_units(text, value):
    assert parse_number(text, True) == value


@pytest.mark.parametrize("text", ["NaN", "1.5", "2abc", "1e999999999"])
def test_invalid_integer(text):
    with pytest.raises(ValueError):
        parse_number(text, True)


def test_repair_does_not_replace_invalid_values():
    schema = [{"key": "count", "kind": "integer", "has_default": True, "default": 5}, {"key": "mode", "kind": "string", "choices": ["a", "b"], "has_default": True, "default": "a"}]
    result = validate_parameters(schema, {"training": {"count": "abc", "old": 10}, "runtime": {"gpu_count": 2}})
    assert result["errors"][0]["field"] == "count"
    assert result["parameters"]["training"] == {"mode": "a"}
    assert {w["field"] for w in result["warnings"]} == {"old", "mode"}
