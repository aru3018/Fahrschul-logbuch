# Fahrschul-Logbuch — Prototyp

Ein einfaches Webtool für Fahrlehrer: pro Schüler erfassen, welche
Lektionen gefahren wurden, welche Themen geübt wurden und wie der
Fortschritt aussieht.

## Starten

```bash
pip install -r requirements.txt
python app.py
```

Danach im Browser öffnen: http://localhost:5000

Beim ersten Start wird automatisch eine SQLite-Datenbank
(`logbuch.db`) mit dem Themenkatalog angelegt. Diese Datei enthält
alle Daten — für ein Backup reicht es, sie zu kopieren.

## Was der Prototyp kann

- Schüler anlegen (Name, Kontakt, Lernfahrausweis-Nr., Status)
- Pro Lektion erfassen: Datum, Dauer, geübte Themen (aus fester
  Liste wählen), Einschätzung (sicher / Übung nötig / unsicher),
  Notiz
- Übersicht pro Schüler: Gesamtstunden, Verlauf aller Lektionen,
  Fortschritt pro Thema (wie oft geübt, letzte Einschätzung)
- Übersichtsseite aller Schüler mit Status und Gesamtstunden

## Was bewusst fehlt (nächste Ausbaustufen)

- Terminbuchung / Kalender
- Mehrbenutzer-Login (aktuell: jeder mit Zugriff auf die Seite sieht
  alles — für den Einsatz mit mehreren Fahrlehrern braucht es ein
  Login-System)
- Rechnungsstellung
- Export (z. B. PDF-Bericht für den Schüler)

## Wichtig vor dem produktiven Einsatz

Sobald hier echte Schülerdaten gespeichert werden (Name, Kontakt,
evtl. Minderjährige), gilt Datenschutzrecht:

- Der Server darf nicht ohne Zugriffsschutz im offenen Internet
  stehen (mindestens: Login, besser zusätzlich HTTPS).
- Es sollten nur die Daten gespeichert werden, die wirklich nötig
  sind.
- Ein regelmässiges Backup der `logbuch.db` ist Pflicht, nicht nur
  eine gute Idee.

## Technischer Aufbau

- **Backend:** Python mit Flask
- **Datenbank:** SQLite (Datei `logbuch.db`, Schema in `schema.sql`)
- **Frontend:** einfache HTML-Templates (Jinja2) + ein CSS-File,
  kein JavaScript-Framework nötig für diesen Funktionsumfang

```
fahrschule-logbuch/
├── app.py              # Flask-Anwendung mit allen Routen
├── schema.sql          # Datenbankschema + Themenkatalog
├── requirements.txt
├── templates/
│   ├── base.html
│   ├── index.html           # Schüler-Übersicht
│   ├── schueler_neu.html    # Formular: neuer Schüler
│   └── schueler_detail.html # Verlauf + neue Lektion erfassen
└── static/
    └── style.css
```
