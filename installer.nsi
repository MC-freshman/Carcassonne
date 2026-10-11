; NSIS 3 Unicode；只安装程序和说明，卸载保留玩家创建的数据。
Unicode True
!include "MUI2.nsh"
!ifndef VERSION
  !define VERSION "0.16.1"
!endif
!ifndef OUTPUT
  !define OUTPUT "release\卡卡颂_v${VERSION}_win64_安装版.exe"
!endif
Name "卡卡颂 ${VERSION}"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Carcassonne"
RequestExecutionLevel user
SetCompressor /SOLID lzma
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Section "游戏"
  SetOutPath "$INSTDIR"
  File "release\卡卡颂.exe"
  File "release\使用说明.txt"
  File "release\版本说明.txt"
  WriteUninstaller "$INSTDIR\卸载.exe"
  ; 静默验证不创建快捷方式；普通安装提供开始菜单入口。
  IfSilent no_shortcuts
  CreateDirectory "$SMPROGRAMS\卡卡颂"
  CreateShortcut "$SMPROGRAMS\卡卡颂\卡卡颂.lnk" "$INSTDIR\卡卡颂.exe"
  CreateShortcut "$SMPROGRAMS\卡卡颂\卸载.lnk" "$INSTDIR\卸载.exe"
  no_shortcuts:
SectionEnd

Section "Uninstall"
  ; 不使用递归删除：游戏目录内的 saves、截图及其他玩家文件均保留。
  Delete "$INSTDIR\卡卡颂.exe"
  Delete "$INSTDIR\使用说明.txt"
  Delete "$INSTDIR\版本说明.txt"
  Delete "$INSTDIR\卸载.exe"
  RMDir "$INSTDIR"
  IfSilent no_shortcuts
  Delete "$SMPROGRAMS\卡卡颂\卡卡颂.lnk"
  Delete "$SMPROGRAMS\卡卡颂\卸载.lnk"
  RMDir "$SMPROGRAMS\卡卡颂"
  no_shortcuts:
SectionEnd
