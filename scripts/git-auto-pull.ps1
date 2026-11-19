[CmdletBinding()]
param(
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Remote = 'origin',
    [string]$Branch = 'main'
)

$ErrorActionPreference = 'Stop'
$logDirectory = Join-Path $RepoRoot 'logs'
$logPath = Join-Path $logDirectory 'git-auto-pull.log'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-Log {
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding utf8
}

function Invoke-Git {
    param([string[]]$Arguments)
    $output = & git @Arguments 2>&1
    $code = $LASTEXITCODE
    foreach ($line in $output) {
        if ($null -ne $line) { Write-Log ([string]$line) }
    }
    return $code
}

$env:GIT_TERMINAL_PROMPT = '0'
$savedHttp = $env:HTTP_PROXY
$savedHttps = $env:HTTPS_PROXY

Push-Location $RepoRoot
try {
    if ((& git rev-parse --is-inside-work-tree 2>$null) -ne 'true') {
        Write-Log 'skip: not a git worktree'
        return
    }

    $dirty = & git status --porcelain
    if ($dirty) {
        Write-Log 'skip: working tree has local changes'
        return
    }

    if (-not $env:HTTPS_PROXY) {
        $env:HTTP_PROXY = 'http://127.0.0.1:7890'
        $env:HTTPS_PROXY = 'http://127.0.0.1:7890'
    }

    $fetchCode = Invoke-Git @('fetch', '--prune', $Remote, $Branch)
    if ($fetchCode -ne 0) {
        Write-Log 'fetch failed with current proxy settings; retrying direct'
        Remove-Item Env:HTTP_PROXY -ErrorAction SilentlyContinue
        Remove-Item Env:HTTPS_PROXY -ErrorAction SilentlyContinue
        $fetchCode = Invoke-Git @('fetch', '--prune', $Remote, $Branch)
    }
    if ($fetchCode -ne 0) {
        Write-Log 'skip: fetch failed'
        return
    }

    $localHead = (& git rev-parse HEAD).Trim()
    $remoteHead = (& git rev-parse "$Remote/$Branch").Trim()
    if ($localHead -eq $remoteHead) {
        return
    }

    & git merge-base --is-ancestor $localHead $remoteHead 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Log 'skip: local branch has commits not present on remote'
        return
    }

    $mergeCode = Invoke-Git @('merge', '--ff-only', "$Remote/$Branch")
    if ($mergeCode -ne 0) {
        Write-Log 'skip: fast-forward merge failed'
        return
    }

    $newHead = (& git rev-parse HEAD).Trim()
    Write-Log "updated $localHead -> $newHead"
}
catch {
    Write-Log "error: $($_.Exception.Message)"
}
finally {
    $env:HTTP_PROXY = $savedHttp
    $env:HTTPS_PROXY = $savedHttps
    Pop-Location
}
