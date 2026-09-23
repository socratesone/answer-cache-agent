param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[a-p]{32}$')][string]$ExtensionId,
    [string]$InnoCompiler = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
)
$ErrorActionPreference = 'Stop'
$InterfaceRoot = Split-Path $PSScriptRoot -Parent
$EngineRoot = Split-Path $InterfaceRoot -Parent
Set-Location $InterfaceRoot
function Invoke-Checked { param([scriptblock]$Action) & $Action; if ($LASTEXITCODE -ne 0) { throw "Build command failed ($LASTEXITCODE)" } }
Invoke-Checked { npm ci --cache .npm-cache }
Invoke-Checked { npm run build }
New-Item -ItemType Directory -Force artifacts\engine-source | Out-Null
# Build a snapshot inside our ownership boundary; never run setuptools against Fable's working directory.
Copy-Item "$EngineRoot\answer_cache_agent" artifacts\engine-source -Recurse -Force
Copy-Item "$EngineRoot\pyproject.toml","$EngineRoot\LICENSE","$EngineRoot\README.md" artifacts\engine-source -Force
Invoke-Checked { py -3 -m venv .venv }
$Python = Join-Path $InterfaceRoot '.venv\Scripts\python.exe'
Invoke-Checked { & $Python -m pip install .\artifacts\engine-source .\companion pyinstaller pytest }
Invoke-Checked { & $Python packaging\download_model.py }
ConvertTo-Json -InputObject @("chrome-extension://$ExtensionId/") | Set-Content artifacts\allowed-origins.json -Encoding ascii
Invoke-Checked { & $Python -m PyInstaller packaging\host.spec --distpath artifacts\windows --workpath artifacts\pyinstaller --noconfirm }
Invoke-Checked { & $Python scripts\dependency_notices.py }
Invoke-Checked { & $InnoCompiler "/DExtensionId=$ExtensionId" packaging\installer.iss }
Invoke-Checked { npm run package:store }
Write-Host 'Development artifacts built. Native Windows acceptance, signing, store review and publication remain separate release gates.'
