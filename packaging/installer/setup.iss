; 山河回响 —— Windows 安装包脚本 (Inno Setup 6)
;
; 本地构建:
;   ISCC.exe packaging\installer\setup.iss
; 产物默认落在 packaging\installer\Output\ 下。
;
; 设计取舍:
;   · 安装到 %LOCALAPPDATA%\Programs, 用 PrivilegesRequired=lowest —— 不需要管理员权限,
;     学生机/办公机上双击就能装。
;   · 用户数据(下载的音乐、日志、已策展的曲库副本)放在 %LOCALAPPDATA% 下另一个目录,
;     与本安装目录分离, 所以「覆盖安装」和「卸载」都不会弄丢已下载的歌。
;   · 曲库母本随安装包一起分发到 {app}\library, 应用首次启动才复制到用户数据目录。

#define MyAppName "山河回响"
#define MyAppVersion "1.0.0"
; ↓ 发布者: 显示在「程序和功能」列表与安装向导里, 与 README 中的项目归属是两件事
#define MyAppPublisher "李大光"
#define MyAppURL "https://github.com/biabia-55/mountainriverechoes"
#define MyAppExeName "mountainriverechoes.exe"
#define MyDbName "mountainriverechoes.db"

[Setup]
AppId={{7A3B1E52-4C8D-4F1A-9B6E-2D5A8C3F1E40}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
; 免管理员安装: 装到当前用户目录, 不触发 UAC
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=MountainRiverEchoes-Setup-{#MyAppVersion}
SetupIconFile=..\mountainriverechoes.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableDirPage=auto
DisableProgramGroupPage=auto
; 曲库 200MB 级, 磁盘空间提示给足
ExtraDiskSpaceRequired=800000000
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
; 若你的 Inno Setup 不带简中语言包, 删掉下面这一行即可正常编译
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
; PyInstaller 单目录产物: exe + _internal 全量拷入
Source: "..\..\dist\mountainriverechoes\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 曲库母本: 首次启动时由应用复制到用户数据目录
Source: "..\..\dist\library\{#MyDbName}"; DestDir: "{app}\library"; Flags: ignoreversion
; 版权与说明随包分发
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 只清安装目录里应用自己生成的文件; 用户数据目录不在其中, 不会被删
Type: filesandordirs; Name: "{app}\_internal\app\__pycache__"

[Code]
// 卸载前若应用还在跑, 请求它优雅退出(端口释放了重装才不会抢端口)
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if CheckForMutexes('mountainriverechoes') then
  begin
    if MsgBox('{#MyAppName} 似乎正在运行。是否先关闭它再继续卸载？',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      Exec('taskkill.exe', '/IM {#MyAppExeName} /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end
    else
      Result := False;
  end;
end;
