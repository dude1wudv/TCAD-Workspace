param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$outDir = Join-Path $root "build"

if ($Clean -and (Test-Path $outDir)) {
    Remove-Item -Recurse -Force $outDir
}
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

Push-Location $root
try {
    & xelatex -interaction=nonstopmode -halt-on-error -output-directory="$outDir" main.tex
    if ($LASTEXITCODE -ne 0) { throw "First xelatex pass failed ($LASTEXITCODE)" }

    if (Test-Path (Join-Path $outDir "main.aux")) {
        $auxText = Get-Content -Raw (Join-Path $outDir "main.aux")
        if ($auxText -match "\\citation\{") {
            & bibtex (Join-Path $outDir "main")
            if ($LASTEXITCODE -ne 0) { throw "bibtex failed ($LASTEXITCODE)" }
        }
    }

    & xelatex -interaction=nonstopmode -halt-on-error -output-directory="$outDir" main.tex
    if ($LASTEXITCODE -ne 0) { throw "Second xelatex pass failed ($LASTEXITCODE)" }

    & xelatex -interaction=nonstopmode -halt-on-error -output-directory="$outDir" main.tex
    if ($LASTEXITCODE -ne 0) { throw "Third xelatex pass failed ($LASTEXITCODE)" }

    $pdf = Join-Path $outDir "main.pdf"
    if (-not (Test-Path $pdf)) { throw "PDF was not generated: $pdf" }
    Write-Output "BUILD_OK: $pdf ($((Get-Item $pdf).Length) bytes)"
}
finally {
    Pop-Location
}
