Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
Name "AI Experiment"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\AI Experiment"
RequestExecutionLevel user
!define MUI_ICON "${BUNDLE}\_internal\native\AppIcon.ico"
!define MUI_UNICON "${BUNDLE}\_internal\native\AppIcon.ico"
!define MUI_FINISHPAGE_RUN "$INSTDIR\ai-experiment.exe"
!define MUI_FINISHPAGE_RUN_PARAMETERS "desktop"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "${BUNDLE}\LICENSE"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Section "AI Experiment" Main
  SetShellVarContext current
  IfFileExists "$INSTDIR\ai-experiment.exe" 0 prepare_done
  MessageBox MB_YESNO|MB_ICONEXCLAMATION "Updating will close the desktop window and stop this workspace's local service. Finish any CLI commands first. Remote training and experiment data will be preserved. Continue?" /SD IDYES IDYES prepare_service
  Abort
  prepare_service:
  ExecWait '"$INSTDIR\ai-experiment.exe" --prepare-install' $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "The desktop or local service could not be safely closed. Close the application, finish CLI commands, then run ai-experiment service stop --yes and try again. No processes were killed."
    Abort
  ${EndIf}
  prepare_done:
  InitPluginsDir
  File /oname=$PLUGINSDIR\WebView2Setup.exe "${BOOTSTRAP}"
  ExecWait '"$PLUGINSDIR\WebView2Setup.exe" /silent /install' $0
  ${If} $0 != 0
  ${AndIf} $0 != 3010
    MessageBox MB_OK|MB_ICONSTOP "Microsoft WebView2 could not be installed. Connect to the internet or install the WebView2 Evergreen Runtime, then try again."
    Abort
  ${EndIf}
  SetOutPath "$INSTDIR"
  File /r "${BUNDLE}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\AI Experiment"
  CreateShortcut "$SMPROGRAMS\AI Experiment\AI Experiment.lnk" "$INSTDIR\ai-experiment.exe" "desktop" "$INSTDIR\_internal\native\AppIcon.ico"
  CreateShortcut "$DESKTOP\AI Experiment.lnk" "$INSTDIR\ai-experiment.exe" "desktop" "$INSTDIR\_internal\native\AppIcon.ico"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Experiment" "DisplayName" "AI Experiment"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Experiment" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Experiment" "Publisher" "AI Experiment Contributors"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Experiment" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Experiment" "DisplayIcon" "$INSTDIR\_internal\native\AppIcon.ico"
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Experiment" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Experiment" "NoRepair" 1
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  MessageBox MB_YESNO|MB_ICONEXCLAMATION "Uninstalling will close the desktop window and stop this workspace's local service. Finish any CLI commands first. Remote training and cached experiments will be preserved. Continue?" /SD IDYES IDYES un_prepare
  Abort
  un_prepare:
  ExecWait '"$INSTDIR\ai-experiment.exe" --prepare-install' $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "The application is still in use. Close desktop and CLI windows, run ai-experiment service stop --yes, then retry. No application files have been removed."
    Abort
  ${EndIf}
  ClearErrors
  RMDir /r "$INSTDIR\_internal"
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "Some application files are still locked. Finish any CLI commands and run the uninstaller again. Experiment data has been preserved."
    Abort
  ${EndIf}
  Delete "$DESKTOP\AI Experiment.lnk"
  Delete "$SMPROGRAMS\AI Experiment\AI Experiment.lnk"
  RMDir "$SMPROGRAMS\AI Experiment"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Experiment"
  Delete "$INSTDIR\ai-experiment.exe"
  Delete "$INSTDIR\LICENSE"
  Delete "$INSTDIR\THIRD-PARTY-NOTICES.txt"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  ; Shared experiment data under LOCALAPPDATA\AI Experiment is retained.
SectionEnd
