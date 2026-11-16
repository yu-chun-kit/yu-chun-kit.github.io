[CmdletBinding()]
param([switch]$NoOpen)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Chatblog environment is missing. Run 'uv sync' in $repoRoot first."
}

# CommandDeck owns the service process tree and redirects its logs. Keep Python
# attached to this wrapper so its Stop button can stop this exact instance.
$env:PYTHONUTF8 = '1'
Push-Location -LiteralPath $repoRoot
try {
    $chatblogArgs = @('-u', '-m', 'chatblog', 'gui')
    if ($NoOpen) { $chatblogArgs += '--no-open' }
    & $pythonPath @chatblogArgs
    $chatblogExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $chatblogExitCode
