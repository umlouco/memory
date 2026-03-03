param(
    [Parameter(Mandatory = $false)]
    [switch]$PayloadsOnly,

    [Parameter(Mandatory = $false)]
    [switch]$KnowledgeOnly,

    [Parameter(Mandatory = $false)]
    [switch]$TranscriptsOnly,

    [Parameter(Mandatory = $false)]
    [string]$DbPath = ".chroma"
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $repoRoot

$dbFullPath = Join-Path $repoRoot $DbPath
if (Test-Path $dbFullPath) {
    Remove-Item -Recurse -Force $dbFullPath
}

$argsList = @("tools/memory/reindex_memory_store.py", "--db-path", $dbFullPath)
if ($PayloadsOnly) { $argsList += "--payloads-only" }
if ($KnowledgeOnly) { $argsList += "--knowledge-only" }
if ($TranscriptsOnly) { $argsList += "--transcripts-only" }

python @argsList
exit $LASTEXITCODE
