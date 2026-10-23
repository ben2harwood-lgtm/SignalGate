# Offline negative/positive checks for the shared compile-evidence gate.
# Only synthetic text and binary fixtures; never invokes MetaEditor, MT5 or a broker.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot "verify_mt5_compile_artifact.ps1")

$tempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("sg-mt5-evidence-gate-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempDir -ErrorAction Stop | Out-Null
try {
    $source = Join-Path $tempDir "SignalGateEA.mq5"
    $binary = Join-Path $tempDir "SignalGateEA.ex5"
    [System.IO.File]::WriteAllText($source, "// synthetic source - no trading")
    $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()

    $cases = @(
        @{ Label = "valid-exit-zero"; Exit = 0; Errors = 0; Warnings = 0; Binary = "nonempty"; SourceHash = $sourceHash; ExpectedPass = $true; Reason = "clean_log_fresh_ex5_source_unchanged" },
        @{ Label = "valid-exit-one"; Exit = 1; Errors = 0; Warnings = 0; Binary = "nonempty"; SourceHash = $sourceHash; ExpectedPass = $true; Reason = "clean_log_fresh_ex5_source_unchanged" },
        @{ Label = "unexpected-exit-two"; Exit = 2; Errors = 0; Warnings = 0; Binary = "nonempty"; SourceHash = $sourceHash; ExpectedPass = $false; Reason = "compiler_unexpected_exit_code" },
        @{ Label = "compile-errors"; Exit = 0; Errors = 1; Warnings = 0; Binary = "nonempty"; SourceHash = $sourceHash; ExpectedPass = $false; Reason = "compiler_diagnostics_not_clean" },
        @{ Label = "compile-warnings"; Exit = 0; Errors = 0; Warnings = 1; Binary = "nonempty"; SourceHash = $sourceHash; ExpectedPass = $false; Reason = "compiler_diagnostics_not_clean" },
        @{ Label = "missing-ex5"; Exit = 0; Errors = 0; Warnings = 0; Binary = "missing"; SourceHash = $sourceHash; ExpectedPass = $false; Reason = "compiled_ex5_missing" },
        @{ Label = "empty-ex5"; Exit = 0; Errors = 0; Warnings = 0; Binary = "empty"; SourceHash = $sourceHash; ExpectedPass = $false; Reason = "compiled_ex5_empty" },
        @{ Label = "mutated-source"; Exit = 0; Errors = 0; Warnings = 0; Binary = "nonempty"; SourceHash = ("0" * 64); ExpectedPass = $false; Reason = "source_mutated_during_compile" },
        @{ Label = "malformed-source-hash"; Exit = 0; Errors = 0; Warnings = 0; Binary = "nonempty"; SourceHash = "bad"; ExpectedPass = $false; Reason = "expected_source_hash_invalid" }
    )
    foreach ($case in $cases) {
        if (Test-Path -LiteralPath $binary) { Remove-Item -LiteralPath $binary -Force }
        if ($case.Binary -eq "nonempty") {
            [System.IO.File]::WriteAllBytes($binary, [byte[]]@(1, 2, 3, 4))
        } elseif ($case.Binary -eq "empty") {
            [System.IO.File]::WriteAllBytes($binary, [byte[]]@())
        }
        $actual = Test-SignalGateCompileEvidence `
            -CompilerExitCode $case.Exit -Errors $case.Errors -Warnings $case.Warnings `
            -SourcePath $source -ExpectedSourceSha256 $case.SourceHash `
            -CompiledBinaryPath $binary
        if ($actual.Passed -ne $case.ExpectedPass -or $actual.Reason -ne $case.Reason) {
            throw ("Case {0}: expected passed={1}/reason={2}, got passed={3}/reason={4}" -f $case.Label, $case.ExpectedPass, $case.Reason, $actual.Passed, $actual.Reason)
        }
        if ($case.ExpectedPass -and ($actual.CompiledEx5SizeBytes -ne 4 -or $actual.CompiledEx5Sha256 -notmatch '^[0-9a-f]{64}$')) {
            throw "Valid case did not produce a 4-byte synthetic artifact fingerprint."
        }
        Write-Host ("PASS {0}" -f $case.Label)
    }
    Write-Host ("MT5 evidence gate: {0}/{0} synthetic offline cases passed" -f $cases.Count)
} finally {
    Remove-Item -LiteralPath $tempDir -Recurse -Force -ErrorAction SilentlyContinue
}
