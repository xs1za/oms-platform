$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..")
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Workspace virtualenv was not found at '$python'. Create it and install service dependencies before running integration tests."
}

if ($args.Count -gt 0) {
    & $python -m unittest @args
} else {
    & $python -m unittest discover -s (Join-Path $repoRoot "platform\tests\integration")
}
