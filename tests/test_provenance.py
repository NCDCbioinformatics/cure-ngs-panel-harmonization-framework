import json
from pathlib import Path

from cure_ngs.provenance import sha256_file, write_manifest


def test_manifest_contains_input_and_output_hashes(tmp_path: Path) -> None:
    input_path = tmp_path / "input.txt"
    output_path = tmp_path / "output.txt"
    input_path.write_text("input\n", encoding="utf-8")
    output_path.write_text("output\n", encoding="utf-8")

    manifest_path = write_manifest(
        tmp_path / "manifest.json",
        command=["example", "--flag"],
        inputs={"input": input_path},
        outputs={"output": output_path},
        parameters={"flag": True},
        tools={"example": "1.0.0"},
    )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["inputs"]["input"]["sha256"] == sha256_file(input_path)
    assert payload["outputs"]["output"]["sha256"] == sha256_file(output_path)
    assert payload["command"] == ["example", "--flag"]

