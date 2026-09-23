#ifndef ExtensionId
  #error Supply /DExtensionId=<Chrome Web Store extension id>
#endif
[Setup]
AppId={{20ED37FC-E856-4C3F-AED3-C84FA26227CE}
AppName=Questionnaire Assistant
AppVersion=0.1.0
AppPublisher=SocratesOne Development LLC
DefaultDirName={localappdata}\Programs\SocratesOne\QuestionnaireAssistant
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\artifacts
OutputBaseFilename=QuestionnaireAssistant-Setup-0.1.0
Compression=lzma2
SolidCompression=yes
AppMutex=Local\SocratesOne.QuestionnaireAssistant
CloseApplications=yes
UninstallDisplayIcon={app}\questionnaire-host.exe
[Files]
Source: "..\artifacts\windows\questionnaire-host\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\artifacts\dependency-notices.txt"; DestDir: "{app}"
Source: "..\LICENSE"; DestDir: "{app}"
[Registry]
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.socratesone.questionnaire"; ValueType: string; ValueData: "{app}\native-host.json"; Flags: uninsdeletekey
[Run]
Filename: "https://chromewebstore.google.com/detail/{#ExtensionId}"; Description: "Open the Chrome Web Store to add the extension"; Flags: shellexec postinstall skipifsilent unchecked
[UninstallDelete]
Type: files; Name: "{app}\native-host.json"
[Code]
function JsonEscape(Value: String): String;
begin
  StringChangeEx(Value, '\', '\\', True);
  StringChangeEx(Value, '"', '\"', True);
  Result := Value;
end;
procedure CurStepChanged(CurStep: TSetupStep);
var Manifest: String;
begin
  if CurStep = ssPostInstall then begin
    Manifest := '{"name":"com.socratesone.questionnaire","description":"Questionnaire Assistant local companion","path":"' + JsonEscape(ExpandConstant('{app}\questionnaire-host.exe')) + '","type":"stdio","allowed_origins":["chrome-extension://{#ExtensionId}/"]}';
    SaveStringToFile(ExpandConstant('{app}\native-host.json'), Manifest, False);
  end;
end;
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if MsgBox('Also permanently delete your answers, variables, provider credentials and local settings? Choose No to retain them.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{localappdata}\SocratesOne\QuestionnaireAssistant'), True, True, True);
end;
