#!/usr/bin/env python3
"""
spendscan.py - private, local-only spending tracker.

You put your bank / credit-card statements (CSV or PDF) in ONE folder on your
own computer. This script reads them there, throws away everything that could
identify you (descriptions, merchant strings, names, account numbers, exact
dates) and keeps only:  month + category + amount.  It then builds an offline
dashboard that compares your spending with the budget you set.

Nothing is uploaded and the script never touches the network.
Standard library only.  (PDF files also need:  pip install pdfplumber)

Usage:
    spendscan "/path/to/my_statements"        (after pip install)
    python3 scripts/spendscan.py "/path/to/my_statements" --open   (no install needed)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import secrets
import sys
import webbrowser
from collections import Counter, defaultdict
from pathlib import Path

VERSION = "1.3"
WORKDIR = "_spend_tracker"          # created inside your statements folder
DEFAULT_ACCOUNT = "main"

# --------------------------------------------------------------------------
# Categories. Format: keyword -> category.  Keywords are matched against the
# UPPER-CASE statement description. The longest matching keyword wins, and
# anything in your own categories.csv beats the built-in list.
# --------------------------------------------------------------------------
INCOME = "Income"
CARD_PAYMENT = "Credit card payment"
OWN_TRANSFER = "Transfers (own accounts)"
OTHER_DEPOSITS = "Other deposits"
P2P = "Person-to-person (Zelle/Venmo/checks)"
AMAZON = "Amazon orders"
BIGBOX = "Walmart/Target (mixed)"
UNCATEGORIZED = "Uncategorized"
EXCLUDED = {INCOME, CARD_PAYMENT, OWN_TRANSFER, OTHER_DEPOSITS}

DEFAULT_RULES: dict[str, list[str]] = {
    INCOME: ["PAYROLL", "DIRECT DEP", "DIRECT DEPOSIT", "SALARY", "PAYCHECK",
             "ADP ", "GUSTO", "DIVIDEND", "INTEREST PAID", "INTEREST PAYMENT",
             "TAX REFUND", "IRS TREAS", "EDD "],
    CARD_PAYMENT: ["PAYMENT THANK YOU", "AUTOPAY", "AUTO PAY", "ONLINE PAYMENT",
                   "CREDIT CARD PAYMENT", "CRCARDPMT", "CARD PAYMENT",
                   "CHASE CREDIT CRD", "AMEX EPAYMENT", "AMERICAN EXPRESS ACH",
                   "DISCOVER E-PAYMENT", "DISCOVER PAYMENT", "CITI AUTOPAY",
                   "CAPITAL ONE ONLINE PMT", "CAPITAL ONE MOBILE PMT",
                   "BARCLAYCARD", "WELLS FARGO CARD", "BK OF AMER VISA",
                   "BANK OF AMERICA CREDIT CARD", "MOBILE PAYMENT",
                   "PAYMENT TO CRD", "CARD ONLINE DES:PAYMENT"],
    OWN_TRANSFER: ["TRANSFER TO SAV", "TRANSFER FROM SAV", "TRANSFER TO CHK",
                   "TRANSFER FROM CHK", "ONLINE TRANSFER", "INTERNAL TRANSFER",
                   "ACCT TRANSFER", "ACCOUNT TRANSFER", "XFER"],
    P2P: ["ZELLE", "VENMO", "CASH APP", "CASHAPP", "SQUARE CASH", "CHECK #",
          "CHECK NO", "WIRE TRANSFER", "WIRE TO"],
    "Groceries": ["SAFEWAY", "KROGER", "TRADER JOE", "WHOLE FOODS", "ALBERTSONS",
                  "VONS", "RALPHS", "SPROUTS", "ALDI", "COSTCO WHSE", "FOOD 4 LESS",
                  "SMART & FINAL", "STATER BROS", "GROCERY", "SUPERMARKET",
                  "H MART", "99 RANCH", "PUBLIX", "HEB ", "WEGMANS", "INSTACART",
                  "FRESH MARKET", "WHOLEFDS", "WINCO", "FOOD LION", "MEIJER"],
    "Eating out": ["TST*", "MCDONALD", "STARBUCKS", "CHIPOTLE", "SUBWAY", "DOMINO",
                   "PIZZA", "DOORDASH", "UBER EATS", "UBEREATS", "GRUBHUB",
                   "CAFE", "COFFEE", "RESTAURANT", "GRILL", "BURGER", "TACO",
                   "SUSHI", "BAKERY", "DINER", "BBQ", "PANERA", "CHICK-FIL",
                   "IN-N-OUT", "WENDY", "DUNKIN", "PEET", "KITCHEN", "BREWING",
                   "BAR & ", "PUB ", "RAMEN", "BOBA", "TEA ", "DELI", "BISTRO"],
    "Gas / fuel": ["SHELL", "CHEVRON", "ARCO ", "EXXON", "MOBIL ", "VALERO",
                   "TEXACO", "SPEEDWAY", "COSTCO GAS", "BP ", "CONOCO",
                   "SUNOCO", "FUEL", "GAS STATION"],
    "Utilities & phone": ["SO CAL EDISON", "SOCAL GAS", "SOUTHERN CALIFORNIA EDISON", "SCE ", "PG&E", "PGE ",
                          "SDG&E", "LADWP", "ELECTRIC", "WATER DISTRICT",
                          "WATER BILL", "SOCALGAS", "GAS COMPANY", "COMCAST",
                          "XFINITY", "SPECTRUM", "AT&T", "VERIZON", "T-MOBILE",
                          "TMOBILE", "INTERNET", "WASTE MANAGEMENT",
                          "REPUBLIC SERVICES", "UTILITIES", "METROPCS"],
    "Subscriptions": ["NETFLIX", "SPOTIFY", "HULU", "DISNEY PLUS", "DISNEYPLUS",
                      "APPLE.COM/BILL", "GOOGLE *", "YOUTUBE", "AMAZON PRIME",
                      "PRIME VIDEO", "ADOBE", "DROPBOX", "ICLOUD", "OPENAI",
                      "ANTHROPIC", "CLAUDE.AI", "PATREON", "AUDIBLE", "NYTIMES",
                      "GITHUB", "MICROSOFT*", "HBO", "PARAMOUNT", "PEACOCK"],
    "Rent & housing": ["RENT ", "MORTGAGE", "PROPERTY MGMT", "PROPERTY MANAGEMENT",
                       "APARTMENT", "HOA ", "LEASING"],
    "Home & garden": ["HOME DEPOT", "LOWES", "LOWE'S", "ACE HARDWARE", "IKEA",
                      "TRUE VALUE", "HARBOR FREIGHT", "BED BATH", "CONTAINER STORE",
                      "NURSERY", "ORCHARD SUPPLY"],
    "Insurance": ["GEICO", "STATE FARM", "PROGRESSIVE", "ALLSTATE", "INSURANCE",
                  "FARMERS INS", "LEMONADE"],
    "Transportation": ["UBER", "LYFT", "METRO", "TRANSIT", "PARKING", "TOLL ",
                       "FASTRAK", "CLIPPER", "AMTRAK"],
    "Health & pharmacy": ["CVS", "WALGREENS", "PHARMACY", "DENTAL", "MEDICAL",
                          "CLINIC", "HOSPITAL", "KAISER", "OPTOMETRY", "LABCORP",
                          "QUEST DIAG", "URGENT CARE", "VISION", "DERMATOLOGY"],
    "Shopping": ["BEST BUY", "NORDSTROM", "MACY", "ZARA", "NIKE",
                 "TJ MAXX", "MARSHALLS", "APPLE STORE", "ETSY", "UNIQLO",
                 "OLD NAVY", "GAP ", "H&M", "DICK'S"],
    AMAZON: ["AMZN MKTP", "AMAZON", "AMZN"],
    BIGBOX: ["WALMART", "WAL-MART", "WM SUPERCENTER", "TARGET", "COSTCO", "SAM'S CLUB"],
    "Entertainment": ["AMC ", "CINEMA", "THEATRE", "THEATER", "TICKETMASTER",
                      "STEAM", "PLAYSTATION", "NINTENDO", "XBOX", "BOWLING",
                      "GOLF", "STUBHUB", "EVENTBRITE", "MUSEUM", "ZOO"],
    "Travel": ["AIRLINES", "UNITED AIR", "DELTA AIR", "SOUTHWEST", "AIRBNB",
               "HOTEL", "MARRIOTT", "HILTON", "EXPEDIA", "BOOKING.COM",
               "HERTZ", "ENTERPRISE RENT", "AVIS"],
    "Fitness & wellness": ["GYM", "FITNESS", "24 HOUR", "PLANET FIT", "YMCA",
                           "PELOTON", "YOGA", "SALON", "BARBER", "SPA "],
    "Fees & interest": ["INTEREST CHARGE", "FINANCE CHARGE", "LATE FEE",
                        "OVERDRAFT", "SERVICE FEE", "ANNUAL FEE", "ATM FEE",
                        "FOREIGN TRANSACTION", "MONTHLY MAINTENANCE"],
    "Cash withdrawals": ["ATM WITHDRAWAL", "ATM W/D", "CASH WITHDRAWAL", "ATM"],
    "Car maintenance": ["TIRE CHOICE", "DISCOUNT TIRE", "FIRESTONE", "JIFFY LUBE", "MIDAS",
                        "VALVOLINE", "PEP BOYS", "AUTOZONE", "O'REILLY AUTO", "OREILLY AUTO",
                        "ADVANCE AUTO", "SMOG", "AUTO REPAIR", "AUTO GLASS", "PAYLESS GLASS",
                        "CAR WASH", "DMV", "BRAKE", "OIL CHANGE"],
    "Pets": ["PETCO", "PETSMART", "VETERINARY", "VET ", "CHEWY"],
    "Education & childcare": ["TUITION", "UNIVERSITY", "SCHOOL", "DAYCARE",
                              "CHILDCARE", "UDEMY", "COURSERA"],
    "Taxes": ["FRANCHISE TAX", "FREETAXUSA", "TURBOTAX", "IRS USATAXPYMT", "H&R BLOCK"],
    "Donations": ["DONATION", "CHARITY", "RED CROSS", "UNITED WAY", "GOFUNDME",
                  "SALVATION ARMY", "GOODWILL DONATION"],
}

# --------------------------------------------------------------------------
# Starter pack: more common US merchants. Merged into DEFAULT_RULES below.
# Your own categories.csv always wins over everything here. Pull requests that
# add well-known merchants are welcome (see CONTRIBUTING.md): keep keywords
# specific, because a keyword matches anywhere a word starts.
# --------------------------------------------------------------------------
STARTER_PACK: dict[str, list[str]] = {
    INCOME: ["PAYROLL", "DIRECT DEP", "SOCIAL SECURITY", "SSA TREAS", "UNEMPLOYMENT", "PENSION"],
    CARD_PAYMENT: ["CHASE CARD", "APPLE CARD", "SYNCHRONY", "WF CREDIT CARD", "WELLS FARGO CREDIT",
                   "BANK OF AMERICA CARD", "BOFA CREDIT", "CITI CARD", "CITIBANK ONLINE",
                   "CAPITAL ONE CRCARDPMT", "DISCOVER E-PAYMENT", "AMEX EPAYMENT", "PAYMENT TO CHASE",
                   "PAYMENT TO AMEX", "PAYMENT TO CITI", "GS BANK"],
    OWN_TRANSFER: ["VANGUARD", "FIDELITY INV", "SCHWAB", "ROBINHOOD", "BETTERMENT", "WEALTHFRONT",
                   "ACORNS", "COINBASE", "TRANSFER TO SAVINGS", "TRANSFER FROM SAVINGS",
                   "TRANSFER TO CHECKING", "TRANSFER FROM CHECKING"],
    "Groceries": ["FRED MEYER", "GIANT EAGLE", "HARRIS TEETER", "PIGGLY WIGGLY", "SHOPRITE",
                  "STOP & SHOP", "GIANT FOOD", "WEIS MARKETS", "GROCERY OUTLET", "SMITHS FOOD",
                  "CARDENAS", "NORTHGATE", "VALLARTA", "SEAFOOD CITY", "WINN-DIXIE", "SAVE MART",
                  "TOM THUMB", "RANDALLS", "KING SOOPERS", "FRYS FOOD", "FRY'S FOOD", "FOOD CITY",
                  "MARKET BASKET", "BJS WHOLESALE", "BJ'S WHOLESALE", "SHIPT", "GOPUFF",
                  "HALAL MARKET", "MEAT MARKET", "FISH MARKET", "FARMERS MARKET", "FARMER'S MARKET",
                  "SMART AND FINAL", "NATURAL GROCERS",
                  "AMAZON FRESH", "FRESH THYME", "LIDL", "MERCADO", "SUPERMERCADO"],
    "Eating out": ["CHICK FIL A", "JACK IN THE BOX", "TACO BELL", "KFC", "POPEYES", "FIVE GUYS",
                   "SHAKE SHACK", "WHATABURGER", "SONIC DRIVE", "CARLS JR", "IHOP", "DENNY",
                   "CRACKER BARREL", "OLIVE GARDEN", "APPLEBEE", "CHILI'S", "OUTBACK STEAK",
                   "RED LOBSTER", "PANDA EXPRESS", "HABIT BURGER", "CULVER", "DUTCH BROS",
                   "KRISPY KREME", "TIM HORTON", "COLDSTONE", "BASKIN", "YOGURTLAND", "JAMBA",
                   "SWEETGREEN", "NOODLES & CO", "PEI WEI", "P.F. CHANG", "PF CHANG", "BUFFALO WILD",
                   "WINGSTOP", "LITTLE CAESAR", "PAPA JOHN", "BLAZE PIZZA", "MOD PIZZA",
                   "COFFEE BEAN", "PHILZ", "CAVA ", "DONUT", "GELATO",
                   "CREAMERY", "ICE CREAM", "JUICE", "SMOOTHIE", "WAFFLE", "PANCAKE", "BAKE SHOP",
                   "STEAKHOUSE", "SEAFOOD", "THAI ", "NOODLE", "KEBAB", "KEBOB", "CHICKEN",
                   "CUISINE", "EATERY", "TAQUERIA", "PHO ", "WINGS", "SANDWICH", "BAGEL",
                   "SEATED", "RESY", "OPENTABLE", "CAVIAR", "POSTMATES"],
    "Gas / fuel": ["UNION 76", "CIRCLE K", "QUIKTRIP", "RACETRAC", "WAWA", "SHEETZ", "PILOT TRAVEL",
                   "LOVES TRAVEL", "MURPHY USA", "CASEY'S", "CASEYS", "MAVERIK", "SINCLAIR",
                   "PHILLIPS 66", "MARATHON PETRO", "CITGO", "GULF OIL", "KUM & GO", "BUC-EE",
                   "CARDLOCK", "USA GAS", "EV CHARGING", "CHARGEPOINT", "ELECTRIFY AMERICA",
                   "EVGO", "TESLA SUPERCHARGER"],
    "Utilities & phone": ["CON ED", "CONSOLIDATED EDISON", "DUKE ENERGY", "NATIONAL GRID",
                          "DOMINION ENERGY", "XCEL ENERGY", "PSE&G", "DTE ENERGY", "AMEREN",
                          "ENTERGY", "CHARTER COMM", "COX COMM", "FRONTIER COMM", "GOOGLE FI",
                          "MINT MOBILE", "CRICKET WIRELESS", "BOOST MOBILE",
                          "STRAIGHT TALK", "US MOBILE", "SEWER", "TRASH", "SOUTHWEST GAS",
                          "PUGET SOUND ENERGY", "AUSTIN ENERGY", "CITY UTILITIES"],
    "Subscriptions": ["NAMECHEAP", "NAME-CHEAP", "GODADDY", "GOOGLE ONE", "GOOGLE WORKSPACE",
                      "GOOGLE*WORKSPACE", "GOOGLE STORAGE", "SLACK", "ZOOM.US", "NOTION", "CANVA",
                      "CHATGPT", "MIDJOURNEY", "SUBSTACK", "DUOLINGO", "MASTERCLASS", "SIRIUS",
                      "PANDORA", "TIDAL", "APPLE TV", "APPLE COM BILL", "CRUNCHYROLL", "LASTPASS",
                      "1PASSWORD", "NORDVPN", "EXPRESSVPN", "DASHLANE", "COSTCO *ANNUAL",
                      "COSTCO ANNUAL", "COSTCO MEMBERSHIP", "WSJ", "WASHINGTON POST", "NEW YORK TIMES",
                      "MAX.COM", "DISCOVERY+", "FUBO", "SLING TV", "ESPN+", "PLAYSTATION PLUS",
                      "XBOX GAME PASS", "NINTENDO ONLINE", "DOORDASH DASHPASS", "UBER ONE", "WALMART+"],
    "Rent & housing": ["ZILLOW RENT", "APARTMENTS.COM", "BUILDIUM", "APPFOLIO", "RENTCAFE", "CHEXY",
                       "RENT PAYMENT", "PROPERTY MGMT", "LANDLORD", "HOMEOWNERS ASSOC"],
    "Home & garden": ["HOMEGOODS", "WAYFAIR", "CRATE & BARREL", "POTTERY BARN", "WEST ELM",
                      "MENARDS", "SHERWIN", "FLOOR & DECOR", "TRACTOR SUPPLY", "PLUMBING", "HVAC",
                      "LANDSCAP", "PEST CONTROL", "LOCKSMITH", "ROOFING", "HANDYMAN", "CONTRACTOR",
                      "WATER HEATER", "APPLIANCE", "FURNITURE", "MATTRESS", "ROOMS TO GO"],
    "Insurance": ["AAA INS", "LIBERTY MUTUAL", "NATIONWIDE", "TRAVELERS INS", "USAA",
                  "AMERICAN FAMILY", "METLIFE", "PRUDENTIAL", "ROOT INSURANCE", "ALLSTATE", "ASSURANT",
                  "BLUE SHIELD", "BLUE CROSS", "ANTHEM", "CIGNA", "AETNA", "UNITEDHEALTH"],
    "Transportation": ["UBR*", "WAY.COM", "PARKMOBILE", "SPOTHERO", "PAYBYPHONE", "LAZ PARKING",
                       "PARKING", "E-ZPASS", "EZPASS", "SUNPASS", "IPASS", "GREYHOUND", "FLIXBUS",
                       "ZIPCAR", "WAYMO", "BART ", "SEPTA", "WMATA", "CTA ", "METROLINK",
                       "PUBLIC TRANSPORT", "TAXI", "PARK MOBILE", "PARKWHIZ"],
    "Health & pharmacy": ["RITE AID", "DENTIST", "ORTHODON", "OPTICAL", "LENSCRAFTERS", "WARBY PARKER",
                          "PEDIATRIC", "PHYSICAL THERAPY", "ZOCDOC", "TELADOC", "ONE MEDICAL",
                          "SUTTER", "SCRIPPS", "CEDARS", "MEMORIALCARE", "COPAY", "GNC", "VITAMIN SHOPPE",
                          "PHARMACY", "PRESCRIPTION", "WALGREENS", "EYE CARE", "CHIROPRACT", "THERAPY",
                          "FAMILY MEDICINE", "LAB CORP"],
    "Shopping": ["ROSS STORES", "DSW", "BURLINGTON", "KOHL", "JCPENNEY", "SEPHORA", "ULTA", "LULULEMON",
                 "ADIDAS", "UNDER ARMOUR", "FOOT LOCKER", "SKECHERS", "ABERCROMBIE", "AMERICAN EAGLE",
                 "HOLLISTER", "BATH & BODY", "FOREVER 21", "SHEIN", "TEMU", "ALIEXPRESS", "EBAY",
                 "GOODWILL", "DOLLAR TREE", "DOLLAR GENERAL", "FIVE BELOW", "BIG LOTS", "MICHAELS",
                 "HOBBY LOBBY", "JOANN", "PARTY CITY", "BARNES & NOBLE", "BOOKSTORE", "GAMESTOP",
                 "BASS PRO", "CABELA", "REI CO", "ACADEMY SPORTS", "BUY BUY BABY", "CARTER",
                 "CHILDREN'S PLACE", "STAPLES", "OFFICE DEPOT", "MICROSOFT STORE", "VICTORIA'S SECRET",
                 "BURLINGTON", "SP ", "SHOPIFY", "PAYPAL *", "ETSY", "WISH.COM", "SHOE", "APPAREL",
                 "CLOTHING", "BOUTIQUE", "PERFUME", "JEWEL", "OUTLET"],
    "Entertainment": ["MOVIE", "REGAL", "CINEMARK", "FANDANGO", "DAVE & BUSTER", "TOPGOLF", "DISNEYLAND",
                      "UNIVERSAL STUDIOS", "SIX FLAGS", "KNOTTS", "SEAWORLD", "LEGOLAND", "NATIONAL PARK",
                      "STATE PARK", "RECREATION.GOV", "RESERVE AMERICA", "ARCADE", "ESCAPE ROOM",
                      "TRAMPOLINE", "AQUARIUM", "CONVENTION CENTER", "CONV C", "BOWL ",
                      "AMUSEMENT", "WATER PARK", "THEME PARK", "REGIONAL PARKS", "MINI GOLF", "CONCERT", "LIVE NATION"],
    "Travel": ["SOUTHWES", "ALASKA AIR", "JETBLUE", "AMERICAN AIR", "SPIRIT AIR", "FRONTIER AIR",
               "UA.COM", "HAWAIIAN AIR", "VRBO", "HYATT", "IHG", "BEST WESTERN", "HOLIDAY INN",
               "MOTEL", "RESORT", "KAYAK", "PRICELINE", "TRIP.COM", "TRAVELOCITY", "AGENT FEE",
               "COSTCO TRAVEL", "CARNIVAL", "ROYAL CARIBBEAN", "CRUISE", "BUDGET RENT", "NATIONAL CAR",
               "ALAMO RENT", "TURO", "AIRPORT", "SMARTPARKING", "HOTELS.COM", "AMEX TRAVEL",
               "CHASE TRAVEL", "TRAVEL AGENCY", "LODGE", "SUITES"],
    "Fitness & wellness": ["ANYTIME FITNESS", "LA FITNESS", "EQUINOX", "ORANGETHEORY", "CRUNCH FIT",
                           "F45", "SOULCYCLE", "CLASSPASS", "BARRY'S", "PILATES", "MASSAGE", "NAILS",
                           "HAIRCUT", "HAIR SALON", "BEAUTY", "WAXING", "TANNING"],
    "Fees & interest": ["WIRE FEE", "NSF ", "RETURNED ITEM", "MAINTENANCE FEE", "FX FEE", "LATE PAYMENT FEE",
                        "INTEREST CHARGED", "PURCHASE INTEREST", "MEMBERSHIP FEE", "FINANCE FEE", "PENALTY"],
    "Pets": ["BARKBOX", "PET SUPPLIES", "PET FOOD", "VETCO", "BANFIELD", "BLUE BUFFALO", "ROVER.COM",
             "PET SMART", "ANIMAL HOSPITAL", "GROOMING"],
    "Education & childcare": ["COLLEGE", "KUMON", "CODE NINJAS", "TUTOR", "BRIGHT HORIZONS", "KINDERCARE",
                             "MONTESSORI", "LEARNING CENTER", "MUSIC LESSON", "COLLEGE BOARD", "KHAN",
                             "LINKEDIN LEARNING", "PTA", "SCHOOL", "CHESS"],
    "Taxes": ["IRS ", "STATE TAX", "TAXACT", "HRBLOCK", "COUNTY TAX", "TAX COLLECTOR", "PROPERTY TAX",
              "FRANCHISE TAX BO", "FRANCHISE TAX BOARD", "TAX PAYMENT", "TAXES"],
    "Donations": ["GOFUNDME", "LAUNCHGOOD", "UNICEF", "DOCTORS WITHOUT", "WIKIMEDIA", "ST JUDE",
                  "SAVE THE CHILDREN", "WORLD VISION", "HABITAT FOR", "FEEDING AMERICA", "ACLU",
                  "CHURCH", "MOSQUE", "MASJID", "SYNAGOGUE", "TITHE", "NPO*", "RELIEF", "CHARIT",
                  "DONATE", "FUNDRAIS", "NONPROFIT"],
}
for _cat, _kws in STARTER_PACK.items():
    DEFAULT_RULES.setdefault(_cat, [])
    DEFAULT_RULES[_cat].extend(k for k in _kws if k not in DEFAULT_RULES[_cat])


RULES_HEADER = ["keyword", "category"]
BUDGET_HEADER = ["category", "monthly_budget"]

ANCHOR_IN_RX = re.compile(r"PAYMENT.{0,6}THANK YOU|PAYMENT RECEIVED")


# ------------------------------ helpers ------------------------------------
def die(msg: str, code: int = 1) -> None:
    print(f"\nERROR: {msg}\n", file=sys.stderr)
    sys.exit(code)


def norm_desc(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").upper()).strip()


DATE_FORMATS = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%m-%d-%y",
                "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y", "%b %d, %Y", "%b %d %Y",
                "%B %d, %Y", "%d-%b-%y"]


def parse_date(s: str):
    s = (s or "").strip().strip('"')
    if not s:
        return None
    s = re.sub(r"\s+", " ", s)
    if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d", s):
        s = s[:10]
    for f in DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, f).date()
        except ValueError:
            pass
    return None


def parse_amount(s):
    """Return (cents:int, flag) or None. flag is 'CR', 'DR' or None."""
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    t = t.replace("−", "-").replace("$", "").replace(",", "").replace(" ", "")
    flag = None
    m = re.search(r"(CR|DR)$", t, re.I)
    if m:
        flag, t = m.group(1).upper(), t[: m.start()]
    if t.endswith("-"):
        neg, t = True, t[:-1]
    if t.startswith("+"):
        t = t[1:]
    try:
        v = float(t)
    except ValueError:
        return None
    cents = int(round(abs(v) * 100))
    if neg or v < 0:
        cents = -cents
    return cents, flag


# ------------------------------ rules --------------------------------------
class Rules:
    def __init__(self, user_rows: list[tuple[str, str]]):
        self.entries = []  # (priority tuple, regex, category)
        for cat, kws in DEFAULT_RULES.items():
            for kw in kws:
                self.entries.append(((0, len(kw.strip())), self._rx(kw), cat))
        for kw, cat in user_rows:
            self.entries.append(((1, len(kw.strip())), self._rx(kw), cat))
        self.entries.sort(key=lambda e: e[0], reverse=True)
        self.income_rx = self._group(INCOME)
        self.pay_rx = self._group(CARD_PAYMENT)

    @staticmethod
    def _rx(kw: str):
        """A keyword never starts in the middle of a word ("RENT" skips "CURRENT").
        Keywords of 3 letters or fewer, or written with a trailing space ("RENT "),
        must also end at a word edge ("BP" skips "BPM")."""
        kw = kw.upper()
        core = kw.strip()
        pat = r"(?<![A-Z0-9])" + re.escape(core)
        if len(core) <= 3 or kw.endswith(" "):
            pat += r"(?![A-Z0-9])"
        return re.compile(pat)

    def _group(self, cat):
        pats = [e[1].pattern for e in self.entries if e[2] == cat]
        return re.compile("|".join(pats)) if pats else re.compile(r"(?!x)x")

    def match(self, desc: str):
        for _, rx, cat in self.entries:
            if rx.search(desc):
                return cat
        return None

    def classify(self, desc: str, direction: str):
        """direction: 'out' (money left) or 'in' (money arrived)."""
        cat = self.match(desc)
        if direction == "in":
            if cat == INCOME:
                return INCOME
            if cat in (CARD_PAYMENT, OWN_TRANSFER):
                return cat
            if cat is None or cat == P2P:
                return OTHER_DEPOSITS
            return cat  # refund or return in a spending category
        # money out
        if cat in (CARD_PAYMENT, OWN_TRANSFER):
            return cat
        if cat in (INCOME, OTHER_DEPOSITS) or cat is None:
            return UNCATEGORIZED
        return cat


def clean_for_review(desc: str) -> str:
    """Only used for the local unmatched_merchants.txt helper file."""
    d = norm_desc(desc)
    d = re.sub(r"[X*#]{2,}\s*\d*", "#", d)
    d = re.sub(r"\d{4,}", "#", d)
    d = re.sub(r"\s+", " ", d).strip()
    return d[:40]


# ------------------------------ CSV parsing --------------------------------
ALIASES = {
    "date": ["transaction date", "trans date", "trans. date", "date",
             "posting date", "post date", "posted date", "booking date"],
    "desc": ["description", "transaction description", "original description",
             "details", "merchant", "payee", "name", "memo", "narrative",
             "reference"],
    "amount": ["amount", "transaction amount", "amount (usd)", "value"],
    "debit": ["debit", "debits", "withdrawal", "withdrawals", "money out",
              "paid out", "debit amount"],
    "credit": ["credit", "credits", "deposit", "deposits", "money in",
               "paid in", "credit amount"],
}


def read_rows(path: Path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(text.splitlines(), dialect))


def map_header(row):
    cells = [c.strip().lower() for c in row]
    m = {}
    for key, names in ALIASES.items():
        for n in names:
            if n in cells:
                m[key] = cells.index(n)
                break
    ok = "date" in m and ("amount" in m or "debit" in m or "credit" in m)
    return m if ok else None


def parse_csv(path: Path):
    rows = read_rows(path)
    header_at, mapping = None, None
    for i, r in enumerate(rows[:40]):
        mp = map_header(r)
        if mp:
            header_at, mapping = i, mp
            break
    txns = []
    dayfirst = [0]

    def check_dayfirst(cell):
        m = re.match(r"^\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\s*$", cell or "")
        if m and int(m.group(1)) > 12 and int(m.group(2)) <= 12:
            dayfirst[0] += 1

    def finish(kind):
        if dayfirst[0]:
            raise FileProblem("dates look day-first (like 31/12/2026), which is not supported "
                              "because 03/04 would be ambiguous. Re-export with month-first or "
                              "year-first dates (2026-12-31) if your bank allows it.")
        return txns, kind

    if mapping is None:  # headerless export: guess the columns
        for r in rows:
            if r:
                check_dayfirst(r[0])
            if not r or parse_date(r[0]) is None:
                continue
            amt_i = next((i for i, c in enumerate(r[1:], 1)
                          if parse_amount(c) is not None and parse_date(c) is None), None)
            if amt_i is None:
                continue
            others = [(len(c), c) for i, c in enumerate(r) if i not in (0, amt_i)
                      and parse_amount(c) is None]
            desc = max(others)[1] if others else ""
            txns.append(_mk(parse_date(r[0]), desc, parse_amount(r[amt_i]), None))
        return finish("headerless")
    for r in rows[header_at + 1:]:
        if not r or len(r) <= mapping["date"]:
            continue
        check_dayfirst(r[mapping["date"]])
        d = parse_date(r[mapping["date"]])
        if d is None:
            continue
        desc = r[mapping["desc"]] if "desc" in mapping and len(r) > mapping["desc"] else ""
        if "amount" in mapping and len(r) > mapping["amount"]:
            a = parse_amount(r[mapping["amount"]])
            if a is None:
                continue
            txns.append(_mk(d, desc, a, None))
        else:
            deb = parse_amount(r[mapping["debit"]]) if "debit" in mapping and len(r) > mapping["debit"] else None
            cre = parse_amount(r[mapping["credit"]]) if "credit" in mapping and len(r) > mapping["credit"] else None
            if deb and deb[0]:
                txns.append(_mk(d, desc, (abs(deb[0]), None), "out"))
            elif cre and cre[0]:
                txns.append(_mk(d, desc, (abs(cre[0]), None), "in"))
    return finish("columns")


def _mk(date, desc, amt, direction):
    cents, flag = amt
    if flag == "CR" and direction is None:
        direction = "in"
    elif flag == "DR" and direction is None:
        direction = "out"
    return {"date": date, "desc": desc or "", "signed": cents, "direction": direction}


def assign_directions(txns, rules: Rules):
    """Decide which sign means 'money left your account' for signed-amount files."""
    pending = [t for t in txns if t["direction"] is None]
    if not pending:
        return "explicit"
    pos_in = neg_in = 0
    for t in pending:
        d = norm_desc(t["desc"])
        # Paychecks and "PAYMENT - THANK YOU" lines are always money coming IN to the
        # account they appear on. (A card payment leaving checking is NOT an anchor.)
        if rules.income_rx.search(d) or ANCHOR_IN_RX.search(d):
            if t["signed"] > 0:
                pos_in += 1
            else:
                neg_in += 1
    if pos_in != neg_in:
        spend_sign = -1 if pos_in > neg_in else 1
        how = "from payroll/payment lines"
    else:
        pos = sum(1 for t in pending if t["signed"] > 0)
        neg = sum(1 for t in pending if t["signed"] < 0)
        spend_sign = 1 if pos > neg else -1
        how = "from the majority sign"
    for t in pending:
        t["direction"] = "out" if (t["signed"] > 0) == (spend_sign > 0) else "in"
    return f"{'positive' if spend_sign > 0 else 'negative'} = spending ({how})"


# ------------------------------ PDF parsing --------------------------------
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
AMT_PAT = r"-?\(?\$?\d[\d,]*\.\d{2}\)?-?(?:\s?(?:CR|DR))?"
TXN_LINE = re.compile(
    r"^(?P<date>\d{1,2}/\d{1,2}(?:/\d{2,4})?|[A-Za-z]{3}\.?\s+\d{1,2}(?:,?\s+\d{4})?)\s+"
    r"(?:(?:\d{1,2}/\d{1,2}|[A-Za-z]{3}\.?\s+\d{1,2})\s+)?"
    r"(?P<desc>.+?)\s+(?P<amt>" + AMT_PAT + r")(?:\s+(?P<bal>-?\$?\d[\d,]*\.\d{2}))?\s*$")


class FileProblem(Exception):
    """A file we cannot read safely; the message is shown to the user."""


PdfProblem = FileProblem


def pdf_lines(path: Path):
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        raise PdfProblem("PDF support needs one extra install:  pip install pdfplumber")
    lines = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                lines += (page.extract_text() or "").splitlines()
    except Exception as e:  # password-protected, corrupt, ...
        raise PdfProblem(f"could not open PDF ({type(e).__name__}). If it is password "
                         "protected, remove the password or download a CSV instead.")
    if not any(l.strip() for l in lines):
        raise PdfProblem("PDF has no text layer (probably a scan). Download a CSV instead.")
    return lines


def parse_pdf(path: Path):
    lines = pdf_lines(path)
    blob = "\n".join(lines).upper()
    is_card = any(k in blob for k in ("NEW BALANCE", "MINIMUM PAYMENT", "PAYMENTS AND CREDITS",
                                      "CREDIT LIMIT", "PURCHASES"))
    this_year = dt.date.today().year
    # ignore implausible numbers that merely look like years (e.g. 2050 in a rewards figure)
    years = sorted({int(y) for y in re.findall(r"\b(20\d{2})\b", blob)
                    if this_year - 10 <= int(y) <= this_year + 1})
    raw = []
    for ln in lines:
        m = TXN_LINE.match(ln.strip())
        if not m:
            continue
        raw.append((m.group("date"), m.group("desc"), m.group("amt")))
    # year-less dates: work out the year(s) from the statement text
    parsed = []
    for dstr, desc, astr in raw:
        d = parse_date(dstr.replace(".", ""))
        month = day = None
        if d is None:
            mm = re.match(r"(\d{1,2})/(\d{1,2})$", dstr)
            if mm:
                month, day = int(mm.group(1)), int(mm.group(2))
            else:
                m2 = re.match(r"([A-Za-z]{3})\.?\s+(\d{1,2})$", dstr)
                if m2 and m2.group(1).upper() in MONTHS:
                    month, day = MONTHS[m2.group(1).upper()], int(m2.group(2))
            if month is None:
                continue
        parsed.append([d, month, day, desc, astr])
    spans_year = len(years) >= 2 and years[-1] - years[0] == 1
    months_seen = {p[1] for p in parsed if p[0] is None}
    wrap = bool(months_seen & {10, 11, 12} and months_seen & {1, 2, 3})
    default_year = years[-1] if years else dt.date.today().year
    txns = []
    for d, month, day, desc, astr in parsed:
        if d is None:
            year = default_year - 1 if (wrap and month >= 7) else default_year
            try:
                d = dt.date(year, month, day)
                if d > dt.date.today() + dt.timedelta(days=31):
                    d = dt.date(year - 1, month, day)  # a statement cannot hold future purchases
            except ValueError:
                continue
        a = parse_amount(astr)
        if a is None:
            continue
        cents, flag = a
        up = desc.upper()
        if flag == "CR":
            direction = "in"
        elif flag == "DR":
            direction = "out"
        elif cents < 0:
            direction = "in" if is_card else "out"
        else:
            direction = "in" if re.search(r"DEPOSIT|REFUND|PAYMENT THANK|PAYROLL|CREDIT|RETURN", up) else "out"
        txns.append({"date": d, "desc": desc, "signed": abs(cents), "direction": direction,
                     "card_stmt": is_card})
    return txns, "pdf (best effort)"


# ------------------------------ dataset ------------------------------------
def load_salt(work: Path) -> str:
    p = work / ".salt"
    if not p.exists():
        p.write_text(secrets.token_hex(16))
    return p.read_text().strip()


def make_id(salt, account, t, occ):
    key = f"{salt}|{account}|{t['date'].isoformat()}|{t['signed']}|{t['direction']}|{norm_desc(t['desc'])}|{occ}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def read_dataset(path: Path):
    out = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["id"]] = r
    return out


def write_dataset(path: Path, data: dict):
    rows = sorted(data.values(), key=lambda r: (r["month"], r["account"], r["category"], r["id"]))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "month", "account", "category", "flow", "amount"])
        w.writeheader()
        w.writerows(rows)


def load_rules(work: Path) -> Rules:
    p = work / "categories.csv"
    if not p.exists():
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(RULES_HEADER)
            w.writerow(["# add your own lines below:  keyword,category   (example: JOES PIZZA,Eating out)", ""])
    user = []
    with p.open(newline="", encoding="utf-8") as f:
        for r in csv.reader(f):
            if len(r) >= 2 and r[0].strip() and not r[0].startswith("#") and r[0] != "keyword":
                user.append((r[0].strip(), r[1].strip()))
    # lines like  $2495.00,Rent & housing  match an exact payment amount (for Zelle/check payments,
    # whose names are never stored). They only apply to money-out lines that are otherwise
    # Person-to-person or Uncategorized.
    amounts = {}
    merges = {}
    plain = []
    for kw, cat in user:
        if kw.startswith("@"):
            merges[kw[1:].strip()] = cat   # "@Groceries,Home & food" renames a whole category
        elif kw.startswith("$"):
            try:
                amounts[int(round(float(kw[1:].replace(",", "")) * 100))] = cat
            except ValueError:
                pass
        else:
            plain.append((kw, cat))
    rules = Rules(plain)
    rules.amount_rules = amounts
    rules.merges = merges
    return rules


def load_budgets(work: Path, categories):
    p = work / "budgets.csv"
    budgets = {}
    if p.exists():
        with p.open(newline="", encoding="utf-8") as f:
            for r in csv.reader(f):
                if len(r) >= 2 and r[0] != "category" and not r[0].startswith("#"):
                    try:
                        budgets[r[0].strip()] = float(r[1].replace("$", "").replace(",", ""))
                    except ValueError:
                        pass
    else:
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(BUDGET_HEADER)
            for c in sorted(categories):
                w.writerow([c, ""])
    return budgets


# ------------------------------ main run -----------------------------------
def discover(folder: Path):
    files = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file() or WORKDIR in p.parts:
            continue
        if p.suffix.lower() in (".csv", ".pdf"):
            files.append(p)
    return files


def account_of(folder: Path, f: Path):
    rel = f.relative_to(folder)
    return rel.parts[0] if len(rel.parts) > 1 else DEFAULT_ACCOUNT



LARGE_P2P_CENTS = 50000


def write_clarify_file(work: Path, dataset):
    """List big Zelle/Venmo/check payments that still have no label, grouped by exact amount.
    Names are never stored, so the user is the only one who knows what they were."""
    groups = defaultdict(list)
    for r in dataset.values():
        if r["category"] == P2P and r["flow"] == "out":
            cents = int(round(float(r["amount"]) * 100))
            if cents >= LARGE_P2P_CENTS:
                groups[cents].append(r["month"])
    path = work / "payments_to_clarify.txt"
    if not groups:
        path.write_text("Nothing to clarify: every large Zelle/Venmo/check payment has a label.\n", encoding="utf-8")
        return 0
    lines = ["LOCAL FILE. Large Zelle / Venmo / check payments (over $500) with no label yet.",
             "Names are not stored, so only you know what these were. For each amount, add a line to",
             "categories.csv such as   $2495.00,Rent & housing   (it labels every payment of exactly that amount),",
             "then run the script again.", ""]
    for cents in sorted(groups, key=lambda c: -c * len(groups[c])):
        months = sorted(groups[cents])
        span = months[0] if months[0] == months[-1] else f"{months[0]} to {months[-1]}"
        lines.append(f"  ${cents / 100:,.2f}  x{len(months)}  ({span})  total ${cents * len(months) / 100:,.2f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(groups)


LEDGER = "processed_files.csv"


def file_fingerprint(salt: str, f: Path, acct: str) -> str:
    h = hashlib.sha256()
    h.update(salt.encode()); h.update(acct.encode()); h.update(f.read_bytes())
    return h.hexdigest()[:20]


def rules_signature(work: Path) -> str:
    cp = work / "categories.csv"
    body = cp.read_bytes() if cp.exists() else b""
    built_in = json.dumps(DEFAULT_RULES, sort_keys=True).encode()
    return hashlib.sha256(VERSION.encode() + built_in + body).hexdigest()[:16]


def read_ledger(work: Path):
    """Return (rules_sig, {fingerprint}) from the last run, or (None, set())."""
    lp = work / LEDGER
    if not lp.exists():
        return None, set()
    sig, ids = None, set()
    for row in csv.reader(lp.open(encoding="utf-8")):
        if not row:
            continue
        if row[0] == "#rules" and len(row) > 1:
            sig = row[1]
        elif row[0] not in ("file_id",) and not row[0].startswith("#"):
            ids.add(row[0])
    return sig, ids


def write_ledger(work: Path, sig: str, entries):
    with (work / LEDGER).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["#rules", sig])
        w.writerow(["file_id", "account", "rows"])
        for fid, acct, n in entries:
            w.writerow([fid, acct, n])


def read_unmatched(path: Path):
    c = Counter()
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*(\d+)  (.+)$", ln)
            if m:
                c[m.group(2).strip()] += int(m.group(1))
    return c


def run(folder: Path, open_after: bool, force: bool = False):
    if not folder.is_dir():
        die(f"'{folder}' is not a folder. Put your statements in one folder and pass its path.")
    work = folder / WORKDIR
    work.mkdir(exist_ok=True)
    salt = load_salt(work)
    rules = load_rules(work)
    files = discover(folder)
    if not files:
        die(f"No .csv or .pdf files found in '{folder}'. Add your statements and run again.")

    dataset_path = work / "transactions.csv"
    dataset = read_dataset(dataset_path)
    before = len(dataset)
    report, unmatched = [], Counter()
    seen_this_run = set()
    new_ids = updated_ids = skipped_rows = 0

    sig = rules_signature(work)
    old_sig, done_ids = read_ledger(work)
    incremental = (not force) and old_sig == sig and bool(dataset)
    ledger_entries, processed_any = [], False

    for f in files:
        acct = account_of(folder, f)
        fid = file_fingerprint(salt, f, acct)
        if incremental and fid in done_ids:
            ledger_entries.append((fid, acct, "kept"))
            report.append(f"  DONE     {f.name}  [{acct}] already processed, skipped")
            continue
        processed_any = True
        try:
            if f.suffix.lower() == ".pdf":
                txns, kind = parse_pdf(f)
            else:
                txns, kind = parse_csv(f)
        except PdfProblem as e:
            report.append(f"  SKIPPED  {f.name}: {e}")
            continue
        except Exception as e:
            report.append(f"  SKIPPED  {f.name}: could not read ({type(e).__name__}).")
            continue
        if not txns:
            report.append(f"  SKIPPED  {f.name}: no transactions recognised (unusual layout).")
            continue
        convention = assign_directions(txns, rules)
        occ = Counter()
        n_new = n_upd = n_dup = 0
        for t in txns:
            key = (t["date"], t["signed"], t["direction"], norm_desc(t["desc"]))
            occ[key] += 1
            tid = make_id(salt, acct, t, occ[key])
            if tid in seen_this_run:
                n_dup += 1
                continue
            seen_this_run.add(tid)
            cat = rules.classify(norm_desc(t["desc"]), t["direction"])
            if t["direction"] == "out" and cat in (P2P, UNCATEGORIZED):
                cat = getattr(rules, "amount_rules", {}).get(abs(t["signed"]), cat)
            cat = getattr(rules, "merges", {}).get(cat, cat)
            if t.get("card_stmt") and t["direction"] == "in" and cat == OTHER_DEPOSITS:
                cat = CARD_PAYMENT  # unlabelled credit on a card statement = payment
            if cat == UNCATEGORIZED:
                unmatched[clean_for_review(t["desc"])] += 1
            row = {"id": tid, "month": t["date"].strftime("%Y-%m"), "account": acct,
                   "category": cat, "flow": t["direction"],
                   "amount": f"{abs(t['signed']) / 100:.2f}"}
            if tid in dataset:
                n_upd += 1
            else:
                n_new += 1
            dataset[tid] = row
        new_ids += n_new
        updated_ids += n_upd
        ledger_entries.append((fid, acct, len(txns)))
        report.append(f"  OK       {f.name}  [{acct}] {len(txns)} rows, {n_new} new, "
                      f"{n_upd} already known, {n_dup} repeated in another file  ({kind}; {convention})")

    write_dataset(dataset_path, dataset)
    n_clarify = write_clarify_file(work, dataset)
    budgets = load_budgets(work, [c for c in DEFAULT_RULES if c not in EXCLUDED] + [UNCATEGORIZED])

    write_ledger(work, sig, ledger_entries)

    # local-only helper: what could not be matched
    um = work / "unmatched_merchants.txt"
    if incremental:
        unmatched = unmatched + read_unmatched(um)  # keep earlier leftovers when old files are skipped
    if unmatched:
        um.write_text(
            "LOCAL FILE - stays on your computer. Contains cleaned merchant text, so do NOT share it\n"
            "unless you have read it and are comfortable. To categorise a line, add it to\n"
            "categories.csv as   KEYWORD,Category   then run the script again.\n\n"
            + "\n".join(f"{n:>4}  {m}" for m, n in unmatched.most_common(60)) + "\n",
            encoding="utf-8")
    elif um.exists():
        try:
            um.unlink()
        except OSError:
            um.write_text("Nothing left to categorise.\n", encoding="utf-8")

    write_dashboard(work, dataset, budgets)

    spend_rows = [r for r in dataset.values() if r["category"] not in EXCLUDED]
    unc = sum(float(r["amount"]) for r in spend_rows if r["category"] == UNCATEGORIZED and r["flow"] == "out")
    tot = sum(float(r["amount"]) for r in spend_rows if r["flow"] == "out") or 1
    lines = ["", f"spendscan {VERSION} - folder: {folder}", "Files:"] + report + [
        "",
        f"Transactions stored: {len(dataset)}  (+{len(dataset) - before} this run)",
        f"Uncategorized: {unc / tot:.0%} of spending",
        (f"To label: {n_clarify} amount(s) of large Zelle/Venmo/check payments (over $500). See payments_to_clarify.txt"
         if n_clarify else "Large Zelle/Venmo/check payments: all labelled"),
        f"Dashboard:   {work / 'dashboard.html'}",
        f"Budgets:     {work / 'budgets.csv'}   (fill in monthly amounts, then run again)",
        f"Categories:  {work / 'categories.csv'}   (add your own keyword,category lines)",
    ]
    if unmatched:
        lines.append(f"Review:      {um}   (local only; lists merchants that need a category)")
    if any("pdf" in r for r in report):
        lines.append("Note: PDF reading is best-effort. Spot-check one month against your statement.")
    text = "\n".join(lines)
    (work / "last_run_report.txt").write_text(text, encoding="utf-8")
    print(text)
    if open_after:
        webbrowser.open((work / "dashboard.html").resolve().as_uri())


# ------------------------------ dashboard ----------------------------------
def write_dashboard(work: Path, dataset: dict, budgets: dict):
    agg = defaultdict(lambda: [0.0, 0])
    for r in dataset.values():
        k = (r["month"], r["account"], r["category"], r["flow"])
        agg[k][0] += float(r["amount"])
        agg[k][1] += 1
    rows = [[m, a, c, fl, round(v[0], 2), v[1]] for (m, a, c, fl), v in sorted(agg.items())]
    data = {
        "rows": rows,
        "excluded": sorted(EXCLUDED),
        "uncategorized": UNCATEGORIZED,
        "budgets": budgets,
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "version": VERSION,
    }
    payload = json.dumps(data).replace("</", "<\\/")
    tpl = (Path(__file__).parent / "dashboard_template.html").read_text(encoding="utf-8")
    (work / "dashboard.html").write_text(tpl.replace("__DATA__", payload), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Private, local-only spending tracker.")
    ap.add_argument("folder", help="folder that holds all your statement files (.csv / .pdf)")
    ap.add_argument("--open", action="store_true", help="open the dashboard in your browser when done")
    ap.add_argument("--force", action="store_true", help="re-read every file even if it was processed before")
    args = ap.parse_args()
    run(Path(args.folder).expanduser().resolve(), args.open, args.force)


if __name__ == "__main__":
    main()
