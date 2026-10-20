-- Datenbankschema für das Fahrschul-Logbuch

CREATE TABLE IF NOT EXISTS schueler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vorname TEXT NOT NULL,
    nachname TEXT NOT NULL,
    email TEXT,
    telefon TEXT,
    lernfahrausweis_nr TEXT,
    status TEXT NOT NULL DEFAULT 'aktiv',  -- aktiv, pausiert, pruefung_bestanden
    erstellt_am TEXT NOT NULL DEFAULT (datetime('now'))
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
    erstellt_am TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (schueler_id) REFERENCES schueler(id) ON DELETE CASCADE
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
