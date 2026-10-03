#define AppName "COKKER Converter"
#define AppVersion "0.9.9"
[Setup]
AppId={{61BE2BDA-3616-4761-96A7-4E5BA25EDB92}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\COKKER Converter
DefaultGroupName=COKKER Converter
OutputDir=..\dist
OutputBaseFilename=COKKER-Converter-Setup-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\COKKER Converter.exe
SetupIconFile=..\assets\logo.ico
[Files]
Source: "..\dist\COKKER Converter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\COKKER Converter"; Filename: "{app}\COKKER Converter.exe"
Name: "{autodesktop}\COKKER Converter"; Filename: "{app}\COKKER Converter.exe"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
[Run]
Filename: "{app}\COKKER Converter.exe"; Description: "Запустить COKKER Converter"; Flags: postinstall nowait skipifsilent
