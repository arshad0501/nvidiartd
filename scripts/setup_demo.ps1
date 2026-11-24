$target = Join-Path $PSScriptRoot '../.env'
if (Test-Path -LiteralPath $target) {
    Write-Output 'Existing .env preserved. Set DRIVESENSE_API_TOKEN there if needed.'
    exit 0
}
$bytes = New-Object byte[] 32
$generator = [Security.Cryptography.RandomNumberGenerator]::Create()
$generator.GetBytes($bytes)
$generator.Dispose()
$token = [Convert]::ToBase64String($bytes)
[IO.File]::WriteAllText([IO.Path]::GetFullPath($target), "DRIVESENSE_API_TOKEN=$token`nDRIVESENSE_ALLOW_EXTERNAL=0`nNVIDIA_API_KEY=`n", [Text.UTF8Encoding]::new($false))
Write-Output 'Created local .env with a random token. Its contents were not printed.'
