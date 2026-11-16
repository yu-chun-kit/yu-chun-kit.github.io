[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'
$cliPath = Join-Path $repoRoot '.venv\Scripts\chatblog.exe'
$listeners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)

if (-not $listeners.Count) {
    Write-Output 'Chatblog is already stopped (port 8765 is free).'
    exit 0
}

foreach ($processId in ($listeners.OwningProcess | Select-Object -Unique)) {
    $server = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
    if (-not $server) { continue }
    $command = $server.CommandLine.Replace('/', '\')
    $hasPythonPath = $command.IndexOf($pythonPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
    $hasCliPath = $command.IndexOf($cliPath, [StringComparison]::OrdinalIgnoreCase) -ge 0
    $isStudio = $command -match '(?i)(?:-m\s+chatblog\s+(?:gui|studio)\b|chatblog\.studio.*\bserve\b)' -or
        ($hasCliPath -and $command -match '(?i)\b(?:gui|studio)\b')
    if ((-not ($hasPythonPath -or $hasCliPath)) -or (-not $isStudio)) {
        throw "Port 8765 is owned by another application (PID $processId); nothing was stopped."
    }
    if ($PSCmdlet.ShouldProcess("Chatblog Studio PID $processId on port 8765", 'Stop')) {
        Stop-Process -Id $processId -Force
        Write-Output "Stopped Chatblog Studio (PID $processId)."
    }
}
