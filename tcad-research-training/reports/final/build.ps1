param(
    [ValidateSet('all','course-report','research-paper')][string]$Document = 'all',
    [string]$XeLaTeX = 'xelatex',
    [string]$BibTeX = 'bibtex'
)
$ErrorActionPreference = 'Stop'
$reportDirectory = $PSScriptRoot
$repositoryDirectory = [IO.Path]::GetFullPath((Join-Path $reportDirectory '..\..'))
$buildDirectory = Join-Path $repositoryDirectory 'local_runtime\report-final-20261011\build'
$dependencyDirectory = Join-Path $repositoryDirectory 'local_runtime\report-writing-20261010\tex-deps'
New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null
$savedTexInputs = $env:TEXINPUTS
$savedBibInputs = $env:BIBINPUTS
$documents = if ($Document -eq 'all') { @('course-report','research-paper') } else { @($Document) }
Push-Location -LiteralPath $reportDirectory
try {
    $localInputs = ($reportDirectory -replace '\\','/') + '//;'
    if (Test-Path -LiteralPath $dependencyDirectory) {
        $localInputs += ($dependencyDirectory -replace '\\','/') + '//;'
    }
    $env:TEXINPUTS = $localInputs + $savedTexInputs
    $env:BIBINPUTS = ($reportDirectory -replace '\\','/') + ';' + $savedBibInputs
    foreach ($name in $documents) {
        $source = Join-Path $reportDirectory ($name + '.tex')
        $pass = 1
        $consoleLog = Join-Path $buildDirectory "$name-pass-$pass.log"
        & $XeLaTeX --disable-installer -no-shell-escape -interaction=nonstopmode -halt-on-error "-output-directory=$buildDirectory" $source *> $consoleLog
        if ($LASTEXITCODE -ne 0) { throw "XeLaTeX failed: $consoleLog" }
        $bibliographyLog = Join-Path $buildDirectory "$name-bibtex.log"
        & $BibTeX (Join-Path $buildDirectory $name) *> $bibliographyLog
        if ($LASTEXITCODE -ne 0) { throw "BibTeX failed: $bibliographyLog" }
        for ($pass = 2; $pass -le 3; $pass++) {
            $consoleLog = Join-Path $buildDirectory "$name-pass-$pass.log"
            & $XeLaTeX --disable-installer -no-shell-escape -interaction=nonstopmode -halt-on-error "-output-directory=$buildDirectory" $source *> $consoleLog
            if ($LASTEXITCODE -ne 0) { throw "XeLaTeX failed: $consoleLog" }
        }
        Copy-Item -LiteralPath (Join-Path $buildDirectory "$name.pdf") -Destination (Join-Path $reportDirectory "$name.pdf")
        Write-Output (Join-Path $reportDirectory "$name.pdf")
    }
} finally {
    $env:TEXINPUTS = $savedTexInputs
    $env:BIBINPUTS = $savedBibInputs
    Pop-Location
}
