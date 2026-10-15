; 声动阿昌 —— 阿昌族民族音乐桌面播放器 安装包脚本 (Inno Setup 6)
;
; 本地构建:
;   ISCC.exe packaging\installer\shengdong-achang.iss
; 产物默认落在 packaging\installer\Output\ 下。

#define MyAppName "声动阿昌"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "声动阿昌"
#define MyAppExeName "shengdong-achang.exe"

[Setup]
AppId={{B8F5D3C2-6A9E-4D4B-9C7F-2E3A4B5C6D7E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
; 免管理员安装: 装到当前用户目录, 不触发 UAC
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=ShengdongAchang-Setup-{#MyAppVersion}
SetupIconFile=..\shengdong-achang.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableDirPage=auto
DisableProgramGroupPage=auto
; 音源客户端依赖较大, 磁盘空间提示给足
ExtraDiskSpaceRequired=600000000
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"

[Files]
; PyInstaller 单目录产物: exe + _internal 全量拷入
Source: "..\..\dist\shengdong-achang\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
// 卸载前若应用还在跑, 请求它优雅退出
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if MsgBox('{#MyAppName} 似乎正在运行。是否先关闭它再继续卸载？',
            mbConfirmation, MB_YESNO) = IDYES then
  begin
    Exec('taskkill.exe', '/IM {#MyAppExeName} /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end
  else
    Result := False;
end;
