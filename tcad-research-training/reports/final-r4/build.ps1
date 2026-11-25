param(
    [ValidateSet('all','course-report','research-paper')][string]$Document = 'all',
    [string]$BuildTag = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'),
    [string]$XeLaTeX = 'C:\Program Files\MiKTeX\miktex\bin\x64\xelatex.exe',
    [string]$BibTeX = 'C:\Program Files\MiKTeX\miktex\bin\x64\bibtex.exe'
)
$ErrorActionPreference = 'Stop'
if ($BuildTag -notmatch '^[a-zA-Z0-9-]+$') { throw 'BuildTag must be a simple directory name' }
$reportDirectory = $PSScriptRoot
$repositoryDirectory = [IO.Path]::GetFullPath((Join-Path $reportDirectory '..\..'))
$buildDirectory = Join-Path $repositoryDirectory ('local_runtime\dram-see-v3\final-r4-document-build\tex-' + $BuildTag)
if (Test-Path -LiteralPath $buildDirectory) { throw 'Build directory already exists; preserve prior logs' }
if (-not (Test-Path -LiteralPath (Join-Path $reportDirectory 'data\snapshot-binding.json'))) { throw 'No accepted snapshot bound' }
New-Item -ItemType Directory -Path $buildDirectory | Out-Null
$dependencyDirectory = Join-Path $repositoryDirectory 'local_runtime\report-writing-20261010\tex-deps'
$savedTexInputs = $env:TEXINPUTS
$savedBibInputs = $env:BIBINPUTS
$receipts = @()
$documents = if ($Document -eq 'all') { @('course-report','research-paper') } else { @($Document) }
Push-Location -LiteralPath $reportDirectory
try {
    $env:TEXINPUTS = ($reportDirectory -replace '\\','/') + '//;' + ($dependencyDirectory -replace '\\','/') + '//;' + $savedTexInputs
    $env:BIBINPUTS = ($reportDirectory -replace '\\','/') + ';' + $savedBibInputs
    foreach ($name in $documents) {
        $source = Join-Path $reportDirectory ($name + '.tex')
        foreach ($pass in 1..4) {
            $log = Join-Path $buildDirectory "$name-pass-$pass.log"
            $started = (Get-Date).ToUniversalTime().ToString('o')
            if ($pass -eq 2) {
                & $BibTeX (Join-Path $buildDirectory $name) *> $log
                $command = @($BibTeX,(Join-Path $buildDirectory $name))
            } else {
                & $XeLaTeX --disable-installer -no-shell-escape -interaction=nonstopmode -halt-on-error "-output-directory=$buildDirectory" $source *> $log
                $command = @($XeLaTeX,'--disable-installer','-no-shell-escape','-interaction=nonstopmode','-halt-on-error',"-output-directory=$buildDirectory",$source)
            }
            $code = $LASTEXITCODE
            $receipts += [pscustomobject]@{ argv=$command; started_utc=$started; finished_utc=(Get-Date).ToUniversalTime().ToString('o'); exit_code=$code; log=$log }
            $receipts | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $buildDirectory 'commands.json') -Encoding utf8
            if ($code -ne 0) { throw "Compilation failed; preserve log $log" }
        }
    }
    foreach ($name in $documents) {
        Copy-Item -LiteralPath (Join-Path $buildDirectory "$name.pdf") -Destination (Join-Path $reportDirectory "$name.pdf")
    }
    Write-Output $buildDirectory
} finally {
    $env:TEXINPUTS = $savedTexInputs
    $env:BIBINPUTS = $savedBibInputs
    Pop-Location
}
