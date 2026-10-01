"""Real-tool regressions on a tiny coding transcript, not a human cache."""
import argparse
from pathlib import Path

from cure_ngs.self_test import run_annotation_regressions

parser = argparse.ArgumentParser()
parser.add_argument("work", type=Path)
parser.add_argument("fixture", type=Path)
args = parser.parse_args()
run_annotation_regressions(args.work, args.fixture)
print("PASS: real bcftools/VEP/vcf2maf sanitation, parallel isolation, and changed-allele rerun")
