-- Datenbankschema für das Fahrschul-Logbuch

CREATE TABLE IF NOT EXISTS schueler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vorname TEXT NOT NULL,
    nachname TEXT NOT NULL,
    email TEXT,
    telefon TEXT,
    lernfahrausweis_nr TEXT,
    status TEXT NOT NULL DEFAULT 'aktiv',  -- aktiv, pausiert, pruefung_bestanden
    erstellt_am TEXT NOT NULL DEFAULT (datetime('now')),
    erstellt_von TEXT NOT NULL DEFAULT 'aru',  -- Benutzername des Fahrlehrers, dem der Schüler gehört
    fahrzeug TEXT,   -- z. B. "VW Golf GTI"
    getriebe TEXT,   -- "Automatik" oder "Geschaltet"
    theorie_pruefung_datum TEXT,   -- geplantes/erfolgtes Datum der Theorieprüfung
    praxis_pruefung_datum TEXT,    -- geplantes/erfolgtes Datum der praktischen Prüfung
    archiviert INTEGER NOT NULL DEFAULT 0  -- 1 = archiviert (Soft-Delete), 0 = aktiv sichtbar
);

-- Fahrzeugflotte, über das Admin-UI verwaltbar
CREATE TABLE IF NOT EXISTS fahrzeug (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    getriebe TEXT NOT NULL  -- "Automatik" oder "Geschaltet"
);

CREATE TABLE IF NOT EXISTS thema (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bezeichnung TEXT NOT NULL UNIQUE,
    kategorie TEXT NOT NULL  -- Grundfahraufgaben, Verkehrssituationen, Autobahn, Spezial
);

CREATE TABLE IF NOT EXISTS lektion (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schueler_id INTEGER NOT NULL,
    datum TEXT NOT NULL,
    dauer_minuten INTEGER NOT NULL,
    notiz TEXT,
    einschaetzung INTEGER NOT NULL,  -- 1 = unsicher, 2 = Übung nötig, 3 = sicher
    typ TEXT NOT NULL DEFAULT 'normal',  -- 'probe' = Probelektion, 'normal' = normale Lektion
    preis REAL NOT NULL DEFAULT 0,       -- Betrag in CHF für diese Lektion
    bezahlt INTEGER NOT NULL DEFAULT 0,  -- 1 = bezahlt, 0 = offen
    erstellt_am TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (schueler_id) REFERENCES schueler(id) ON DELETE CASCADE
);

-- Geplante nächste Fahrstunden (Termine), optional beim Erfassen einer
-- normalen Lektion mit angelegt. Grundlage für die Termine-Übersicht.
CREATE TABLE IF NOT EXISTS termin (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schueler_id INTEGER NOT NULL,
    datum TEXT NOT NULL,
    uhrzeit TEXT,
    geplante_themen TEXT,
    erledigt INTEGER NOT NULL DEFAULT 0,
    erstellt_am TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (schueler_id) REFERENCES schueler(id) ON DELETE CASCADE
);

-- Einmalige Rechnungspositionen pro Schüler (Pauschalen), getrennt von den
-- Lektionen: z. B. Versicherungs-/Administrationspauschale bei Anmeldung
-- oder die Prüfungspauschale.
CREATE TABLE IF NOT EXISTS rechnungsposition (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    schueler_id INTEGER NOT NULL,
    bezeichnung TEXT NOT NULL,
    betrag REAL NOT NULL,
    bezahlt INTEGER NOT NULL DEFAULT 0,
    erstellt_am TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (schueler_id) REFERENCES schueler(id) ON DELETE CASCADE
);

-- Protokoll wichtiger Aktionen, nur für den Admin einsehbar
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zeitpunkt TEXT NOT NULL DEFAULT (datetime('now')),
    benutzer TEXT NOT NULL,
    aktion TEXT NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS lektion_thema (
    lektion_id INTEGER NOT NULL,
    thema_id INTEGER NOT NULL,
    PRIMARY KEY (lektion_id, thema_id),
    FOREIGN KEY (lektion_id) REFERENCES lektion(id) ON DELETE CASCADE,
    FOREIGN KEY (thema_id) REFERENCES thema(id) ON DELETE CASCADE
);

-- Vordefinierter Themenkatalog, damit nicht jedes Mal Freitext nötig ist
INSERT OR IGNORE INTO thema (bezeichnung, kategorie) VALUES
    ('Anfahren / Schalten', 'Grundfahraufgaben'),
    ('Rückwärtsparkieren', 'Grundfahraufgaben'),
    ('Wenden', 'Grundfahraufgaben'),
    ('Spurwechsel', 'Grundfahraufgaben'),
    ('Kreisverkehr', 'Verkehrssituationen'),
    ('Vortritt / Kreuzungen', 'Verkehrssituationen'),
    ('Fussgängerstreifen', 'Verkehrssituationen'),
    ('Innerorts allgemein', 'Verkehrssituationen'),
    ('Autobahn-Auffahrt', 'Autobahn'),
    ('Autobahn-Ausfahrt / Überholen', 'Autobahn'),
    ('Nachtfahrt', 'Spezial'),
    ('Schlechtwetterfahrt', 'Spezial'),
    ('Parkieren allgemein (vorwärts/seitlich)', 'Grundfahraufgaben');
