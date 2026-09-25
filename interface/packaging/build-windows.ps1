param(
    [string]$InnoCompiler = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    [string]$PythonExe = ''
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$InterfaceRoot = Split-Path $PSScriptRoot -Parent
$EngineRoot = Split-Path $InterfaceRoot -Parent
function Invoke-Checked { param([scriptblock]$Action) & $Action; if ($LASTEXITCODE -ne 0) { throw "Build command failed ($LASTEXITCODE): $Action" } }
foreach ($command in @('node.exe','npm.cmd')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Missing $command. Install Python 3.10 x64 and Node 22 LTS on the build machine." }
}
if (-not (Test-Path $InnoCompiler)) { throw 'Inno Setup compiler missing. Install Inno Setup 6.7.3 and pass -InnoCompiler <full path to ISCC.exe>.' }
$InnoCompiler = (Resolve-Path $InnoCompiler).Path
Push-Location $EngineRoot
try {
    if ($PythonExe) {
        $PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
        Invoke-Checked { & $PythonExe -c 'import sys,struct; assert sys.version_info[:2] == (3,10) and struct.calcsize(chr(80)) == 8' }
        if (-not (Test-Path '.venv\Scripts\python.exe')) { Invoke-Checked { & $PythonExe -m venv .venv } }
    } else {
        if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) { throw 'Missing Python launcher. Install Python 3.10 x64 or pass -PythonExe <absolute path>.' }
        Invoke-Checked { py -3.10 -c 'import struct; assert struct.calcsize(chr(80)) == 8' }
        if (-not (Test-Path '.venv\Scripts\python.exe')) { Invoke-Checked { py -3.10 -m venv .venv } }
    }
    $Python = Join-Path $EngineRoot '.venv\Scripts\python.exe'
    # A pre-existing .venv may have been created by another interpreter; validate the one actually used for packaging.
    Invoke-Checked { & $Python -c 'import sys,struct; assert sys.version_info[:2] == (3,10) and struct.calcsize(chr(80)) == 8, sys.version' }
    # Install the engine from a build snapshot so setuptools leaves source files untouched.
    $EngineSnapshot = Join-Path $InterfaceRoot ('artifacts\engine-source-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $EngineSnapshot -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $EngineRoot 'answer_cache_agent') -Destination $EngineSnapshot -Recurse
    Copy-Item -LiteralPath @((Join-Path $EngineRoot 'pyproject.toml'), (Join-Path $EngineRoot 'LICENSE'), (Join-Path $EngineRoot 'README.md')) -Destination $EngineSnapshot
    Invoke-Checked { & $Python -m pip install -r interface\packaging\requirements-windows.lock }
    Invoke-Checked { & $Python -m pip install --no-deps --no-build-isolation $EngineSnapshot .\interface\companion }
    Invoke-Checked { & $Python -m pip check }
    Invoke-Checked { & $Python -m pytest tests interface\tests -q }
    Set-Location $InterfaceRoot
    Invoke-Checked { npm.cmd ci --cache .npm-cache }
    Invoke-Checked { npm.cmd run build }
    Invoke-Checked { npm.cmd test }
    Invoke-Checked { & $Python packaging\download_model.py }
    Invoke-Checked { & $Python -m PyInstaller packaging\host.spec --distpath artifacts\windows --workpath artifacts\pyinstaller --noconfirm --clean }
    Invoke-Checked { & $Python scripts\dependency_notices.py }
    Invoke-Checked { & $InnoCompiler packaging\installer.iss }
    Invoke-Checked { npm.cmd run package:store }
    Get-FileHash artifacts\QuestionnaireAssistant-Setup-0.1.1-x64.exe -Algorithm SHA256 |
        Format-List | Out-File artifacts\installer-sha256.txt
    Write-Host 'Unsigned local installer built. Configure the actual extension ID during installation.'
} finally { Pop-Location }
