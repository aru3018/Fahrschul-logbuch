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

import io
import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, render_template, request, redirect, url_for, g, session, abort, send_file

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "logbuch.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

app = Flask(__name__)
# Für Produktivbetrieb sollte der Secret Key über eine Umgebungsvariable
# gesetzt werden (z. B. FLASK_SECRET_KEY=... in der systemd-Unit), damit
# Sessions auch nach einem Neustart gültig bleiben.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-key-bitte-in-produktion-ersetzen")

# ---------- Login (Prototyp: feste Konten) ----------

# Start-Fuhrpark, mit dem die "fahrzeug"-Tabelle beim ersten Start befüllt
# wird. Danach läuft die Verwaltung über das Admin-UI (/admin/fahrzeuge).
FAHRZEUGE_STANDARD = {
    "VW Golf GTI": "Automatik",
    "VW Golf": "Automatik",
    "Seat": "Geschaltet",
    "VW T-Roc": "Automatik",
}

BENUTZER = {
    "aru": {"passwort": "Test123", "rolle": "user", "anzeigename": "Aru"},
    "Pesche": {"passwort": "Pesche1", "rolle": "user", "anzeigename": "Pesche"},
    "Administrator": {"passwort": "Admin$1", "rolle": "admin", "anzeigename": "Administrator"},
}

# Liste der Fahrlehrer-Benutzernamen (ohne Admin-Konten) – wird für die
# manuelle Fahrlehrer-Zuteilung durch den Admin verwendet.
FAHRLEHRER_LISTE = [name for name, daten in BENUTZER.items() if daten["rolle"] != "admin"]


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


def hole_fahrzeuge(db):
    """Aktuelle Fahrzeugflotte aus der DB als {Name: Getriebeart}-Dict,
    damit bestehende Templates (Formulare, JS-Auto-Select) unverändert
    funktionieren."""
    return {
        row["name"]: row["getriebe"]
        for row in db.execute("SELECT name, getriebe FROM fahrzeug ORDER BY name").fetchall()
    }


def log_aktion(db, aktion, details=""):
    """Schreibt einen Eintrag ins Audit-Log (nur für den Admin einsehbar)."""
    db.execute(
        "INSERT INTO audit_log (benutzer, aktion, details) VALUES (?, ?, ?)",
        (session.get("benutzer", "system"), aktion, details),
    )


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
    if "fahrzeug" not in spalten:
        db.execute("ALTER TABLE schueler ADD COLUMN fahrzeug TEXT")
    if "getriebe" not in spalten:
        db.execute("ALTER TABLE schueler ADD COLUMN getriebe TEXT")
    if "theorie_pruefung_datum" not in spalten:
        db.execute("ALTER TABLE schueler ADD COLUMN theorie_pruefung_datum TEXT")
    if "praxis_pruefung_datum" not in spalten:
        db.execute("ALTER TABLE schueler ADD COLUMN praxis_pruefung_datum TEXT")
    if "archiviert" not in spalten:
        db.execute("ALTER TABLE schueler ADD COLUMN archiviert INTEGER NOT NULL DEFAULT 0")

    lektion_spalten = [row[1] for row in db.execute("PRAGMA table_info(lektion)").fetchall()]
    if "typ" not in lektion_spalten:
        db.execute("ALTER TABLE lektion ADD COLUMN typ TEXT NOT NULL DEFAULT 'normal'")
    if "preis" not in lektion_spalten:
        db.execute("ALTER TABLE lektion ADD COLUMN preis REAL NOT NULL DEFAULT 0")
    if "bezahlt" not in lektion_spalten:
        db.execute("ALTER TABLE lektion ADD COLUMN bezahlt INTEGER NOT NULL DEFAULT 0")

    # Fuhrpark-Tabelle beim ersten Start mit dem Standard-Fuhrpark befüllen.
    for name, getriebe in FAHRZEUGE_STANDARD.items():
        db.execute("INSERT OR IGNORE INTO fahrzeug (name, getriebe) VALUES (?, ?)", (name, getriebe))

    # Konto "Viji" wurde durch "Pesche" ersetzt – bisherige Schüler von Viji
    # werden automatisch Pesche zugeordnet, statt verwaist zu sein.
    db.execute("UPDATE schueler SET erstellt_von = 'Pesche' WHERE erstellt_von = 'Viji'")

    # Fuhrpark wurde ersetzt (Tesla Model 3 / Mercedes-Benz A43 ausgemustert) –
    # Schüler mit einem der alten Fahrzeuge verlieren die Zuweisung, statt auf
    # ein nicht mehr existierendes Fahrzeug zu verweisen.
    db.execute(
        "UPDATE schueler SET fahrzeug = NULL, getriebe = NULL "
        "WHERE fahrzeug IN ('Tesla Model 3', 'Mercedes-Benz A43')"
    )

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
    suche = request.args.get("q", "").strip()
    zeige_archiviert = request.args.get("archiviert") == "1"

    bedingungen = []
    parameter = []

    if not ist_admin:
        bedingungen.append("s.erstellt_von = ?")
        parameter.append(session["benutzer"])

    if not zeige_archiviert:
        bedingungen.append("s.archiviert = 0")

    if suche:
        bedingungen.append("(s.vorname LIKE ? OR s.nachname LIKE ?)")
        parameter.extend([f"%{suche}%", f"%{suche}%"])

    where = ("WHERE " + " AND ".join(bedingungen)) if bedingungen else ""

    basis_query = f"""
        SELECT s.*,
               COUNT(l.id) AS anzahl_lektionen,
               COALESCE(SUM(l.dauer_minuten), 0) AS total_minuten,
               COALESCE(SUM(CASE WHEN l.bezahlt = 0 THEN l.preis ELSE 0 END), 0) AS offener_betrag
        FROM schueler s
        LEFT JOIN lektion l ON l.schueler_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY s.nachname, s.vorname
    """
    schueler = db.execute(basis_query, parameter).fetchall()

    return render_template(
        "index.html",
        schueler=schueler,
        ist_admin=ist_admin,
        suche=suche,
        zeige_archiviert=zeige_archiviert,
    )


# ---------- Schüler anlegen ----------

@app.route("/schueler/neu", methods=["GET", "POST"])
@login_erforderlich
def schueler_neu():
    ist_admin = session.get("rolle") == "admin"
    db = get_db()

    if request.method == "POST":
        # Admins können den Schüler direkt einem Fahrlehrer zuteilen,
        # normale Fahrlehrer legen den Schüler immer bei sich selbst an.
        erstellt_von = session["benutzer"]
        if ist_admin:
            gewaehlt = request.form.get("fahrlehrer", "").strip()
            if gewaehlt in FAHRLEHRER_LISTE:
                erstellt_von = gewaehlt

        cur = db.execute(
            """
            INSERT INTO schueler
                (vorname, nachname, email, telefon, lernfahrausweis_nr, status, erstellt_von,
                 fahrzeug, getriebe, theorie_pruefung_datum, praxis_pruefung_datum)
            VALUES (?, ?, ?, ?, ?, 'aktiv', ?, ?, ?, ?, ?)
            """,
            (
                request.form["vorname"].strip(),
                request.form["nachname"].strip(),
                request.form.get("email", "").strip(),
                request.form.get("telefon", "").strip(),
                request.form.get("lernfahrausweis_nr", "").strip(),
                erstellt_von,
                request.form.get("fahrzeug", "").strip(),
                request.form.get("getriebe", "").strip(),
                request.form.get("theorie_pruefung_datum", "").strip() or None,
                request.form.get("praxis_pruefung_datum", "").strip() or None,
            ),
        )
        log_aktion(
            db, "Schüler erstellt",
            f"{request.form['vorname'].strip()} {request.form['nachname'].strip()} (ID {cur.lastrowid}), Fahrlehrer: {erstellt_von}",
        )
        db.commit()
        return redirect(url_for("admin_dashboard") if ist_admin else url_for("index"))
    return render_template(
        "schueler_neu.html",
        fahrzeuge=hole_fahrzeuge(db),
        ist_admin=ist_admin,
        fahrlehrer_liste=FAHRLEHRER_LISTE,
    )


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
        lektion_typ = request.form.get("lektion_typ", "normal")
        if lektion_typ not in ("probe", "normal"):
            lektion_typ = "normal"

        try:
            preis = float(request.form.get("preis", "0").replace(",", ".") or 0)
        except ValueError:
            preis = 0
        bezahlt = 1 if request.form.get("bezahlt") else 0

        cur = db.execute(
            """
            INSERT INTO lektion (schueler_id, datum, dauer_minuten, notiz, einschaetzung, typ, preis, bezahlt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (schueler_id, datum, dauer, notiz, einschaetzung, lektion_typ, preis, bezahlt),
        )
        lektion_id = cur.lastrowid
        log_aktion(
            db, "Lektion erfasst",
            f"Schüler-ID {schueler_id}, {datum}, {dauer} Min., {lektion_typ}",
        )
        for tid in thema_ids:
            db.execute(
                "INSERT INTO lektion_thema (lektion_id, thema_id) VALUES (?, ?)",
                (lektion_id, tid),
            )

        # Bei einer normalen Lektion kann direkt der nächste Termin geplant werden.
        naechster_termin_datum = request.form.get("naechster_termin_datum", "").strip()
        if lektion_typ == "normal" and naechster_termin_datum:
            db.execute(
                """
                INSERT INTO termin (schueler_id, datum, uhrzeit, geplante_themen)
                VALUES (?, ?, ?, ?)
                """,
                (
                    schueler_id,
                    naechster_termin_datum,
                    request.form.get("naechster_termin_zeit", "").strip(),
                    request.form.get("naechster_termin_themen", "").strip(),
                ),
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

    offene_termine = db.execute(
        """
        SELECT * FROM termin
        WHERE schueler_id = ? AND erledigt = 0
        ORDER BY datum, uhrzeit
        """,
        (schueler_id,),
    ).fetchall()

    total_minuten = sum(l["dauer_minuten"] for l in lektionen)
    heute = datetime.now().strftime("%Y-%m-%d")

    anzahl_themen_geuebt = sum(1 for f in fortschritt if f["anzahl_geuebt"] > 0)
    fortschritt_prozent = (
        round(100 * anzahl_themen_geuebt / anzahl_themen_total) if anzahl_themen_total else 0
    )

    total_betrag = sum(l["preis"] for l in lektionen)
    offener_betrag = sum(l["preis"] for l in lektionen if not l["bezahlt"])

    return render_template(
        "schueler_detail.html",
        schueler=schueler,
        lektionen=lektionen,
        themen=themen,
        fortschritt=fortschritt,
        offene_termine=offene_termine,
        total_minuten=total_minuten,
        heute=heute,
        anzahl_themen_total=anzahl_themen_total,
        anzahl_themen_geuebt=anzahl_themen_geuebt,
        fortschritt_prozent=fortschritt_prozent,
        total_betrag=total_betrag,
        offener_betrag=offener_betrag,
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
    ist_admin = session.get("rolle") == "admin"

    if request.method == "POST":
        # Nur Admins dürfen hier den zuständigen Fahrlehrer umstellen.
        erstellt_von = schueler["erstellt_von"]
        if ist_admin:
            gewaehlt = request.form.get("fahrlehrer", "").strip()
            if gewaehlt in FAHRLEHRER_LISTE:
                erstellt_von = gewaehlt

        db.execute(
            """
            UPDATE schueler
            SET vorname = ?, nachname = ?, email = ?, telefon = ?,
                lernfahrausweis_nr = ?, status = ?, fahrzeug = ?, getriebe = ?,
                erstellt_von = ?, theorie_pruefung_datum = ?, praxis_pruefung_datum = ?
            WHERE id = ?
            """,
            (
                request.form["vorname"].strip(),
                request.form["nachname"].strip(),
                request.form.get("email", "").strip(),
                request.form.get("telefon", "").strip(),
                request.form.get("lernfahrausweis_nr", "").strip(),
                request.form["status"],
                request.form.get("fahrzeug", "").strip(),
                request.form.get("getriebe", "").strip(),
                erstellt_von,
                request.form.get("theorie_pruefung_datum", "").strip() or None,
                request.form.get("praxis_pruefung_datum", "").strip() or None,
                schueler_id,
            ),
        )
        log_aktion(db, "Schüler bearbeitet", f"{schueler['vorname']} {schueler['nachname']} (ID {schueler_id})")
        db.commit()
        return redirect(url_for("schueler_detail", schueler_id=schueler_id))

    return render_template(
        "schueler_bearbeiten.html",
        schueler=schueler,
        fahrzeuge=hole_fahrzeuge(db),
        ist_admin=ist_admin,
        fahrlehrer_liste=FAHRLEHRER_LISTE,
    )


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
        log_aktion(db, "Lektion gelöscht", f"Lektion-ID {lektion_id}, Schüler-ID {row['schueler_id']}")
        db.commit()
        return redirect(url_for("schueler_detail", schueler_id=row["schueler_id"]))
    return redirect(url_for("index"))


# ---------- Lektion als bezahlt / offen markieren ----------

@app.route("/lektion/<int:lektion_id>/bezahlt", methods=["POST"])
@login_erforderlich
def lektion_bezahlt_umschalten(lektion_id):
    db = get_db()
    row = db.execute(
        """
        SELECT l.schueler_id, l.bezahlt, s.erstellt_von
        FROM lektion l JOIN schueler s ON s.id = l.schueler_id
        WHERE l.id = ?
        """,
        (lektion_id,),
    ).fetchone()
    if row is not None:
        pruefe_zugriff(row)
        neuer_status = 0 if row["bezahlt"] else 1
        db.execute("UPDATE lektion SET bezahlt = ? WHERE id = ?", (neuer_status, lektion_id))
        db.commit()
        return redirect(url_for("schueler_detail", schueler_id=row["schueler_id"]))
    return redirect(url_for("index"))


# ---------- Schüler archivieren / reaktivieren (Soft-Delete) ----------

@app.route("/schueler/<int:schueler_id>/archivieren", methods=["POST"])
@login_erforderlich
def schueler_archivieren(schueler_id):
    db = get_db()
    schueler = db.execute("SELECT * FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
    if schueler is None:
        return redirect(url_for("index"))
    pruefe_zugriff(schueler)

    neuer_status = 0 if schueler["archiviert"] else 1
    db.execute("UPDATE schueler SET archiviert = ? WHERE id = ?", (neuer_status, schueler_id))
    log_aktion(
        db,
        "Schüler archiviert" if neuer_status else "Schüler reaktiviert",
        f"{schueler['vorname']} {schueler['nachname']} (ID {schueler_id})",
    )
    db.commit()
    return redirect(url_for("schueler_detail", schueler_id=schueler_id))


# ---------- PDF-Export: Fortschrittsbericht eines Schülers ----------

@app.route("/schueler/<int:schueler_id>/pdf")
@login_erforderlich
def schueler_pdf(schueler_id):
    db = get_db()
    schueler = db.execute("SELECT * FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
    if schueler is None:
        return redirect(url_for("index"))
    pruefe_zugriff(schueler)

    lektionen = db.execute(
        """
        SELECT l.*, GROUP_CONCAT(t.bezeichnung, ', ') AS themen_namen
        FROM lektion l
        LEFT JOIN lektion_thema lt ON lt.lektion_id = l.id
        LEFT JOIN thema t ON t.id = lt.thema_id
        WHERE l.schueler_id = ?
        GROUP BY l.id
        ORDER BY l.datum, l.id
        """,
        (schueler_id,),
    ).fetchall()

    fortschritt = db.execute(
        """
        SELECT t.bezeichnung, t.kategorie,
               COUNT(lt.lektion_id) AS anzahl_geuebt,
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

    einschaetzung_text = {1: "unsicher", 2: "Übung nötig", 3: "sicher", None: "noch nicht geübt"}
    total_minuten = sum(l["dauer_minuten"] for l in lektionen)

    puffer = io.BytesIO()
    doc = SimpleDocTemplate(puffer, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
    stile = getSampleStyleSheet()
    elemente = [
        Paragraph("Fahrschule Bern — Fortschrittsbericht", stile["Title"]),
        Paragraph(f"{schueler['vorname']} {schueler['nachname']}", stile["Heading2"]),
        Paragraph(
            f"Status: {schueler['status'].replace('_', ' ')} &nbsp;|&nbsp; "
            f"Fahrzeug: {schueler['fahrzeug'] or '–'} &nbsp;|&nbsp; "
            f"Lektionen: {len(lektionen)} &nbsp;|&nbsp; Fahrzeit: {round(total_minuten / 60, 1)} h",
            stile["Normal"],
        ),
        Spacer(1, 0.6 * cm),
        Paragraph("Fortschritt pro Thema", stile["Heading3"]),
    ]

    fortschritt_daten = [["Thema", "Kategorie", "Geübt", "Letzte Einschätzung"]]
    for f in fortschritt:
        fortschritt_daten.append([
            f["bezeichnung"], f["kategorie"], f["anzahl_geuebt"],
            einschaetzung_text.get(f["letzte_einschaetzung"], "–"),
        ])
    fortschritt_tabelle = Table(fortschritt_daten, repeatRows=1, hAlign="LEFT")
    fortschritt_tabelle.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243d84")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f5f7")]),
    ]))
    elemente.append(fortschritt_tabelle)
    elemente.append(Spacer(1, 0.8 * cm))
    elemente.append(Paragraph("Lektionsverlauf", stile["Heading3"]))

    verlauf_daten = [["Datum", "Typ", "Dauer", "Themen", "Einschätzung", "Notiz"]]
    for l in lektionen:
        verlauf_daten.append([
            l["datum"],
            "Probe" if l["typ"] == "probe" else "Normal",
            f"{l['dauer_minuten']} min",
            l["themen_namen"] or "–",
            einschaetzung_text.get(l["einschaetzung"], "–"),
            l["notiz"] or "–",
        ])
    verlauf_tabelle = Table(verlauf_daten, repeatRows=1, hAlign="LEFT", colWidths=[2 * cm, 1.8 * cm, 1.6 * cm, 5 * cm, 2.8 * cm, 4.5 * cm])
    verlauf_tabelle.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243d84")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f5f7")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elemente.append(verlauf_tabelle)
    elemente.append(Spacer(1, 0.8 * cm))
    elemente.append(Paragraph(
        f"Erstellt am {datetime.now().strftime('%d.%m.%Y')} · Fahrschule Bern", stile["Normal"],
    ))

    doc.build(elemente)
    puffer.seek(0)

    dateiname = f"Fortschrittsbericht_{schueler['vorname']}_{schueler['nachname']}.pdf".replace(" ", "_")
    return send_file(puffer, mimetype="application/pdf", as_attachment=True, download_name=dateiname)


# ---------- Eigenes Thema hinzufügen ----------

@app.route("/thema/neu", methods=["POST"])
@login_erforderlich
def thema_neu():
    db = get_db()
    bezeichnung = request.form.get("neues_thema", "").strip()
    schueler_id = request.form.get("schueler_id", type=int)

    if schueler_id:
        schueler = db.execute("SELECT * FROM schueler WHERE id = ?", (schueler_id,)).fetchone()
        if schueler is not None:
            pruefe_zugriff(schueler)

    if bezeichnung:
        db.execute(
            "INSERT OR IGNORE INTO thema (bezeichnung, kategorie) VALUES (?, 'Eigene Themen')",
            (bezeichnung,),
        )
        db.commit()

    if schueler_id:
        return redirect(url_for("schueler_detail", schueler_id=schueler_id))
    return redirect(url_for("index"))


# ---------- Termine (nächste Fahrstunden) ----------

WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


@app.route("/termine")
@login_erforderlich
def termine():
    db = get_db()
    ist_admin = session.get("rolle") == "admin"
    ansicht = request.args.get("ansicht", "liste")
    if ansicht not in ("liste", "woche"):
        ansicht = "liste"

    heute = datetime.now().strftime("%Y-%m-%d")

    # Für die Wochenansicht werden auch erledigte Termine angezeigt (damit
    # die Woche vollständig ist), für die Listenansicht nur offene.
    basis_query = """
        SELECT t.*, s.vorname, s.nachname, s.erstellt_von
        FROM termin t
        JOIN schueler s ON s.id = t.schueler_id
        WHERE {erledigt_filter}
        {und_filter}
        ORDER BY t.datum, t.uhrzeit
    """
    erledigt_filter = "1=1" if ansicht == "woche" else "t.erledigt = 0"
    if ist_admin:
        alle_termine = db.execute(
            basis_query.format(erledigt_filter=erledigt_filter, und_filter="")
        ).fetchall()
    else:
        alle_termine = db.execute(
            basis_query.format(erledigt_filter=erledigt_filter, und_filter="AND s.erstellt_von = ?"),
            (session["benutzer"],),
        ).fetchall()

    if ansicht == "woche":
        try:
            start_param = datetime.strptime(request.args.get("start", ""), "%Y-%m-%d")
        except ValueError:
            start_param = datetime.now()
        wochenstart = start_param - timedelta(days=start_param.weekday())  # Montag dieser Woche

        termine_pro_tag = {}
        for t in alle_termine:
            termine_pro_tag.setdefault(t["datum"], []).append(t)

        woche_tage = []
        for i in range(7):
            tag = wochenstart + timedelta(days=i)
            tag_str = tag.strftime("%Y-%m-%d")
            woche_tage.append({
                "datum": tag_str,
                "label": f"{WOCHENTAGE_KURZ[i]} {tag.strftime('%d.%m.')}",
                "ist_heute": tag_str == heute,
                "termine": termine_pro_tag.get(tag_str, []),
            })

        return render_template(
            "termine.html",
            ansicht=ansicht,
            woche_tage=woche_tage,
            woche_start=wochenstart.strftime("%Y-%m-%d"),
            woche_vorher=(wochenstart - timedelta(days=7)).strftime("%Y-%m-%d"),
            woche_danach=(wochenstart + timedelta(days=7)).strftime("%Y-%m-%d"),
            ist_admin=ist_admin,
            heute=heute,
        )

    # Für die Agenda-/Listenansicht nach Datum gruppieren
    nach_datum = {}
    for t in alle_termine:
        nach_datum.setdefault(t["datum"], []).append(t)

    return render_template(
        "termine.html",
        ansicht=ansicht,
        nach_datum=nach_datum,
        ist_admin=ist_admin,
        heute=heute,
    )


@app.route("/termin/<int:termin_id>/erledigt", methods=["POST"])
@login_erforderlich
def termin_erledigt(termin_id):
    db = get_db()
    row = db.execute(
        """
        SELECT s.erstellt_von
        FROM termin t JOIN schueler s ON s.id = t.schueler_id
        WHERE t.id = ?
        """,
        (termin_id,),
    ).fetchone()
    if row is not None:
        pruefe_zugriff(row)
        db.execute("UPDATE termin SET erledigt = 1 WHERE id = ?", (termin_id,))
        db.commit()
    return redirect(url_for("termine"))


# ---------- Fahrlehrer-Zuteilung (nur Admin, direkt aus dem Dashboard) ----------

@app.route("/schueler/<int:schueler_id>/fahrlehrer", methods=["POST"])
@admin_erforderlich
def schueler_fahrlehrer_zuweisen(schueler_id):
    gewaehlt = request.form.get("fahrlehrer", "").strip()
    if gewaehlt in FAHRLEHRER_LISTE:
        db = get_db()
        db.execute("UPDATE schueler SET erstellt_von = ? WHERE id = ?", (gewaehlt, schueler_id))
        log_aktion(db, "Fahrlehrer zugewiesen", f"Schüler-ID {schueler_id} → {gewaehlt}")
        db.commit()
    return redirect(url_for("admin_dashboard"))


# ---------- Fahrzeugverwaltung (nur Admin) ----------

@app.route("/admin/fahrzeuge", methods=["GET", "POST"])
@admin_erforderlich
def admin_fahrzeuge():
    db = get_db()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        getriebe = request.form.get("getriebe", "").strip()
        if name and getriebe in ("Automatik", "Geschaltet"):
            db.execute("INSERT OR IGNORE INTO fahrzeug (name, getriebe) VALUES (?, ?)", (name, getriebe))
            log_aktion(db, "Fahrzeug hinzugefügt", f"{name} ({getriebe})")
            db.commit()
        return redirect(url_for("admin_fahrzeuge"))

    fahrzeuge = db.execute("SELECT * FROM fahrzeug ORDER BY name").fetchall()
    return render_template("admin_fahrzeuge.html", fahrzeuge=fahrzeuge)


@app.route("/admin/fahrzeuge/<int:fahrzeug_id>/loeschen", methods=["POST"])
@admin_erforderlich
def admin_fahrzeug_loeschen(fahrzeug_id):
    db = get_db()
    fahrzeug = db.execute("SELECT * FROM fahrzeug WHERE id = ?", (fahrzeug_id,)).fetchone()
    if fahrzeug is not None:
        # Schüler, die dieses Fahrzeug hatten, verlieren die Zuweisung statt
        # auf ein nicht mehr existierendes Fahrzeug zu verweisen.
        db.execute(
            "UPDATE schueler SET fahrzeug = NULL, getriebe = NULL WHERE fahrzeug = ?",
            (fahrzeug["name"],),
        )
        db.execute("DELETE FROM fahrzeug WHERE id = ?", (fahrzeug_id,))
        log_aktion(db, "Fahrzeug entfernt", fahrzeug["name"])
        db.commit()
    return redirect(url_for("admin_fahrzeuge"))


# ---------- Audit-Log (nur Admin) ----------

@app.route("/admin/log")
@admin_erforderlich
def admin_log():
    db = get_db()
    eintraege = db.execute(
        "SELECT * FROM audit_log ORDER BY zeitpunkt DESC, id DESC LIMIT 300"
    ).fetchall()
    return render_template("admin_log.html", eintraege=eintraege)


# ---------- Admin-Dashboard ----------

@app.route("/admin")
@admin_erforderlich
def admin_dashboard():
    db = get_db()

    gesamt = db.execute(
        """
        SELECT COUNT(DISTINCT s.id) AS anzahl_schueler,
               COUNT(l.id) AS anzahl_lektionen,
               COALESCE(SUM(l.dauer_minuten), 0) AS total_minuten,
               COALESCE(SUM(CASE WHEN l.bezahlt = 0 THEN l.preis ELSE 0 END), 0) AS offene_betraege
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
               COALESCE(SUM(l.dauer_minuten), 0) AS total_minuten,
               COALESCE(SUM(CASE WHEN l.bezahlt = 0 THEN l.preis ELSE 0 END), 0) AS offener_betrag
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
        fahrlehrer_liste=FAHRLEHRER_LISTE,
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
