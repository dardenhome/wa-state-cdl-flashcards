# WA CDL Flashcards

A command-line multiple-choice quiz trainer for the Washington State CDL
knowledge test. All 152 questions are generated from the official WA CDL guide
(`cdlguide.pdf`) and stored in a local SQLite database. The quiz uses a Leitner
spaced-repetition system so questions you miss come back sooner and ones you
master get spaced further out.

## Requirements

Python 3 only — no third-party packages (uses the built-in `sqlite3`).

## Files

| File | Purpose |
|------|---------|
| `quiz.py` | The quiz application (run this) |
| `flashcards.db` | SQLite database: cards + your review progress |
| `build_db.py` | (Re)builds the database from `cards/*.json` |
| `cards/cards_sN.json` | Source flashcards, one file per guide section |
| `cdlguide.txt` | Extracted text of the guide (source material) |

## Quick start

Just run it — you get an interactive menu:

```bash
python3 quiz.py
```

```
  WA CDL Flashcard Trainer
  1. Quiz due cards (spaced repetition)
  2. Study new (unseen) cards
  3. Review missed cards only
  4. Practice exam (timed, pass/fail)
  5. Quiz by section
  6. View stats / progress
  7. List sections
  8. Reset progress
  q. Quit
```

Answer each question with `1`–`4`. Press `s` to skip, `q` to quit (progress is
always saved).

- **Review missed cards** (menu 3) — drills only the questions you've gotten
  wrong at least once.
- **Practice exam** (menu 4) — pick a question count (default 50) and sections,
  then take a timed exam with *no* feedback until the end (like the real test).
  Pass mark is **80%**, and you get a full review of everything you missed.

## Power-user flags (skip the menu)

```bash
python3 quiz.py --sections 1 2 3   # general-knowledge test only
python3 quiz.py --sections 5       # air-brakes endorsement only
python3 quiz.py --missed           # only cards you've missed before
python3 quiz.py --exam -n 50       # timed 50-question practice exam
python3 quiz.py -n 20              # cap a round at 20 questions
python3 quiz.py --all              # quiz everything, ignoring due dates
python3 quiz.py --new-only         # only cards you've never seen
python3 quiz.py --stats            # progress + mastery
python3 quiz.py --list-sections    # list sections + card counts
python3 quiz.py --reset            # wipe all review progress
```

## Sections

| # | Section | Cards | Needed for |
|---|---------|-------|------------|
| 1 | Introduction | 14 | General knowledge |
| 2 | Driving Safely | 32 | General knowledge |
| 3 | Transporting Cargo Safely | 9 | General knowledge |
| 4 | Transporting Passengers Safely | 10 | Passenger endorsement |
| 5 | Air Brakes | 18 | Air brakes |
| 6 | Combination Vehicles | 16 | Class A / combination |
| 7 | Doubles and Triples | 10 | Doubles/Triples endorsement |
| 8 | Tank Vehicles | 9 | Tank endorsement |
| 9 | Hazardous Materials | 20 | HazMat endorsement |
| 10 | School Buses | 14 | School bus endorsement |

## How the spacing works

Each card lives in a Leitner "box" (1–5). Answer correctly → it moves up a box
and is scheduled further out (1, 3, 7, then 16 days). Answer wrong → it drops
back to box 1 and becomes due immediately. `--stats` shows the box distribution
so you can see what still needs work.

## Editing or adding questions

Edit the JSON files in `cards/`, then run `python3 build_db.py`. Re-running is
safe — it updates card text without erasing your review progress (cards are
matched by question text).
