"""Tests for the private spend tracker. Standard library only:  python3 -m unittest -v"""
import csv
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from private_spend_tracker import spendscan as S  # noqa: E402

SAMPLES = ROOT / "examples" / "sample_statements"
HAVE_PDF = True
try:
    import pdfplumber  # noqa: F401
except ImportError:
    HAVE_PDF = False


def run_tool(folder, *extra):
    p = subprocess.run([sys.executable, "-m", "private_spend_tracker", str(folder), *extra],
                       cwd=ROOT, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def read_ds(folder):
    with open(Path(folder) / "_spend_tracker" / "transactions.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if header:
            w.writerow(header)
        w.writerows(rows)


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.r = S.Rules([])

    def test_common_merchants(self):
        cases = {
            "SAFEWAY #1234 ANYTOWN CA": "Groceries",
            "STARBUCKS STORE 5521": "Eating out",
            "CHEVRON 0012345": "Gas / fuel",
            "NETFLIX.COM": "Subscriptions",
            "HOME DEPOT #55": "Home & garden",
            "COSTCO WHSE #1": "Groceries",
            "COSTCO GAS #1": "Gas / fuel",
            "TST*SOME BAKERY": "Eating out",
            "JIFFY LUBE 123": "Car maintenance",
            "ZELLE PAYMENT TO JANE": S.P2P,
        }
        for desc, cat in cases.items():
            self.assertEqual(self.r.match(desc), cat, desc)

    def test_keywords_do_not_start_mid_word(self):
        self.assertNotEqual(self.r.match("CURRENT BALANCE ADJ"), "Rent & housing")
        self.assertIsNone(self.r.match("BALTIMORE MD"))  # state abbreviations must not match
        self.assertIsNone(self.r.match("BPM STUDIO"))    # 'BP' must not match inside BPM

    def test_user_rule_beats_default_and_longest_wins(self):
        r = S.Rules([("STARBUCKS", "Work coffee"), ("JOES PIZZA", "Eating out")])
        self.assertEqual(r.match("STARBUCKS 1"), "Work coffee")
        self.assertEqual(r.match("JOES PIZZA 1"), "Eating out")

    def test_direction_handling(self):
        self.assertEqual(self.r.classify("ACME PAYROLL", "in"), S.INCOME)
        self.assertEqual(self.r.classify("SAFEWAY REFUND", "in"), "Groceries")  # refund reduces category
        self.assertEqual(self.r.classify("RANDOM ZELLE FROM BOB", "in"), S.OTHER_DEPOSITS)
        self.assertEqual(self.r.classify("MYSTERY SHOP", "out"), S.UNCATEGORIZED)
        self.assertEqual(self.r.classify("AUTOPAY THANK YOU", "out"), S.CARD_PAYMENT)


class EndToEnd(TmpCase):
    def copy_samples(self):
        dst = self.tmp / "stmts"
        shutil.copytree(SAMPLES, dst)
        if not HAVE_PDF:
            shutil.rmtree(dst / "pdfcard")
        return dst

    def test_all_sample_layouts_parse(self):
        d = self.copy_samples()
        code, out = run_tool(d)
        self.assertEqual(code, 0, out)
        self.assertNotIn("SKIPPED", out)
        rows = read_ds(d)
        self.assertGreaterEqual(len(rows), 40)
        accounts = {r["account"] for r in rows}
        self.assertTrue({"amex", "checking", "credit", "savings", "wells"} <= accounts)

    def test_output_holds_only_allowlisted_fields(self):
        d = self.copy_samples()
        run_tool(d)
        with open(d / "_spend_tracker" / "transactions.csv", encoding="utf-8") as f:
            self.assertEqual(f.readline().strip(), "id,month,account,category,flow,amount")
        rows = read_ds(d)
        for r in rows:
            self.assertRegex(r["month"], r"^\d{4}-\d{2}$")       # never an exact day
            self.assertRegex(r["id"], r"^[0-9a-f]{16}$")
            self.assertIn(r["flow"], ("in", "out"))
        # merchant text from the samples must not appear in anything that is meant to be shareable
        shareable = [d / "_spend_tracker" / n for n in ("transactions.csv", "dashboard.html", "budgets.csv")]
        for path in shareable:
            text = path.read_text(encoding="utf-8").upper()
            for needle in ("SAFEWAY", "STARBUCKS", "MAPLE APARTMENTS", "ACME CORP", "HULU"):
                self.assertNotIn(needle, text, f"{needle} leaked into {path.name}")

    def test_duplicate_file_is_not_double_counted(self):
        d = self.copy_samples()
        run_tool(d)
        n = len(read_ds(d))
        shutil.copy(d / "amex" / "amex_sep.csv", d / "amex" / "amex_sep_copy.csv")
        run_tool(d, "--force")
        self.assertEqual(len(read_ds(d)), n)

    def test_overlapping_statements_dedupe(self):
        d = self.copy_samples()
        code, out = run_tool(d)
        self.assertIn("repeated in another file", out)

    def test_processed_files_are_skipped_then_reread_when_rules_change(self):
        d = self.copy_samples()
        run_tool(d)
        code, out = run_tool(d)
        self.assertIn("already processed", out)
        self.assertNotIn("   OK ", out)
        cats = d / "_spend_tracker" / "categories.csv"
        with open(cats, "a", encoding="utf-8") as f:
            f.write("SAFEWAY,Corner store\n")
        code, out = run_tool(d)
        self.assertNotIn("already processed", out)
        self.assertIn("Corner store", {r["category"] for r in read_ds(d)})

    def test_new_file_is_added_incrementally(self):
        d = self.copy_samples()
        run_tool(d)
        n = len(read_ds(d))
        write_csv(d / "amex" / "amex_oct.csv", ["Date", "Description", "Amount"],
                  [["10/03/2026", "SAFEWAY #1 ANYTOWN", "40.00"], ["10/04/2026", "SHELL OIL 123", "35.00"]])
        code, out = run_tool(d)
        self.assertIn("already processed", out)
        self.assertEqual(len(read_ds(d)), n + 2)
        self.assertIn("2026-10", {r["month"] for r in read_ds(d)})

    def test_force_rereads_everything(self):
        d = self.copy_samples()
        run_tool(d)
        code, out = run_tool(d, "--force")
        self.assertNotIn("already processed", out)

    def test_unmatched_merchants_listed_locally(self):
        d = self.tmp / "s"
        write_csv(d / "card" / "a.csv", ["Date", "Description", "Amount"],
                  [["01/05/2026", "ZZ UNKNOWN WIDGETS 8837451", "10.00"], ["01/06/2026", "SAFEWAY 1", "20.00"]])
        run_tool(d)
        txt = (d / "_spend_tracker" / "unmatched_merchants.txt").read_text(encoding="utf-8")
        self.assertIn("ZZ UNKNOWN WIDGETS", txt)
        self.assertNotIn("8837451", txt)  # long digit runs (account/card/store numbers) are masked
        self.assertEqual(
            {r["category"] for r in read_ds(d)}, {S.UNCATEGORIZED, "Groceries"})

    def test_budgets_and_dashboard_created(self):
        d = self.copy_samples()
        run_tool(d)
        work = d / "_spend_tracker"
        for name in ("dashboard.html", "budgets.csv", "categories.csv", "last_run_report.txt", "processed_files.csv"):
            self.assertTrue((work / name).exists(), name)
        html = (work / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", html)
        self.assertNotIn("__DATA__", html)
        data = re.search(r'id="data">(.*?)</script>', html, re.S).group(1)
        self.assertIn("rows", json.loads(data))


class SpecialRules(TmpCase):
    def make(self, rules):
        d = self.tmp / "s"
        rows = [["03/01/2026", "ZELLE PAYMENT TO ALEX 123", "-2495.00"],
                ["04/01/2026", "ZELLE PAYMENT TO ALEX 124", "-2495.00"],
                ["04/02/2026", "VENMO PAYMENT TO JAMIE", "-700.00"],
                ["04/03/2026", "VENMO PAYMENT TO SOMEONE", "-80.00"],
                ["04/04/2026", "SAFEWAY 1", "-60.00"],
                ["04/05/2026", "ACME PAYROLL", "5000.00"]]
        write_csv(d / "checking" / "c.csv", ["Date", "Description", "Amount"], rows)
        if rules:
            (d / "_spend_tracker").mkdir()
            (d / "_spend_tracker" / "categories.csv").write_text(
                "keyword,category\n" + "\n".join(rules) + "\n", encoding="utf-8")
        run_tool(d)
        return d

    def cats(self, d):
        out = {}
        for r in read_ds(d):
            out.setdefault(r["category"], []).append(float(r["amount"]))
        return out

    def test_exact_amount_rule(self):
        d = self.make(["$2495.00,Rent & housing"])
        c = self.cats(d)
        self.assertEqual(c["Rent & housing"], [2495.0, 2495.0])
        self.assertIn(S.P2P, c)  # the other Venmo payments stay unlabeled

    def test_large_unlabelled_payments_are_listed_without_names(self):
        d = self.make([])
        txt = (d / "_spend_tracker" / "payments_to_clarify.txt").read_text(encoding="utf-8")
        self.assertIn("$2,495.00", txt)
        self.assertIn("$700.00", txt)
        self.assertNotIn("$80.00", txt)       # small payments do not need asking about
        self.assertNotIn("ALEX", txt.upper())
        self.assertNotIn("JAMIE", txt.upper())

    def test_clarify_file_empty_once_labelled(self):
        d = self.make(["$2495.00,Rent & housing", "$700.00,Education & childcare"])
        txt = (d / "_spend_tracker" / "payments_to_clarify.txt").read_text(encoding="utf-8")
        self.assertIn("Nothing to clarify", txt)

    def test_merge_rule_combines_categories(self):
        d = self.make(["@Groceries,Groceries & household", "TARGET,Target", "@Target,Groceries & household"])
        self.assertIn("Groceries & household", self.cats(d))
        self.assertNotIn("Groceries", self.cats(d))


class ParsingEdgeCases(TmpCase):
    def test_sign_convention_flipped_file(self):
        d = self.tmp / "s"
        # this bank exports spending as positive numbers and payroll as negative
        write_csv(d / "a" / "x.csv", ["Date", "Description", "Amount"],
                  [["05/01/2026", "ACME PAYROLL DIRECT DEP", "-3000.00"],
                   ["05/02/2026", "SAFEWAY 1", "50.00"], ["05/03/2026", "SHELL 22", "40.00"]])
        run_tool(d)
        rows = read_ds(d)
        spend = sum(float(r["amount"]) for r in rows if r["flow"] == "out" and r["category"] not in S.EXCLUDED)
        self.assertAlmostEqual(spend, 90.0)

    def test_day_first_dates_are_refused_not_guessed(self):
        d = self.tmp / "s"
        write_csv(d / "a" / "x.csv", ["Date", "Description", "Amount"],
                  [["31/01/2026", "SAFEWAY 1", "-50.00"], ["25/02/2026", "SHELL 22", "-40.00"]])
        code, out = run_tool(d)
        self.assertIn("SKIPPED", out)
        self.assertIn("day-first", out)

    def test_refund_reduces_category(self):
        d = self.tmp / "s"
        write_csv(d / "a" / "x.csv", ["Date", "Description", "Amount"],
                  [["05/01/2026", "ACME PAYROLL DIRECT DEP", "3000.00"],
                   ["05/02/2026", "SAFEWAY 1", "-100.00"], ["05/03/2026", "SAFEWAY REFUND", "30.00"]])
        run_tool(d)
        net = 0
        for r in read_ds(d):
            if r["category"] == "Groceries":
                net += float(r["amount"]) * (1 if r["flow"] == "out" else -1)
        self.assertAlmostEqual(net, 70.0)

    def test_repeated_identical_purchases_both_count(self):
        d = self.tmp / "s"
        write_csv(d / "a" / "x.csv", ["Date", "Description", "Amount"],
                  [["05/01/2026", "ACME PAYROLL DIRECT DEP", "3000.00"],
                   ["05/02/2026", "STARBUCKS 1", "-5.75"], ["05/02/2026", "STARBUCKS 1", "-5.75"]])
        run_tool(d)
        self.assertEqual(len([r for r in read_ds(d) if r["category"] == "Eating out"]), 2)

    def test_empty_folder_gives_clear_error(self):
        d = self.tmp / "empty"
        d.mkdir()
        code, out = run_tool(d)
        self.assertNotEqual(code, 0)
        self.assertIn("No .csv or .pdf", out)

    @unittest.skipUnless(HAVE_PDF, "pdfplumber not installed")
    def test_sample_pdf_parses(self):
        txns, kind = S.parse_pdf(SAMPLES / "pdfcard" / "visa_sep.pdf")
        self.assertGreaterEqual(len(txns), 4)


class Hygiene(unittest.TestCase):
    def test_source_has_no_network_or_process_code(self):
        src = (ROOT / "private_spend_tracker" / "spendscan.py").read_text(encoding="utf-8")
        for banned in ("import socket", "import urllib", "import requests", "import http",
                       "import subprocess", "import ftplib", "import smtplib", "os.system"):
            self.assertNotIn(banned, src)

    def test_dashboard_makes_no_network_requests(self):
        tpl = (ROOT / "private_spend_tracker" / "dashboard_template.html").read_text(encoding="utf-8")
        self.assertIn("default-src 'none'", tpl)
        self.assertNotRegex(tpl, r"(src|href)=[\"']https?://")
        for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon", "import("):
            self.assertNotIn(banned, tpl)

    def test_no_real_statements_or_outputs_in_repo(self):
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT)
            if "_spend_tracker" in rel.parts:
                self.fail(f"generated output committed: {rel}")
            if p.suffix.lower() in (".pdf", ".csv") and rel.parts[:2] != ("examples", "sample_statements"):
                self.fail(f"unexpected statement-like file: {rel}")


if __name__ == "__main__":
    unittest.main()
