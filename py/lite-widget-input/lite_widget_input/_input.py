"""The experimental v1 widget snapshot protocol."""

import json
import math
import re
from collections.abc import Sequence
from typing import Any

MARKER = "jupyterlite-widget-input:v1:"
MAX_REQUEST_BYTES = 8192
MAX_REPLY_BYTES = 65536
MAX_FIELDS = 32
MAX_DEPTH = 16
MAX_MODEL_ID_BYTES = 256
MAX_SAFE_INTEGER = 2**53 - 1
_FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,127}\Z")
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class WidgetInputError(RuntimeError):
    """The widget input request or reply could not be completed."""


class WidgetInputCancelled(WidgetInputError):  # noqa: N818 - retain the prototype's public name
    """The user cancelled the input request."""


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _utf8_size(value: str, description: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise WidgetInputError(f"{description} contains invalid Unicode") from error


def _validate_number(value: int | float) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WidgetInputError("Reply contains a non-finite number")
        if not value.is_integer():
            return
    if abs(value) > MAX_SAFE_INTEGER:
        raise WidgetInputError("Reply contains an unsafe integer")


def _validate_value(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise WidgetInputError("Reply state is nested too deeply")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        _validate_number(value)
        return
    if isinstance(value, str):
        _utf8_size(value, "Reply")
        if value.startswith("IPY_MODEL_"):
            raise WidgetInputError("Widget references are not supported")
        return
    if isinstance(value, list):
        for item in value:
            _validate_value(item, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _utf8_size(key, "Reply")
            _validate_value(item, depth + 1)
        return
    raise WidgetInputError("Reply contains an unsupported value")


def _validated_fields(widget: Any, fields: Sequence[str]) -> list[str]:
    if isinstance(fields, (str, bytes)) or not isinstance(fields, Sequence):
        raise WidgetInputError("fields must be a sequence of field names")
    names = list(fields)
    if not 1 <= len(names) <= MAX_FIELDS:
        raise WidgetInputError(f"Select between 1 and {MAX_FIELDS} fields")
    if any(not isinstance(name, str) or not _FIELD.fullmatch(name) for name in names):
        raise WidgetInputError("Invalid or protected field name")
    if len(set(names)) != len(names):
        raise WidgetInputError("Duplicate field name")
    traits = getattr(widget, "traits", None)
    if not callable(traits) or not set(names).issubset(traits(sync=True)):
        raise WidgetInputError("Each field must be a synced widget trait")
    return names


def _request(widget: Any, names: list[str], prompt: str) -> str:
    model_id = getattr(widget, "model_id", None)
    if (
        not isinstance(model_id, str)
        or not model_id
        or _utf8_size(model_id, "Model ID") > MAX_MODEL_ID_BYTES
    ):
        raise WidgetInputError("Widget must have a valid model_id")
    if not isinstance(prompt, str):
        raise WidgetInputError("prompt must be a string")
    _utf8_size(prompt, "Prompt")

    request = MARKER + json.dumps(
        {"model_id": model_id, "fields": names, "prompt": prompt},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if _utf8_size(request, "Request") > MAX_REQUEST_BYTES:
        raise WidgetInputError("Request is too large")
    return request


def _decode_reply(raw: str, names: list[str]) -> dict[str, Any]:
    if _utf8_size(raw, "Reply") > MAX_REPLY_BYTES:
        raise WidgetInputError("Reply is too large")
    try:
        reply = json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as error:
        raise WidgetInputError("Invalid JSON reply") from error
    if not isinstance(reply, dict):
        raise WidgetInputError("Reply must be an object")
    if reply == {"status": "cancelled"}:
        raise WidgetInputCancelled("Widget input cancelled")
    if (
        set(reply) == {"status", "code"}
        and reply.get("status") == "error"
        and isinstance(reply.get("code"), str)
        and _ERROR_CODE.fullmatch(reply["code"])
    ):
        raise WidgetInputError(f"Frontend widget input error: {reply['code']}")
    if set(reply) != {"status", "state"} or reply.get("status") != "ok":
        raise WidgetInputError("Invalid reply envelope")
    state = reply["state"]
    if not isinstance(state, dict) or set(state) != set(names):
        raise WidgetInputError("Reply fields do not match the request")
    _validate_value(state)
    return state


def widget_input(
    widget: Any, *, fields: Sequence[str], prompt: str = "Submit widget input"
) -> dict[str, Any]:
    """Return selected frontend state without updating the Python widget."""
    names = _validated_fields(widget, fields)
    return _decode_reply(input(_request(widget, names, prompt)), names)
