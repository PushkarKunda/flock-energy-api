"""Unit tests for the dashboard's CSV exporter — the code that actually ships.

The inline <script> section is extracted verbatim from DASHBOARD_HTML (no copy,
no drift) and executed with Node.js against stubbed DOM globals. Skipped, not
failing, when Node.js is not installed.

Covered:
  - csvCell escaping: commas, embedded quotes, newlines, “null” cells
  - spreadsheet formula-injection guard (=, +, -, @, tab prefixes)
  - BOM + CRLF framing written by downloadCSV
  - todayStamp shape (dates land in the export filename)
"""

import json
import pathlib
import re
import shutil
import subprocess

import pytest

from app.dashboard import DASHBOARD_HTML

HARNESS = r"""'use strict';
const fs = require('fs');
const document = { createElement: () => ({ click() {}, remove() {} }), body: { appendChild() {} } };
let lastBlob = null;
const Blob = class { constructor(parts, opts) { lastBlob = { parts, opts }; } };
const URL = { createObjectURL: () => 'blob:fake', revokeObjectURL() {} };
const setTimeout = (fn) => 0;

__SECTION__

const mode = process.argv[2];
const path3 = process.argv[3];
if (mode === 'cells') {
  process.stdout.write(JSON.stringify(JSON.parse(fs.readFileSync(path3, 'utf8')).map(csvCell)));
} else if (mode === 'stamp') {
  process.stdout.write(todayStamp());
} else if (mode === 'cap') {
  process.stdout.write(String(EXPORT_METER_CAP));
} else if (mode === 'download') {
  downloadCSV('test.csv', ['Meter ID', 'Serial No'], [['=cmd', '12'], ['a,b', null]]);
  fs.writeFileSync(path3, JSON.stringify({ parts: lastBlob.parts, opts: lastBlob.opts }));
}
"""


def _extract_csv_section() -> str:
    match = re.search(
        r"// ================= CSV export =================\n(.*?)  // ================= Detail slide-over",
        DASHBOARD_HTML,
        re.S,
    )
    assert match, "CSV export section not found inside DASHBOARD_HTML"
    return match.group(1).rstrip()


@pytest.fixture(scope="module")
def harness_dir(tmp_path_factory):
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed; CSV-export unit tests skipped")
    return tmp_path_factory.mktemp("csv_harness")


def _run(harness_dir: pathlib.Path, mode: str, payload=None):
    harness = harness_dir / "harness.js"
    harness.write_text(HARNESS.replace("__SECTION__", _extract_csv_section()), encoding="utf-8")

    args = ["node", str(harness), mode]
    side_path = None
    if payload is not None:
        side_path = harness_dir / (mode + "_io.json")
        side_path.write_text(json.dumps(payload), encoding="utf-8")
        args.append(str(side_path))
    elif mode == "download":
        side_path = harness_dir / "blob.json"
        args.append(str(side_path))

    proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, "harness failed:\n" + proc.stderr
    return proc.stdout if payload is not None or mode != "download" else side_path


def test_csv_cell_escaping(harness_dir):
    inputs = [
        "J100000",                       # plain id passes through
        "", "  ", None, 12.5,            # empties / numbers
        "SE33962, rev A",                # comma -> quoted
        'say "hi"',                      # quotes -> doubled inside quotes
        "line\nbreak",                   # newline -> quoted
        "=1+2",                          # formula injection guarded
        "+1", "-1", "@abra", "\ttabbed",  # every guarded prefix
    ]
    expected = [
        "J100000",
        "", "  ", "", "12.5",
        '"SE33962, rev A"',
        '"say ""hi"""',
        '"line\nbreak"',
        "'=1+2",
        "'+1", "'-1", "'@abra", "'\ttabbed",
    ]
    outputs = json.loads(_run(harness_dir, "cells", payload=inputs))
    assert outputs == expected


def test_download_csv_framing_bom_and_crlf(harness_dir):
    blob_path = _run(harness_dir, "download")
    blob = json.loads(blob_path.read_text(encoding="utf-8"))

    assert blob["opts"]["type"] == "text/csv;charset=utf-8"
    body = "".join(blob["parts"])
    assert body.startswith("\ufeff")                              # BOM for Excel
    csv_text = body.lstrip("\ufeff")
    lines = csv_text.split("\r\n")
    assert lines[0] == "Meter ID,Serial No"                       # header
    assert lines[1] == "'=cmd,12"                                 # injection guard in data row
    assert lines[2] == '"a,b",'                                   # quoting + trailing empty cell


def test_todaystamp_is_iso_date(harness_dir):
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _run(harness_dir, "stamp"))


def test_export_meter_cap_is_sane(harness_dir):
    assert int(_run(harness_dir, "cap")) == 2500
