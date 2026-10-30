---
name: private-spend-tracker
description: Guides a user through a local-only spending tracker. Their statements (CSV/PDF) stay on their computer; a script strips identifying data, sorts spending into categories, and builds a budget-vs-actual dashboard. Use when someone wants to track spending against a budget without giving an AI their bank data.
---

# Private spend tracker

The user keeps all statements in ONE folder on their own computer. A Python script
(`scripts/spendscan.py`) reads them there and writes a dataset that holds only
**month + category + amount**, plus an offline `dashboard.html` that compares spending
with the user's budget. Claude's job is to explain how to run it and to help interpret
the results. Claude does not process the statements.

## Privacy rules for Claude (follow strictly)

1. **Never ask the user to upload or paste statements, and never ask for transaction
   lines, merchant names, account numbers or balances.** If the user pastes any,
   say it is not needed, do not use it, and point them to the script instead.
2. **The script is run by the user on their machine.** Give them the command and let
   them run it. Do not run it on their statements yourself.
3. What is safe to talk about: `last_run_report.txt` (counts only), `budgets.csv`,
   `categories.csv` rules the user writes, and the category totals they read off the dashboard.
   `transactions.csv` holds only month/category/amount/hashed id, so it is safe to share if the
   user chooses to.
4. `unmatched_merchants.txt` is a LOCAL helper that lists cleaned merchant text. Do not ask
   for it. If the user decides to paste lines from it to get category suggestions, remind them
   to read the lines first and remove anything personal (people's names, small businesses
   they would rather not share).
5. The script uses only the Python standard library and never touches the network. If the
   user wants to confirm, they can run it with Wi-Fi off, or search the file for
   `socket`, `urllib` or `requests` (none appear).

## One-time setup (walk the user through it)

1. **Check Python 3.8 or newer.**
   - Mac/Linux: `python3 --version`
   - Windows: `py --version`
   If missing, install from python.org.
2. **Only if they have PDF statements:** `pip install pdfplumber` (Windows: `py -m pip install pdfplumber`).
   CSV files need nothing extra, and CSV is more reliable than PDF, so suggest the bank's CSV download first.
3. **Make one folder** for statements, for example `Documents/my_statements`. Inside it make
   **one subfolder per account** and name each with something that is not personal
   (`checking`, `amex`, `savings`). The folder name is stored as the account label.
   ```
   my_statements/
     checking/   chase_sep.csv  chase_oct.pdf
     amex/       amex_sep.csv
   ```
   Files placed directly in the main folder are labelled `main`.
4. **Put the statement files in the account subfolders.** Overlapping date ranges are fine;
   duplicates are detected.
5. **Run the script** (adjust both paths; keep the quotes):
   - Mac/Linux: `python3 "/path/to/private-spend-tracker/scripts/spendscan.py" "/path/to/my_statements" --open`
     (or, after `pip install .` inside the folder: `spendscan "/path/to/my_statements" --open`)
   - Windows: `py "C:\path\to\private-spend-tracker\scripts\spendscan.py" "C:\path\to\my_statements" --open`
   `--open` opens the dashboard in their browser. Without it, they open
   `my_statements/_spend_tracker/dashboard.html` themselves.

Tip: `python3 examples/generate_demo.py /tmp/demo` makes nine months of fake statements so they can try
the whole flow first.

## Setting a budget

- In the dashboard, type a monthly amount next to a category. It saves in that browser.
- To keep budgets permanently, either press **Download budgets.csv** and replace
  `_spend_tracker/budgets.csv`, or edit `budgets.csv` directly (`category,monthly_budget`), then run the script again.

## Monthly update

Download the new statement, drop it into the right account subfolder, run the same command.
New transactions are added, old ones are kept, and duplicates are ignored. Files can be
removed from the folder afterwards and the history stays.

## Fixing categories

- The run report shows the share of spending that is **Uncategorized**. To fix it, the user opens
  `_spend_tracker/unmatched_merchants.txt` (local), and for each merchant adds a line to
  `_spend_tracker/categories.csv` in the form `KEYWORD,Category`, for example `JOES PIZZA,Eating out`.
  Then they run the script again; old months are recategorized as long as the original files are still in the folder.
- Keywords are matched against the upper-case description; the longest match wins and the
  user's own lines beat the built-in list. Any category name is allowed (a new name becomes a new category).
- To combine categories, add a line like `@Groceries,Groceries & household` (the `@` means "rename every purchase in this category"). Several categories can be merged into one name.
- Marketplace stores whose purchases could be anything (Amazon, Walmart, Target) are kept as
  their own categories ("Amazon orders", "Walmart/Target (mixed)"; users can rename these with their own rules) on purpose.

## Large Zelle / Venmo / check payments

The script never stores names, so a payment to a person has no category. When one is **$500 or more**
and unlabelled, the run report says "To label: N amount(s)" and `_spend_tracker/payments_to_clarify.txt`
lists each amount, how many times it appeared and in which months (no names). **Ask the user what each one
is** (rent, childcare, a family transfer, a business payment). Then they add one line per amount to
`categories.csv`, for example `$2495.00,Rent & housing`, which labels every payment of exactly that amount.
Smaller person-to-person payments stay as "Person-to-person" and do not need asking about.

## Already-processed files

The script remembers each file (a fingerprint of its contents, no file names) in `processed_files.csv`
and skips files it has already read. Everything is re-read once whenever `categories.csv` or the script
changes, so old months pick up new rules. `--force` re-reads everything.

## What the script keeps and drops

- **Kept:** month (not the exact day), category, amount, direction (money out or in), the user's
  account label, and a salted one-way hash used only to spot duplicates.
- **Dropped:** descriptions, merchant names, names of people paid by Zelle/Venmo/check (these become
  "Person-to-person"), account and card numbers, exact dates, balances, file names.
- **Not counted as spending:** income, credit-card payments, transfers between the user's own accounts,
  and other deposits. This avoids counting the same money twice when both a checking account and a credit card are included.
- Refunds reduce the category they belong to.

## Troubleshooting

| Symptom | What to tell the user |
|---|---|
| `SKIPPED ... no transactions recognised` | The CSV layout is unusual. Ask only for the **column header names** (not any rows) so you can say what to rename, or have them try the bank's other export option. |
| `PDF has no text layer` | The PDF is a scan. Download a CSV instead. |
| `could not open PDF` | Likely password-protected. Remove the password in a PDF viewer or use the CSV. |
| Spending and income look flipped | The script decides which sign means "spending" from paychecks and "payment - thank you" lines. If a file has neither, it uses the majority sign. Suggest adding a month that includes a paycheck or card payment, or use the bank's other CSV option. |
| PDF totals look off | PDF reading is best-effort. Spot-check one month against the statement; prefer CSV. |
| `dates look day-first` | Day-first dates (31/12/2026) are not supported because `03/04` would be ambiguous. Re-export with month-first or year-first dates (2026-12-31), or use the bank's other export. |
| Dashboard budgets disappeared | Browser-saved edits are per browser. Download `budgets.csv` and keep it in `_spend_tracker`. |

## Limits to be upfront about

- It was tested on fake statements in several layouts (Chase, Amex, Capital One, Bank of America and
  Wells Fargo style CSVs, plus a text-based PDF). It has not been tested on every bank, and the first run on a real
  statement may need a rule or two.
- Categorisation is keyword-based, not AI. That keeps data local but means unusual merchants need a rule.
- The output holds spending patterns, which can still be personal. Treat the folder like financial records.
- This is a tracking tool, not financial, tax or legal advice.
