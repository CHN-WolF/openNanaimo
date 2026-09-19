$ErrorActionPreference='Stop'
$Root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Python=Join-Path $Root 'tools\python\python.exe'
if(-not(Test-Path -LiteralPath $Python)){throw "Bundled Python missing: $Python"}
& $Python -B (Join-Path $PSScriptRoot 'verify_package.py') --root $Root
if($LASTEXITCODE){throw 'package verifier failed'}
# Never read a real player's profile into a publishable validation transcript.
$tempRoot=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
$tmp=[IO.Path]::GetFullPath((Join-Path $tempRoot ('nanaimo-validate-'+[guid]::NewGuid().ToString('N'))))
if(-not $tmp.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase)){throw 'unsafe validation directory'}
[IO.Directory]::CreateDirectory($tmp)|Out-Null
try {
 $ini=Join-Path $tmp 'synthetic_profile.ini'
 $json=Join-Path $tmp 'synthetic_profile.json'
 [IO.File]::WriteAllText($ini,"name_hex=504C41594552`r`nlevel=25`r`n",[Text.Encoding]::ASCII)
 powershell -NoProfile -ExecutionPolicy Bypass -STA -File (Join-Path $Root 'gui_launcher\nanaimo_launcher.ps1') -ValidateOnly -ProfileIniOverride $ini -ProfileJsonOverride $json
 if($LASTEXITCODE){throw 'launcher validation failed'}
} finally {
 $checked=[IO.Path]::GetFullPath($tmp)
 if(-not $checked.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase)){throw 'unsafe validation cleanup'}
 if([IO.Directory]::Exists($checked)){[IO.Directory]::Delete($checked,$true)}
}
Write-Host 'OPEN_NANAIMO_PACKAGE_ALL_PASS runtime_acceptance=false'
