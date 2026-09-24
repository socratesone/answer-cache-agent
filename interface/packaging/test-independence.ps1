# Run from outside the repository so Windows can temporarily rename the build tree.
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Parent = Split-Path $Root -Parent
if ((Get-Location).Path.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Run this script from the parent of the repository.' }
$Registry = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.socratesone.questionnaire'
$UninstallKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{20ED37FC-E856-4C3F-AED3-C84FA26227CE}_is1'
if ((Test-Path $Registry) -or (Test-Path $UninstallKey)) { throw 'Existing app installation detected; refusing to overwrite it.' }
$Token = [Guid]::NewGuid().ToString('N')
$TestRoot = Join-Path $Parent ('packaging-independence-' + $Token)
$HiddenRoot = Join-Path $Parent ('build-unavailable-' + $Token)
# Both rename targets must remain inside the same explicitly resolved workspace parent.
if ((Split-Path ([IO.Path]::GetFullPath($HiddenRoot)) -Parent) -ne $Parent -or (Test-Path $HiddenRoot)) { throw 'Unsafe rename destination' }
New-Item -ItemType Directory $TestRoot | Out-Null
Copy-Item "$PSScriptRoot\test_installed.py" "$TestRoot\test_installed.py"
$InstallDir = Join-Path $TestRoot 'installed'
try {
    $p = Start-Process "$Root\interface\artifacts\QuestionnaireAssistant-Setup-0.1.1-x64.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="'+$InstallDir+'"'),'/EXTENSIONID=abcdefghijklmnopabcdefghijklmnop',('/LOG="'+$TestRoot+'\install.log"')) -WindowStyle Hidden -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw 'Independence install failed' }
    Rename-Item -LiteralPath $Root -NewName (Split-Path $HiddenRoot -Leaf)
    & py -3.10 "$TestRoot\test_installed.py" --install $InstallDir --data "$TestRoot\data"
    if ($LASTEXITCODE -ne 0) { throw 'Installed app failed with build directory unavailable' }
    Write-Output 'BUILD_DIRECTORY_INDEPENDENCE_OK'
} finally {
    if (Test-Path $HiddenRoot) { Rename-Item -LiteralPath $HiddenRoot -NewName (Split-Path $Root -Leaf) }
    if (Test-Path "$InstallDir\unins000.exe") {
        $p = Start-Process "$InstallDir\unins000.exe" -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/LOG="'+$TestRoot+'\uninstall.log"')) -WindowStyle Hidden -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw 'Independence test uninstall failed' }
    }
}
if ((Test-Path $Registry) -or (Test-Path $UninstallKey)) { throw 'Integration entry survived uninstall' }
if (-not (Test-Path "$TestRoot\data\SocratesOne\QuestionnaireAssistant\answer_cache.db")) { throw 'Synthetic data was not preserved' }
Write-Output "INDEPENDENCE_CLEANUP_OK: $TestRoot"
