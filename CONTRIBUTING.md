# Contributing

The two most useful things are **bank layouts** and **merchant rules**. Please never include real statements,
real transactions or real names in an issue or pull request. Use invented values.

## My bank's file doesn't work

Open an issue with:
- the **column header row only** (for example `Details,Posting Date,Description,Amount,Type,Balance`),
- two or three **invented** rows in the same format (fake merchants, fake amounts, same date and sign style),
- the message from `last_run_report.txt`.

If you can, add the fake file as `examples/sample_statements/<bank>/<name>.csv` plus a test in `tests/`.

## Adding merchants

Add well-known US merchants to `STARTER_PACK` in `private_spend_tracker/spendscan.py`. Guidelines:
- A keyword matches anywhere a word **starts** in the upper-case description, so keep it specific
  (`"DOLLAR TREE"`, not `"DOLLAR"`). Keywords of three letters or fewer must match a whole word.
- Skip names that are also common words, state abbreviations or personal (a local shop only you use).
- Add a case to `RuleTests.test_common_merchants` for anything tricky.

## Ground rules

- Standard library only for the core tool (pdfplumber stays optional).
- No network, subprocess or telemetry code. `tests/` enforces this.
- Anything new written to `transactions.csv` must pass the privacy allowlist test.

Run the tests with `python3 -m unittest discover -s tests -v`.
