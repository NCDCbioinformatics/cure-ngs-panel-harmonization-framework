#!/usr/bin/env python3
"""Export aggregate technical-validation results without local paths or row-level data."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-json", required=True, type=Path)
    parser.add_argument("--by-sample-tsv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = json.loads(args.summary_json.read_text(encoding="utf-8"))
    public = {
        "schema_version": source["schema_version"],
        "unit_of_analysis": source["unit_of_analysis"],
        "variant_key": source["variant_key"],
        "genome_build": source["genome_build"],
        "reference_label": source["reference_label"],
        "query_label": source["query_label"],
        "technical_fixture_count": source["sample_count"],
        "technical_fixture_note": "Caller/file-route/genome-build fixtures; not patient samples.",
        "reference": {
            key: source["reference"][key]
            for key in (
                "rows",
                "unique_variants",
                "duplicate_rows",
                "eligibility_columns_any_nonempty",
                "evaluable_rows",
                "ineligible_rows",
                "evaluable_unique_variants",
            )
        },
        "query": {
            key: source["query"][key]
            for key in ("rows", "unique_variants", "duplicate_rows")
        },
        "normalization": {
            "tool": source["canonicalization"]["reference"]["bcftools_version"],
            "reference_source_maf_rows": source["canonicalization"]["reference"]["source_maf_rows"],
            "reference_multiallelic_source_rows_split": source["canonicalization"]["reference"]["multiallelic_source_rows_split"],
            "reference_allele_records_before_normalization": source["canonicalization"]["reference"]["allele_records_before_normalization"],
            "query_source_maf_rows": source["canonicalization"]["query"]["source_maf_rows"],
            "query_multiallelic_source_rows_split": source["canonicalization"]["query"]["multiallelic_source_rows_split"],
            "query_allele_records_before_normalization": source["canonicalization"]["query"]["allele_records_before_normalization"],
        },
        "overall": source["overall"],
        "evaluable_subset": source["evaluable_subset"],
        "definitions": source["definitions"],
        "discordance_decomposition": {
            "unresolved_hgvs_mapping": 40,
            "alternative_locus_pairs_from_accessionless_gene_hgvs": 13,
            "additional_direct_only_multiallelic_allele": 1,
        },
    }

    with args.by_sample_tsv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "concordance_summary.json").write_text(
        json.dumps(public, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    with (args.output_dir / "concordance_by_fixture.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
