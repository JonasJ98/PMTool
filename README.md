# MPP-Auswertungstool – Prototyp

Einlesen, Historisierung und Bewertung von MS-Project-Dateien (.mpp) mehrerer
Fachabteilungen und automatische Erzeugung des PJM-Project-Review-Foliensatzes
(PPTX/PDF). Desktop-Anwendung gemäß ADR-001 (Python, PySide6, MPXJ via JPype).

## Voraussetzungen

- Python 3.10+
- Java-Laufzeitumgebung (JDK/JRE 11+), `JAVA_HOME` gesetzt – MPXJ ist eine
  Java-Bibliothek; ohne Java funktionieren Demo-Daten, Bewertung und Export,
  aber kein Datei-Import.

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

## Schnellstart

```powershell
python -m mpptool.main gui            # Desktop-Oberfläche (oder .\run_gui.ps1)
python -m mpptool.main demo           # 6 synthetische Wochen in die Datenbank laden
python -m mpptool.main report --out output\review.pptx
python -m pytest                      # Tests
```

Ablauf in der Oberfläche: **1. Input** (Datei importieren oder Demo-Daten) →
**2. Vergleichsauswahl** (Snapshots ankreuzen; der jüngste ist „aktuell“, der
davor „Vorwoche“) → **3. Vorschau** (Tabs: Übersicht, Master Timeline,
Abteilungen, Überfällige, Trend-Tabelle, Aufgabenliste) → **4. Export** PPTX/PDF.

## Weitere Befehle

```powershell
python -m mpptool.main import Plan.mpp --date 2026-09-04 --label "KW36"
python -m mpptool.main list
python -m mpptool.main delete 3 4
python -m mpptool.main report --ids 5 6 --out output\review.pdf --name "Charging Cable"
python -m mpptool.main report --report-date 2026-09-15   # Stichtag explizit setzen (Standard: heute)
python -m mpptool.main demo-files .\demo     # Demo-Stände als MSPDI-XML (Master + Unterdatei)
python -m mpptool.inspect_fields Plan.mpp     # belegte Textfelder / Ressourcengruppen anzeigen
```

## Aufbau

| Modul | Aufgabe |
| --- | --- |
| `mpptool/config.py` | Stellschrauben: Abteilungsfeld, Aliasse, Hold-Erkennung, Unterdatei-Suche, Filter |
| `mpptool/model.py` | `TaskRecord`, `Snapshot`, `TaskStatus` |
| `mpptool/reader.py` | MPXJ-Zugriff (JPype), Unterdatei-Auflösung, Konvertierung nach `TaskRecord` |
| `mpptool/snapshot_store.py` | SQLite-Historisierung (`data/snapshots.sqlite`) |
| `mpptool/metrics.py` | Statuslogik (Open/Open Overdue/Closed/Closed Overdue/Hold), Kennzahlen, Wochenvergleich |
| `mpptool/charts.py` | matplotlib-Diagramme (Vorschau und Export identisch) |
| `mpptool/report.py` | `build_review`, `export_pptx`, `export_pdf` |
| `mpptool/demo_data.py` | synthetischer 6-Wochen-Verlauf, auch als MSPDI-Dateien |
| `mpptool/gui/` | PySide6-Oberfläche |
| `mpptool/main.py` | CLI |
| `build.ps1` | PyInstaller-Build für den Packaging-/Antivirus-Test (ADR-001) |

## Statuslogik

Stichtag = Snapshot-Datum; für den **aktuellen** Vergleichspunkt eines Berichts
immer der **Auswertungstag** (Tag der Berichtserstellung, siehe unten) –
unabhängig von der Kalenderwoche des zuletzt importierten Standes.
Referenzende = Basisplan-Ende, sonst geplantes Ende.

| Status | Regel |
| --- | --- |
| Cancelled | Aufgabe storniert (Cancel-Textfeld gesetzt, `config.CANCEL_TEXT_FIELD_INDEX`) |
| Hold | Aufgabe inaktiv (`Active = Nein`) oder Hold-Textfeld gesetzt |
| Closed | abgeschlossen, tatsächliches Ende ≤ Referenzende |
| Closed Overdue | abgeschlossen, tatsächliches Ende > Referenzende |
| Open | nicht abgeschlossen, geplantes Ende ≥ Stichtag |
| Open Overdue | nicht abgeschlossen, geplantes Ende < Stichtag |

Erfüllungsgrad = tatsächlich geschlossen / laut Plan bis Stichtag geschlossen.
Sammelvorgänge und externe Platzhalter werden herausgefiltert (konfigurierbar).

### Gezählte Vorgänge: Aufgabe vs. Meilenstein

Gezählt werden nur **Aufgaben mit Dauer > 0** und **Meilensteine** (MS-Project-
Meilenstein-Flag). Sammelvorgänge sowie sonstige Vorgänge mit Dauer 0, die kein
Meilenstein sind (z. B. Sammelaufgaben ohne eigene Dauer), fallen aus allen
Kennzahlen heraus (`config.EXCLUDE_ZERO_DURATION_NON_MILESTONES`,
`TaskRecord.is_countable`).

Die Dauer kommt aus dem MS-Project-Feld „Dauer“ (beim Import eingelesen), sodass
auch 1-Tages-Aufgaben korrekt zählen. Snapshots, die vor dieser Umstellung
importiert wurden, haben das Feld nicht; dort wird auf Ende − Start (Kalendertage)
zurückgefallen – 1-Tages-Aufgaben fallen dann heraus. Für korrekte Zahlen solche
Snapshots einmal neu importieren.

### Ressourcengruppen-Auswahl

In der GUI listet „Ressourcengruppen“ (unten links) alle Gruppen der angekreuzten
Snapshots. Die An-/Abwahl wirkt sofort auf die Vorschau und gleichermaßen auf den
Export, und zwar auf die Gruppen-Folien: Aufgaben je Fachabteilung, Überfällige je
Fachabteilung, Top-Overdues und Liste überfälliger Aufgaben (Titelzusatz
„Auswahl: n von m Gruppen“). Übersicht und Master Timeline zeigen weiterhin das
Gesamtprojekt.

### Projektende-Trend

Folie „Projektende-Trend“: erwartetes Projektende je Snapshot = spätestes geplantes
Ende aller gezählten Vorgänge im Datenstand der Datei, chronologisch nach
Snapshot-Datum. An jedem Punkt stehen Datum und Verschiebung zum vorherigen Stand
in Tagen; gestrichelt das späteste Basisplan-Ende als Referenz (falls vorhanden).
Die Folie zeigt immer das Gesamtprojekt (unabhängig von der Gruppenauswahl).

### Auswertungstag und Vergleich

Das Reporting ist **KW-unabhängig**: Der Stichtag des aktuellen Vergleichspunkts
ist immer der Tag, an dem der Bericht erzeugt wird (Auswertungstag = heute, per
`--report-date` überschreibbar), nicht das interne Statusdatum der zuletzt
importierten Datei. Der Vergleich erfolgt immer gegen den letzten (chronologisch
vorherigen) Stichtag der ausgewählten Snapshots.

### Top-Overdues mit Trendanalyse

Die Top-N-Überfällig-Tabelle zeigt neben Vorwoche/Aktuell und Trendpfeil auch den
Verlauf (Sparkline) der überfälligen Aufgaben je Fachabteilung über alle im
Vergleich enthaltenen Snapshots.

## Weitergabe als .exe (Team-Test)

```powershell
.\build.ps1            # erzeugt dist\mpptool-gui\ (mit portabler JRE) und dist\mpptool-gui.zip
.\build.ps1 -SkipJre   # ohne JRE – Zielrechner brauchen dann installiertes Java
```

Zum Bauen wird ein JDK 17+ mit `jlink` benötigt (`JAVA_HOME` gesetzt); die Empfänger
brauchen nichts außer dem entpackten Zip: `mpptool-gui.exe` starten, „Demo-Daten“ klicken.
Die gepackte Anwendung legt ihre Datenbank unter `%LOCALAPPDATA%\mpptool\data` und
Exporte unter `Dokumente\mpptool` ab. Eine portable JRE wird im Ordner `jre` neben der
.exe gesucht (alternativ Umgebungsvariable `MPPTOOL_JRE`).

Der erste Start auf einem Rechner der Fachabteilungen ist zugleich der Packaging-Test
aus ADR-001: Antivirus-/Endpoint-Meldungen dokumentieren.

## Offene Punkte

Führendes Backlog: [`docs/Backlog_MPP_Auswertungstool.docx`](docs/Backlog_MPP_Auswertungstool.docx)
(zusätzlich als `.odt`). Bei Änderungen am Tool dort mitpflegen und mitcommitten;
eine Kopie für den Auftraggeber liegt auf dem K:-Laufwerk.


1. `DEPARTMENT_TEXT_FIELD_INDEX` an einer echten .mpp mit `inspect_fields` bestimmen.
2. Import gegen echte Master-Datei mit Teilprojekten prüfen (Konsole/Dialog auf Warnungen achten).
3. Packaging-Test mit `build.ps1` auf einem Rechner mit Endpoint-Security der Fachabteilungen.
4. Abteilungsübergreifende Kapazitätsplanung.
