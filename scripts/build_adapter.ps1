param([switch]$KeepOutputs,[string]$TccPath)
$ErrorActionPreference='Stop'
$Root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Tcc=if($TccPath){[IO.Path]::GetFullPath($TccPath)}else{Join-Path $Root 'tools\tcc\tcc.exe'}
$Mod=Join-Path $Root 'adapter'
$Src=Join-Path $Root 'release'
$Manifest=Get-Content -LiteralPath (Join-Path $Root 'manifest\source_closure.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if(-not(Test-Path -LiteralPath $Tcc)){throw "TCC missing (supply tools/tcc or -TccPath): $Tcc"}
$tmp=Join-Path $env:TEMP ('open-nanaimo-build-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($tmp)|Out-Null
try{
 $jobs=@(
  @('nanaimo_adapter.c','nanaimo_adapter.exe'),
  @('nanaimo_adapter_testports.c','nanaimo_adapter_testports.exe')
 )
 foreach($j in $jobs){
  $input=Join-Path $Mod $j[0];$output=Join-Path $tmp $j[1]
  $contract=$Manifest.build_outputs.('adapter/'+$j[1])
  if(-not $contract){throw ('Missing build contract: '+$j[1])}
  & $Tcc -I $Root -I $Mod -I $Src $input -o $output
  if($LASTEXITCODE){throw "compile failed: $($j[0])"}
  $hash=(Get-FileHash -LiteralPath $output -Algorithm SHA256).Hash
  if($hash-ne$contract.sha256 -or (Get-Item -LiteralPath $output).Length-ne$contract.size){throw "rebuild contract mismatch: $output`nexpected=$($contract.sha256)`nactual=$hash"}
  if($KeepOutputs){$build=Join-Path $Root 'build';[IO.Directory]::CreateDirectory($build)|Out-Null;Copy-Item -LiteralPath $output -Destination (Join-Path $build $j[1]) -Force}
  Write-Host "REBUILD_PASS $($j[1]) $hash"
 }
}finally{
 $full=[IO.Path]::GetFullPath($tmp);$tempRoot=[IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')+'\'
 if(-not$full.StartsWith($tempRoot,[StringComparison]::OrdinalIgnoreCase)){throw "unsafe temp cleanup: $full"}
 if([IO.Directory]::Exists($full)){[IO.Directory]::Delete($full,$true)}
}