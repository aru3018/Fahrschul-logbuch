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

import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, g, session, abort

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "logbuch.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

app = Flask(__name__)
# Für Produktivbetrieb sollte der Secret Key über eine Umgebungsvariable
# gesetzt werden (z. B. FLASK_SECRET_KEY=... in der systemd-Unit), damit
# Sessions auch nach einem Neustart gültig bleiben.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-key-bitte-in-produktion-ersetzen")

# ---------- Login (Prototyp: feste Konten) ----------

BENUTZER = {
    "aru": {"passwort": "Test123", "rolle": "user", "anzeigename": "Aru"},
    "Viji": {"passwort": "Viji1$", "rolle": "user", "anzeigename": "Viji"},
    "Administrator": {"passwort": "Admin$1", "rolle": "admin", "anzeigename": "Administrator"},
}


def login_erforderlich(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "benutzer" not in session:
            return redirect(url_for("login", weiter=request.path))
        return view(*args, **kwargs)
    return wrapper


def admin_erforderlich(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "benutzer" not in session:
            return redirect(url_for("login", weiter=request.path))
        if session.get("rolle") != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapper


def pruefe_zugriff(schueler):
    """Bricht mit 403 ab, falls der eingeloggte Benutzer diesen Schüler
    weder selbst erstellt hat noch Administrator ist."""
    if session.get("rolle") != "admin" and schueler["erstellt_von"] != session.get("benutzer"):
        abort(403)


@app.route("/login", methods=["GET", "POST"])
def login():
    fehler = None
    if request.method == "POST":
        name = request.form.get("benutzername", "").strip()
        passwort = request.form.get("passwort", "")
        konto = BENUTZER.get(name)
        if konto and konto["passwort"] == passwort:
            session["benutzer"] = name
            session["rolle"] = konto["rolle"]
            session["anzeigename"] = konto["anzeigename"]
            standardziel = url_for("admin_dashboard") if konto["rolle"] == "admin" else url_for("index")
            ziel = request.form.get("weiter") or standardziel
            return redirect(ziel)
        fehler = "Benutzername oder Passwort ist falsch."
    weiter = request.args.get("weiter", "")
    return render_template("login.html", fehler=fehler, weiter=weiter)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


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

    # Migration für bestehende Datenbanken (vor Einführung der Login-Trennung
    # angelegt): Spalte "erstellt_von" nachträglich ergänzen, falls sie fehlt.
    spalten = [row[1] for row in db.execute("PRAGMA table_info(schueler)").fetchall()]
    if "erstellt_von" not in spalten:
        db.execute("ALTER TABLE schueler ADD COLUMN erstellt_von TEXT NOT NULL DEFAULT 'aru'")

    db.commit()
    db.close()
    if first_run:
        print(f"Neue Datenbank angelegt: {DB_PATH}")


# ---------- Übersichtsseite: alle Schüler ----------

@app.route("/")
@login_erforderlich
def index():
    db = get_db()
    ist_admin = session.get("rolle") == "admin"

    basis_query = """
        SELECT s.*,
               COUNT(l.id) AS anzahl_lektionen,
               COALESCE(SUM(l.dauer_minuten), 0) AS total_minuten
        FROM schueler s
        LEFT JOIN lektion l ON l.schueler_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY s.nachname, s.vorname
    """
    if ist_admin:
        schueler = db.execute(basis_query.format(where="")).fetchall()
    else:
        schueler = db.execute(
            basis_query.format(where="WHERE s.erstellt_von = ?"),
            (session["benutzer"],),
        ).fetchall()

    return render_template("index.html", schueler=schueler, ist_admin=ist_admin)


# ---------- Schüler anlegen ----------

@app.route("/schueler/neu", methods=["GET", "POST"])
@login_erforderlich
def schueler_neu():
    if request.method == "POST":
        db = get_db()
        db.execute(
            """
            INSERT INTO schueler (vorname, nachname, email, telefon, lernfahrausweis_nr, status, erstellt_von)
            VALUES (?, ?, ?, ?, ?, 'aktiv', ?)
            """,
            (
                request.form["vorname"].strip(),
                request.form["nachname"].strip(),
                request.form.get("email", "").strip(),
                request.form.get("telefon", "").strip(),
                request.form.get("lernfahrausweis_nr", "").strip(),
                session["benutzer"],
            ),
        )
        db.commit()
        return redirect(url_for("index"))
    return render_template("schueler_neu.html")


# ---------- Schülerdetail: Verlauf + neue Lektion erfassen ----------

@app.route("/schueler/<int:schueler_id>", methods=["GET", "POST"])
@login_erforderlich
def schueler_detail(schueler_id):
    db = get_db()

    schueler_pruefung = db.execute("SELECT * FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
    if schueler_pruefung is None:
        return redirect(url_for("index"))
    pruefe_zugriff(schueler_pruefung)

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

    schueler = schueler_pruefung

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
@login_erforderlich
def schueler_bearbeiten(schueler_id):
    db = get_db()
    schueler = db.execute("SELECT * FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
    if schueler is None:
        return redirect(url_for("index"))
    pruefe_zugriff(schueler)

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
@login_erforderlich
def lektion_loeschen(lektion_id):
    db = get_db()
    row = db.execute(
        """
        SELECT l.schueler_id, s.erstellt_von
        FROM lektion l JOIN schueler s ON s.id = l.schueler_id
        WHERE l.id = ?
        """,
        (lektion_id,),
    ).fetchone()
    if row is not None:
        pruefe_zugriff(row)
        db.execute("DELETE FROM lektion WHERE id = ?", (lektion_id,))
        db.commit()
        return redirect(url_for("schueler_detail", schueler_id=row["schueler_id"]))
    return redirect(url_for("index"))


# ---------- Admin-Dashboard ----------

@app.route("/admin")
@admin_erforderlich
def admin_dashboard():
    db = get_db()

    gesamt = db.execute(
        """
        SELECT COUNT(DISTINCT s.id) AS anzahl_schueler,
               COUNT(l.id) AS anzahl_lektionen,
               COALESCE(SUM(l.dauer_minuten), 0) AS total_minuten
        FROM schueler s
        LEFT JOIN lektion l ON l.schueler_id = s.id
        """
    ).fetchone()

    pro_fahrlehrer = db.execute(
        """
        SELECT s.erstellt_von AS benutzer,
               COUNT(DISTINCT s.id) AS anzahl_schueler,
               COUNT(l.id) AS anzahl_lektionen,
               COALESCE(SUM(l.dauer_minuten), 0) AS total_minuten
        FROM schueler s
        LEFT JOIN lektion l ON l.schueler_id = s.id
        GROUP BY s.erstellt_von
        ORDER BY s.erstellt_von
        """
    ).fetchall()

    alle_schueler = db.execute(
        """
        SELECT s.*,
               COUNT(l.id) AS anzahl_lektionen,
               COALESCE(SUM(l.dauer_minuten), 0) AS total_minuten
        FROM schueler s
        LEFT JOIN lektion l ON l.schueler_id = s.id
        GROUP BY s.id
        ORDER BY s.erstellt_von, s.nachname, s.vorname
        """
    ).fetchall()

    benutzerkonten = [
        {"benutzername": name, **{k: v for k, v in daten.items() if k != "passwort"}}
        for name, daten in BENUTZER.items()
    ]

    gesamt_stunden = round((gesamt["total_minuten"] or 0) / 60, 1)

    return render_template(
        "admin_dashboard.html",
        gesamt=gesamt,
        gesamt_stunden=gesamt_stunden,
        pro_fahrlehrer=pro_fahrlehrer,
        alle_schueler=alle_schueler,
        benutzerkonten=benutzerkonten,
    )


@app.errorhandler(403)
def kein_zugriff(e):
    return render_template("403.html"), 403


# Datenbank immer initialisieren, wenn das Modul geladen wird – nicht nur
# beim direkten Start per "python app.py". Das ist wichtig für den Betrieb
# über einen WSGI-Server wie gunicorn, der die App nur importiert und daher
# den "__main__"-Block sonst nie ausführen würde.
init_db()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
