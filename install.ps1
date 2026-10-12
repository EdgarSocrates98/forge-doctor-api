# Forge account install — editable runtime + user-scoped environment.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = $null
foreach ($c in @("python3", "python", "py")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) { Write-Error "install: no python on PATH (need >=3.10)"; exit 2 }
$installArgs = @("--editable", "--persist-env", "--allow-download") + $args
if ($py.EndsWith("py.exe")) { & $py -3 scripts/forge_bootstrap.py @installArgs } else { & $py scripts/forge_bootstrap.py @installArgs }
exit $LASTEXITCODE
