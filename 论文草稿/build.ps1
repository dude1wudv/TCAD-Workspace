param(
    [string]$XeLaTeX = 'xelatex',
    [string]$BibTeX = 'bibtex'
)
$ErrorActionPreference = 'Stop'
$thesisDirectory = $PSScriptRoot
$buildDirectory = Join-Path $thesisDirectory 'build'
New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null
$savedTexInputs = $env:TEXINPUTS
$savedBibInputs = $env:BIBINPUTS
Push-Location -LiteralPath $thesisDirectory
try {
    $localInputs = ($thesisDirectory -replace '\\\\','/') + '//;'
    $env:TEXINPUTS = $localInputs + $savedTexInputs
    $env:BIBINPUTS = ($thesisDirectory -replace '\\\\','/') + ';' + $savedBibInputs
    for ($pass = 1; $pass -le 3; $pass++) {
        $consoleLog = Join-Path $buildDirectory "main-pass-$pass.log"
        & $XeLaTeX --disable-installer -no-shell-escape -interaction=nonstopmode -halt-on-error "-output-directory=$buildDirectory" 'main.tex' *> $consoleLog
        if ($LASTEXITCODE -ne 0) { throw "XeLaTeX failed: $consoleLog" }
        if ($pass -eq 1) {
            $bibliographyLog = Join-Path $buildDirectory 'main-bibtex.log'
            & $BibTeX (Join-Path $buildDirectory 'main') *> $bibliographyLog
            if ($LASTEXITCODE -ne 0) { throw "BibTeX failed: $bibliographyLog" }
        }
    }
    Write-Output (Join-Path $buildDirectory 'main.pdf')
} finally {
    $env:TEXINPUTS = $savedTexInputs
    $env:BIBINPUTS = $savedBibInputs
    Pop-Location
}
