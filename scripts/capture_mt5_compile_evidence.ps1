<#
.SYNOPSIS
Compile the exact SignalGate EA with MetaEditor and write a candidate-bound evidence receipt.

.DESCRIPTION
This script is intentionally evidence-oriented:
- the supplied candidate SHA must equal the checked-out Git HEAD;
- the EA source SHA-256 is recorded before compilation;
- MetaEditor is invoked with /compile and /log;
- the generated compiler log must contain the final result line;
- PASS requires exactly 0 errors and 0 warnings;
- MetaEditor and optional MetaTrader terminal file versions are recorded;
- the source file and raw compile log are copied into a timestamped evidence directory.

It does not run trades and does not enable real-money mode.
#>

[CmdletBinding()]
param(
    [string]$MetaEditorPath = "",
    [string]$Mql5Root = "",
    [string]$TerminalPath = "",
    [string]$EAPath = "",
    [string]$CandidateSha = "",
    [string]$EvidenceRoot = "",
    [switch]$AllowDirtyWorktree
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-SingleFile {
    param(
        [string]$ExplicitPath,
        [string]$FileName,
        [string[]]$Roots
    )

    if ($ExplicitPath) {
        $resolved = Resolve-Path -LiteralPath $ExplicitPath -ErrorAction Stop
        return $resolved.Path
    }

    $matches = @()
    foreach ($root in $Roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $matches += Get-ChildItem -LiteralPath $root -Filter $FileName -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName
    }
    $matches = @($matches | Sort-Object -Unique)

    if ($matches.Count -eq 1) {
        return $matches[0]
    }
    if ($matches.Count -eq 0) {
        throw "Could not find $FileName automatically. Pass the path explicitly."
    }

    $joined = $matches -join [Environment]::NewLine
    throw "Found multiple $FileName candidates. Pass the exact path explicitly:$([Environment]::NewLine)$joined"
}

function Resolve-Mql5Root {
    param([string]$ExplicitPath)

    if ($ExplicitPath) {
        $resolved = Resolve-Path -LiteralPath $ExplicitPath -ErrorAction Stop
        $tradeHeader = Join-Path $resolved.Path "Include\Trade\Trade.mqh"
        if (-not (Test-Path -LiteralPath $tradeHeader)) {
            throw "MQL5 root does not contain Include\Trade\Trade.mqh: $($resolved.Path)"
        }
        return $resolved.Path
    }

    $terminalRoot = Join-Path $env:APPDATA "MetaQuotes\Terminal"
    if (-not (Test-Path -LiteralPath $terminalRoot)) {
        throw "Could not locate the MetaQuotes terminal data root. Pass -Mql5Root explicitly."
    }

    $candidates = @(
        Get-ChildItem -LiteralPath $terminalRoot -Directory -ErrorAction SilentlyContinue |
            ForEach-Object {
                $mql5 = Join-Path $_.FullName "MQL5"
                $tradeHeader = Join-Path $mql5 "Include\Trade\Trade.mqh"
                if (Test-Path -LiteralPath $tradeHeader) { $mql5 }
            } |
            Sort-Object -Unique
    )

    if ($candidates.Count -eq 1) {
        return $candidates[0]
    }
    if ($candidates.Count -eq 0) {
        throw "No MQL5 data directory with the standard Trade library was found. Pass -Mql5Root explicitly."
    }

    $joined = $candidates -join [Environment]::NewLine
    throw "Multiple MQL5 data directories were found. Pass the exact -Mql5Root to avoid compiling against the wrong terminal:$([Environment]::NewLine)$joined"
}

function Read-CompileLog {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "MetaEditor did not create the expected compile log: $Path"
    }

    $text = Get-Content -LiteralPath $Path -Raw
    $matches = [regex]::Matches(
        $text,
        '(?im)result\s+(\d+)\s+errors?,\s+(\d+)\s+warnings?'
    )
    if ($matches.Count -lt 1) {
        throw "Compile log does not contain a final MetaEditor result line."
    }

    $last = $matches[$matches.Count - 1]
    return [pscustomobject]@{
        Errors   = [int]$last.Groups[1].Value
        Warnings = [int]$last.Groups[2].Value
        Text     = $text
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $EAPath) {
    $EAPath = Join-Path $repoRoot "mt5_ea\SignalGateEA.mq5"
}
$EAPath = (Resolve-Path -LiteralPath $EAPath -ErrorAction Stop).Path

if (-not $EvidenceRoot) {
    $EvidenceRoot = Join-Path $repoRoot "artifacts\mt5-acceptance"
}

$head = (& git -C $repoRoot rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') {
    throw "Could not resolve the repository HEAD commit."
}

if (-not $CandidateSha) {
    $CandidateSha = $head
}
$CandidateSha = $CandidateSha.Trim().ToLowerInvariant()
if ($CandidateSha -notmatch '^[0-9a-f]{40}$') {
    throw "CandidateSha must be an exact 40-character Git SHA."
}
if ($CandidateSha -ne $head) {
    throw "CandidateSha $CandidateSha does not match checked-out HEAD $head."
}

$dirty = (& git -C $repoRoot status --porcelain)
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect Git worktree status."
}
if ($dirty -and -not $AllowDirtyWorktree) {
    throw "Working tree is dirty. Commit/stash changes or pass -AllowDirtyWorktree explicitly. A normal acceptance receipt must use the exact candidate tree."
}

$programRoots = @(
    $env:ProgramFiles,
    [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
) | Where-Object { $_ }

$MetaEditorPath = Resolve-SingleFile -ExplicitPath $MetaEditorPath -FileName "metaeditor64.exe" -Roots $programRoots
$Mql5Root = Resolve-Mql5Root -ExplicitPath $Mql5Root

if (-not $TerminalPath) {
    $siblingTerminal = Join-Path (Split-Path -Parent $MetaEditorPath) "terminal64.exe"
    if (Test-Path -LiteralPath $siblingTerminal) {
        $TerminalPath = $siblingTerminal
    }
}
if ($TerminalPath) {
    $TerminalPath = (Resolve-Path -LiteralPath $TerminalPath -ErrorAction Stop).Path
}

$sourceHash = (Get-FileHash -LiteralPath $EAPath -Algorithm SHA256).Hash.ToLowerInvariant()
$metaEditorVersion = (Get-Item -LiteralPath $MetaEditorPath).VersionInfo.FileVersion
$terminalVersion = $null
if ($TerminalPath) {
    $terminalVersion = (Get-Item -LiteralPath $TerminalPath).VersionInfo.FileVersion
}

$compileLog = [System.IO.Path]::ChangeExtension($EAPath, ".log")
if (Test-Path -LiteralPath $compileLog) {
    Remove-Item -LiteralPath $compileLog -Force
}

$arguments = @(
    ('/compile:"{0}"' -f $EAPath),
    ('/include:"{0}"' -f $Mql5Root),
    '/log'
)

$startedUtc = [DateTime]::UtcNow
$process = Start-Process -FilePath $MetaEditorPath -ArgumentList $arguments -Wait -PassThru -NoNewWindow
$completedUtc = [DateTime]::UtcNow

$result = Read-CompileLog -Path $compileLog
$pass = ($result.Errors -eq 0 -and $result.Warnings -eq 0)

$stamp = $startedUtc.ToString("yyyyMMddTHHmmssZ")
$evidenceDir = Join-Path $EvidenceRoot ("{0}-MT5-COMPILE-{1}" -f $stamp, $CandidateSha.Substring(0, 12))
New-Item -ItemType Directory -Path $evidenceDir -Force | Out-Null

$sourceCopy = Join-Path $evidenceDir "SignalGateEA.mq5"
$logCopy = Join-Path $evidenceDir "SignalGateEA.log"
Copy-Item -LiteralPath $EAPath -Destination $sourceCopy -Force
Copy-Item -LiteralPath $compileLog -Destination $logCopy -Force

$receipt = [ordered]@{
    schema                  = "signalgate-mt5-compile-receipt-v1"
    generated_at_utc        = $completedUtc.ToString("o")
    started_at_utc          = $startedUtc.ToString("o")
    candidate_sha           = $CandidateSha
    repository_head         = $head
    working_tree_clean      = (-not [bool]$dirty)
    ea_source_path          = $EAPath
    ea_source_sha256        = $sourceHash
    metaeditor_path         = $MetaEditorPath
    metaeditor_file_version = $metaEditorVersion
    mql5_root               = $Mql5Root
    terminal_path           = $TerminalPath
    terminal_file_version   = $terminalVersion
    compiler_process_exit   = $process.ExitCode
    compile_errors          = $result.Errors
    compile_warnings        = $result.Warnings
    result                  = $(if ($pass) { "PASS" } else { "FAIL" })
    source_copy             = "SignalGateEA.mq5"
    compile_log             = "SignalGateEA.log"
}

$jsonPath = Join-Path $evidenceDir "receipt.json"
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$markdown = @"
# SignalGate MT5 Compile Receipt

Result: **$($receipt.result)**
Candidate SHA: $CandidateSha
Repository HEAD: $head
Working tree clean: $($receipt.working_tree_clean)
EA SHA-256: $sourceHash
MetaEditor version: $metaEditorVersion
MetaTrader terminal version: $terminalVersion
Compile errors: **$($result.Errors)**
Compile warnings: **$($result.Warnings)**
Compiler process exit code: $($process.ExitCode)
Started UTC: $($startedUtc.ToString("o"))
Completed UTC: $($completedUtc.ToString("o"))

Raw evidence:
- SignalGateEA.mq5
- SignalGateEA.log
- receipt.json

This receipt proves compilation of the recorded source/candidate only. It does not prove demo execution scenarios, security clearance, regulatory status, profitability, or real-money readiness.
"@
$markdown | Set-Content -LiteralPath (Join-Path $evidenceDir "receipt.md") -Encoding UTF8

Write-Host ""
Write-Host "SignalGate MT5 compile evidence"
Write-Host "  Candidate:  $CandidateSha"
Write-Host "  EA SHA256:  $sourceHash"
Write-Host "  MetaEditor: $metaEditorVersion"
Write-Host "  Errors:     $($result.Errors)"
Write-Host "  Warnings:   $($result.Warnings)"
Write-Host "  Result:     $($receipt.result)"
Write-Host "  Evidence:   $evidenceDir"

if (-not $pass) {
    exit 2
}
exit 0
