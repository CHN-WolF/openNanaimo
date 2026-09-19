$ErrorActionPreference='Stop'
$Root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$rootPrefix=$Root.TrimEnd('\')+'\'
$active=@(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(nanaimo_adapter|nanaimo_client|game_unpack)' -or ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase) -and $_.Name -eq 'game.exe') })
if($active.Count -gt 0){throw 'Client/service still running. Close it explicitly before removing private state.'}

$patterns=@('adapter_*.log','*_stderr.log','accounts.dat','nanaimo_launcher_profile.ini','nanaimo_launcher_profile.json','adapter_ip.txt','*_state*.dat','*_state*.bak','*_state*.new','card_inventory_*.dat','card_key_*.dat','card_synthesis_rewards_*.dat','gui*_*.dat','adapter_*.dat','quickbar_state_*.dat','quickbar_state_*.handles','skill_progress_state_*.dat')
$targets=@()
foreach($pat in $patterns){$targets+=Get-ChildItem -LiteralPath $Root -Filter $pat -File -ErrorAction SilentlyContinue}
foreach($p in $targets|Sort-Object FullName -Unique){$full=[IO.Path]::GetFullPath($p.FullName);if(-not$full.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase)){throw "unsafe target: $full"};Remove-Item -LiteralPath $full -Force}
$backup=Join-Path $Root 'inventory_admin_backups';if(Test-Path -LiteralPath $backup){$full=[IO.Path]::GetFullPath($backup);if(-not$full.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase)){throw "unsafe target: $full"};Remove-Item -LiteralPath $full -Recurse -Force}
Write-Host 'Generated local state removed.'
