param(
    [ValidateRange(1, 20)][int]$Repeats = 3,
    [string]$KyvernoPath,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot)
if (-not $KyvernoPath) { $KyvernoPath = Join-Path $repoRoot 'work/tools/kyverno-v1.19.1/kyverno.exe' }
$KyvernoPath = (Resolve-Path -LiteralPath $KyvernoPath).Path
$started = [DateTimeOffset]::UtcNow
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $PSScriptRoot ('results/' + $started.ToString('yyyyMMddTHHmmssZ') + '-' + [Environment]::MachineName)
}
if (Test-Path -LiteralPath $OutputDirectory) { throw 'Use a new output directory to preserve earlier evidence.' }
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$version = (& $KyvernoPath version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $version -notmatch '(?m)^Version: 1\.19\.1\s*$') { throw 'This baseline requires Kyverno 1.19.1.' }
$expected = @(Import-Csv -LiteralPath (Join-Path $PSScriptRoot 'expectations.csv'))
if ($expected.Count -ne 12) { throw 'Expected exactly 12 baseline assertions.' }
$inputFiles = @('expectations.csv', 'run.ps1', 'install-cli.ps1')
foreach ($suite in @('nonroot', 'privileged', 'registry')) {
    foreach ($name in @('policy.yaml', 'resources.yaml', 'kyverno-test.yaml')) { $inputFiles += "$suite/$name" }
}
$inputHashes = @($inputFiles | ForEach-Object {
    [ordered]@{ path = $_; sha256 = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot $_) -Algorithm SHA256).Hash.ToLowerInvariant() }
})
$runs = @()
$assertions = @()
$signatures = @()
Push-Location $repoRoot
try {
    for ($iteration = 1; $iteration -le $Repeats; $iteration++) {
        $stdoutPath = Join-Path $OutputDirectory "run-$iteration.stdout.log"
        $stderrPath = Join-Path $OutputDirectory "run-$iteration.stderr.log"
        $timer = [Diagnostics.Stopwatch]::StartNew()
        & $KyvernoPath test $PSScriptRoot --require-tests --remove-color --detailed-results --output-format json 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
        $timer.Stop()
        $raw = Get-Content -LiteralPath $stdoutPath -Raw
        # Kyverno emits a JSON array per test suite among progress messages.
        $rows = @([regex]::Matches($raw, '(?ms)^\[\r?\n.*?^\]') | ForEach-Object { $_.Value | ConvertFrom-Json })
        $keys = @($rows | ForEach-Object { $_.POLICY + '/' + ($_.RESOURCE -split '/')[-1] })
        $valid = $exitCode -eq 0 -and $rows.Count -eq 12 -and @($keys | Sort-Object -Unique).Count -eq 12
        foreach ($expectation in $expected) {
            $matched = @($rows | Where-Object { $_.POLICY -eq $expectation.policy -and ($_.RESOURCE -split '/')[-1] -eq $expectation.resource })
            if ($matched.Count -ne 1) { $valid = $false; continue }
            $row = $matched[0]
            if ($row.RESULT -ne 'Pass' -or $row.REASON -ne 'Ok') { $valid = $false }
            $assertions += [pscustomobject][ordered]@{
                iteration = $iteration; policy = $expectation.policy; resource = $expectation.resource
                expectedPolicyResult = $expectation.expected; assertionResult = $row.RESULT
                reason = $row.REASON; message = $row.Message
            }
        }
        $signatures += ($rows | Sort-Object POLICY, RESOURCE | Select-Object POLICY, RESOURCE, RESULT, REASON, Message | ConvertTo-Json -Compress)
        $runs += [ordered]@{ iteration = $iteration; exitCode = $exitCode; assertions = $rows.Count; matchedExpectations = $valid; wallTimeMs = [math]::Round($timer.Elapsed.TotalMilliseconds, 2) }
    }
} finally { Pop-Location }
$consistent = @($signatures | Sort-Object -Unique).Count -eq 1
$passed = @($runs | Where-Object { -not $_.matchedExpectations }).Count -eq 0 -and $consistent
$summary = [ordered]@{
    experiment = 'policy-baseline'; status = $(if ($passed) { 'PASS' } else { 'FAIL' })
    startedUtc = $started.ToString('o'); finishedUtc = [DateTimeOffset]::UtcNow.ToString('o')
    machine = [Environment]::MachineName; os = [Environment]::OSVersion.VersionString
    powershell = $PSVersionTable.PSVersion.ToString(); kyvernoVersion = $version
    kyvernoBinarySha256 = (Get-FileHash -LiteralPath $KyvernoPath -Algorithm SHA256).Hash.ToLowerInvariant()
    repeats = $Repeats; casesPerRepeat = 12; identicalAssertionResultsAcrossRepeats = $consistent
    timingMeaning = 'CLI process wall time including startup and file IO; not admission latency or a performance benchmark.'
    command = 'kyverno test experiments/policy-baseline --require-tests --remove-color --detailed-results --output-format json'
    inputs = $inputHashes; runs = $runs
}
$assertions | Export-Csv -LiteralPath (Join-Path $OutputDirectory 'assertions.csv') -NoTypeInformation -Encoding utf8
$summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'summary.json') -Encoding utf8
Write-Output "$($summary.status): $($assertions.Count) assertions; consistent=$consistent; results=$OutputDirectory"
if (-not $passed) { throw 'Baseline failed. Inspect the preserved logs and summary.' }
