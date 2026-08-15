[CmdletBinding()]
param(
    [string]$Engine = $env:CONTAINER_ENGINE,
    [string]$Image = $(if ($env:CURE_NGS_IMAGE) { $env:CURE_NGS_IMAGE } else { "cure-ngs-harmonizer:reviewer-core" })
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Examples = Join-Path $Root "examples"
$RunId = "{0}-{1}" -f (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ"), $PID
$Output = Join-Path $Root (Join-Path "reviewer-output" $RunId)

if (-not $Engine) {
    foreach ($Candidate in @("docker", "podman")) {
        if (Get-Command $Candidate -ErrorAction SilentlyContinue) {
            & $Candidate info *> $null
            if ($LASTEXITCODE -eq 0) {
                $Engine = $Candidate
                break
            }
        }
    }
}
if (-not $Engine -or -not (Get-Command $Engine -ErrorAction SilentlyContinue)) {
    throw "Container engine not found: $Engine"
}
New-Item -ItemType Directory -Force -Path $Output | Out-Null
$SecurityOption = "no-new-privileges:true"
$EngineVersion = (& $Engine --version 2>$null) -join " "
if ($EngineVersion -match "Podman") {
    $SecurityOption = "no-new-privileges"
}

function Invoke-Checked {
    param([string[]]$Arguments)
    & $Engine @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Engine exited with code $LASTEXITCODE"
    }
}

function Invoke-CureNgs {
    param([string[]]$Arguments)
    $ContainerArgs = @(
        "run", "--rm", "--network", "none", "--read-only",
        "--tmpfs", "/tmp:size=256m,mode=1777",
        "--security-opt", $SecurityOption,
        "--mount", "type=bind,source=$Examples,target=/examples,readonly",
        "--mount", "type=bind,source=$Output,target=/data/output",
        $Image
    ) + $Arguments
    & $Engine @ContainerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CURE-NGS command exited with code $LASTEXITCODE"
    }
}

Write-Host "[1/8] Building pinned core image"
Invoke-Checked @("build", "--file", (Join-Path $Root "docker/Dockerfile.core"), "--tag", $Image, $Root)

Write-Host "[2/8] Checking pinned executables"
Invoke-CureNgs @("versions") | Set-Content -Encoding utf8 (Join-Path $Output "versions.json")
Invoke-CureNgs @("doctor", "--profile", "core") |
    Set-Content -Encoding utf8 (Join-Path $Output "doctor.json")
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "doctor.json") -Pattern '"status": "READY"')) {
    throw "Core preflight did not report READY"
}

Write-Host "[3/8] Inspecting the public GRCh37 vcf2maf fixture"
Invoke-CureNgs @("inspect-vcf", "/examples/public/vcf2maf/test_b37.vcf", "--assembly", "GRCh37") |
    Set-Content -Encoding utf8 (Join-Path $Output "public-vcf-inspection.json")
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "public-vcf-inspection.json") -Pattern '"record_count": 25')) {
    throw "Unexpected public fixture record count"
}

Write-Host "[4/8] Normalizing a synthetic GRCh37 VCF"
Invoke-CureNgs @(
    "normalize-vcf", "/examples/synthetic/normalize.grch37.vcf",
    "/data/output/normalized.grch37.vcf", "--reference-fasta",
    "/examples/synthetic/tiny.grch37.fa", "--assembly", "GRCh37"
)
$Records = (Get-Content (Join-Path $Output "normalized.grch37.vcf") | Where-Object { -not $_.StartsWith("#") }).Count
if ($Records -ne 4) { throw "Expected four normalized records, observed $Records" }

Write-Host "[5/8] Replaying HGVS conversion and minimal-MAF conversion"
Invoke-CureNgs @(
    "hgvs-table-to-minimal-maf", "/examples/synthetic/hgvs_to_minimal_input.tsv",
    "/data/output/from-hgvs.grch37.maf", "--failed", "/data/output/from-hgvs.failed.tsv",
    "--reference-fasta", "/examples/synthetic/tiny.grch37.fa", "--assembly", "GRCh37",
    "--response-cache", "/examples/synthetic/rest-cache", "--offline-replay"
)
New-Item -ItemType Directory -Force -Path (Join-Path $Output "from-minimal") | Out-Null
Invoke-CureNgs @(
    "minimal-maf-to-vcf", "/examples/synthetic/minimal.grch37.maf",
    "/data/output/from-minimal", "--reference-fasta",
    "/examples/synthetic/tiny.grch37.fa", "--assembly", "GRCh37"
)

Write-Host "[6/8] Testing gene, fusion, and HGVS normalization"
Invoke-CureNgs @("normalize-gene", "P53", "--gtf", "/examples/synthetic/genes.gtf", "--hgnc", "/examples/synthetic/hgnc.tsv") |
    Set-Content -Encoding utf8 (Join-Path $Output "gene.json")
Invoke-CureNgs @("normalize-fusion", "EML4-ALK", "--gtf", "/examples/synthetic/genes.gtf", "--hgnc", "/examples/synthetic/hgnc.tsv") |
    Set-Content -Encoding utf8 (Join-Path $Output "fusion.json")
Invoke-CureNgs @(
    "normalize-hgvs-table", "/examples/synthetic/hgvs_input.csv",
    "/data/output/hgvs.normalized.csv", "--delimiter", "comma"
)

Write-Host "[7/8] Calculating exact cross-route concordance"
New-Item -ItemType Directory -Force -Path (Join-Path $Output "concordance") | Out-Null
Invoke-CureNgs @(
    "compare-maf-routes", "/data/output/concordance",
    "--reference-maf", "/examples/synthetic/concordance_direct.grch37.maf",
    "--query-maf", "/examples/synthetic/concordance_report.grch37.maf",
    "--reference-require-any", "HGVSc", "--reference-fasta",
    "/examples/synthetic/tiny.grch37.fa"
)
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "concordance\concordance_summary.json") -Pattern '"exact_set_agreement_percent": 100.0')) {
    throw "Synthetic concordance did not reach 100%"
}

Write-Host "[8/8] Reviewer demonstration passed"
Write-Host "Results: $Output"
