#!/usr/bin/env bash
# Keep repository Markdown links valid before a version tag exists; render
# immutable GitHub links only when publishing notes for that existing tag.
set -euo pipefail
tag=${1:?Existing version tag is required}
notes=${2:?Release notes file is required}
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.-]+)?$ ]]
test -s "$notes"
sed -E 's|\]\(([A-Z0-9_.]+\.md)(#[^)]*)?\)|](https://github.com/NCDCbioinformatics/cure-ngs-panel-harmonization-framework/blob/'"$tag"'/docs/\1\2)|g' "$notes"
