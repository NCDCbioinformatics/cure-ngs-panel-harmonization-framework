[CmdletBinding()]
param(
    [string]$Engine = $env:CONTAINER_ENGINE,
    [string]$Image = $(if ($env:CURE_NGS_IMAGE) { $env:CURE_NGS_IMAGE } else { "ghcr.io/ncdcbioinformatics/cure-ngs-harmonizer:0.2.3-core" })
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

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
    throw "Docker or Podman is required."
}

Write-Host "CURE-NGS beginner tutorial"
Write-Host "Container engine: $Engine"
Write-Host "Image: $Image"

if ($env:CURE_NGS_SKIP_PULL -ne "1") {
    & $Engine pull $Image
    if ($LASTEXITCODE -ne 0) {
        throw "$Engine could not pull $Image"
    }
}

$env:CONTAINER_ENGINE = $Engine
$env:CURE_NGS_IMAGE = $Image
$env:CURE_NGS_SKIP_BUILD = "1"
$env:CURE_NGS_OUTPUT_ROOT = Join-Path $Root "tutorial-output"
$env:CURE_NGS_COMPLETION_MESSAGE = "Beginner six-component tutorial passed"

& (Join-Path $PSScriptRoot "run_reviewer_demo.ps1") -Engine $Engine -Image $Image

Write-Host ""
Write-Host "Next: read docs/BEGINNER_TUTORIAL.md to understand each command and output."
Write-Host "The exported original inputs and reference outputs are inside component-test-data/."
Write-Host "The optional full-annotation section explains the external GRCh37/VEP data."
