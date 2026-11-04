import json
import unittest
from unittest.mock import patch

from lite_widget_input import WidgetInputCancelled, WidgetInputError, widget_input
from lite_widget_input._input import (
    MARKER,
    MAX_FIELDS,
    MAX_REPLY_BYTES,
    MAX_REQUEST_BYTES,
    MAX_SAFE_INTEGER,
)


class Widget:
    model_id = "model-1"
    value = 0

    def traits(self, **metadata):
        if metadata != {"sync": True}:
            return {}
        return {f"field{i}": object() for i in range(MAX_FIELDS)} | {"value": object()}


class WidgetInputTests(unittest.TestCase):
    def test_snapshot_is_returned_without_changing_python_trait(self):
        widget = Widget()
        with patch("builtins.input", return_value='{"status":"ok","state":{"value":2}}') as read:
            self.assertEqual(widget_input(widget, fields=["value"]), {"value": 2})
        self.assertEqual(widget.value, 0)
        request = read.call_args.args[0]
        self.assertTrue(request.startswith(MARKER))
        self.assertEqual(
            json.loads(request[len(MARKER) :]),
            {"model_id": "model-1", "fields": ["value"], "prompt": "Submit widget input"},
        )

    def test_invalid_requests_do_not_call_input(self):
        invalid_fields = [
            [],
            ["missing"],
            ["_esm"],
            ["value", "value"],
            "value",
            b"value",
            [1],
            [f"field{i}" for i in range(MAX_FIELDS + 1)],
        ]
        for fields in invalid_fields:
            with self.subTest(fields=fields), patch("builtins.input") as read:
                with self.assertRaises(WidgetInputError):
                    widget_input(Widget(), fields=fields)
                read.assert_not_called()

        for model_id in ("", "x" * 257, "\ud800", None):
            widget = Widget()
            widget.model_id = model_id
            with self.subTest(model_id=model_id), patch("builtins.input") as read:
                with self.assertRaises(WidgetInputError):
                    widget_input(widget, fields=["value"])
                read.assert_not_called()

        for prompt in (None, "\ud800"):
            with self.subTest(prompt=prompt), patch("builtins.input") as read:
                with self.assertRaises(WidgetInputError):
                    widget_input(Widget(), fields=["value"], prompt=prompt)
                read.assert_not_called()

    def test_request_byte_limit_and_unicode(self):
        reply = '{"status":"ok","state":{"value":1}}'
        with patch("builtins.input", return_value=reply) as read:
            widget_input(Widget(), fields=["value"], prompt="")
        base_size = len(read.call_args.args[0].encode("utf-8"))
        prompt = "a" * (MAX_REQUEST_BYTES - base_size - 2) + "é"
        with patch("builtins.input", return_value=reply) as read:
            self.assertEqual(widget_input(Widget(), fields=["value"], prompt=prompt), {"value": 1})
        self.assertEqual(len(read.call_args.args[0].encode("utf-8")), MAX_REQUEST_BYTES)
        with patch("builtins.input") as read:
            with self.assertRaisesRegex(WidgetInputError, "too large"):
                widget_input(Widget(), fields=["value"], prompt=prompt + "a")
            read.assert_not_called()

    def test_maximum_field_count(self):
        fields = [f"field{i}" for i in range(MAX_FIELDS)]
        state = dict.fromkeys(fields, None)
        with patch("builtins.input", return_value=json.dumps({"status": "ok", "state": state})):
            self.assertEqual(widget_input(Widget(), fields=fields), state)

    def test_reply_byte_limit(self):
        prefix = '{"status":"ok","state":{"value":"'
        suffix = '"}}'
        raw = prefix + "x" * (MAX_REPLY_BYTES - len(prefix) - len(suffix)) + suffix
        with patch("builtins.input", return_value=raw):
            self.assertEqual(
                len(widget_input(Widget(), fields=["value"])["value"]),
                len(raw) - len(prefix) - len(suffix),
            )
        with (
            patch("builtins.input", return_value=raw + " "),
            self.assertRaisesRegex(WidgetInputError, "too large"),
        ):
            widget_input(Widget(), fields=["value"])

    def test_cancel_and_frontend_error(self):
        for reply, error in (
            ('{"status":"cancelled"}', WidgetInputCancelled),
            ('{"status":"error","code":"model_unavailable"}', WidgetInputError),
        ):
            with (
                self.subTest(reply=reply),
                patch("builtins.input", return_value=reply),
                self.assertRaises(error),
            ):
                widget_input(Widget(), fields=["value"])

    def test_rejects_malformed_and_unsupported_replies(self):
        replies = [
            "not JSON",
            "[]",
            '{"status":"ok","state":{"value":NaN}}',
            '{"status":"ok","state":{"value":1e999}}',
            '{"status":"ok","state":{"value":9007199254740992}}',
            '{"status":"ok","state":{"value":1e20}}',
            '{"status":"ok","state":{"value":2,"other":3}}',
            '{"status":"ok","state":{"value":1},"extra":1}',
            '{"status":"ok","state":{"value":1,"value":2}}',
            '{"status":"ok","state":{"value":{"x":1,"x":2}}}',
            '{"status":"ok","state":{"value":"IPY_MODEL_123"}}',
            '{"status":"ok","state":{"value":"\\ud800"}}',
            '{"status":"ok","state":{"value":{"\\ud800":1}}}',
            '{"status":"cancelled","extra":1}',
            '{"status":"error","code":"INVALID"}',
            '{"status":"error","code":"bad\\ncode"}',
            '{"status":"ok","state":{"value":' + "[" * 16 + "0" + "]" * 16 + "}}",
            "\ud800",
        ]
        for reply in replies:
            with (
                self.subTest(reply=reply[:100]),
                patch("builtins.input", return_value=reply),
                self.assertRaises(WidgetInputError),
            ):
                widget_input(Widget(), fields=["value"])

    def test_safe_numbers_and_depth_boundary(self):
        for value in (MAX_SAFE_INTEGER, -MAX_SAFE_INTEGER, 0.5):
            reply = json.dumps({"status": "ok", "state": {"value": value}})
            with self.subTest(value=value), patch("builtins.input", return_value=reply):
                self.assertEqual(widget_input(Widget(), fields=["value"]), {"value": value})
        raw = '{"status":"ok","state":{"value":' + "[" * 15 + "0" + "]" * 15 + "}}"
        with patch("builtins.input", return_value=raw):
            self.assertIsInstance(widget_input(Widget(), fields=["value"])["value"], list)


if __name__ == "__main__":
    unittest.main()
