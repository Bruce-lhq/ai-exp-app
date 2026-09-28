import math
import re
from decimal import Decimal, DecimalException

MANAGED_KEYS = {"run_dir", "data_root", "resume", "allow_nonexact_resume", "allow_world_size_change"}


def parse_number(text: str, integer: bool = False) -> int | float:
    if len(text) > 128:
        raise ValueError("数值过长")
    match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([kKmMbB]?)\s*", text)
    if not match:
        raise ValueError("请输入数值，可使用 K、M、B")
    try:
        value = Decimal(match[1]) * {"": 1, "k": 1000, "m": 1000000, "b": 1000000000}[match[2].lower()]
        if not value.is_finite() or abs(value) > Decimal("1e308"):
            raise ValueError("数值超出范围")
        if integer:
            if value != value.to_integral_value():
                raise ValueError("需要整数")
            return int(value)
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("需要有限数值")
        return result
    except DecimalException as exc:
        raise ValueError("非法数值") from exc


def coerce(field: dict, value):
    kind = field.get("kind", "string")
    if value is None:
        if field.get("nullable") or (field.get("has_default") and field.get("default") is None):
            return None
        raise ValueError("不能为空")
    choices = field.get("choices") or []
    if kind in {"integer", "int", "number", "float", "number_or_choice"}:
        if kind == "number_or_choice" and isinstance(value, str) and value in choices:
            return value
        if isinstance(value, bool):
            raise ValueError("需要数值")
        value = parse_number(str(value), integer=kind in {"integer", "int"})
    elif kind in {"boolean", "bool"}:
        if isinstance(value, str) and value.lower() in {"true", "false"}:
            value = value.lower() == "true"
        if not isinstance(value, bool):
            raise ValueError("需要 true 或 false")
    elif not isinstance(value, str):
        raise ValueError("需要字符串")
    if choices and kind != "number_or_choice" and value not in choices:
        raise ValueError("不在可选值中")
    constraints = field.get("constraints") or {}
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "min" in constraints and value < constraints["min"]:
            raise ValueError(f"不得小于 {constraints['min']}")
        if "max" in constraints and value > constraints["max"]:
            raise ValueError(f"不得大于 {constraints['max']}")
    return value


def validate_parameters(schema: list[dict], parameters: dict) -> dict:
    if not isinstance(parameters, dict):
        return {"parameters": {"training": {}, "runtime": {"gpu_count": 1}}, "warnings": [], "errors": [{"field": "parameters", "message": "参数必须为 JSON 对象"}]}
    training = parameters.get("training", parameters)
    runtime = parameters.get("runtime", {"gpu_count": 1})
    if not isinstance(training, dict) or not isinstance(runtime, dict):
        return {"parameters": parameters, "warnings": [], "errors": [{"field": "parameters", "message": "training 和 runtime 必须为对象"}]}
    fields = {field["key"]: field for field in schema if field["key"] not in MANAGED_KEYS}
    warnings, errors, fixed = [], [], {}
    for key in training.keys() - fields.keys():
        if key not in {"version", "runtime", "name"}:
            warnings.append({"field": key, "message": "当前代码没有此参数，已忽略"})
    for key, field in fields.items():
        if key not in training:
            if field.get("has_default", "default" in field):
                fixed[key] = field.get("default")
                warnings.append({"field": key, "message": "未填写，已使用源码默认值"})
            elif field.get("required"):
                errors.append({"field": key, "message": "此参数必填且没有默认值"})
            continue
        try:
            fixed[key] = coerce(field, training[key])
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append({"field": key, "message": str(exc)})
    try:
        if isinstance(runtime.get("gpu_count", 1), bool):
            raise ValueError("GPU 卡数必须为正整数")
        gpu_count = parse_number(str(runtime.get("gpu_count", 1)), integer=True)
        if gpu_count < 1:
            raise ValueError("GPU 卡数必须为正整数")
    except (ValueError, TypeError):
        gpu_count = runtime.get("gpu_count")
        errors.append({"field": "gpu_count", "message": "GPU 卡数必须为正整数"})
    return {"parameters": {"training": fixed, "runtime": {"gpu_count": gpu_count}}, "warnings": warnings, "errors": errors}
