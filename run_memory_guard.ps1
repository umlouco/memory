param(
    [Parameter(Mandatory = $false)]
    [string]$SessionId,

    [Parameter(Mandatory = $false)]
    [string]$TurnId,

    [Parameter(Mandatory = $false)]
    [string]$UserRequest,

    [Parameter(Mandatory = $false)]
    [string]$TranscriptPath,

    [Parameter(Mandatory = $false)]
    [switch]$TranscriptFromStdin,

    [Parameter(Mandatory = $false)]
    [string]$Summary,

    [Parameter(Mandatory = $false)]
    [string]$Outcome,

    [Parameter(Mandatory = $false)]
    [string[]]$Constraints = @(),

    [Parameter(Mandatory = $false)]
    [string[]]$FilesRead = @(),

    [Parameter(Mandatory = $false)]
    [string[]]$FilesChanged = @(),

    [Parameter(Mandatory = $false)]
    [string[]]$KnowledgeSources = @(),

    [Parameter(Mandatory = $false)]
    [string[]]$Decisions = @(),

    [Parameter(Mandatory = $false)]
    [string[]]$OpenQuestions = @(),

    [Parameter(Mandatory = $false)]
    [string]$QueryMemory,

    [Parameter(Mandatory = $false)]
    [string]$RecallSession,

    [Parameter(Mandatory = $false)]
    [switch]$RequireRecallFirst,

    [Parameter(Mandatory = $false)]
    [switch]$AllowEmptyRecall,

    [Parameter(Mandatory = $false)]
    [int]$RecallLimit = 3,

    [Parameter(Mandatory = $false)]
    [string[]]$Run = @(),

    [Parameter(Mandatory = $false)]
    [string]$RunCommand
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
Set-Location $repoRoot

if (-not $SessionId) {
    if ($env:COPILOT_SESSION_ID) {
        $SessionId = $env:COPILOT_SESSION_ID
    } else {
        $SessionId = "session-$([DateTimeOffset]::UtcNow.ToUnixTimeSeconds())"
    }
}

if (-not $TurnId) {
    $TurnId = "turn-$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())"
}

if (-not $UserRequest -and -not $TranscriptPath -and -not $TranscriptFromStdin) {
    throw "Provide -UserRequest, -TranscriptPath, or -TranscriptFromStdin."
}

$payloadDir = Join-Path $repoRoot "storage\app\memory-payloads"
New-Item -ItemType Directory -Force -Path $payloadDir | Out-Null
$payloadPath = Join-Path $payloadDir "$SessionId-$TurnId.json"
$transcriptStoreDir = Join-Path $repoRoot "storage\app\memory-transcripts"
New-Item -ItemType Directory -Force -Path $transcriptStoreDir | Out-Null
$transcriptStorePath = Join-Path $transcriptStoreDir "$SessionId-$TurnId.txt"

$buildArgs = @(
    "build_turn_payload.py",
    "--session-id", $SessionId,
    "--turn-id", $TurnId,
    "--output", $payloadPath
)

if ($UserRequest) { $buildArgs += @("--user-request", $UserRequest) }
if ($Summary) { $buildArgs += @("--summary", $Summary) }
if ($Outcome) { $buildArgs += @("--outcome", $Outcome) }
foreach ($item in $Constraints) { $buildArgs += @("--constraint", $item) }
foreach ($item in $FilesRead) { $buildArgs += @("--file-read", $item) }
foreach ($item in $FilesChanged) { $buildArgs += @("--file-changed", $item) }
foreach ($item in $KnowledgeSources) { $buildArgs += @("--knowledge-source", $item) }
foreach ($item in $Decisions) { $buildArgs += @("--decision", $item) }
foreach ($item in $OpenQuestions) { $buildArgs += @("--open-question", $item) }

if ($TranscriptFromStdin) {
    $stdinText = [Console]::In.ReadToEnd()
    $stdinText | Set-Content -Path $transcriptStorePath -Encoding UTF8
    $buildArgs += @("--transcript-path", $transcriptStorePath)
    python @buildArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    if ($TranscriptPath) {
        Copy-Item -Path $TranscriptPath -Destination $transcriptStorePath -Force
        $buildArgs += @("--transcript-path", $transcriptStorePath)
    }
    python @buildArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if ($QueryMemory) {
    $recallArgs = @("recall_turn_context.py", "--query", $QueryMemory, "--limit", "$RecallLimit")
    if ($RecallSession) {
        $recallArgs += @("--session", $RecallSession)
    }
    python @recallArgs
}

$command = @()
if ($RequireRecallFirst) {
    if (-not $QueryMemory) {
        throw "-RequireRecallFirst requires -QueryMemory."
    }
    $command += @("python", "enforce_memory_recall.py", "--query", $QueryMemory, "--limit", "$RecallLimit")
    if ($RecallSession) {
        $command += @("--session", $RecallSession)
    }
    if ($AllowEmptyRecall) {
        $command += "--allow-empty"
    }
    if ($RunCommand) {
        $command += "--run"
        $command += "powershell"
        $command += "-Command"
        $command += $RunCommand
    } elseif ($Run.Count -gt 0) {
        $command += "--run"
        $command += $Run
    }
} else {
    $command += @("python", "enforce_memory_write.py", "--input", $payloadPath)
    if ($RunCommand) {
        $command += "--run"
        $command += "powershell"
        $command += "-Command"
        $command += $RunCommand
    } elseif ($Run.Count -gt 0) {
        $command += "--run"
        $command += $Run
    }
}

& $command[0] @($command[1..($command.Count - 1)])
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python enforce_memory_write.py --input $payloadPath
exit $LASTEXITCODE
