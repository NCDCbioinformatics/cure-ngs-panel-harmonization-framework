"""Real-tool regressions on a tiny coding transcript, not a human cache."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import json
from pathlib import Path

from cure_ngs.annotation import annotate_vcf
from cure_ngs.batch import repair_vcf_structure
from cure_ngs.models import Assembly
from cure_ngs.tools import normalize_vcf

parser = argparse.ArgumentParser()
parser.add_argument("work", type=Path)
parser.add_argument("fixture", type=Path)
args = parser.parse_args()
root = args.work
template = args.fixture.read_text()


def run(label, alt):
    job = root / label
    job.mkdir(exist_ok=True)
    source = job / "legacy.vcf"
    text = template.replace("##fileformat=VCFv4.2\n", "")
    text = text.replace("\tG\tA\t", f"\tG\t{alt}\t")
    text = text.replace("PASS\t.\t", "PASS\t'location':'exonic','origAlt':'metadata;not-an-allele'\t")
    source.write_text(text)
    before = source.read_bytes()
    repaired = repair_vcf_structure(source, job / "repaired.vcf", fallback_sample="TUMOR")
    normalize_vcf(repaired, job / "normalized.vcf", reference_fasta=root / "reference.fa")
    result = annotate_vcf(job / "normalized.vcf", job / "result.maf",
        reference_fasta=root / "reference.fa", assembly=Assembly.GRCH37,
        cache_version=116, vep_data=root / "cache", vep_config=root / "vep.ini",
        vep_path="/opt/vep/src/ensembl-vep", tumor_id=label, vcf_tumor_id="TUMOR",
        temporary_directory=root / "shared-tmp", stdout_log=job / f"{alt}.stdout.log",
        stderr_log=job / f"{alt}.stderr.log")
    with (job / "result.maf").open() as handle:
        rows = list(csv.DictReader((line for line in handle if not line.startswith("#")), delimiter="\t"))
    assert len(rows) == 1 and rows[0]["Tumor_Seq_Allele2"] == alt, rows
    assert rows[0]["Tumor_Sample_Barcode"] == label, rows
    assert rows[0]["Variant_Classification"] == "Missense_Mutation", rows
    assert source.read_bytes() == before
    return {"sample": label, "allele": alt, "rows": result.output_rows,
            "tmp": result.command[result.command.index("--tmp-dir") + 1]}


with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(lambda job: run(*job), [("SAME0001-A", "A"), ("SAME0001-B", "C")]))
results.append(run("SAME0001-A", "T"))
assert len({result["tmp"] for result in results}) == 3
(root / "real-tool-regressions.json").write_text(json.dumps(results, indent=2))
print("PASS: real bcftools/VEP/vcf2maf sanitation, parallel isolation, and changed-allele rerun")
