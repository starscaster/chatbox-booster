; Chatbox Booster Installer - Inno Setup Script
; Build: iscc installer\build.iss

#define MyAppName "Chatbox Booster"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "Chatbox Booster"
#define MyAppExeName "manager_main.py"
#define AppRoot ".."

[Setup]
AppId={{CB-BOOSTER-2026}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\ChatboxBooster
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=ChatboxBooster-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile=
UninstallDisplayIcon=

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
; Core application
Source: "{#AppRoot}\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs
Source: "{#AppRoot}\server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppRoot}\manager_main.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#AppRoot}\config\*"; DestDir: "{app}\config"; Flags: recursesubdirs onlyifdoesntexist
Source: "{#AppRoot}\locale\*"; DestDir: "{app}\locale"; Flags: recursesubdirs
Source: "{#AppRoot}\requirements-core.txt"; DestDir: "{app}"; Flags: ignoreversion

; Runtime (embedded Python + dependencies)
Source: "{#AppRoot}\runtime\*"; DestDir: "{app}\runtime"; Flags: recursesubdirs

; User plugins directory (empty, created on install)
Source: "{#AppRoot}\user_plugins\*"; DestDir: "{app}\user_plugins"; Flags: recursesubdirs onlyifdoesntexist

[Icons]
Name: "{group}\Chatbox Booster Settings"; Filename: "{app}\runtime\python\python.exe"; Parameters: "{app}\manager_main.py"; WorkingDir: "{app}"; IconFilename: "{app}\app\manager\static\icon.ico"
Name: "{group}\Uninstall Chatbox Booster"; Filename: "{uninstallexe}"

[Run]
; Optionally launch the manager after install
Filename: "{app}\runtime\python\python.exe"; Parameters: "{app}\manager_main.py"; WorkingDir: "{app}"; Description: "Launch Chatbox Booster"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up runtime and data, but preserve config and user_plugins
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: filesandordirs; Name: "{app}\app\core\__pycache__"
Type: filesandordirs; Name: "{app}\app\plugins\*\__pycache__"