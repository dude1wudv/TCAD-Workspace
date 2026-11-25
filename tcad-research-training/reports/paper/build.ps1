param([string]$XeLaTeX = 'xelatex')
$ErrorActionPreference = 'Stop'
$paperDir = $PSScriptRoot
$repoRoot = [IO.Path]::GetFullPath((Join-Path $paperDir '..\..'))
$buildDir = Join-Path $repoRoot 'local_runtime\report-writing-20261010\build'
$dependencyDir = Join-Path $repoRoot 'local_runtime\report-writing-20261010\tex-deps'
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
$oldTexInputs = $env:TEXINPUTS
try {
    if (Test-Path -LiteralPath $dependencyDir) {
        $env:TEXINPUTS = ($dependencyDir -replace '\\','/') + '//;' + $oldTexInputs
    }
    for ($pass = 1; $pass -le 2; $pass++) {
        $consoleLog = Join-Path $buildDir "export-pass-$pass.log"
        & $XeLaTeX --disable-installer -no-shell-escape -interaction=nonstopmode -halt-on-error "-output-directory=$buildDir" (Join-Path $paperDir 'report.tex') *> $consoleLog
        if ($LASTEXITCODE -ne 0) {
            throw "XeLaTeX failed on pass $pass. See $consoleLog"
        }
    }
    Copy-Item -LiteralPath (Join-Path $buildDir 'report.pdf') -Destination (Join-Path $paperDir 'report.pdf')
    Write-Output (Join-Path $paperDir 'report.pdf')
} finally {
    $env:TEXINPUTS = $oldTexInputs
}
