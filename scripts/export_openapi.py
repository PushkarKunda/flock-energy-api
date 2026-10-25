"""Write openapi.json from the running app's schema.

Usage (credentials must be set as env vars or in a gitignored .env, because
app.config loads them at import time):

    python scripts/export_openapi.py [output_path]

Default output: openapi.json in the repository root (gitignored).
"""

import json
import pathlib
import sys

# Make the repo root importable no matter where the script is run from.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: E402  (path setup must come first)


def main() -> None:
    output = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("openapi.json")
    schema = app.openapi()
    output.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {output.resolve()} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
