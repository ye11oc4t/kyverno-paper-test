$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot)
$toolDir = Join-Path $repoRoot 'work/tools/kyverno-v1.19.1'
$archive = Join-Path $toolDir 'kyverno-cli_v1.19.1_windows_x86_64.zip'
$expectedHash = 'fe329f8ec5cfb19d3776d6a9e568d9857e3bf2be6ed82c6feb12d4fa73b626b8'
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64' -or -not $IsWindows) {
    throw 'This installer requires Windows x64 and PowerShell 7.'
}
New-Item -ItemType Directory -Path $toolDir -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -Uri 'https://github.com/kyverno/kyverno/releases/download/v1.19.1/kyverno-cli_v1.19.1_windows_x86_64.zip' -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'Kyverno release archive SHA256 mismatch.'
}
Expand-Archive -LiteralPath $archive -DestinationPath $toolDir -Force
& (Join-Path $toolDir 'kyverno.exe') version
if ($LASTEXITCODE -ne 0) { throw 'Kyverno version check failed.' }
