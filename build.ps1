# Erzeugt eine verteilbare Windows-Anwendung:  dist\mpptool-gui\mpptool-gui.exe
# (+ portable JRE, sodass auf den Zielrechnern KEIN Java installiert sein muss)
#
# Aufruf in PowerShell im Projektordner:   .\build.ps1
#          ohne JRE-Bündelung:             .\build.ps1 -SkipJre
# Voraussetzung zum Bauen: Python 3.10+ und (nur zum Bauen) ein JDK mit jlink, JAVA_HOME gesetzt.
# Ergebnis anschließend als Zip an das Team geben:  dist\mpptool-gui.zip
#
# Dies ist zugleich der Packaging-Test aus ADR-001: die .exe auf einem Rechner mit den
# Endpoint-Security-Richtlinien der Fachabteilungen starten und Antivirus-Verhalten dokumentieren.

param(
    [switch]$SkipJre,
    [switch]$OneFile
)
$ErrorActionPreference = "Stop"

Write-Host "== 1/4 Abhängigkeiten installieren" -ForegroundColor Cyan
python -m pip install --upgrade -r requirements.txt pyinstaller | Out-Null

Write-Host "== 2/4 PyInstaller-Build" -ForegroundColor Cyan
$mpxjLib = python -c "import mpxj, os; print(os.path.join(os.path.dirname(mpxj.__file__), 'lib'))"
$mode = if ($OneFile) { "--onefile" } else { "--onedir" }
python -m PyInstaller --noconfirm --clean --windowed $mode --name mpptool-gui `
    --add-data "$mpxjLib;mpxj/lib" `
    --collect-submodules mpxj --collect-submodules jpype `
    --hidden-import matplotlib.backends.backend_qtagg `
    --hidden-import matplotlib.backends.backend_pdf `
    launcher.py

$dist = Join-Path $PSScriptRoot "dist\mpptool-gui"
if ($OneFile) { $dist = Join-Path $PSScriptRoot "dist" }

if (-not $SkipJre) {
    Write-Host "== 3/4 Portable JRE mit jlink erzeugen (nach $dist\jre)" -ForegroundColor Cyan
    if (-not $env:JAVA_HOME) { throw "JAVA_HOME ist nicht gesetzt – JDK 17+ nötig (oder -SkipJre verwenden)." }
    $jlink = Join-Path $env:JAVA_HOME "bin\jlink.exe"
    if (-not (Test-Path $jlink)) { throw "jlink.exe nicht gefunden unter $jlink – ein vollständiges JDK wird benötigt." }
    $jre = Join-Path $dist "jre"
    if (Test-Path $jre) { Remove-Item $jre -Recurse -Force }
    # java.desktop/java.sql/java.xml werden von MPXJ (POI, Jackcess, JAXB) benötigt
    & $jlink --add-modules java.base,java.desktop,java.sql,java.xml,java.logging,java.naming,java.management,java.scripting,jdk.charsets,jdk.crypto.ec,jdk.zipfs,jdk.unsupported `
        --strip-debug --no-header-files --no-man-pages --compress=2 --output $jre
    Write-Host "   JRE erzeugt: $jre"
} else {
    Write-Host "== 3/4 JRE-Bündelung übersprungen – Zielrechner brauchen installiertes Java (JAVA_HOME)" -ForegroundColor Yellow
}

Write-Host "== 4/4 Zip für die Weitergabe" -ForegroundColor Cyan
$zip = Join-Path $PSScriptRoot "dist\mpptool-gui.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$dist\*" -DestinationPath $zip
Write-Host ""
Write-Host "Fertig:" -ForegroundColor Green
Write-Host "  Anwendung: $dist\mpptool-gui.exe"
Write-Host "  Weitergabe: $zip   (entpacken, mpptool-gui.exe starten, 'Demo-Daten' klicken)"
Write-Host "  ADR-001: Antivirus-/Endpoint-Verhalten auf einem Rechner der Fachabteilungen dokumentieren."
