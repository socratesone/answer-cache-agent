[Setup]
AppId={{20ED37FC-E856-4C3F-AED3-C84FA26227CE}
AppName=Questionnaire Assistant
AppVersion=0.1.1
AppPublisher=SocratesOne Development LLC
DefaultDirName={localappdata}\Programs\SocratesOne\QuestionnaireAssistant
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
OutputDir=..\artifacts
OutputBaseFilename=QuestionnaireAssistant-Setup-0.1.1-x64
Compression=lzma2
SolidCompression=yes
AppMutex=Local\SocratesOne.QuestionnaireAssistant
CloseApplications=yes
UninstallDisplayIcon={app}\questionnaire-host.exe
LicenseFile=..\LICENSE
[Files]
Source: "..\artifacts\windows\questionnaire-host\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\artifacts\dependency-notices.txt"; DestDir: "{app}"
Source: "..\artifacts\model-provenance.json"; DestDir: "{app}"
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE-interface.txt"
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE-engine.txt"
[Registry]
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.socratesone.questionnaire"; ValueType: string; ValueData: "{app}\native-host.json"
[UninstallDelete]
Type: files; Name: "{app}\native-host.json"
Type: files; Name: "{app}\allowed-origins.json"
[Code]
var ExtensionPage: TInputQueryWizardPage;

function ValidId(Value: String): Boolean;
var I: Integer;
begin
  Result := Length(Value) = 32;
  for I := 1 to Length(Value) do
    if (Value[I] < 'a') or (Value[I] > 'p') then Result := False;
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if WizardSilent and not ValidId(ExpandConstant('{param:EXTENSIONID|}')) then begin
    Log('A valid /EXTENSIONID=<32 letters a-p> is required for silent installation.');
    Result := False;
  end;
end;

procedure InitializeWizard;
begin
  ExtensionPage := CreateInputQueryPage(wpSelectDir, 'Connect your Chrome extension',
    'Enter the exact extension ID from chrome://extensions.',
    'Load the supplied extension folder using Chrome Developer mode, then copy its ID. No store listing is configured. Keep that folder in a permanent location.');
  ExtensionPage.Add('Chrome extension ID:', False);
  ExtensionPage.Values[0] := ExpandConstant('{param:EXTENSIONID|}');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ExtensionPage.ID then begin
    Result := ValidId(ExtensionPage.Values[0]);
    if not Result then MsgBox('Enter the 32-letter Chrome extension ID (letters a-p).', mbError, MB_OK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Existing: String;
begin
  Result := '';
  if not ValidId(ExtensionPage.Values[0]) then
    Result := 'A valid extension ID is required. Use /EXTENSIONID=<ID> for silent installation.';
  if RegQueryStringValue(HKCU, 'Software\Google\Chrome\NativeMessagingHosts\com.socratesone.questionnaire', '', Existing) then
    if CompareText(Existing, ExpandConstant('{app}\native-host.json')) <> 0 then
      Result := 'A companion is registered in another directory. Uninstall it before changing installation directories.';
end;

function JsonEscape(Value: String): String;
begin
  StringChangeEx(Value, '\', '\\', True);
  StringChangeEx(Value, '"', '\"', True);
  Result := Value;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Manifest, Origins: String;
begin
  if CurStep = ssPostInstall then begin
    Origins := '["chrome-extension://' + ExtensionPage.Values[0] + '/"]';
    Manifest := '{"name":"com.socratesone.questionnaire","description":"Questionnaire Assistant local companion","path":"' + JsonEscape(ExpandConstant('{app}\questionnaire-host.exe')) + '","type":"stdio","allowed_origins":' + Origins + '}';
    if not SaveStringToFile(ExpandConstant('{app}\native-host.json'), UTF8Encode(Manifest), False) then
      RaiseException('Could not write native host manifest');
    if not SaveStringToFile(ExpandConstant('{app}\allowed-origins.json'), Origins, False) then
      RaiseException('Could not write native host origin allowlist');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var Existing: String;
begin
  if CurUninstallStep = usPostUninstall then begin
    if RegQueryStringValue(HKCU, 'Software\Google\Chrome\NativeMessagingHosts\com.socratesone.questionnaire', '', Existing) then
      if CompareText(Existing, ExpandConstant('{app}\native-host.json')) = 0 then begin
        RegDeleteValue(HKCU, 'Software\Google\Chrome\NativeMessagingHosts\com.socratesone.questionnaire', '');
        RegDeleteKeyIfEmpty(HKCU, 'Software\Google\Chrome\NativeMessagingHosts\com.socratesone.questionnaire');
      end;
  end;
end;
