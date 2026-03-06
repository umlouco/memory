<#
.SYNOPSIS
    Set up chat-memory for a VS Code workspace.

.DESCRIPTION
    Creates a Python venv, installs dependencies, writes Copilot hooks into
    the target workspace's .github/hooks/hooks.json, adds MCP server settings
    into .vscode/settings.json, and verifies the LM Studio embedding endpoint
    is reachable.

.PARAMETER TargetWorkspace
    Path to the VS Code workspace folder to wire hooks into.
    If omitted you will be prompted.

.PARAMETER SkipVenv
    Skip venv creation (use if you already have one).

.PARAMETER SkipHooks
    Skip writing Copilot hook configuration and MCP settings.

.EXAMPLE
    .\setup.ps1 -TargetWorkspace D:\git\my-project
#>
param(
    [Parameter(Mandatory = $false)]
    [string]$TargetWorkspace,

    [switch]$SkipVenv,
    [switch]$SkipHooks
)

$ErrorActionPreference = 'Stop'
$chatMemoryDir = $PSScriptRoot

function ConvertTo-HashtableRecursive {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)

    if ($null -eq $InputObject) {
        return $null
    }

    if ($InputObject -is [hashtable]) {
        $out = @{}
        foreach ($key in $InputObject.Keys) {
            $out[$key] = ConvertTo-HashtableRecursive $InputObject[$key]
        }
        return $out
    }

    if ($InputObject -is [System.Collections.IDictionary]) {
        $out = @{}
        foreach ($key in $InputObject.Keys) {
            $out[$key] = ConvertTo-HashtableRecursive $InputObject[$key]
        }
        return $out
    }

    if ($InputObject -is [System.Management.Automation.PSCustomObject]) {
        $out = @{}
        foreach ($prop in $InputObject.PSObject.Properties) {
            $out[$prop.Name] = ConvertTo-HashtableRecursive $prop.Value
        }
        return $out
    }

    if (($InputObject -is [System.Collections.IEnumerable]) -and ($InputObject -isnot [string])) {
        $items = @()
        foreach ($item in $InputObject) {
            $items += ,(ConvertTo-HashtableRecursive $item)
        }
        return $items
    }

    return $InputObject
}

if (-not $TargetWorkspace) {
    $TargetWorkspace = Read-Host "Enter the path to the VS Code workspace to wire hooks into"
}
$TargetWorkspace = (Resolve-Path $TargetWorkspace).Path

Write-Host "`n=== Chat Memory Setup ===" -ForegroundColor Cyan
Write-Host "Chat-memory dir : $chatMemoryDir"
Write-Host "Target workspace: $TargetWorkspace`n"

# 1. Python venv
$venvDir = Join-Path $chatMemoryDir ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"

if (-not $SkipVenv) {
    if (-not (Test-Path $venvDir)) {
        Write-Host "[1/4] Creating Python venv..." -ForegroundColor Yellow
        python -m venv $venvDir
    } else {
        Write-Host "[1/4] Venv already exists, skipping creation." -ForegroundColor Green
    }

    Write-Host "[2/4] Installing dependencies..." -ForegroundColor Yellow
    & $pythonExe -m pip install --upgrade pip --quiet
    & $pythonExe -m pip install -r (Join-Path $chatMemoryDir "requirements.txt") --quiet
    Write-Host "       Done." -ForegroundColor Green
} else {
    Write-Host "[1/4] Skipping venv creation (--SkipVenv)." -ForegroundColor DarkGray
    Write-Host "[2/4] Skipping dependency install (--SkipVenv)." -ForegroundColor DarkGray
}

# 2. Copilot hooks + MCP settings
if (-not $SkipHooks) {
    Write-Host "[3/4] Configuring Copilot hooks + MCP settings..." -ForegroundColor Yellow

    $vscodeDir = Join-Path $TargetWorkspace ".vscode"
    if (-not (Test-Path $vscodeDir)) {
        New-Item -ItemType Directory -Path $vscodeDir -Force | Out-Null
    }

    $settingsPath = Join-Path $vscodeDir "settings.json"
    $settings = @{}
    if (Test-Path $settingsPath) {
        $raw = Get-Content $settingsPath -Raw -ErrorAction SilentlyContinue
        if ($raw) {
            $cleaned = ($raw -split "`n" | ForEach-Object {
                $_ -replace '^\s*//.*', ''
            }) -join "`n"
            try {
                $parsed = $cleaned | ConvertFrom-Json
                $settings = ConvertTo-HashtableRecursive $parsed
            } catch {
                $settings = @{}
            }
        }
    }

    $hookDir = $chatMemoryDir.Replace('\', '/')

    $hooksObject = @{
        hooks = @{
            UserPromptSubmit = @(
                @{
                    type = "command"
                    command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_get_context.py"
                },
                @{
                    type = "command"
                    command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_log_prompt.py"
                }
            )
            Stop = @(
                @{
                    type = "command"
                    command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_on_stop.py"
                }
            )
            SubagentStop = @(
                @{
                    type = "command"
                    command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_on_subagent_stop.py"
                }
            )
            PreCompact = @(
                @{
                    type = "command"
                    command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_on_stop.py"
                }
            )
        }
    }

    $hooksJson = $hooksObject | ConvertTo-Json -Depth 10

    $hooksDir = Join-Path $TargetWorkspace ".github\hooks"
    if (-not (Test-Path $hooksDir)) {
        New-Item -ItemType Directory -Path $hooksDir -Force | Out-Null
    }
    $hooksPath = Join-Path $hooksDir "hooks.json"
    Set-Content -Path $hooksPath -Value $hooksJson -Encoding UTF8
    Write-Host "       Wrote hooks to $hooksPath" -ForegroundColor Green

    # Optional compatibility path requested by some local workflows.
    $hookDirLegacy = Join-Path $TargetWorkspace ".github\hook"
    if (-not (Test-Path $hookDirLegacy)) {
        New-Item -ItemType Directory -Path $hookDirLegacy -Force | Out-Null
    }
    $hooksPathLegacy = Join-Path $hookDirLegacy "hooks.json"
    Set-Content -Path $hooksPathLegacy -Value $hooksJson -Encoding UTF8
    Write-Host "       Wrote hooks to $hooksPathLegacy" -ForegroundColor Green

    $settings["github.copilot.chat.hooks"] = @{
        userPromptSubmit = @(
            @{
                command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_get_context.py"
            },
            @{
                command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_log_prompt.py"
            }
        )
        stop = @(
            @{
                command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_on_stop.py"
            }
        )
        subagentStop = @(
            @{
                command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_on_subagent_stop.py"
            }
        )
        preCompact = @(
            @{
                command = "$hookDir/.venv/Scripts/python.exe $hookDir/hook_on_stop.py"
            }
        )
    }
    Write-Host "       Wrote VS Code hooks to $settingsPath (github.copilot.chat.hooks)" -ForegroundColor Green

    if (-not $settings.ContainsKey("mcp") -or $null -eq $settings["mcp"]) {
        $settings["mcp"] = @{}
    } else {
        $settings["mcp"] = ConvertTo-HashtableRecursive $settings["mcp"]
    }

    if (-not $settings["mcp"].ContainsKey("servers") -or $null -eq $settings["mcp"]["servers"]) {
        $settings["mcp"]["servers"] = @{}
    } else {
        $settings["mcp"]["servers"] = ConvertTo-HashtableRecursive $settings["mcp"]["servers"]
    }

    $settings["mcp"]["servers"]["memory"] = @{
        type = "stdio"
        command = "npx"
        args = @("-y", "@modelcontextprotocol/server-memory")
    }

    $settingsJson = $settings | ConvertTo-Json -Depth 10
    Set-Content -Path $settingsPath -Value $settingsJson -Encoding UTF8
    Write-Host "       Wrote MCP settings to $settingsPath" -ForegroundColor Green
} else {
    Write-Host "[3/4] Skipping hook and MCP configuration (--SkipHooks)." -ForegroundColor DarkGray
}

# 3. Verify LM Studio
Write-Host "[4/4] Verifying LM Studio embedding endpoint..." -ForegroundColor Yellow
try {
    $probeOutput = & $pythonExe (Join-Path $chatMemoryDir "inspect_embedding_runtime.py") 2>&1
    $probe = $probeOutput | ConvertFrom-Json
    if ($probe.probe_success -eq $true) {
        Write-Host "       LM Studio OK  model=$($probe.model_name)  dims=$($probe.embedding_dimensions)" -ForegroundColor Green
    } else {
        Write-Host "       WARNING: LM Studio probe failed: $($probe.probe_error)" -ForegroundColor Red
        Write-Host "       Make sure LM Studio is running on localhost:1234 with qwen3-embedding-0.6b loaded." -ForegroundColor Red
    }
} catch {
    Write-Host "       WARNING: Could not reach LM Studio. Start it before using memory." -ForegroundColor Red
}

Write-Host "`n=== Setup complete ===" -ForegroundColor Cyan
Write-Host "Next steps:"
Write-Host "  1. Make sure LM Studio is running with qwen3-embedding-0.6b"
Write-Host "  2. Open your workspace in VS Code - hooks are active automatically"
Write-Host "  3. (Optional) Rebuild the memory store:"
Write-Host "     powershell -ExecutionPolicy Bypass -File $chatMemoryDir\rebuild_memory_store.ps1"
Write-Host ""
