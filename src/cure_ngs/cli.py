from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import __version__
from .annotation import annotate_vcf
from .batch import batch_vcf_to_maf, prepare_v133_workspace
from .concordance import compare_maf_routes
from .fusion import normalize_fusion
from .gene import GeneCatalog
from .hgvs import normalize_hgvs
from .hgvs_to_maf import hgvs_table_to_minimal_maf
from .liftover import liftover_vcf
from .maf import minimal_maf_to_vcfs
from .models import Assembly
from .preflight import check_environment
from .provenance import write_manifest
from .reference_bundle import (
    inspect_reference_bundle,
    load_reference_bundle,
    write_reference_config_template,
)
from .resources import verify_profile_resources
from .runtime import runtime_versions
from .table_io import normalize_hgvs_table
from .tools import normalize_vcf, tool_version
from .tutorial_data import (
    export_tutorial_data,
    export_v133_example_workspace,
    verify_tutorial_data,
)
from .vcf import inspect_vcf, sanitize_vcf
from .workflows import DEFAULT_TARGET_ASSEMBLY, vcf_to_maf


def _assembly(value: str) -> Assembly:
    try:
        return Assembly(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("assembly must be GRCh37 or GRCh38") from exc


def _delimiter(value: str) -> str:
    if value in {",", "\t"}:
        return value
    choices = {"comma": ",", "csv": ",", "tab": "\t", "tsv": "\t", "\\t": "\t"}
    try:
        return choices[value.casefold()]
    except KeyError as exc:
        raise argparse.ArgumentTypeError(
            "delimiter must be comma/csv or tab/tsv"
        ) from exc


def _sheet(value: str) -> str | int:
    return int(value) if value.isdecimal() else value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cure-ngs")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    versions = subparsers.add_parser("versions", help="Report executable versions")
    versions.add_argument("--bcftools", default="bcftools")
    versions.add_argument("--samtools", default="samtools")
    versions.add_argument("--vep", default="vep")
    versions.add_argument("--perl", default="perl")
    versions.add_argument("--java", default="java")
    versions.add_argument("--picard-jar")
    versions.add_argument("--vcf2maf")

    doctor = subparsers.add_parser(
        "doctor", help="Check tools and mounted resources before a workflow run"
    )
    doctor.add_argument(
        "--profile",
        choices=("core", "vcf-to-maf", "liftover", "gene", "all"),
        default="core",
    )
    doctor.add_argument("--assembly", type=_assembly, default=Assembly.GRCH37)
    doctor.add_argument("--reference-fasta")
    doctor.add_argument("--vep-data")
    doctor.add_argument("--cache-version", type=int, default=116)
    doctor.add_argument("--chain")
    doctor.add_argument("--gtf")
    doctor.add_argument("--hgnc")
    doctor.add_argument("--bcftools", default="bcftools")
    doctor.add_argument("--samtools", default="samtools")
    doctor.add_argument("--vep", default="vep")
    doctor.add_argument("--perl", default="perl")
    doctor.add_argument("--java", default="java")
    doctor.add_argument("--picard-jar")
    doctor.add_argument("--vcf2maf")

    bundle_doctor = subparsers.add_parser(
        "doctor-bundle",
        help="Validate every FASTA, index, chain, and VEP cache in a reference bundle",
    )
    bundle_doctor.add_argument("--reference-config", required=True)
    bundle_doctor.add_argument("--reference-root")
    bundle_doctor.add_argument("--vep", default="vep")

    bundle_init = subparsers.add_parser(
        "init-reference-config",
        help="Create a multi-reference config for a user-selected reference root",
    )
    bundle_init.add_argument("output")
    bundle_init.add_argument(
        "--reference-root",
        required=True,
        help=(
            "Root visible to cure-ngs (normally /references in Docker); "
            "candidate paths in the generated config are relative to this root"
        ),
    )
    bundle_init.add_argument("--cache-version", type=int, default=116)
    bundle_init.add_argument("--force", action="store_true")

    tutorial_data = subparsers.add_parser(
        "export-tutorial-data",
        help="Copy the six-component public test bundle from the image to the host",
    )
    tutorial_data.add_argument("output")
    tutorial_data.add_argument(
        "--force",
        action="store_true",
        help="Overwrite named bundle files in a non-empty output directory",
    )
    tutorial_data.add_argument("--source", help=argparse.SUPPRESS)

    v133_example = subparsers.add_parser(
        "export-v1.3.3-example",
        help=(
            "Create the manuscript's VCF_ALL/LOG/MAF/TMP tree with the public "
            "25-record VCF and validated 25-row reference MAF"
        ),
    )
    v133_example.add_argument("workspace_root")
    v133_example.add_argument("--force", action="store_true")
    v133_example.add_argument("--source", help=argparse.SUPPRESS)

    tutorial_verify = subparsers.add_parser(
        "verify-tutorial-data",
        help="Verify every bundled public test file against its SHA-256 manifest",
    )
    tutorial_verify.add_argument("--source", help=argparse.SUPPRESS)

    inspect = subparsers.add_parser("inspect-vcf", help="Inspect VCF structure")
    inspect.add_argument("input")
    inspect.add_argument("--assembly", type=_assembly)
    inspect.add_argument(
        "--allow-unknown-assembly",
        action="store_true",
        help="Return null assembly instead of failing when no evidence is present",
    )

    sanitize = subparsers.add_parser(
        "sanitize-vcf", help="Convert VCF text to validated UTF-8/LF form"
    )
    sanitize.add_argument("input")
    sanitize.add_argument("output")

    gene = subparsers.add_parser(
        "normalize-gene", help="Resolve one gene token with GTF and HGNC data"
    )
    gene.add_argument("symbol")
    gene.add_argument("--gtf", required=True)
    gene.add_argument("--hgnc", required=True)
    gene.add_argument("--fuzzy", action="store_true")
    gene.add_argument("--cutoff", type=float, default=0.92)
    gene.add_argument("--ambiguity-delta", type=float, default=0.02)

    fusion = subparsers.add_parser(
        "normalize-fusion", help="Resolve a directional gene-fusion token"
    )
    fusion.add_argument("fusion")
    fusion.add_argument("--gtf", required=True)
    fusion.add_argument("--hgnc", required=True)
    fusion.add_argument("--fuzzy", action="store_true")

    hgvs = subparsers.add_parser(
        "normalize-hgvs", help="Conservatively sanitize one HGVS expression"
    )
    hgvs.add_argument("value")
    hgvs.add_argument("--kind", required=True, choices=("c", "n", "p"))

    hgvs_table = subparsers.add_parser(
        "normalize-hgvs-table",
        help="Normalize HGVS columns in CSV, TSV, or XLSX with an audit trail",
    )
    hgvs_table.add_argument("input")
    hgvs_table.add_argument("output")
    hgvs_table.add_argument(
        "--delimiter", type=_delimiter, default="\t", metavar="comma|tab"
    )
    hgvs_table.add_argument("--sheet", type=_sheet, default=0)
    hgvs_table.add_argument("--coding-column", action="append")
    hgvs_table.add_argument("--protein-column", action="append")
    hgvs_table.add_argument("--manifest")

    hgvs_to_maf = subparsers.add_parser(
        "hgvs-table-to-minimal-maf",
        help="Resolve HGVS rows through a frozen, replayable Ensembl REST cache",
    )
    hgvs_to_maf.add_argument("input")
    hgvs_to_maf.add_argument("output")
    hgvs_to_maf.add_argument("--failed")
    hgvs_to_maf.add_argument("--reference-fasta", required=True)
    hgvs_to_maf.add_argument("--assembly", required=True, type=_assembly)
    hgvs_to_maf.add_argument("--response-cache", required=True)
    hgvs_to_maf.add_argument("--delimiter", type=_delimiter, default="\t")
    hgvs_to_maf.add_argument("--sheet", type=_sheet, default=0)
    hgvs_to_maf.add_argument("--offline-replay", action="store_true")
    hgvs_to_maf.add_argument("--endpoint")
    hgvs_to_maf.add_argument("--threads", type=int, default=4)
    hgvs_to_maf.add_argument("--retries", type=int, default=3)
    hgvs_to_maf.add_argument("--timeout-seconds", type=float, default=30.0)
    hgvs_to_maf.add_argument("--manifest")

    normalize = subparsers.add_parser(
        "normalize-vcf", help="Split and reference-normalize VCF alleles"
    )
    normalize.add_argument("input")
    normalize.add_argument("output")
    normalize.add_argument("--reference-fasta", required=True)
    normalize.add_argument("--assembly", required=True, type=_assembly)
    normalize.add_argument("--bcftools", default="bcftools")
    normalize.add_argument("--manifest")

    minimal_to_vcf = subparsers.add_parser(
        "minimal-maf-to-vcf",
        help="Convert minimal MAF rows to reference-valid per-sample VCFs",
    )
    minimal_to_vcf.add_argument("input")
    minimal_to_vcf.add_argument("output_directory")
    minimal_to_vcf.add_argument("--reference-fasta", required=True)
    minimal_to_vcf.add_argument("--assembly", required=True, type=_assembly)
    minimal_to_vcf.add_argument("--manifest")

    liftover = subparsers.add_parser(
        "liftover-vcf", help="Lift a VCF between GRCh37 and GRCh38 with Picard"
    )
    liftover.add_argument("input")
    liftover.add_argument("output")
    liftover.add_argument("--rejected", required=True)
    liftover.add_argument("--source-assembly", required=True, type=_assembly)
    liftover.add_argument("--target-assembly", required=True, type=_assembly)
    liftover.add_argument("--chain", required=True)
    liftover.add_argument("--target-reference", required=True)
    liftover.add_argument("--picard-jar", required=True)
    liftover.add_argument("--java", default="java")
    liftover.add_argument("--manifest")

    verify_resources = subparsers.add_parser(
        "verify-resources", help="Verify mounted assets against a resource lock"
    )
    verify_resources.add_argument("--lock", required=True)
    verify_resources.add_argument("--profile", required=True)
    verify_resources.add_argument(
        "--resource",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Supply one path for every resource required by the profile",
    )

    annotate = subparsers.add_parser(
        "annotate-vcf", help="Annotate a normalized VCF with pinned VEP/vcf2maf"
    )
    annotate.add_argument("input")
    annotate.add_argument("output")
    annotate.add_argument("--reference-fasta", required=True)
    annotate.add_argument("--assembly", required=True, type=_assembly)
    annotate.add_argument("--cache-version", required=True, type=int)
    annotate.add_argument("--vep-data", required=True)
    annotate.add_argument("--vcf2maf")
    annotate.add_argument("--vep-path")
    annotate.add_argument("--tumor-id")
    annotate.add_argument("--vcf-tumor-id")
    annotate.add_argument("--normal-id")
    annotate.add_argument("--vcf-normal-id")
    annotate.add_argument("--forks", type=int, default=1)
    annotate.add_argument("--temporary-directory")
    annotate.add_argument("--manifest")

    workflow = subparsers.add_parser(
        "vcf-to-maf",
        help="Normalize, optionally lift, and annotate a VCF in one workflow",
    )
    workflow.add_argument("input")
    workflow.add_argument("output")
    workflow.add_argument("--source-reference", required=True)
    workflow.add_argument("--target-reference")
    workflow.add_argument("--source-assembly", type=_assembly)
    workflow.add_argument(
        "--target-assembly",
        type=_assembly,
        default=DEFAULT_TARGET_ASSEMBLY,
        help=(
            "Target genome assembly (default: GRCh37/hg19 for the CURE-NGS "
            "Korean clinical-panel deployment; pass GRCh38 explicitly when needed)"
        ),
    )
    workflow.add_argument("--chain")
    workflow.add_argument("--picard-jar")
    workflow.add_argument("--java", default="java")
    workflow.add_argument("--bcftools", default="bcftools")
    workflow.add_argument("--cache-version", required=True, type=int)
    workflow.add_argument("--vep-data", required=True)
    workflow.add_argument("--vcf2maf")
    workflow.add_argument("--vep-path")
    workflow.add_argument("--tumor-id")
    workflow.add_argument("--vcf-tumor-id")
    workflow.add_argument("--normal-id")
    workflow.add_argument("--vcf-normal-id")
    workflow.add_argument("--forks", type=int, default=1)
    workflow.add_argument("--work-directory")
    workflow.add_argument("--manifest")

    batch_workflow = subparsers.add_parser(
        "batch-vcf-to-maf",
        help=(
            "Run the restored NCDC V1.3.3 batch workflow with portable "
            "reference and liftover fallback configuration"
        ),
    )
    batch_workflow.add_argument(
        "input_directory",
        nargs="?",
        help="Input VCF directory (omit when --workspace-root is used)",
    )
    batch_workflow.add_argument(
        "output_directory",
        nargs="?",
        help="Output MAF directory (omit when --workspace-root is used)",
    )
    batch_workflow.add_argument(
        "--workspace-root",
        help=(
            "Create/use the manuscript and NCDC V1.3.3 layout below this root: "
            "VCF_ALL, VCF_ALL_LOG, VCF_ALL_MAF, and VCF_ALL_TMP"
        ),
    )
    batch_workflow.add_argument("--reference-config", required=True)
    batch_workflow.add_argument("--reference-root")
    batch_workflow.add_argument("--source-assembly", type=_assembly)
    batch_workflow.add_argument("--target-assembly", type=_assembly)
    batch_workflow.add_argument("--jobs", type=int, default=4)
    batch_workflow.add_argument("--sample-tag-length", type=int, default=8)
    batch_workflow.add_argument("--picard-jar")
    batch_workflow.add_argument("--java", default="java")
    batch_workflow.add_argument("--bcftools", default="bcftools")
    batch_workflow.add_argument("--vcf2maf")
    batch_workflow.add_argument("--vep-path")
    batch_workflow.add_argument("--forks", type=int, default=1)
    batch_workflow.add_argument("--work-directory")
    batch_workflow.add_argument("--overwrite", action="store_true")

    concordance = subparsers.add_parser(
        "compare-maf-routes",
        help="Calculate sample-aware exact concordance between two MAF routes",
    )
    concordance.add_argument("output_directory")
    concordance.add_argument("--reference-maf", action="append", required=True)
    concordance.add_argument("--query-maf", action="append", required=True)
    concordance.add_argument("--reference-label", default="direct-vcf")
    concordance.add_argument("--query-label", default="report-hgvs")
    concordance.add_argument(
        "--reference-require-any",
        action="append",
        default=[],
        metavar="COLUMN",
        help="Define an evaluable reference subset where any named column is non-empty",
    )
    concordance.add_argument(
        "--reference-fasta",
        help="Canonicalize both routes with this FASTA and bcftools before comparison",
    )
    concordance.add_argument("--bcftools", default="bcftools")
    concordance.add_argument("--manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "versions":
            print(
                json.dumps(
                    runtime_versions(
                        bcftools=args.bcftools,
                        samtools=args.samtools,
                        vep=args.vep,
                        perl=args.perl,
                        java=args.java,
                        picard_jar=args.picard_jar,
                        vcf2maf=args.vcf2maf,
                    ),
                    indent=2,
                )
            )
            return 0

        if args.command == "doctor":
            report = check_environment(
                profile=args.profile,
                assembly=args.assembly,
                reference_fasta=args.reference_fasta,
                vep_data=args.vep_data,
                cache_version=args.cache_version,
                chain=args.chain,
                gtf=args.gtf,
                hgnc=args.hgnc,
                bcftools=args.bcftools,
                samtools=args.samtools,
                vep=args.vep,
                perl=args.perl,
                java=args.java,
                picard_jar=args.picard_jar,
                vcf2maf=args.vcf2maf,
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report["status"] == "READY" else 2

        if args.command == "doctor-bundle":
            bundle = load_reference_bundle(
                args.reference_config, reference_root=args.reference_root
            )
            runtime = runtime_versions(vep=args.vep)
            vep_runtime = runtime.get("vep")
            report = inspect_reference_bundle(
                bundle,
                runtime_vep=(
                    vep_runtime if isinstance(vep_runtime, dict) else None
                ),
            )
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report["status"] == "READY" else 2

        if args.command == "init-reference-config":
            output = write_reference_config_template(
                args.output,
                reference_root=args.reference_root,
                cache_version=args.cache_version,
                force=args.force,
            )
            print(
                json.dumps(
                    {
                        "status": "CREATED",
                        "config": str(output),
                        "reference_root": args.reference_root,
                        "next_steps": [
                            "Edit candidate paths or arrange files under the root",
                            (
                                "cure-ngs doctor-bundle --reference-config "
                                f"{output} --reference-root {args.reference_root}"
                            ),
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "export-tutorial-data":
            result = export_tutorial_data(
                args.output, source=args.source, force=args.force
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0

        if args.command == "export-v1.3.3-example":
            result = export_v133_example_workspace(
                args.workspace_root, source=args.source, force=args.force
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0

        if args.command == "verify-tutorial-data":
            result = verify_tutorial_data(args.source)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0

        if args.command == "inspect-vcf":
            result = inspect_vcf(
                args.input,
                assembly_override=args.assembly,
                require_assembly=not args.allow_unknown_assembly,
            )
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "sanitize-vcf":
            output = sanitize_vcf(args.input, args.output)
            print(
                json.dumps(
                    {"status": "VALID", "output": str(output.resolve())}, indent=2
                )
            )
            return 0

        if args.command == "normalize-gene":
            catalog = GeneCatalog.from_files(gtf=args.gtf, hgnc=args.hgnc)
            result = catalog.resolve(
                args.symbol,
                fuzzy=args.fuzzy,
                cutoff=args.cutoff,
                ambiguity_delta=args.ambiguity_delta,
            )
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "normalize-fusion":
            catalog = GeneCatalog.from_files(gtf=args.gtf, hgnc=args.hgnc)
            result = normalize_fusion(args.fusion, catalog, fuzzy=args.fuzzy)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "normalize-hgvs":
            result = normalize_hgvs(args.value, kind=args.kind)
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "normalize-hgvs-table":
            coding_columns = tuple(args.coding_column or ("HGVSc",))
            protein_columns = tuple(
                args.protein_column or ("HGVSp", "HGVSp_short")
            )
            summary = normalize_hgvs_table(
                args.input,
                args.output,
                coding_columns=coding_columns,
                protein_columns=protein_columns,
                delimiter=args.delimiter,
                sheet=args.sheet,
            )
            manifest = args.manifest or f"{args.output}.manifest.json"
            write_manifest(
                manifest,
                command=["cure-ngs", *(argv or sys.argv[1:])],
                inputs={"table": args.input},
                outputs={"normalized_table": args.output},
                parameters={
                    **summary,
                    "delimiter": "comma" if args.delimiter == "," else "tab",
                    "sheet": args.sheet,
                    "coding_columns": coding_columns,
                    "protein_columns": protein_columns,
                },
                tools={},
            )
            print(
                json.dumps(
                    {
                        **summary,
                        "output": str(Path(args.output).resolve()),
                        "manifest": str(Path(manifest).resolve()),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "hgvs-table-to-minimal-maf":
            failure_output = args.failed or f"{args.output}.failed.tsv"
            result = hgvs_table_to_minimal_maf(
                args.input,
                args.output,
                failure_output=failure_output,
                reference_fasta=args.reference_fasta,
                assembly=args.assembly,
                response_cache=args.response_cache,
                delimiter=args.delimiter,
                sheet=args.sheet,
                offline_replay=args.offline_replay,
                endpoint=args.endpoint,
                threads=args.threads,
                retries=args.retries,
                timeout_seconds=args.timeout_seconds,
            )
            manifest = args.manifest or f"{args.output}.manifest.json"
            write_manifest(
                manifest,
                command=["cure-ngs", *(argv or sys.argv[1:])],
                inputs={
                    "hgvs_table": args.input,
                    "reference_fasta": args.reference_fasta,
                },
                outputs={
                    "minimal_maf": args.output,
                    "failed_rows": failure_output,
                },
                parameters={
                    **result.to_dict(),
                    "delimiter": "comma" if args.delimiter == "," else "tab",
                    "sheet": args.sheet,
                    "offline_replay": args.offline_replay,
                },
                tools={
                    "ensembl_rest_endpoint": result.endpoint,
                },
            )
            print(
                json.dumps(
                    {
                        **result.to_dict(),
                        "output": str(Path(args.output).resolve()),
                        "manifest": str(Path(manifest).resolve()),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 2 if result.status == "FAILED_ALL" else 0

        if args.command == "normalize-vcf":
            before = inspect_vcf(args.input, assembly_override=args.assembly)
            normalization = normalize_vcf(
                args.input,
                args.output,
                reference_fasta=args.reference_fasta,
                bcftools=args.bcftools,
            )
            after = inspect_vcf(args.output, assembly_override=args.assembly)
            manifest = args.manifest or f"{args.output}.manifest.json"
            write_manifest(
                manifest,
                command=[item for command in normalization.commands for item in command],
                inputs={
                    "vcf": args.input,
                    "reference_fasta": args.reference_fasta,
                },
                outputs={"normalized_vcf": args.output},
                parameters={
                    "assembly": args.assembly.value,
                    "check_ref": "error",
                    "split_multiallelic": True,
                    "remove_duplicates": "exact",
                    "bcftools_norm_summaries": normalization.summaries,
                    "before": before.to_dict(),
                    "after": after.to_dict(),
                },
                tools={"bcftools": normalization.tool_version},
            )
            print(
                json.dumps(
                    {
                        "status": after.status.value,
                        "output": str(Path(args.output).resolve()),
                        "manifest": str(Path(manifest).resolve()),
                        "records_before": before.record_count,
                        "records_after": after.record_count,
                    },
                    indent=2,
                )
            )
            return 0

        if args.command == "minimal-maf-to-vcf":
            result = minimal_maf_to_vcfs(
                args.input,
                args.output_directory,
                reference_fasta=args.reference_fasta,
                assembly=args.assembly,
            )
            manifest = args.manifest or str(
                Path(args.output_directory) / "minimal-maf-to-vcf.manifest.json"
            )
            write_manifest(
                manifest,
                command=["cure-ngs", *(argv or sys.argv[1:])],
                inputs={
                    "minimal_maf": args.input,
                    "reference_fasta": args.reference_fasta,
                },
                outputs={
                    f"vcf:{sample_id}": output
                    for sample_id, output in result.sample_files.items()
                },
                parameters={
                    "assembly": args.assembly.value,
                    **result.to_dict(),
                },
                tools={},
            )
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "liftover-vcf":
            result = liftover_vcf(
                args.input,
                args.output,
                rejected_path=args.rejected,
                source_assembly=args.source_assembly,
                target_assembly=args.target_assembly,
                chain_path=args.chain,
                target_reference=args.target_reference,
                picard_jar=args.picard_jar,
                java=args.java,
            )
            manifest = args.manifest or f"{args.output}.manifest.json"
            write_manifest(
                manifest,
                command=list(result.command),
                inputs={
                    "vcf": args.input,
                    "chain": args.chain,
                    "target_reference": args.target_reference,
                    "picard_jar": args.picard_jar,
                },
                outputs={
                    "lifted_vcf": args.output,
                    "rejected_vcf": args.rejected,
                },
                parameters=result.to_dict(),
                tools={
                    "java": result.java_version,
                    "picard": result.picard_version,
                },
            )
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "verify-resources":
            supplied: dict[str, str] = {}
            for item in args.resource:
                if "=" not in item:
                    raise ValueError(f"Invalid --resource {item!r}; expected NAME=PATH")
                name, path = item.split("=", 1)
                if not name or not path:
                    raise ValueError(f"Invalid --resource {item!r}; expected NAME=PATH")
                if name in supplied:
                    raise ValueError(f"Duplicate --resource name: {name}")
                supplied[name] = path
            results = verify_profile_resources(
                args.lock, profile=args.profile, supplied_paths=supplied
            )
            print(
                json.dumps(
                    {
                        "status": "VALID",
                        "profile": args.profile,
                        "resources": [result.__dict__ for result in results],
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0

        if args.command == "annotate-vcf":
            result = annotate_vcf(
                args.input,
                args.output,
                reference_fasta=args.reference_fasta,
                assembly=args.assembly,
                cache_version=args.cache_version,
                vep_data=args.vep_data,
                vcf2maf=args.vcf2maf,
                vep_path=args.vep_path,
                tumor_id=args.tumor_id,
                vcf_tumor_id=args.vcf_tumor_id,
                normal_id=args.normal_id,
                vcf_normal_id=args.vcf_normal_id,
                forks=args.forks,
                temporary_directory=args.temporary_directory,
            )
            manifest = args.manifest or f"{args.output}.manifest.json"
            write_manifest(
                manifest,
                command=list(result.command),
                inputs={
                    "vcf": args.input,
                    "reference_fasta": args.reference_fasta,
                },
                outputs={"annotated_maf": args.output},
                parameters=result.to_dict(),
                tools={
                    "vcf2maf_sha256": result.vcf2maf_sha256,
                    "vep_cache_version": str(result.cache_version),
                },
            )
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "vcf-to-maf":
            result = vcf_to_maf(
                args.input,
                args.output,
                source_reference=args.source_reference,
                target_reference=args.target_reference,
                target_assembly=args.target_assembly,
                source_assembly=args.source_assembly,
                chain_path=args.chain,
                picard_jar=args.picard_jar,
                java=args.java,
                bcftools=args.bcftools,
                cache_version=args.cache_version,
                vep_data=args.vep_data,
                vcf2maf_path=args.vcf2maf,
                vep_path=args.vep_path,
                tumor_id=args.tumor_id,
                vcf_tumor_id=args.vcf_tumor_id,
                normal_id=args.normal_id,
                vcf_normal_id=args.vcf_normal_id,
                forks=args.forks,
                work_directory=args.work_directory,
            )
            manifest = args.manifest or f"{args.output}.manifest.json"
            manifest_inputs = {
                "vcf": args.input,
                "source_reference": args.source_reference,
                "target_reference": args.target_reference or args.source_reference,
            }
            if args.chain:
                manifest_inputs["chain"] = args.chain
            if args.picard_jar:
                manifest_inputs["picard_jar"] = args.picard_jar
            write_manifest(
                manifest,
                command=["cure-ngs", *(argv or sys.argv[1:])],
                inputs=manifest_inputs,
                outputs={"annotated_maf": args.output},
                parameters=result.to_dict(),
                tools={
                    "vcf2maf_sha256": str(
                        result.annotation.get("vcf2maf_sha256", "")
                    ),
                    "vep_cache_version": str(args.cache_version),
                },
            )
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "batch-vcf-to-maf":
            if args.workspace_root:
                if args.input_directory or args.output_directory:
                    raise ValueError(
                        "Use either --workspace-root or input/output directories, not both"
                    )
                if args.work_directory:
                    raise ValueError(
                        "--work-directory cannot be combined with --workspace-root; "
                        "VCF_ALL_TMP is selected automatically"
                    )
                workspace = prepare_v133_workspace(args.workspace_root)
                input_directory = workspace.input_directory
                output_directory = workspace.maf_directory
                work_directory = workspace.temporary_directory
                log_directory = workspace.log_directory
                manifest_directory = workspace.manifest_directory
                v133_layout = True
            else:
                if not args.input_directory or not args.output_directory:
                    raise ValueError(
                        "Supply input_directory and output_directory, or use --workspace-root"
                    )
                input_directory = args.input_directory
                output_directory = args.output_directory
                work_directory = args.work_directory
                log_directory = None
                manifest_directory = None
                v133_layout = False
            bundle = load_reference_bundle(
                args.reference_config, reference_root=args.reference_root
            )
            result = batch_vcf_to_maf(
                input_directory,
                output_directory,
                bundle=bundle,
                target_assembly=args.target_assembly,
                source_assembly=args.source_assembly,
                jobs=args.jobs,
                sample_tag_length=args.sample_tag_length,
                picard_jar=args.picard_jar,
                java=args.java,
                bcftools=args.bcftools,
                vcf2maf_path=args.vcf2maf,
                vep_path=args.vep_path,
                forks=args.forks,
                work_directory=work_directory,
                log_directory=log_directory,
                manifest_directory=manifest_directory,
                v133_layout=v133_layout,
                overwrite=args.overwrite,
            )
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            return 0 if result.failed == 0 else 2

        if args.command == "compare-maf-routes":
            result = compare_maf_routes(
                args.reference_maf,
                args.query_maf,
                args.output_directory,
                reference_label=args.reference_label,
                query_label=args.query_label,
                reference_require_any=tuple(args.reference_require_any),
                reference_fasta=args.reference_fasta,
                bcftools=args.bcftools,
            )
            manifest = args.manifest or str(
                Path(args.output_directory) / "concordance.manifest.json"
            )
            inputs = {
                **{
                    f"reference_maf:{index}": path
                    for index, path in enumerate(args.reference_maf, start=1)
                },
                **{
                    f"query_maf:{index}": path
                    for index, path in enumerate(args.query_maf, start=1)
                },
            }
            write_manifest(
                manifest,
                command=["cure-ngs", *(argv or sys.argv[1:])],
                inputs=inputs,
                outputs={
                    "summary_json": result.summary_json,
                    "by_sample_tsv": result.by_sample_tsv,
                    "discordant_tsv": result.discordant_tsv,
                    **(
                        {"reference_canonical_vcf": result.reference_canonical_vcf}
                        if result.reference_canonical_vcf
                        else {}
                    ),
                    **(
                        {"query_canonical_vcf": result.query_canonical_vcf}
                        if result.query_canonical_vcf
                        else {}
                    ),
                },
                parameters={
                    **result.to_dict(),
                    "reference_label": args.reference_label,
                    "query_label": args.query_label,
                    "reference_require_any": args.reference_require_any,
                    "canonicalized": args.reference_fasta is not None,
                },
                tools={
                    **(
                        {"bcftools": tool_version(args.bcftools)}
                        if args.reference_fasta
                        else {}
                    )
                },
            )
            print(
                json.dumps(
                    {
                        **result.to_dict(),
                        "manifest": str(Path(manifest).resolve()),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 0
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        print(f"ERROR: external command failed: {detail}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
