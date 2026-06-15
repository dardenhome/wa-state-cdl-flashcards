#!/usr/bin/env python3
"""Build/refresh the SQLite flashcard database from the cards/*.json files.

Re-running this is safe: it inserts new cards and updates the text of existing
ones (matched by question text) WITHOUT wiping your review progress.
"""
import glob
import json
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "flashcards.db")
CARDS_DIR = os.path.join(HERE, "cards")

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    section       INTEGER NOT NULL,
    section_name  TEXT    NOT NULL,
    topic         TEXT,
    question      TEXT    NOT NULL UNIQUE,
    choices       TEXT    NOT NULL,   -- JSON array of strings
    answer_index  INTEGER NOT NULL,
    explanation   TEXT
);

-- Per-card review state for spaced repetition (Leitner system).
CREATE TABLE IF NOT EXISTS review (
    card_id        INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
    box            INTEGER NOT NULL DEFAULT 1,   -- Leitner box 1..5 (higher = known better)
    times_seen     INTEGER NOT NULL DEFAULT 0,
    times_correct  INTEGER NOT NULL DEFAULT 0,
    times_wrong    INTEGER NOT NULL DEFAULT 0,
    last_seen      TEXT,                          -- ISO timestamp
    due_at         TEXT                           -- ISO timestamp when card is due again
);
"""


def load_cards():
    files = sorted(
        glob.glob(os.path.join(CARDS_DIR, "cards_s*.json")),
        key=lambda x: int(x.split("_s")[1].split(".")[0]),
    )
    cards = []
    for f in files:
        cards.extend(json.load(open(f)))
    return cards


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    cards = load_cards()
    inserted = updated = 0
    for c in cards:
        cur = conn.execute(
            """INSERT INTO cards (section, section_name, topic, question, choices, answer_index, explanation)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(question) DO UPDATE SET
                   section=excluded.section,
                   section_name=excluded.section_name,
                   topic=excluded.topic,
                   choices=excluded.choices,
                   answer_index=excluded.answer_index,
                   explanation=excluded.explanation""",
            (
                c["section"],
                c["section_name"],
                c.get("topic", ""),
                c["question"],
                json.dumps(c["choices"]),
                c["answer_index"],
                c.get("explanation", ""),
            ),
        )
        if cur.rowcount == 1:
            inserted += 1
        else:
            updated += 1
    # Make sure every card has a review row.
    conn.execute(
        "INSERT OR IGNORE INTO review (card_id) SELECT id FROM cards"
    )
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    print(f"Database ready: {DB_PATH}")
    print(f"  {inserted} new, {updated} updated, {n} cards total.")
    by_sec = conn.execute(
        "SELECT section, section_name, COUNT(*) FROM cards GROUP BY section ORDER BY section"
    ).fetchall()
    for sec, name, count in by_sec:
        print(f"  Section {sec:>2}  {name:<28} {count:>3} cards")
    conn.close()


if __name__ == "__main__":
    main()
