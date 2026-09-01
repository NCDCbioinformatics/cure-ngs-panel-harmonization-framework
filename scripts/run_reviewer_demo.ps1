[CmdletBinding()]
param(
    [string]$Engine = $env:CONTAINER_ENGINE,
    [string]$Image = $(if ($env:CURE_NGS_IMAGE) { $env:CURE_NGS_IMAGE } else { "cure-ngs-harmonizer:reviewer-core" })
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunId = "{0}-{1}" -f (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ"), $PID
$OutputRoot = if ($env:CURE_NGS_OUTPUT_ROOT) { $env:CURE_NGS_OUTPUT_ROOT } else { Join-Path $Root "reviewer-output" }
$Output = Join-Path $OutputRoot $RunId
$CompletionMessage = if ($env:CURE_NGS_COMPLETION_MESSAGE) { $env:CURE_NGS_COMPLETION_MESSAGE } else { "Reviewer demonstration passed" }

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
        "--mount", "type=bind,source=$Output,target=/data/output",
        $Image
    ) + $Arguments
    & $Engine @ContainerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "CURE-NGS command exited with code $LASTEXITCODE"
    }
}

if ($env:CURE_NGS_SKIP_BUILD -eq "1") {
    Write-Host "[1/11] Using prebuilt core image $Image"
} else {
    Write-Host "[1/11] Building pinned core image"
    Invoke-Checked @("build", "--file", (Join-Path $Root "docker/Dockerfile.core"), "--tag", $Image, $Root)
}

Write-Host "[2/11] Checking pinned executables"
Invoke-CureNgs @("versions") | Set-Content -Encoding utf8 (Join-Path $Output "versions.json")
Invoke-CureNgs @("doctor", "--profile", "core") |
    Set-Content -Encoding utf8 (Join-Path $Output "doctor.json")
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "doctor.json") -Pattern '"status": "READY"')) {
    throw "Core preflight did not report READY"
}

Write-Host "[3/11] Exporting and verifying the original six-component test bundle"
Invoke-CureNgs @("verify-tutorial-data") |
    Set-Content -Encoding utf8 (Join-Path $Output "component-test-data.verification.json")
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "component-test-data.verification.json") -Pattern '"file_count": 11')) {
    throw "Bundled test-data verification failed"
}
Invoke-CureNgs @("export-tutorial-data", "/data/output/component-test-data") |
    Set-Content -Encoding utf8 (Join-Path $Output "component-test-data.export.json")
Invoke-CureNgs @("export-v1.3.3-example", "/data/output/NGS_VCF") |
    Set-Content -Encoding utf8 (Join-Path $Output "NGS_VCF.reference-export.json")

Write-Host "[4/11] Inspecting the non-empty public GRCh37 VCF and reference MAF"
Invoke-CureNgs @("inspect-vcf", "/opt/cure-ngs/examples/component-tests/inputs/test_b37.vcf", "--assembly", "GRCh37") |
    Set-Content -Encoding utf8 (Join-Path $Output "public-vcf-inspection.json")
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "public-vcf-inspection.json") -Pattern '"record_count": 25')) {
    throw "Unexpected public fixture record count"
}
$VcfRecords = @(Get-Content (Join-Path $Output "component-test-data\inputs\test_b37.vcf") | Where-Object { -not $_.StartsWith("#") }).Count
$MafLines = @(Get-Content (Join-Path $Output "component-test-data\expected\test_b37.maf") | Where-Object { $_ -and -not $_.StartsWith("#") }).Count
if ($VcfRecords -ne 25 -or ($MafLines - 1) -ne 25) {
    throw "The non-empty VCF/MAF pair must contain 25 variants"
}
$PaperVcfRecords = @(Get-Content (Join-Path $Output "NGS_VCF\VCF_ALL\test_b37.vcf") | Where-Object { -not $_.StartsWith("#") }).Count
$PaperMafLines = @(Get-Content (Join-Path $Output "NGS_VCF\VCF_ALL_MAF\test_b37.maf") | Where-Object { $_ -and -not $_.StartsWith("#") }).Count
if ($PaperVcfRecords -ne 25 -or ($PaperMafLines - 1) -ne 25) {
    throw "The paper-layout VCF/MAF pair must contain 25 variants"
}

Write-Host "[5/11] Normalizing a synthetic GRCh37 VCF"
Invoke-CureNgs @(
    "normalize-vcf", "/opt/cure-ngs/examples/synthetic/normalize.grch37.vcf",
    "/data/output/normalized.grch37.vcf", "--reference-fasta",
    "/opt/cure-ngs/examples/synthetic/tiny.grch37.fa", "--assembly", "GRCh37"
)
$Records = @(Get-Content (Join-Path $Output "normalized.grch37.vcf") | Where-Object { -not $_.StartsWith("#") }).Count
if ($Records -ne 4) { throw "Expected four normalized records, observed $Records" }

Write-Host "[6/11] Replaying HGVS conversion without network access"
Invoke-CureNgs @(
    "hgvs-table-to-minimal-maf", "/opt/cure-ngs/examples/synthetic/hgvs_to_minimal_input.tsv",
    "/data/output/from-hgvs.grch37.maf", "--failed", "/data/output/from-hgvs.failed.tsv",
    "--reference-fasta", "/opt/cure-ngs/examples/synthetic/tiny.grch37.fa", "--assembly", "GRCh37",
    "--response-cache", "/opt/cure-ngs/examples/synthetic/rest-cache", "--offline-replay"
)

Write-Host "[7/11] Converting minimal MAF to a reference-valid VCF"
New-Item -ItemType Directory -Force -Path (Join-Path $Output "from-minimal") | Out-Null
Invoke-CureNgs @(
    "minimal-maf-to-vcf", "/opt/cure-ngs/examples/synthetic/minimal.grch37.maf",
    "/data/output/from-minimal", "--reference-fasta",
    "/opt/cure-ngs/examples/synthetic/tiny.grch37.fa", "--assembly", "GRCh37"
)

Write-Host "[8/11] Running original gene, fusion, and HGVS-table examples"
Invoke-CureNgs @("normalize-gene", "C11ORF30", "--gtf", "/opt/cure-ngs/examples/synthetic/genes.gtf", "--hgnc", "/opt/cure-ngs/examples/synthetic/hgnc.tsv") |
    Set-Content -Encoding utf8 (Join-Path $Output "gene.json")
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "gene.json") -Pattern '"matched_symbol": "EMSY"')) {
    throw "C11ORF30 did not resolve to EMSY"
}
Invoke-CureNgs @("normalize-fusion", "ALK-EML4", "--gtf", "/opt/cure-ngs/examples/synthetic/genes.gtf", "--hgnc", "/opt/cure-ngs/examples/synthetic/hgnc.tsv") |
    Set-Content -Encoding utf8 (Join-Path $Output "fusion.json")
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "fusion.json") -Pattern '"normalized": "ALK--EML4"')) {
    throw "ALK-EML4 did not normalize directionally"
}
Invoke-CureNgs @(
    "normalize-hgvs-table", "/opt/cure-ngs/examples/component-tests/inputs/hgvs_to_minimal_maf_test.xlsx",
    "/data/output/hgvs_to_minimal_maf_test.current.normalized.xlsx"
) | Set-Content -Encoding utf8 (Join-Path $Output "hgvs-original-summary.json")
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "hgvs-original-summary.json") -Pattern '"rows": 2625')) {
    throw "The original HGVS workbook did not produce 2,625 rows"
}

Write-Host "[9/11] Calculating exact cross-route concordance"
New-Item -ItemType Directory -Force -Path (Join-Path $Output "concordance") | Out-Null
Invoke-CureNgs @(
    "compare-maf-routes", "/data/output/concordance",
    "--reference-maf", "/opt/cure-ngs/examples/synthetic/concordance_direct.grch37.maf",
    "--query-maf", "/opt/cure-ngs/examples/synthetic/concordance_report.grch37.maf",
    "--reference-require-any", "HGVSc", "--reference-fasta",
    "/opt/cure-ngs/examples/synthetic/tiny.grch37.fa"
)
if (-not (Select-String -Quiet -LiteralPath (Join-Path $Output "concordance\concordance_summary.json") -Pattern '"exact_set_agreement_percent": 100.0')) {
    throw "Synthetic concordance did not reach 100%"
}

Write-Host "[10/11] Executing the V1.3.3 four-directory workspace contract"
$RuntimeRoot = Join-Path $Output "NGS_VCF_RUNTIME_TEST"
$RuntimeInput = Join-Path $RuntimeRoot "VCF_ALL"
New-Item -ItemType Directory -Force -Path $RuntimeInput | Out-Null
Copy-Item -LiteralPath (Join-Path $Root "examples\synthetic\batch-input\empty.grch37.vcf") -Destination $RuntimeInput -Force
Invoke-CureNgs @(
    "batch-vcf-to-maf", "--workspace-root", "/data/output/NGS_VCF_RUNTIME_TEST",
    "--reference-config", "/opt/cure-ngs/examples/synthetic/reference-config.reviewer.json",
    "--jobs", "1"
)
if (-not (Select-String -Quiet -LiteralPath (Join-Path $RuntimeRoot "VCF_ALL_LOG\vcf2maf_batch_summary.json") -Pattern 'NCDC_batch_vcf2maf_V.1.3.3')) {
    throw "Batch test did not report the V1.3.3 workspace layout"
}
if (-not (Select-String -Quiet -LiteralPath (Join-Path $RuntimeRoot "VCF_ALL_LOG\vcf2maf_batch_log.tsv") -Pattern "SUCCESS`tVCF has no variants; created empty MAF header")) {
    throw "V1.3.3 compatibility log was not generated"
}

@(
    "component`toriginal_input_rows`treference_output_rows`tquick_test",
    "panel_VCF_vcf2maf_pipeline`t25`t25`tnon-empty VCF inspected; full MAF included",
    "HGVS_to_minimal_MAF_pipeline`t2625`t2113`toffline synthetic HGVS conversion passed",
    "minimal_MAF_to_annotated_MAF_pipeline`t2113`t2054`tminimal-MAF-to-VCF conversion passed",
    "gene_name_harmonization`t324`t324`tC11ORF30 to EMSY passed",
    "gene_fusion_normalizer`t274`tNA`tALK-EML4 to ALK--EML4 passed",
    "hgvs_normerlizer`t2625`t2625`tfull original XLSX normalization passed"
) | Set-Content -Encoding utf8 (Join-Path $Output "component-test-summary.tsv")

Write-Host "[11/11] $CompletionMessage"
Write-Host "Container /data/output was saved to the local host directory below."
Write-Host "Local results (host): $Output"
Write-Host "Non-empty VCF reference MAF: $(Join-Path $Output 'component-test-data\expected\test_b37.maf')"
Write-Host "Paper/V1.3.3 folder example: $(Join-Path $Output 'NGS_VCF')"
Write-Host "Bundled example VCF: $(Join-Path $Output 'NGS_VCF\VCF_ALL\test_b37.vcf')"
Write-Host "Executed V1.3.3 runtime tree: $RuntimeRoot"
