#!/usr/bin/env python3
"""Create the quantitative cross-route concordance figure used in the manuscript."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


BLUE = "#1769AA"
ORANGE = "#D97706"
GREEN = "#17855B"
DARK = "#263238"
GRID = "#D5DDE3"
PALE_BLUE = "#E8F2FA"
PALE_ORANGE = "#FFF1DE"
PALE_GREEN = "#E5F4ED"
FIXTURE_LABELS = {
    "test": "Baseline",
    "test_b37": "GRCh37",
    "test_b38": "GRCh38 → GRCh37",
    "test_maf": "MAF → VCF",
    "test_mer": "Merged callers",
    "test_mus": "MuSE",
    "test_mut": "MuTect",
    "test_pin": "Pindel",
    "test_rad": "RADIA",
    "test_sni": "SomaticSniper",
    "test_str": "Strelka",
    "test_var": "VarScan",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-tsv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--svg", type=Path)
    return parser.parse_args()


def load_rows(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    rows = [row for row in rows if row["analysis_set"] == "hgvs-evaluable-subset"]
    overall = next(row for row in rows if row["sample_id"] == "ALL")
    per_fixture = [row for row in rows if row["sample_id"] != "ALL"]
    return overall, per_fixture


def box(ax, x: float, y: float, w: float, h: float, color: str, title: str, value: str) -> None:
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle="round,pad=0.012,rounding_size=0.025",
        linewidth=0,
        facecolor=color,
        transform=ax.transAxes,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h * 0.62, value, ha="center", va="center", fontsize=15, fontweight="bold", color=DARK, transform=ax.transAxes)
    ax.text(x + w / 2, y + h * 0.23, title, ha="center", va="center", fontsize=8.5, color=DARK, transform=ax.transAxes)


def make_figure(metrics_tsv: Path, output: Path, svg: Path | None) -> None:
    overall, rows = load_rows(metrics_tsv)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9})
    fig = plt.figure(figsize=(9.0, 5.35), facecolor="white")
    gs = fig.add_gridspec(1, 2, width_ratios=[0.86, 1.55], wspace=0.31)
    ax0 = fig.add_subplot(gs[0, 0])
    ax1 = fig.add_subplot(gs[0, 1])

    fig.suptitle(
        "Cross-route concordance after allele normalization",
        x=0.075,
        y=0.985,
        ha="left",
        fontsize=14,
        fontweight="bold",
        color=DARK,
    )
    fig.text(
        0.075,
        0.947,
        "GRCh37 · HGVS-evaluable subset · 12 technical VCF/caller/build fixtures (not patient samples)",
        ha="left",
        va="top",
        fontsize=8.8,
        color="#53636D",
    )

    ax0.set_axis_off()
    ax0.text(0.0, 0.94, "A  Overall variant accounting", transform=ax0.transAxes, fontweight="bold", fontsize=10.2, color=DARK)
    box(ax0, 0.00, 0.68, 0.47, 0.17, PALE_BLUE, "Direct-VCF unique", overall["reference_unique"])
    box(ax0, 0.53, 0.68, 0.47, 0.17, PALE_ORANGE, "Report-HGVS unique", overall["query_unique"])
    box(ax0, 0.00, 0.45, 1.00, 0.17, PALE_GREEN, "Concordant", overall["concordant"])
    box(ax0, 0.00, 0.23, 0.47, 0.16, PALE_BLUE, "Direct only", overall["reference_only"])
    box(ax0, 0.53, 0.23, 0.47, 0.16, PALE_ORANGE, "Report only", overall["query_only"])

    kpis = [
        ("Sensitivity", overall["reference_recovery_percent"]),
        ("PPV", overall["query_ppv_percent"]),
        ("Jaccard", overall["exact_set_agreement_percent"]),
        ("F1", overall["f1_percent"]),
    ]
    for i, (name, value) in enumerate(kpis):
        x = 0.01 + i * 0.25
        ax0.text(x, 0.12, f"{float(value):.2f}%", transform=ax0.transAxes, ha="left", va="center", fontsize=10.2, fontweight="bold", color=GREEN)
        ax0.text(x, 0.065, name, transform=ax0.transAxes, ha="left", va="center", fontsize=7.7, color="#53636D")

    ordered = sorted(rows, key=lambda row: float(row["reference_recovery_percent"]))
    labels = [FIXTURE_LABELS.get(row["sample_id"], row["sample_id"]) for row in ordered]
    sensitivity = [float(row["reference_recovery_percent"]) for row in ordered]
    ppv = [float(row["query_ppv_percent"]) for row in ordered]
    y = list(range(len(ordered)))

    ax1.set_title("B  Per-fixture agreement", loc="left", fontweight="bold", fontsize=10.2, color=DARK, pad=11)
    for yi, s, p in zip(y, sensitivity, ppv):
        ax1.plot([s, p], [yi, yi], color="#AAB7C0", linewidth=1.2, zorder=1)
    y_sensitivity = [yi - 0.07 for yi in y]
    y_ppv = [yi + 0.07 for yi in y]
    ax1.scatter(sensitivity, y_sensitivity, s=28, color=BLUE, label="Sensitivity", zorder=3)
    ax1.scatter(ppv, y_ppv, s=28, color=ORANGE, marker="s", label="PPV", zorder=3)
    ax1.set_yticks(y, labels)
    ax1.set_xlim(90, 100.55)
    ax1.set_xticks([90, 92, 94, 96, 98, 100])
    ax1.set_xlabel("Agreement (%)")
    ax1.grid(axis="x", color=GRID, linewidth=0.7)
    ax1.spines[["top", "right", "left"]].set_visible(False)
    ax1.spines["bottom"].set_color("#AAB7C0")
    ax1.tick_params(axis="y", length=0)
    ax1.legend(loc="upper right", frameon=False, fontsize=8, ncol=2, bbox_to_anchor=(1.0, 1.045))

    for yi, row in zip(y, ordered):
        if row["sample_id"] == "test_pin":
            ax1.text(90.05, yi + 0.31, "29/31 concordant", fontsize=7.2, color="#53636D", va="bottom")

    fig.text(
        0.075,
        0.018,
        "Unique sample-aware CHROM:POS:REF:ALT keys after multiallelic splitting, reference validation, and bcftools left normalization.",
        ha="left",
        va="bottom",
        fontsize=7.5,
        color="#53636D",
    )
    fig.subplots_adjust(left=0.075, right=0.985, top=0.875, bottom=0.13)

    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=320, bbox_inches="tight", facecolor="white")
    if svg is not None:
        svg.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(svg, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    make_figure(args.metrics_tsv, args.output, args.svg)


if __name__ == "__main__":
    main()
