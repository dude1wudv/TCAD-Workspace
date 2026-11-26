[CmdletBinding()]
param(
    [string]$PythonPath,
    [string]$ConfigPath,
    [switch]$Preflight,
    [switch]$Apply,
    [switch]$LoggedOnOnly
)

$ErrorActionPreference = 'Stop'

if ($Preflight -and $Apply) {
    throw 'Preflight and Apply cannot be used together.'
}

function Resolve-LocalFile($Path, $Label) {
    if ($Path -notmatch '^[A-Za-z]:[\\/]' -or $Path -match '[%"\x00-\x1f]') {
        throw "$Label must be an absolute drive path without percent signs, quotation marks, or control characters."
    }
    try {
        $file = Get-Item -LiteralPath $Path -Force
    } catch {
        throw "$Label must point to an existing local file."
    }
    if ($file -isnot [System.IO.FileInfo]) {
        throw "$Label must point to an existing local file."
    }
    $file.FullName
}

function New-CampaignTaskDefinition($Service, $Task, $UserId, $Executable, $Watchdog, $Config) {
    $definition = $Service.NewTask(0)
    $definition.Principal.UserId = $UserId
    $definition.Principal.LogonType = 3
    $definition.Principal.RunLevel = 0
    $definition.Settings.MultipleInstances = 2
    $definition.Settings.WakeToRun = $false
    $definition.Settings.StartWhenAvailable = $true

    if ($Task.Startup) {
        if (-not $LoggedOnOnly) {
            $null = $definition.Triggers.Create(8)
        }
        $logon = $definition.Triggers.Create(9)
        $logon.UserId = $UserId
    }
    $periodic = $definition.Triggers.Create(1)
    $periodic.StartBoundary = '2000-01-01T00:00:00Z'
    $periodic.Repetition.Interval = $Task.Interval

    $action = $definition.Actions.Create(0)
    $action.Path = $Executable
    $action.Arguments = '"{0}" --config "{1}" {2}' -f $Watchdog, $Config, $Task.Flags
    $action.WorkingDirectory = [System.IO.Path]::GetDirectoryName($Watchdog)
    $definition
}

if ($Preflight) {
    if (-not $PythonPath) {
        $PythonPath = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    }
    if (-not $ConfigPath) {
        $ConfigPath = Join-Path $PSScriptRoot 'config.example.json'
    }
} elseif (-not $PythonPath -or -not $ConfigPath) {
    throw 'Specify PythonPath and ConfigPath when previewing or registering tasks.'
}

$python = Resolve-LocalFile $PythonPath 'PythonPath'
if ([System.IO.Path]::GetExtension($python) -ne '.exe') {
    throw 'PythonPath must point to the Python interpreter executable.'
}
$config = Resolve-LocalFile $ConfigPath 'ConfigPath'
$watchdog = Resolve-LocalFile (Join-Path $PSScriptRoot 'watchdog.py') 'watchdog.py'

if ($Preflight) {
    $PSNativeCommandUseErrorActionPreference = $false
    try {
        $helpText = (& $python -B $watchdog --help 2>$null | Out-String)
    } catch {
        throw 'Could not launch Python for watchdog.py help preflight.'
    }
    if ($LASTEXITCODE -ne 0) {
        throw ('watchdog.py help preflight returned exit code {0}.' -f $LASTEXITCODE)
    }
    foreach ($flag in '--config', '--keepalive', '--tick', '--scheduled-pulse') {
        if ($helpText -cnotmatch ('(?m)^[ \t]+{0}(?=\s|,|$)' -f $flag)) {
            throw "watchdog.py help preflight is missing $flag."
        }
    }
}

$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$userId = $identity.User.Value
if ($Apply) {
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $LoggedOnOnly -and -not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'The boot trigger requires an elevated shell under the intended task account. No tasks were changed.'
    }
}

$tasks = @(
    @{Name = 'TCAD-Codex-Watchdog-Keepalive'; Startup = $true; Interval = 'PT10M'; Flags = '--keepalive'}
    @{Name = 'TCAD-Codex-Progress-Pulse'; Startup = $false; Interval = 'PT2H'; Flags = '--tick --scheduled-pulse'}
)

try {
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    if ($Apply) {
        $folder = $service.GetFolder('\')
    }
} catch {
    throw ('Could not connect to Windows Task Scheduler (0x{0:X8}).' -f $_.Exception.HResult)
}

foreach ($task in $tasks) {
    try {
        $task.Definition = New-CampaignTaskDefinition $service $task $userId $python $watchdog $config
        $task.Xml = [xml]$task.Definition.XmlText
    } catch {
        throw ('Could not build {0} (0x{1:X8}).' -f $task.Name, $_.Exception.HResult)
    }
}

if ($Preflight) {
    foreach ($task in $tasks) {
        $xml = $task.Xml
        $isKeepalive = $task.Name -eq 'TCAD-Codex-Watchdog-Keepalive'
        $triggerNames = $xml.Task.Triggers.ChildNodes.LocalName -join ','
            $expectedNames = if (-not $isKeepalive) {
                'TimeTrigger'
            } elseif ($LoggedOnOnly) {
                'LogonTrigger,TimeTrigger'
            } else {
                'BootTrigger,LogonTrigger,TimeTrigger'
            }
        $expectedInterval = if ($isKeepalive) { 'PT10M' } else { 'PT2H' }
        $expectedFlags = if ($isKeepalive) { '--keepalive' } else { '--tick --scheduled-pulse' }
        $expectedArguments = '"{0}" --config "{1}" {2}' -f $watchdog, $config, $expectedFlags
        if ($triggerNames -ne $expectedNames -or
            ($isKeepalive -and $xml.Task.Triggers.LogonTrigger.UserId -ne $userId) -or
            $xml.Task.Triggers.TimeTrigger.Repetition.Interval -ne $expectedInterval -or
            $xml.Task.Triggers.TimeTrigger.Repetition.Duration -or
            $xml.Task.Principals.Principal.UserId -ne $userId -or
            $xml.Task.Principals.Principal.LogonType -ne 'InteractiveToken' -or
            $xml.Task.Principals.Principal.RunLevel -ne 'LeastPrivilege' -or
            $xml.Task.Settings.MultipleInstancesPolicy -ne 'IgnoreNew' -or
            $xml.Task.Settings.WakeToRun -ne 'false' -or
            $xml.Task.Actions.ChildNodes.Count -ne 1 -or
            $xml.Task.Actions.Exec.Command -cne $python -or
            $xml.Task.Actions.Exec.Arguments -cne $expectedArguments -or
            $xml.Task.Actions.Exec.WorkingDirectory -cne [System.IO.Path]::GetDirectoryName($watchdog)) {
            throw ('Task XML preflight did not match the Phase 0 definition for {0}.' -f $task.Name)
        }
    }
    [pscustomobject]@{
        Status = 'Preflight'
        WatchdogHelpExitCode = 0
        TaskXml = 'PASS'
        TaskNames = $tasks.Name
        RegistrationAttempted = $false
    }
    return
}

foreach ($task in $tasks) {
    if ($Apply) {
        try {
            $null = $folder.RegisterTaskDefinition($task.Name, $task.Definition, 6, $userId, $null, 3, $null)
        } catch {
            throw ('Could not register {0} (0x{1:X8}). Earlier successful updates remain in place.' -f $task.Name, $_.Exception.HResult)
        }
    }
    [pscustomobject]@{
        Status = if ($Apply) { 'Registered' } else { 'Preview' }
        TaskName = $task.Name
        Triggers = if (-not $task.Startup) {
            'Every 2 hours'
        } elseif ($LoggedOnOnly) {
            'Current user logon, every 10 minutes'
        } else {
            'Boot, current user logon, every 10 minutes'
        }
        Mode = $task.Flags
        RunsOnlyWhenLoggedOn = $true
    }
}
