# Shared fail-closed evidence predicate for official and operator MT5 compile receipts.
# This checks source continuity and a nonempty EX5 produced after callers deleted old output.
# It does not establish broker-demo execution, EX5 authenticity or external acceptance.
function Test-SignalGateCompileEvidence {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][int]$CompilerExitCode,
        [Parameter(Mandatory = $true)][int]$Errors,
        [Parameter(Mandatory = $true)][int]$Warnings,
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$ExpectedSourceSha256,
        [Parameter(Mandatory = $true)][string]$CompiledBinaryPath
    )

    $result = [ordered]@{
        Passed               = $false
        Reason               = ""
        SourceSha256After    = $null
        CompiledEx5Sha256    = $null
        CompiledEx5SizeBytes = 0
    }
    if ($CompilerExitCode -ne 0) {
        $result.Reason = "compiler_nonzero_exit"
        return [pscustomobject]$result
    }
    if ($Errors -ne 0 -or $Warnings -ne 0) {
        $result.Reason = "compiler_diagnostics_not_clean"
        return [pscustomobject]$result
    }
    if ($ExpectedSourceSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        $result.Reason = "expected_source_hash_invalid"
        return [pscustomobject]$result
    }
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        $result.Reason = "source_missing_after_compile"
        return [pscustomobject]$result
    }

    $result.SourceSha256After = (Get-FileHash -LiteralPath $SourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($result.SourceSha256After -ne $ExpectedSourceSha256.ToLowerInvariant()) {
        $result.Reason = "source_mutated_during_compile"
        return [pscustomobject]$result
    }
    if (-not (Test-Path -LiteralPath $CompiledBinaryPath -PathType Leaf)) {
        $result.Reason = "compiled_ex5_missing"
        return [pscustomobject]$result
    }
    $binary = Get-Item -LiteralPath $CompiledBinaryPath
    if ($binary.Length -le 0) {
        $result.Reason = "compiled_ex5_empty"
        return [pscustomobject]$result
    }
    $result.CompiledEx5SizeBytes = [int64]$binary.Length
    $result.CompiledEx5Sha256 = (Get-FileHash -LiteralPath $CompiledBinaryPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $result.Passed = $true
    $result.Reason = "clean_log_zero_exit_fresh_ex5_source_unchanged"
    return [pscustomobject]$result
}
