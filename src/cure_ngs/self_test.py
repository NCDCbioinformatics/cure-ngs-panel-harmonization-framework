"""Image-contained, offline execution checks; never substitutes for human-cache validation."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from .annotation import annotate_vcf
from .batch import repair_vcf_structure
from .models import Assembly
from .runtime import runtime_versions
from .tools import normalize_vcf
from .tutorial_data import export_tutorial_data, verify_tutorial_data


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _maf_rows(path: Path) -> list[dict[str, str]]:
    with path.open() as handle:
        return list(csv.DictReader((line for line in handle if line.strip() and not line.startswith("#")), delimiter="\t"))


def run_annotation_regressions(root: Path, fixture: Path) -> list[dict[str, object]]:
    """Exercise actual tools using the caller's explicitly synthetic GFF/cache."""
    template = fixture.read_text()

    def run(label: str, alt: str) -> dict[str, object]:
        job = root / label
        job.mkdir(exist_ok=True)
        source = job / "legacy.vcf"
        text = template.replace("##fileformat=VCFv4.2\n", "")
        text = text.replace("\tG\tA\t", f"\tg\t{alt.lower()}\t")
        text = text.replace("PASS\t.\t", "PASS\t'location':'exonic','origAlt':'metadata;not-an-allele'\t")
        source.write_text(text)
        before = source.read_bytes()
        repaired = repair_vcf_structure(source, job / "repaired.vcf", fallback_sample="TUMOR")
        normalize_vcf(repaired, job / "normalized.vcf", reference_fasta=root / "reference.fa")
        executable = shutil.which("vep")
        if executable is None:
            raise FileNotFoundError("VEP missing; use the full image, not the -core image")
        result = annotate_vcf(job / "normalized.vcf", job / "result.maf",
            reference_fasta=root / "reference.fa", assembly=Assembly.GRCH37,
            cache_version=116, vep_data=root / "cache", vep_config=root / "vep.ini",
            vep_path=Path(executable).resolve().parent, tumor_id=label, vcf_tumor_id="TUMOR",
            temporary_directory=root / "shared-tmp", stdout_log=job / f"{alt}.stdout.log",
            stderr_log=job / f"{alt}.stderr.log")
        rows = _maf_rows(job / "result.maf")
        _require(len(rows) == 1 and rows[0]["Tumor_Seq_Allele2"] == alt, "Wrong annotation allele or row count")
        _require(rows[0]["Tumor_Sample_Barcode"] == label, "Cross-sample contamination")
        _require(rows[0]["Variant_Classification"] == "Missense_Mutation", "Wrong synthetic coding consequence")
        _require(source.read_bytes() == before, "Original input changed")
        return {"sample": label, "allele": alt, "rows": result.output_rows,
                "tmp": result.command[result.command.index("--tmp-dir") + 1]}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda job: run(*job), [("SAME0001-A", "A"), ("SAME0001-B", "C")]))
    results.append(run("SAME0001-A", "T"))
    _require(len({result["tmp"] for result in results}) == 3, "Temporary files reused")
    (root / "real-tool-regressions.json").write_text(json.dumps(results, indent=2))
    return results


def run_self_test(output: str | Path, *, profile: str = "full") -> dict[str, object]:
    if profile not in {"core", "full"}:
        raise ValueError("Self-test profile must be core or full")
    root = Path(output) / f"run-{uuid4().hex[:12]}"
    try:
        root.mkdir(parents=True)
    except PermissionError as exc:
        raise PermissionError("Output mount is not writable. Use --user with your host UID/GID and choose a writable output directory.") from exc
    package = Path(__file__).resolve().parents[2]
    examples = package / "examples/synthetic"
    report: dict[str, object] = {"status": "RUNNING", "profile": profile, "output": str(root),
        "scope": "Offline tool execution and public fixture integrity; NOT full human-cache annotation",
        "checks": [], "versions": runtime_versions()}
    checks: list[dict[str, object]] = report["checks"]  # type: ignore[assignment]

    def cli(name: str, *arguments: object) -> dict[str, object]:
        command = [sys.executable, "-m", "cure_ngs.cli", *map(str, arguments)]
        result = subprocess.run(command, capture_output=True, text=True)
        (root / f"{name}.stdout.log").write_text(result.stdout)
        (root / f"{name}.stderr.log").write_text(result.stderr)
        _require(result.returncode == 0, f"{name} failed: {result.stderr[-2000:]}")
        payload = json.loads(result.stdout)
        checks.append({"name": name, "status": "PASS"})
        return payload

    try:
        tools = json.loads((package / "resources/tools.lock.json").read_text())["tools"]
        versions = report["versions"]
        for name in ("bcftools", "samtools"):
            observed = versions[name]  # type: ignore[index]
            _require(observed["status"] == "available" and observed["version"].startswith(f"{name} {tools[name]['version']}"),
                     f"Pinned {name} is missing or incompatible")
        if profile == "full":
            for name in ("picard", "vcf2maf"):
                observed = versions[name]  # type: ignore[index]
                lock_name = "picard-primary" if name == "picard" else name
                _require(observed["status"] == "available" and observed.get("sha256") == tools[lock_name]["sha256"],
                         f"Pinned {name} is missing or its checksum differs")
        checks.append({"name": "pinned-tool-inventory", "status": "PASS"})
        verify_tutorial_data()
        exported = root / "component-test-data"
        export_tutorial_data(exported)
        public_input = root / "NGS_VCF/VCF_ALL"
        public_input.mkdir(parents=True)
        shutil.copyfile(exported / "inputs/test_b37.vcf", public_input / "test_b37.vcf")
        checks.append({"name": "bundled_public_input_integrity", "status": "PASS"})
        cli("vcf-preprocessing", "normalize-vcf", examples / "normalize.grch37.vcf", root / "normalized.vcf",
            "--reference-fasta", examples / "tiny.grch37.fa", "--assembly", "GRCh37")
        cli("hgvs-to-minimal-maf", "hgvs-table-to-minimal-maf", examples / "hgvs_to_minimal_input.tsv",
            root / "from-hgvs.maf", "--failed", root / "hgvs.failed.tsv", "--reference-fasta", examples / "tiny.grch37.fa",
            "--assembly", "GRCh37", "--response-cache", examples / "rest-cache", "--offline-replay")
        _require(bool(_maf_rows(root / "from-hgvs.maf")), "HGVS conversion returned an empty MAF")
        cli("minimal-maf-to-vcf", "minimal-maf-to-vcf", root / "from-hgvs.maf", root / "from-minimal",
            "--reference-fasta", examples / "tiny.grch37.fa", "--assembly", "GRCh37")
        gene = cli("gene-normalization", "normalize-gene", "C11ORF30", "--hgnc", examples / "hgnc.tsv",
            "--gtf", examples / "genes.gtf")
        _require(gene["matched_symbol"] == "EMSY", "Gene normalization mismatch")
        fusion = cli("fusion-normalization", "normalize-fusion", "ALK-EML4", "--hgnc", examples / "hgnc.tsv",
            "--gtf", examples / "genes.gtf")
        _require(fusion["normalized"] == "ALK--EML4", "Fusion normalization mismatch")
        hgvs = cli("hgvs-table-normalization", "normalize-hgvs-table", exported / "inputs/hgvs_to_minimal_maf_test.xlsx",
            root / "hgvs.normalized.xlsx")
        _require(hgvs["rows"] == 2625, "Public HGVS row count mismatch")
        if profile == "full":
            work = root / "actual-synthetic-annotation"
            work.mkdir()
            fixture = examples / "self-test"
            shutil.copyfile(fixture / "reference.fa", work / "reference.fa")
            subprocess.run(["samtools", "faidx", str(work / "reference.fa")], check=True, capture_output=True)
            picard = os.environ.get("PICARD_JAR")
            _require(bool(picard), "PICARD_JAR missing; use the full image")
            subprocess.run(["java", "-jar", str(picard), "CreateSequenceDictionary",
                f"R={work / 'reference.fa'}", f"O={work / 'reference.dict'}"], check=True, capture_output=True)
            (work / "source.grch38.vcf").write_text((fixture / "input.vcf").read_text().replace("##reference=GRCh37", "##reference=GRCh38"))
            lifted = cli("actual-picard-synthetic-liftover", "liftover-vcf", work / "source.grch38.vcf",
                work / "lifted.grch37.vcf", "--rejected", work / "rejected.vcf", "--source-assembly", "GRCh38",
                "--target-assembly", "GRCh37", "--chain", fixture / "identity.chain",
                "--target-reference", work / "reference.fa", "--picard-jar", str(picard))
            _require(lifted["accepted_records"] == 1 and lifted["rejected_records"] == 0, "Synthetic liftover mismatch")
            with (work / "transcripts.gff.gz").open("wb") as handle:
                subprocess.run(["bgzip", "-c", str(fixture / "transcripts.gff")], check=True, stdout=handle, stderr=subprocess.PIPE)
            subprocess.run(["tabix", "-p", "gff", str(work / "transcripts.gff.gz")], check=True, capture_output=True)
            (work / "vep.ini").write_text(f"gff {work / 'transcripts.gff.gz'}\ncache 0\n")
            cache = work / "cache/homo_sapiens/116_GRCh37"
            (cache / "1").mkdir(parents=True)
            (cache / "info.txt").write_text("species\thomo_sapiens\nassembly\tGRCh37\nsource_sift\tsynthetic-no-predictions\nsource_polyphen\tsynthetic-no-predictions\n")
            results = run_annotation_regressions(work, fixture / "input.vcf")
            checks.append({"name": "actual-vep-vcf2maf-parallel-and-rerun", "status": "PASS", "executions": len(results)})
        else:
            report["annotation"] = "NOT_TESTED: core image does not contain VEP/vcf2maf; select the full image"
        report["status"] = "PASS"
    except Exception as exc:
        report.update(status="FAILED", error=str(exc))
    (root / "self-test-report.json").write_text(json.dumps(report, indent=2))
    return report
