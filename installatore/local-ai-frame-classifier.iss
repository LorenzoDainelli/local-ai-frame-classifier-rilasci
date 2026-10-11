#define NomeApp "Local AI Frame Classifier"
#define IdApp "LorenzoDainelli.LocalAIFrameClassifier"

#ifndef Versione
  #define Versione "2.0.0-sviluppo"
#endif
#ifndef VersioneNumerica
  #define VersioneNumerica "2.0.0.0"
#endif
#ifndef Sorgente
  #define Sorgente "..\costruzione"
#endif
#ifndef Uscita
  #define Uscita "..\uscita"
#endif

[Setup]
AppId={{8B1F4C2E-6D3A-4E1B-9A57-2C0D5E7F9A11}
AppName={#NomeApp}
AppVersion={#Versione}
AppVerName={#NomeApp} {#Versione}
AppPublisher=Lorenzo Dainelli
AppComments=Le tue foto, sul tuo computer
VersionInfoVersion={#VersioneNumerica}
VersionInfoProductName={#NomeApp}
VersionInfoDescription=Installazione di {#NomeApp}
DefaultDirName={autopf}\{#NomeApp}
DefaultGroupName={#NomeApp}
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableReadyPage=yes
DisableWelcomePage=no
PrivilegesRequired=lowest
UsedUserAreasWarning=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#Uscita}
OutputBaseFilename=local-ai-frame-classifier-{#Versione}
SetupIconFile=..\officina\web\statici\officina.ico
UninstallDisplayIcon={app}\app\officina\web\statici\officina.ico
UninstallDisplayName={#NomeApp}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
AppMutex=LocalAIFrameClassifier-una-sola
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=no
LanguageDetectionMethod=none

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"

[Tasks]
Name: "desktop"; Description: "Metti un'icona sul desktop"

[Files]
Source: "{#Sorgente}\python\*"; DestDir: "{app}\python"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Sorgente}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Sorgente}\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: ServeWebView2

[Icons]
Name: "{autoprograms}\{#NomeApp}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m officina.programma"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\officina\web\statici\officina.ico"; Comment: "Le tue foto, sul tuo computer"; AppUserModelID: "{#IdApp}"
Name: "{autodesktop}\{#NomeApp}"; Filename: "{app}\python\pythonw.exe"; Parameters: "-m officina.programma"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\officina\web\statici\officina.ico"; Comment: "Le tue foto, sul tuo computer"; AppUserModelID: "{#IdApp}"; Tasks: desktop

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Preparo la finestra del programma..."; Flags: waituntilterminated; Check: ServeWebView2
Filename: "{app}\python\pythonw.exe"; Parameters: "-m officina.programma"; WorkingDir: "{app}\app"; Description: "Apri {#NomeApp}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\python\pythonw.exe"; Parameters: "-m officina.programma"; WorkingDir: "{app}\app"; Flags: nowait; Check: VuoleRiaprire

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\app.vecchia"
Type: filesandordirs; Name: "{app}\python.vecchia"

[Code]
const
  ChiaveWebView2 = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function VersioneValida(Valore: String): Boolean;
begin
  Result := (Valore <> '') and (Valore <> '0.0.0.0');
end;

function WebView2Presente: Boolean;
var
  Valore: String;
begin
  Result := False;
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\' + ChiaveWebView2, 'pv', Valore) then
    Result := VersioneValida(Valore);
  if (not Result) and RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\' + ChiaveWebView2, 'pv', Valore) then
    Result := VersioneValida(Valore);
  if (not Result) and RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\' + ChiaveWebView2, 'pv', Valore) then
    Result := VersioneValida(Valore);
end;

function ServeWebView2: Boolean;
begin
  Result := not WebView2Presente;
end;

function VuoleRiaprire: Boolean;
begin
  Result := ExpandConstant('{param:RIAPRI|0}') = '1';
end;

var
  Finito: Boolean;

procedure FermaIlProgramma;
var
  Codice: Integer;
begin
  Exec('powershell.exe', '-NoProfile -NonInteractive -WindowStyle Hidden -Command "$d=''' + ExpandConstant('{app}') + '\''; Get-Process | Where-Object { $_.Path -and $_.Path.StartsWith($d, [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue"', '', SW_HIDE, ewWaitUntilTerminated, Codice);
end;

function Sposta(Da, A: String): Boolean;
var
  Prova: Integer;
begin
  Result := True;
  if not DirExists(Da) then
    Exit;
  if DirExists(A) then
    DelTree(A, True, True, True);
  for Prova := 1 to 20 do
  begin
    if RenameFile(Da, A) then
      Exit;
    if (Prova mod 5) = 0 then
      FermaIlProgramma;
    Sleep(500);
  end;
  Result := False;
end;

procedure Rimetti(Parte: String);
begin
  if DirExists(ExpandConstant('{app}\' + Parte + '.vecchia')) then
  begin
    DelTree(ExpandConstant('{app}\' + Parte), True, True, True);
    RenameFile(ExpandConstant('{app}\' + Parte + '.vecchia'), ExpandConstant('{app}\' + Parte));
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  SetCurrentDir(ExpandConstant('{tmp}'));
  if not DirExists(ExpandConstant('{app}')) then
    Exit;
  FermaIlProgramma;
  Sleep(1000);
  if Sposta(ExpandConstant('{app}\app'), ExpandConstant('{app}\app.vecchia')) then
  begin
    if Sposta(ExpandConstant('{app}\python'), ExpandConstant('{app}\python.vecchia')) then
      Exit;
    Rimetti('app');
  end;
  Result := 'Il programma non si lascia chiudere. Riavvia il computer e apri di nuovo questa installazione: le tue foto e il tuo archivio non sono stati toccati.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    Finito := True;
    DelTree(ExpandConstant('{app}\app.vecchia'), True, True, True);
    DelTree(ExpandConstant('{app}\python.vecchia'), True, True, True);
  end;
end;

procedure DeinitializeSetup;
begin
  if not Finito then
  begin
    Rimetti('app');
    Rimetti('python');
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Cartella: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Cartella := ExpandConstant('{localappdata}\{#NomeApp}\librerie');
    if DirExists(Cartella) and (not UninstallSilent) then
      if MsgBox('Vuoi togliere anche i motori scaricati al primo avvio? Occupano qualche GB.' + #13#10#13#10 + 'Il tuo archivio e le tue foto non si toccano.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Cartella, True, True, True);
  end;
end;
