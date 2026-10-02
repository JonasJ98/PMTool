@echo off
rem Startet das MPP-Auswertungstool von einem Netzlaufwerk aus.
rem Liegt neben dem Ordner "mpptool-gui" (Ausgabe von build.ps1). Beim Start wird
rem dieser Ordner nach %LOCALAPPDATA%\mpptool\app gespiegelt (nur geaenderte Dateien)
rem und das Tool lokal gestartet - so muss die Anwendung nicht bei jedem Start
rem uebers Netz geladen werden. Die Daten (%LOCALAPPDATA%\mpptool\data) bleiben unberuehrt.
setlocal
set "SRC=%~dp0mpptool-gui"
set "DST=%LOCALAPPDATA%\mpptool\app"

if not exist "%SRC%\mpptool-gui.exe" (
  echo Anwendungsordner nicht gefunden: %SRC%
  echo Starte die zuletzt kopierte Version, falls vorhanden ...
  goto start
)

if not exist "%DST%\mpptool-gui.exe" (
  echo Erster Start: Das Tool wird einmalig auf diesen Rechner kopiert ^(ca. 260 MB^).
  echo Das kann je nach Netzverbindung einige Minuten dauern - bitte Fenster offen lassen.
) else (
  echo Pruefe auf neue Version ...
)
robocopy "%SRC%" "%DST%" /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo Hinweis: Aktualisierung unvollstaendig - ist das Tool noch geoeffnet?
  echo Es wird die vorhandene Version gestartet.
  timeout /t 5 >nul
)

:start
if not exist "%DST%\mpptool-gui.exe" (
  echo Fehler: Keine lauffaehige Version gefunden. Bitte Netzlaufwerk pruefen.
  pause
  exit /b 1
)
start "" "%DST%\mpptool-gui.exe"
