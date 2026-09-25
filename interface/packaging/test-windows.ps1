param([Parameter(Mandatory=$true)][string]$Installer)
$ErrorActionPreference = 'Stop'
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Registry = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.socratesone.questionnaire'
$Uninstall = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{20ED37FC-E856-4C3F-AED3-C84FA26227CE}_is1'
if ((Test-Path $Registry) -or (Test-Path $Uninstall)) { throw 'Existing installation/registration detected. Use a disposable Windows user; test refuses to overwrite it.' }
$TestRoot = Join-Path $Root ('acceptance-' + [Guid]::NewGuid().ToString('N'))
$InstallDir = Join-Path $TestRoot 'installed'
$DataDir = Join-Path $TestRoot 'data'
New-Item -ItemType Directory $TestRoot | Out-Null
$Installer = (Resolve-Path $Installer).Path
# Synthetic origin is ONLY a framing/installer test fixture, never a published extension ID.
$TestId = 'abcdefghijklmnopabcdefghijklmnop'
$InstallArguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="'+$InstallDir+'"'),('/EXTENSIONID='+$TestId),('/LOG="'+$TestRoot+'\install.log"'))
function Install-Test {
    $p = Start-Process -FilePath $Installer -ArgumentList $InstallArguments -WindowStyle Hidden -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Installer failed: $($p.ExitCode). See $TestRoot" }
    if ((Get-Item $Registry).GetValue('') -ne "$InstallDir\native-host.json") { throw 'Incorrect native-host registration' }
}
try {
    $InvalidArguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="'+$InstallDir+'"'),'/EXTENSIONID=invalid')
    $invalid = Start-Process -FilePath $Installer -ArgumentList $InvalidArguments -WindowStyle Hidden -Wait -PassThru
    if ($invalid.ExitCode -eq 0 -or (Test-Path $Registry)) { throw 'Invalid extension ID was accepted' }
    Install-Test
    & $Python "$PSScriptRoot\test_installed.py" --install $InstallDir --data $DataDir
    if ($LASTEXITCODE -ne 0) { throw 'Installed protocol acceptance failed' }
    $Before = Get-FileHash "$DataDir\SocratesOne\QuestionnaireAssistant\private.dpapi"
    Install-Test
    & $Python "$PSScriptRoot\test_installed.py" --install $InstallDir --data $DataDir --reopen
    if ($LASTEXITCODE -ne 0) { throw 'Reinstall acceptance failed' }
    if ((Get-FileHash $Before.Path).Hash -ne $Before.Hash) { throw 'Reinstall changed private data' }
} finally {
    $Uninstaller = Join-Path $InstallDir 'unins000.exe'
    if (Test-Path $Uninstaller) {
        $p = Start-Process -FilePath $Uninstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/LOG="'+$TestRoot+'\uninstall.log"')) -WindowStyle Hidden -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "Uninstall failed: $($p.ExitCode)" }
    }
}
if ((Test-Path $Registry) -or (Test-Path $Uninstall)) { throw 'Registration survived uninstall' }
if (Test-Path "$InstallDir\questionnaire-host.exe") { throw 'Executable survived uninstall' }
if (-not (Test-Path "$DataDir\SocratesOne\QuestionnaireAssistant\answer_cache.db")) { throw 'User data missing after uninstall' }
"LIFECYCLE_OK: install, repeat install, reconnect, registration cleanup, user-data retained. Evidence: $TestRoot"
