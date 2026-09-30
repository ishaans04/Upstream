"""Write the Core API's OpenAPI schema to web/lib/openapi.json (then `npm run types`).

services/core-api/tests/test_web_support.py fails while the committed copy differs
from what the code serves, so a backend change cannot silently break the web client.
"""
import json
import pathlib

from upstream_api.main import app

OUT = pathlib.Path(__file__).resolve().parents[1] / "web" / "lib" / "openapi.json"


def schema_text() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    OUT.write_text(schema_text(), encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
