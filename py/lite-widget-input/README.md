# lite-widget-input

This experimental, pure-Python package requests a snapshot of selected
frontend widget state over Jupyter stdin. It requires a compatible frontend
bridge, which is not bundled with this package. An experimental notebook
bridge has been tested in locally patched JupyterLab 4.6.0 with a regular
Python kernel and in a release-matched JupyterLite 0.8.7 / JupyterLab 4.6.5
site with Pyodide, including notebook and console frontends. It is not a
published or independently installable frontend integration. Without a
compatible bridge the protocol marker appears as an ordinary input prompt;
this package cannot detect its absence or fail fast.

```python
from IPython.display import display
from lite_widget_input import widget_input

display(widget)
snapshot = widget_input(widget, fields=["value"])
```

Only request fields that the caller is permitted to disclose. The helper
checks that fields are synced widget traits, but field names cannot reliably
identify secrets. The frontend widget must commit pending edits to its model
before submission. Cancel raises `WidgetInputCancelled` and does not undo
widget edits; recognized frontend errors raise `WidgetInputError`.

The result is a snapshot, not an update to Python traits. While synchronous
input is waiting, Python trait updates from the browser can remain queued.
After the cell resumes, those updates can overwrite subsequent Python writes.
Do not assume the widget's Python state already matches the returned state.

The provisional v1 format uses UTF-8 JSON, a maximum 8192-byte marked request,
a maximum 65536-byte reply, up to 32 distinct synced fields, and at most 16
levels of nested state. JSON keys must be unique. JSON numbers must be finite
binary64 values; integer-valued numbers must lie in the JavaScript safe
integer range. Signed zero is not preserved. Strings must contain valid
Unicode scalar values, and `IPY_MODEL_` references and binary buffers are not
supported. Only exact documented reply envelope fields are accepted.
Custom serializers are supported only when their frontend value is already
representable under these restrictions. A provisional frontend implementation
has focused and cross-language tests, but the protocol is not yet stable.

The accepted reply envelopes are `{"status":"ok","state":{"value":2}}`,
`{"status":"cancelled"}`, and
`{"status":"error","code":"model_unavailable"}`. Successful state must
contain exactly the requested fields. Error codes contain lowercase ASCII
letters, digits, or underscores and start with a letter.

To build or install the package from the JupyterLite checkout, use
`python -m pip wheel --no-deps ./py/lite-widget-input` or
`python -m pip install ./py/lite-widget-input`. Installing the wheel in
Pyodide does not install the frontend integration.

To run focused tests from this directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```
