"""Local-only validation helper; input paths are supplied explicitly, never uploaded."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

parser = argparse.ArgumentParser()
parser.add_argument("input_list", type=Path)
parser.add_argument("output", type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
input_dir = args.output / "NGS_VCF" / "VCF_ALL"
input_dir.mkdir(parents=True, exist_ok=True)
rows = []
for name in args.input_list.read_text(encoding="utf-8-sig").splitlines():
    if not name.strip():
        continue
    source = Path(name)
    data = source.read_bytes()
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    header = next((line for line in lines if line.startswith("#CHROM")), "")
    records = [line.split("\t") for line in lines if line and not line.startswith("#")]
    destination = input_dir / source.name
    if destination.exists() and destination.read_bytes() != data:
        raise ValueError(f"Conflicting input basename: {source.name}")
    shutil.copy2(source, destination)
    rows.append({
        "name": source.name, "source": str(source), "sha256": hashlib.sha256(data).hexdigest(),
        "records": len(records), "header": header,
        "fileformat": next((line for line in lines if line.startswith("##fileformat=")), None),
        "build_evidence": [line for line in lines if line.startswith(("##reference=", "##assembly=", "##contig=<ID=1,", "##contig=<ID=chr1,"))],
        "symbolic_or_breakend": sum(1 for row in records if len(row) > 4 and ("<" in row[4] or "[" in row[4] or "]" in row[4])),
        "dictionary_info": sum(1 for row in records if len(row) > 7 and row[7].lstrip().startswith("{")),
        "first_record": records[0] if records else None,
    })
(args.output / "input-inventory.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
for row in rows:
    print(row["name"], row["records"], "SV=" + str(row["symbolic_or_breakend"]), "dict=" + str(row["dictionary_info"]), row["fileformat"], row["header"])
