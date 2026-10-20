"""
Fahrschul-Logbuch — Prototyp
----------------------------
Ein einfaches Webtool für Fahrlehrer, um pro Schüler die gefahrenen
Lektionen, geübten Themen und den Fortschritt zu dokumentieren.

Start:
    pip install -r requirements.txt
    python app.py
Dann im Browser: http://localhost:5000
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, g

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "logbuch.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

app = Flask(__name__)


# ---------- Datenbank-Hilfsfunktionen ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    first_run = not DB_PATH.exists()
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA_PATH.read_text())
    db.commit()
    db.close()
    if first_run:
        print(f"Neue Datenbank angelegt: {DB_PATH}")


# ---------- Übersichtsseite: alle Schüler ----------

@app.route("/")
def index():
    db = get_db()
    schueler = db.execute(
        """
        SELECT s.*,
               COUNT(l.id) AS anzahl_lektionen,
               COALESCE(SUM(l.dauer_minuten), 0) AS total_minuten
        FROM schueler s
        LEFT JOIN lektion l ON l.schueler_id = s.id
        GROUP BY s.id
        ORDER BY s.nachname, s.vorname
        """
    ).fetchall()
    return render_template("index.html", schueler=schueler)


# ---------- Schüler anlegen ----------

@app.route("/schueler/neu", methods=["GET", "POST"])
def schueler_neu():
    if request.method == "POST":
        db = get_db()
        db.execute(
            """
            INSERT INTO schueler (vorname, nachname, email, telefon, lernfahrausweis_nr, status)
            VALUES (?, ?, ?, ?, ?, 'aktiv')
            """,
            (
                request.form["vorname"].strip(),
                request.form["nachname"].strip(),
                request.form.get("email", "").strip(),
                request.form.get("telefon", "").strip(),
                request.form.get("lernfahrausweis_nr", "").strip(),
            ),
        )
        db.commit()
        return redirect(url_for("index"))
    return render_template("schueler_neu.html")


# ---------- Schülerdetail: Verlauf + neue Lektion erfassen ----------

@app.route("/schueler/<int:schueler_id>", methods=["GET", "POST"])
def schueler_detail(schueler_id):
    db = get_db()

    if request.method == "POST":
        dauer = int(request.form["dauer_minuten"])
        datum = request.form["datum"]
        notiz = request.form.get("notiz", "").strip()
        einschaetzung = int(request.form["einschaetzung"])
        thema_ids = request.form.getlist("themen")

        cur = db.execute(
            """
            INSERT INTO lektion (schueler_id, datum, dauer_minuten, notiz, einschaetzung)
            VALUES (?, ?, ?, ?, ?)
            """,
            (schueler_id, datum, dauer, notiz, einschaetzung),
        )
        lektion_id = cur.lastrowid
        for tid in thema_ids:
            db.execute(
                "INSERT INTO lektion_thema (lektion_id, thema_id) VALUES (?, ?)",
                (lektion_id, tid),
            )
        db.commit()
        return redirect(url_for("schueler_detail", schueler_id=schueler_id))

    schueler = db.execute("SELECT * FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
    if schueler is None:
        return redirect(url_for("index"))

    themen = db.execute("SELECT * FROM thema ORDER BY kategorie, bezeichnung").fetchall()
    anzahl_themen_total = len(themen)

    lektionen = db.execute(
        """
        SELECT l.*,
               GROUP_CONCAT(t.bezeichnung, ', ') AS themen_namen
        FROM lektion l
        LEFT JOIN lektion_thema lt ON lt.lektion_id = l.id
        LEFT JOIN thema t ON t.id = lt.thema_id
        WHERE l.schueler_id = ?
        GROUP BY l.id
        ORDER BY l.datum DESC, l.id DESC
        """,
        (schueler_id,),
    ).fetchall()

    # Fortschritt pro Thema: wie oft geübt, letzte Einschätzung
    fortschritt = db.execute(
        """
        SELECT t.id, t.bezeichnung, t.kategorie,
               COUNT(lt.lektion_id) AS anzahl_geuebt,
               MAX(l.einschaetzung) AS beste_einschaetzung,
               (
                   SELECT l2.einschaetzung FROM lektion_thema lt2
                   JOIN lektion l2 ON l2.id = lt2.lektion_id
                   WHERE lt2.thema_id = t.id AND l2.schueler_id = ?
                   ORDER BY l2.datum DESC, l2.id DESC LIMIT 1
               ) AS letzte_einschaetzung
        FROM thema t
        LEFT JOIN lektion_thema lt ON lt.thema_id = t.id
        LEFT JOIN lektion l ON l.id = lt.lektion_id AND l.schueler_id = ?
        GROUP BY t.id
        ORDER BY t.kategorie, t.bezeichnung
        """,
        (schueler_id, schueler_id),
    ).fetchall()

    total_minuten = sum(l["dauer_minuten"] for l in lektionen)
    heute = datetime.now().strftime("%Y-%m-%d")

    anzahl_themen_geuebt = sum(1 for f in fortschritt if f["anzahl_geuebt"] > 0)
    fortschritt_prozent = (
        round(100 * anzahl_themen_geuebt / anzahl_themen_total) if anzahl_themen_total else 0
    )

    return render_template(
        "schueler_detail.html",
        schueler=schueler,
        lektionen=lektionen,
        themen=themen,
        fortschritt=fortschritt,
        total_minuten=total_minuten,
        heute=heute,
        anzahl_themen_total=anzahl_themen_total,
        anzahl_themen_geuebt=anzahl_themen_geuebt,
        fortschritt_prozent=fortschritt_prozent,
    )


# ---------- Schüler bearbeiten (Kontaktdaten + Status) ----------

@app.route("/schueler/<int:schueler_id>/bearbeiten", methods=["GET", "POST"])
def schueler_bearbeiten(schueler_id):
    db = get_db()
    schueler = db.execute("SELECT * FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
    if schueler is None:
        return redirect(url_for("index"))

    if request.method == "POST":
        db.execute(
            """
            UPDATE schueler
            SET vorname = ?, nachname = ?, email = ?, telefon = ?,
                lernfahrausweis_nr = ?, status = ?
            WHERE id = ?
            """,
            (
                request.form["vorname"].strip(),
                request.form["nachname"].strip(),
                request.form.get("email", "").strip(),
                request.form.get("telefon", "").strip(),
                request.form.get("lernfahrausweis_nr", "").strip(),
                request.form["status"],
                schueler_id,
            ),
        )
        db.commit()
        return redirect(url_for("schueler_detail", schueler_id=schueler_id))

    return render_template("schueler_bearbeiten.html", schueler=schueler)


# ---------- Lektion löschen (Korrektur bei Fehleingabe) ----------

@app.route("/lektion/<int:lektion_id>/loeschen", methods=["POST"])
def lektion_loeschen(lektion_id):
    db = get_db()
    row = db.execute("SELECT schueler_id FROM lektion WHERE id = ?", (lektion_id,)).fetchone()
    if row is not None:
        db.execute("DELETE FROM lektion WHERE id = ?", (lektion_id,))
        db.commit()
        return redirect(url_for("schueler_detail", schueler_id=row["schueler_id"]))
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
