#!/usr/bin/env python3
"""
Einmaliges Hilfsskript für die Demo-VM: legt ein paar Test-Schüler an,
verteilt auf verschiedene Fahrlehrer, jeweils mit Fahrzeugzuteilung,
ein paar erledigten Lektionen mit zufälligem Datum in der Vergangenheit
und einem offenen Termin für die nächste Fahrstunde.

NICHT auf dem produktiven aruserver ausführen – das legt sichtbare
Test-Schüler an.

Verwendung (im Projektverzeichnis, mit aktivierter venv):
    python3 scripts/seed_demo_daten.py
"""

import random
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as logbuch  # nutzt dieselbe DB_PATH, Preise und Pauschalen-Logik wie die App

DEMO_SCHUELER = [
    ("Laura", "Brunner", "aru"),
    ("Noah", "Schmid", "aru"),
    ("Mia", "Zimmermann", "Pesche"),
    ("Luca", "Hofer", "Pesche"),
]

EINSCHAETZUNGEN = [1, 2, 3]
DAUERN = [45, 50]
UHRZEITEN = ["08:00", "09:30", "13:00", "15:30", "17:00"]


def main():
    db = sqlite3.connect(logbuch.DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")

    fahrzeuge = [row["name"] for row in db.execute("SELECT name, getriebe FROM fahrzeug ORDER BY name").fetchall()]
    fahrzeug_getriebe = {
        row["name"]: row["getriebe"] for row in db.execute("SELECT name, getriebe FROM fahrzeug").fetchall()
    }
    if not fahrzeuge:
        print("Keine Fahrzeuge in der Flotte gefunden — bitte zuerst über /admin/fahrzeuge welche anlegen.")
        return

    heute = datetime.now()

    for i, (vorname, nachname, fahrlehrer) in enumerate(DEMO_SCHUELER):
        fahrzeug = fahrzeuge[i % len(fahrzeuge)]
        getriebe = fahrzeug_getriebe[fahrzeug]

        cur = db.execute(
            """
            INSERT INTO schueler (vorname, nachname, status, erstellt_von, fahrzeug, getriebe)
            VALUES (?, ?, 'aktiv', ?, ?, ?)
            """,
            (vorname, nachname, fahrlehrer, fahrzeug, getriebe),
        )
        schueler_id = cur.lastrowid

        # Pauschalen, genau wie bei einer echten Anmeldung über die App
        for bezeichnung, betrag in logbuch.PAUSCHALEN_BEI_ANMELDUNG:
            db.execute(
                "INSERT INTO rechnungsposition (schueler_id, bezeichnung, betrag) VALUES (?, ?, ?)",
                (schueler_id, bezeichnung, betrag),
            )

        # 2–4 erledigte Lektionen mit zufälligem Datum in der Vergangenheit
        anzahl_lektionen = random.randint(2, 4)
        for _ in range(anzahl_lektionen):
            tage_zurueck = random.randint(1, 60)
            datum = (heute - timedelta(days=tage_zurueck)).strftime("%Y-%m-%d")
            dauer = random.choice(DAUERN)
            preis = round(dauer * logbuch.LEKTION_PREIS_PRO_MINUTE, 2)
            bezahlt = random.choice([0, 1])
            einschaetzung = random.choice(EINSCHAETZUNGEN)
            db.execute(
                """
                INSERT INTO lektion (schueler_id, datum, dauer_minuten, einschaetzung, typ, preis, bezahlt)
                VALUES (?, ?, ?, ?, 'normal', ?, ?)
                """,
                (schueler_id, datum, dauer, einschaetzung, preis, bezahlt),
            )

        # Ein offener Termin für die nächste Fahrstunde
        tage_voraus = random.randint(1, 14)
        termin_datum = (heute + timedelta(days=tage_voraus)).strftime("%Y-%m-%d")
        db.execute(
            "INSERT INTO termin (schueler_id, datum, uhrzeit) VALUES (?, ?, ?)",
            (schueler_id, termin_datum, random.choice(UHRZEITEN)),
        )

        db.execute(
            "INSERT INTO audit_log (benutzer, aktion, details) VALUES (?, ?, ?)",
            ("System (Seed-Skript)", "Schüler erstellt", f"{vorname} {nachname} (Demo-Daten, ID {schueler_id})"),
        )

        print(
            f"Angelegt: {vorname} {nachname} ({fahrlehrer}), Fahrzeug: {fahrzeug}, "
            f"{anzahl_lektionen} Lektionen, nächster Termin am {termin_datum}"
        )

    db.commit()
    db.close()
    print("Fertig.")


if __name__ == "__main__":
    main()
