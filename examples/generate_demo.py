#!/usr/bin/env python3
"""Make a folder of FAKE statements (nine months, checking + credit card) to try the tool.

    python3 examples/generate_demo.py /tmp/demo_statements
    python3 scripts/spendscan.py /tmp/demo_statements --open

Everything here is invented: merchants are real chain names so the starter rules recognise them,
but no amounts, dates or people are real. A few merchants are deliberately unknown so you can
try the "fix categories" flow.
"""
import csv
import random
import sys
from pathlib import Path

random.seed(7)
out = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_statements")

CARD = [
    ("SAFEWAY #1204 ANYTOWN CA", 55, 140, 4), ("TRADER JOE S #55 ANYTOWN CA", 35, 90, 3),
    ("COSTCO WHSE #0123 ANYTOWN CA", 120, 320, 1), ("STARBUCKS STORE 08842", 4, 9, 7),
    ("CHIPOTLE 1923", 11, 24, 3), ("TST*SUNRISE BAKERY ANYTOWN CA", 6, 18, 2),
    ("DOORDASH*PIZZA PLACE", 22, 55, 2), ("SHELL OIL 57444", 28, 62, 3),
    ("CHEVRON 0091234", 30, 66, 1), ("AMAZON.COM*2K4LP0", 12, 95, 4),
    ("AMZN MKTP US*8H2JK", 9, 60, 2), ("TARGET 00012345", 18, 110, 3),
    ("NETFLIX.COM", 15.49, 15.49, 1), ("SPOTIFY USA", 11.99, 11.99, 1),
    ("HOME DEPOT #6601", 20, 140, 1), ("CVS/PHARMACY #7731", 8, 45, 1),
    ("UBER *TRIP HELP.UBER.COM", 9, 32, 2), ("AMC THEATRES 0431", 14, 48, 1),
    ("JIFFY LUBE #2231", 60, 95, 0.3), ("SOUTHWEST AIRLINES", 180, 420, 0.25),
    ("ZZ QUARTZ HOLDINGS 5521", 14, 40, 1),   # unknown on purpose
]
CHECKING = [
    ("COMCAST CABLE COMM", 79, 79), ("VERIZON WIRELESS PAYMENTS", 85, 85),
    ("SOUTHERN CALIFORNIA EDISON", 80, 190), ("STATE FARM INSURANCE", 142, 142),
]

def money(x):
    return f"{x:.2f}"

card_rows, chk_rows = [], []
for m in range(1, 10):
    for name, lo, hi, per in CARD:
        n = int(per) + (1 if random.random() < per % 1 else 0)
        for _ in range(n):
            day = random.randint(1, 27)
            card_rows.append([f"{m:02d}/{day:02d}/2026", name, money(random.uniform(lo, hi))])
    chk_rows.append([f"{m:02d}/01/2026", "ACME CORP PAYROLL DIRECT DEP 4471", money(4200)])
    chk_rows.append([f"{m:02d}/15/2026", "ACME CORP PAYROLL DIRECT DEP 4471", money(4200)])
    chk_rows.append([f"{m:02d}/01/2026", "ZELLE PAYMENT TO LANDLORD 99123", money(-1800)])
    chk_rows.append([f"{m:02d}/18/2026", "PAYMENT TO CRD 7788 CONFIRMATION", money(-sum(float(r[2]) for r in card_rows if r[0].startswith(f"{m:02d}/")))])
    if m % 3 == 0:  # an unlabelled person-to-person payment over $500, to try the "clarify" flow
        chk_rows.append([f"{m:02d}/20/2026", "ZELLE PAYMENT TO J SMITH 55", money(-600)])
    for name, lo, hi in CHECKING:
        chk_rows.append([f"{m:02d}/{random.randint(3, 12):02d}/2026", name, money(-random.uniform(lo, hi))])

(out / "card").mkdir(parents=True, exist_ok=True)
(out / "checking").mkdir(parents=True, exist_ok=True)
for rows, path, hdr in ((card_rows, out / "card" / "card_2026.csv", ["Date", "Description", "Amount"]),
                        (chk_rows, out / "checking" / "checking_2026.csv", ["Date", "Description", "Amount"])):
    # card exports show purchases as positive numbers, checking exports show money out as negative
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(rows)
print(f"Fake statements written to {out}")
