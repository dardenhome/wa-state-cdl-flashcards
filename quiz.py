#!/usr/bin/env python3
"""Washington State CDL flashcard quiz — command-line trainer.

Run with no arguments for an interactive menu:

    python3 quiz.py

Multiple-choice quizzing with a Leitner spaced-repetition system: missed
questions come back soon, mastered ones get spaced further out.

Power-user flags (skip the menu):
    python3 quiz.py --sections 1 2 5   # only these sections
    python3 quiz.py -n 20              # limit to 20 questions this round
    python3 quiz.py --all             # ignore due dates; quiz everything
    python3 quiz.py --new-only        # only cards you've never seen
    python3 quiz.py --missed          # only cards you've gotten wrong before
    python3 quiz.py --exam [-n 50]    # timed practice exam (pass = 80%)
    python3 quiz.py --stats           # show your progress and exit
    python3 quiz.py --reset           # reset all review progress
    python3 quiz.py --list-sections   # list sections and card counts

In a quiz, answer with 1-4. Other keys: 's' skip, 'q' quit and save.
"""
import argparse
import datetime as dt
import json
import os
import random
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "flashcards.db")

# Leitner box -> days until a correctly-answered card is due again.
BOX_INTERVALS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 16}
MAX_BOX = 5
EXAM_DEFAULT = 50          # questions in a practice exam
EXAM_PASS_PCT = 80         # WA knowledge tests require 80% to pass
# Default sections for a practice exam (Class A + HazMat): general knowledge,
# air brakes, combination vehicles, hazardous materials. Override on the CLI
# with --sections, or by entering section numbers at the menu prompt.
EXAM_SECTIONS = [1, 2, 3, 5, 6, 9]


def now():
    return dt.datetime.now()


def iso(t):
    return t.replace(microsecond=0).isoformat()


def connect():
    if not os.path.exists(DB_PATH):
        sys.exit("No database found. Run:  python3 build_db.py")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------- selection

def pick_cards(conn, sections, limit, mode):
    """mode: 'due' | 'all' | 'new' | 'missed'."""
    where = ["1=1"]
    params = []
    if sections:
        where.append("c.section IN (%s)" % ",".join("?" * len(sections)))
        params += sections

    if mode == "new":
        where.append("r.times_seen = 0")
    elif mode == "missed":
        where.append("r.times_wrong > 0")
    elif mode == "due":
        where.append("(r.due_at IS NULL OR r.due_at <= ?)")
        params.append(iso(now()))

    sql = f"""
        SELECT c.*, r.box, r.times_seen, r.times_correct, r.times_wrong, r.due_at
        FROM cards c JOIN review r ON r.card_id = c.id
        WHERE {' AND '.join(where)}
    """
    rows = list(conn.execute(sql, params).fetchall())
    # Prioritize weaker cards (lower box, more wrong answers), then shuffle.
    random.shuffle(rows)
    rows.sort(key=lambda r: (r["box"], -r["times_wrong"], r["times_seen"]))
    if limit:
        rows = rows[:limit]
    return rows


def pick_exam(conn, sections, count):
    """Random selection ignoring due dates, for a practice exam."""
    where = ["1=1"]
    params = []
    if sections:
        where.append("c.section IN (%s)" % ",".join("?" * len(sections)))
        params += sections
    sql = f"""
        SELECT c.*, r.box, r.times_seen, r.times_correct, r.times_wrong, r.due_at
        FROM cards c JOIN review r ON r.card_id = c.id
        WHERE {' AND '.join(where)}
    """
    rows = list(conn.execute(sql, params).fetchall())
    random.shuffle(rows)
    return rows[:count]


# ---------------------------------------------------------------- scheduling

def record_answer(conn, card, correct):
    box = card["box"]
    if correct:
        box = min(box + 1, MAX_BOX)
    else:
        box = 1  # demote to box 1 -> due immediately
    due = now() + dt.timedelta(days=BOX_INTERVALS[box])
    conn.execute(
        """UPDATE review SET
               box=?,
               times_seen=times_seen+1,
               times_correct=times_correct+?,
               times_wrong=times_wrong+?,
               last_seen=?,
               due_at=?
           WHERE card_id=?""",
        (box, 1 if correct else 0, 0 if correct else 1, iso(now()), iso(due), card["id"]),
    )
    conn.commit()


# ---------------------------------------------------------------- ui helpers

class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    YELLOW = "\033[93m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def ask(prompt):
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return "q"


def present_question(card, index, total):
    """Print a question with shuffled choices; return (shuffled_choices,
    correct_position)."""
    choices = json.loads(card["choices"])
    order = list(range(len(choices)))
    random.shuffle(order)
    shuffled = [choices[o] for o in order]
    correct_pos = order.index(card["answer_index"])
    print(f"{C.CYAN}Q{index}/{total}{C.END}  "
          f"{C.DIM}[Sec {card['section']} · {card['topic']}]{C.END}")
    print(f"{C.BOLD}{card['question']}{C.END}")
    for pos, text in enumerate(shuffled):
        print(f"   {pos + 1}. {text}")
    return shuffled, correct_pos


def grade(ans, correct_pos, n_choices):
    """Return (is_correct, is_skip, is_quit, is_valid)."""
    ans = ans.strip().lower()
    if ans == "q":
        return False, False, True, True
    if ans == "s" or ans == "":
        return False, True, False, True
    if ans.isdigit() and 1 <= int(ans) <= n_choices:
        return (int(ans) - 1) == correct_pos, False, False, True
    return False, False, False, False  # unrecognized -> re-prompt


# ---------------------------------------------------------------- quiz loop

def run_quiz(conn, cards, title="WA CDL Quiz"):
    if not cards:
        print(f"\n{C.GREEN}No cards to study here right now.{C.END}")
        return

    print(f"\n{C.BOLD}{title}{C.END} — {len(cards)} question(s). "
          f"Answer 1-4, [s]kip, [q]uit.\n")
    correct = wrong = skipped = 0

    for i, card in enumerate(cards, 1):
        shuffled, correct_pos = present_question(card, i, len(cards))
        while True:
            is_correct, is_skip, is_quit, is_valid = grade(
                ask("\nYour answer: "), correct_pos, len(shuffled))
            if is_valid:
                break
            print(f"{C.YELLOW}Please enter 1-{len(shuffled)}, [s]kip, or [q]uit.{C.END}")

        if is_quit:
            print(f"\n{C.YELLOW}Quitting — progress saved.{C.END}")
            break
        if is_skip:
            skipped += 1
            print(f"{C.YELLOW}Skipped.{C.END} "
                  f"Correct: {correct_pos + 1}. {shuffled[correct_pos]}")
            print(f"{C.DIM}{card['explanation']}{C.END}\n")
            continue

        if is_correct:
            correct += 1
            print(f"{C.GREEN}✓ Correct!{C.END}")
        else:
            wrong += 1
            print(f"{C.RED}✗ Incorrect.{C.END} "
                  f"Answer: {correct_pos + 1}. {shuffled[correct_pos]}")
        print(f"{C.DIM}{card['explanation']}{C.END}\n")
        record_answer(conn, card, is_correct)

    answered = correct + wrong
    print(f"{C.BOLD}— Round complete —{C.END}")
    if answered:
        pct = 100 * correct / answered
        print(f"Score: {C.GREEN}{correct} correct{C.END}, "
              f"{C.RED}{wrong} wrong{C.END}  ({pct:.0f}%)"
              + (f", {skipped} skipped" if skipped else ""))
    print(f"{C.DIM}Missed cards will resurface sooner.{C.END}")


# ---------------------------------------------------------------- exam mode

def run_exam(conn, cards):
    if not cards:
        print(f"\n{C.YELLOW}Not enough cards for an exam.{C.END}")
        return
    print(f"\n{C.BOLD}Practice Exam{C.END} — {len(cards)} questions. "
          f"Pass mark: {EXAM_PASS_PCT}%.")
    print(f"{C.DIM}No feedback until the end (just like the real test). "
          f"Answer 1-4, [s]kip, [q]uit early.{C.END}\n")

    start = time.time()
    correct = answered = 0
    missed = []  # (card, shuffled_choices, correct_pos, your_pos_or_None)

    for i, card in enumerate(cards, 1):
        shuffled, correct_pos = present_question(card, i, len(cards))
        while True:
            raw = ask("\nYour answer: ")
            is_correct, is_skip, is_quit, is_valid = grade(raw, correct_pos, len(shuffled))
            if is_valid:
                break
            print(f"{C.YELLOW}Please enter 1-{len(shuffled)}, [s]kip, or [q]uit.{C.END}")
        if is_quit:
            print(f"\n{C.YELLOW}Exam ended early.{C.END}")
            break
        print()
        answered += 1
        if is_correct:
            correct += 1
        else:
            your_pos = None
            r = raw.strip()
            if r.isdigit() and 1 <= int(r) <= len(shuffled):
                your_pos = int(r) - 1
            missed.append((card, shuffled, correct_pos, your_pos))
        record_answer(conn, card, is_correct)

    elapsed = int(time.time() - start)
    mins, secs = divmod(elapsed, 60)
    print(f"{C.BOLD}— Exam results —{C.END}")
    if not answered:
        print("No questions answered.")
        return
    pct = 100 * correct / answered
    passed = pct >= EXAM_PASS_PCT
    verdict = (f"{C.GREEN}PASS{C.END}" if passed else f"{C.RED}FAIL{C.END}")
    print(f"  {verdict}  —  {correct}/{answered} correct ({pct:.0f}%), "
          f"need {EXAM_PASS_PCT}%")
    print(f"  Time: {mins}m {secs}s")

    if missed:
        print(f"\n{C.BOLD}Review your {len(missed)} missed question(s):{C.END}")
        for card, shuffled, correct_pos, your_pos in missed:
            print(f"\n{C.DIM}[Sec {card['section']} · {card['topic']}]{C.END}")
            print(f"{C.BOLD}{card['question']}{C.END}")
            if your_pos is not None:
                print(f"  Your answer:  {C.RED}{your_pos + 1}. "
                      f"{shuffled[your_pos]}{C.END}")
            else:
                print(f"  Your answer:  {C.YELLOW}(skipped/invalid){C.END}")
            print(f"  Correct:      {C.GREEN}{correct_pos + 1}. "
                  f"{shuffled[correct_pos]}{C.END}")
            print(f"  {C.DIM}{card['explanation']}{C.END}")


# ---------------------------------------------------------------- stats

def show_stats(conn):
    total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    seen = conn.execute("SELECT COUNT(*) FROM review WHERE times_seen>0").fetchone()[0]
    due = conn.execute(
        "SELECT COUNT(*) FROM review WHERE times_seen>0 AND due_at<=?",
        (iso(now()),),
    ).fetchone()[0]
    missed = conn.execute(
        "SELECT COUNT(*) FROM review WHERE times_wrong>0").fetchone()[0]
    agg = conn.execute(
        "SELECT SUM(times_correct), SUM(times_wrong) FROM review").fetchone()
    tc, tw = (agg[0] or 0), (agg[1] or 0)

    print(f"\n{C.BOLD}Your CDL study progress{C.END}")
    print(f"  Cards total:      {total}")
    print(f"  Cards practiced:  {seen}  ({100*seen/total:.0f}%)")
    print(f"  New (unseen):     {total - seen}")
    print(f"  Due now:          {due}")
    print(f"  Missed at least once: {missed}")
    if tc + tw:
        print(f"  Lifetime answers: {tc + tw}  "
              f"({C.GREEN}{tc} correct{C.END} / {C.RED}{tw} wrong{C.END}, "
              f"{100*tc/(tc+tw):.0f}%)")

    print(f"\n{C.BOLD}Mastery by Leitner box{C.END} "
          f"{C.DIM}(box 1 = needs work … box 5 = mastered){C.END}")
    boxes = dict(conn.execute(
        "SELECT box, COUNT(*) FROM review GROUP BY box").fetchall())
    for b in range(1, MAX_BOX + 1):
        n = boxes.get(b, 0)
        pct = 100 * n / total if total else 0
        interval = BOX_INTERVALS[b]
        due_label = "review now" if interval == 0 else f"{interval}d interval"
        print(f"  Box {b}: [{progress_bar(n, total)}] {n:>3} ({pct:>5.1f}%)  "
              f"{C.DIM}{due_label}{C.END}")

    print(f"\n{C.BOLD}By section{C.END}")
    rows = conn.execute(
        """SELECT c.section, c.section_name, COUNT(*) n,
                  SUM(CASE WHEN r.times_seen>0 THEN 1 ELSE 0 END) practiced,
                  SUM(CASE WHEN r.box>=4 THEN 1 ELSE 0 END) mastered
           FROM cards c JOIN review r ON r.card_id=c.id
           GROUP BY c.section ORDER BY c.section"""
    ).fetchall()
    for r in rows:
        print(f"  Sec {r['section']:>2}  {r['section_name']:<28} "
              f"{r['practiced']}/{r['n']} practiced, {r['mastered']} mastered")
    print()


def section_rows(conn):
    return conn.execute(
        "SELECT section, section_name, COUNT(*) n FROM cards "
        "GROUP BY section ORDER BY section").fetchall()


def list_sections(conn):
    print(f"\n{C.BOLD}Sections available{C.END}")
    for r in section_rows(conn):
        print(f"  {r['section']:>2}  {r['section_name']:<30} {r['n']} cards")
    print(f"\n{C.DIM}General knowledge test: sections 1, 2, 3"
          f"  |  Air brakes: 5  |  Combination: 6{C.END}")
    print(f"{C.DIM}Endorsements — Passenger: 4 · Doubles/Triples: 7 · "
          f"Tank: 8 · HazMat: 9 · School bus: 10{C.END}\n")


def reset(conn):
    if ask("Reset ALL review progress? Type 'yes': ").strip().lower() == "yes":
        conn.execute(
            "UPDATE review SET box=1, times_seen=0, times_correct=0, "
            "times_wrong=0, last_seen=NULL, due_at=NULL")
        conn.commit()
        print("Progress reset.")
    else:
        print("Cancelled.")


# ---------------------------------------------------------------- menu

def choose_sections(conn):
    """Prompt for sections; return a list of ints or None for all."""
    print(f"\n{C.BOLD}Choose sections{C.END}")
    for r in section_rows(conn):
        print(f"  {r['section']:>2}  {r['section_name']:<30} {r['n']} cards")
    raw = ask("\nEnter section numbers (e.g. 1 2 3), or blank for ALL: ").strip()
    if not raw or raw.lower() == "q":
        return None
    nums = [int(x) for x in raw.replace(",", " ").split() if x.isdigit()]
    return nums or None


def choose_int(prompt, default):
    raw = ask(f"{prompt} [{default}]: ").strip()
    return int(raw) if raw.isdigit() else default


def progress_bar(count, total, width=28):
    if total <= 0:
        return "░" * width
    filled = round(width * count / total)
    if count > 0:
        filled = max(1, filled)
    filled = min(width, filled)
    return "█" * filled + "░" * (width - filled)


def menu():
    conn = connect()
    actions = {
        "1": "Quiz due cards (spaced repetition)",
        "2": "Study new (unseen) cards",
        "3": "Review missed cards only",
        "4": "Practice exam (timed, pass/fail)",
        "5": "Quiz by section",
        "6": "View stats / progress",
        "7": "List sections",
        "8": "Reset progress",
        "q": "Quit",
    }
    while True:
        print(f"\n{C.BOLD}{'═'*44}{C.END}")
        print(f"{C.BOLD}  WA CDL Flashcard Trainer{C.END}")
        print(f"{C.BOLD}{'═'*44}{C.END}")
        for k, label in actions.items():
            print(f"  {C.CYAN}{k}{C.END}. {label}")
        choice = ask("\nSelect an option: ").strip().lower()

        if choice == "q":
            print("Good luck on the test!")
            break
        elif choice == "1":
            limit = choose_int("How many questions? (0 = all due)", 20) or None
            run_quiz(conn, pick_cards(conn, None, limit, "due"),
                     "Due cards")
        elif choice == "2":
            limit = choose_int("How many new cards?", 15) or None
            run_quiz(conn, pick_cards(conn, None, limit, "new"),
                     "New cards")
        elif choice == "3":
            cards = pick_cards(conn, None, None, "missed")
            if not cards:
                print(f"\n{C.GREEN}No missed cards — nothing to review yet!{C.END}")
            else:
                run_quiz(conn, cards, "Missed cards")
        elif choice == "4":
            default_label = " ".join(str(s) for s in EXAM_SECTIONS)
            print(f"\n{C.BOLD}Practice exam sections{C.END}")
            for r in section_rows(conn):
                print(f"  {r['section']:>2}  {r['section_name']:<30} {r['n']} cards")
            raw = ask(f"\nEnter section numbers, or blank for default "
                      f"[{default_label}]: ").strip()
            if not raw or raw.lower() == "q":
                secs = list(EXAM_SECTIONS)
            else:
                secs = [int(x) for x in raw.replace(",", " ").split()
                        if x.isdigit()] or list(EXAM_SECTIONS)
            count = choose_int("How many questions on the exam?", EXAM_DEFAULT)
            run_exam(conn, pick_exam(conn, secs, count))
        elif choice == "5":
            secs = choose_sections(conn)
            limit = choose_int("How many questions? (0 = all)", 0) or None
            run_quiz(conn, pick_cards(conn, secs, limit, "all"),
                     "Section quiz")
        elif choice == "6":
            show_stats(conn)
        elif choice == "7":
            list_sections(conn)
        elif choice == "8":
            reset(conn)
        else:
            print(f"{C.YELLOW}Unknown option.{C.END}")
    conn.close()


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description="WA CDL flashcard quiz")
    p.add_argument("--sections", nargs="+", type=int, metavar="N",
                   help="only quiz these section numbers")
    p.add_argument("-n", "--limit", type=int, help="max questions this round")
    p.add_argument("--all", action="store_true",
                   help="quiz all matching cards, ignoring due dates")
    p.add_argument("--new-only", action="store_true",
                   help="only cards you've never seen")
    p.add_argument("--missed", action="store_true",
                   help="only cards you've gotten wrong before")
    p.add_argument("--exam", action="store_true",
                   help="timed practice exam (pass = 80%%)")
    p.add_argument("--stats", action="store_true", help="show progress and exit")
    p.add_argument("--list-sections", action="store_true",
                   help="list sections and exit")
    p.add_argument("--reset", action="store_true", help="reset progress and exit")
    args = p.parse_args()

    # No flags at all -> friendly interactive menu.
    if len(sys.argv) == 1:
        return menu()

    conn = connect()
    if args.stats:
        return show_stats(conn)
    if args.list_sections:
        return list_sections(conn)
    if args.reset:
        return reset(conn)
    if args.exam:
        count = args.limit or EXAM_DEFAULT
        secs = args.sections if args.sections else list(EXAM_SECTIONS)
        return run_exam(conn, pick_exam(conn, secs, count))

    if args.new_only:
        mode = "new"
    elif args.missed:
        mode = "missed"
    elif args.all:
        mode = "all"
    else:
        mode = "due"
    run_quiz(conn, pick_cards(conn, args.sections, args.limit, mode))
    conn.close()


if __name__ == "__main__":
    main()
