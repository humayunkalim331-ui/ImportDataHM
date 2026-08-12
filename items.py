"""RM item catalog — a direct port of CATEGORY_DEFS from the original HTML/JS tool."""
import re

CATEGORY_DEFS = [
    {"key": "primary", "label": "PRIMARY INTERMEDIATES & AUXILIARIES", "items": [
        {"code": "PTA", "name": "PURIFIED TEREPHTHALIC ACID (PTA)", "hs": "2917.3610", "origin": "—", "plant": "Primary Intermediates & Auxiliaries"},
        {"code": "DEG", "name": "DIETHYLENE GLYCOL(DEG)", "hs": "2909.4100", "origin": "—", "plant": "Primary Intermediates & Auxiliaries"},
        {"code": "MEG", "name": "ETHYLENE GLYCOL (MEG)", "hs": "2905.3100", "origin": "—", "plant": "Primary Intermediates & Auxiliaries"},
        {"code": "IPA", "name": "ISOPHTHALIC ACID", "hs": "2917.3910", "origin": "—", "plant": "Primary Intermediates & Auxiliaries"},
    ]},
    {"key": "petchips", "label": "INTERMEDIATE RESINS (PET CHIPS)", "items": [
        {"code": "BGC", "name": "Bottle Grade Chip (BGC)", "hs": "3907.6120", "origin": "—", "plant": "Intermediate Resins (PET Chips)"},
        {"code": "FGR", "name": "FILM GRADE RESIN", "hs": "3907.6910", "origin": "—", "plant": "Intermediate Resins (PET Chips)"},
    ]},
    {"key": "downstream", "label": "DOWNSTREAM CONVERSION PRODUCTS", "items": [
        {"code": "PF-5402.3300", "name": "POLYESTER FILAMENT", "hs": "5402.3300", "origin": "—", "plant": "Downstream Conversion Products"},
        {"code": "PF-5402.4700", "name": "POLYESTER FILAMENT", "hs": "5402.4700", "origin": "—", "plant": "Downstream Conversion Products"},
        {"code": "PFILM-3920.6200", "name": "POLYESTER FILM", "hs": "3920.6200", "origin": "—", "plant": "Downstream Conversion Products"},
        {"code": "PFILM-3920.6900", "name": "POLYESTER FILM", "hs": "3920.6900", "origin": "—", "plant": "Downstream Conversion Products"},
    ]},
    {"key": "other", "label": "Other RMs", "items": [
        {"plant": "Novatex Plant", "code": "100000225/217", "name": "U1 Suspension", "origin": "DE", "hs": "3824.9999"},
        {"plant": "Novatex Plant", "code": "100000208", "name": "Catalyst ATA", "origin": "CN", "hs": "3815.1910"},
        {"plant": "Novatex Plant", "code": "100001785", "name": "Catalyst ATG", "origin": "CN", "hs": "2905.3900"},
        {"plant": "Novatex Plant", "code": "100000161", "name": "Phosphoric Acid", "origin": "JPY/DE", "hs": "2809.2010"},
        {"plant": "Novatex Plant", "code": "100000023", "name": "Blue Toner Powder (Global PRT Blue-2)", "origin": "UK GB", "hs": "3204.1110"},
        {"plant": "Novatex Plant", "code": "100000070", "name": "Red Toner Powder (Global PRT Red Dispersion-2)", "origin": "UK GB", "hs": "3204.1120"},
        {"plant": "Bopet KHI & Bopet SKP", "code": "100000006", "name": "Aluminium Wire", "origin": "INDO/ESP", "hs": "7605.1900"},
        {"plant": "Bopet KHI & Bopet SKP", "code": "100000941", "name": "Aluminium Pellets", "origin": "ESP", "hs": "7605.1100"},
        {"plant": "Bopet KHI & Bopet SKP", "code": "100000044", "name": "Snow XS Silica", "origin": "JPY", "hs": "2811.2200"},
        {"plant": "Bopet KHI & Bopet SKP", "code": "100000065", "name": "Surfactant RY-3", "origin": "JPY", "hs": "3402.4200"},
        {"plant": "Bopet KHI & Bopet SKP", "code": "100000170", "name": "Polyester Resin WB-630", "origin": "CN", "hs": "3907.6990"},
        {"plant": "Bopet KHI & Bopet SKP", "code": "100000058", "name": "Evaporation Boats", "origin": "DE", "hs": "6903.9090"},
        {"plant": "Bopet KHI & Bopet SKP", "code": "270030766", "name": "Graphite Tape", "origin": "DE", "hs": "6815.1900"},
        {"plant": "Bopet KHI & Bopet SKP", "code": "270030764", "name": "Graphite Suspension", "origin": "CN", "hs": "3801.9000"},
        {"plant": "Bopet KHI & Bopet SKP", "code": "110001027", "name": "Container Desiccant Strip", "origin": "CN", "hs": "3824.9999"},
        {"plant": "Gatron", "code": "100000045", "name": "Conning Oil", "origin": "CN", "hs": "2710.1991"},
        {"plant": "Gatron", "code": "100000212", "name": "Spin Finish Oil", "origin": "CN/JPY/DE", "hs": "3403.9131"},
        {"plant": "Gatron", "code": "100000257", "name": "Titanium Dioxide (TiO2)", "origin": "CN/DE", "hs": "2823.0010"},
        {"plant": "Gatron", "code": "100000998", "name": "Parchment Paper 65", "origin": "CN", "hs": "4806.1000"},
        {"plant": "Krystallite", "code": "100000164", "name": "Plastic Molding Comp CC0275L", "origin": "SA", "hs": "3901.2000"},
        {"plant": "Krystallite", "code": "100000164", "name": "Plastic Moulding Comp MB55E9", "origin": "UAE", "hs": "3901.2000"},
        {"plant": "Krystallite", "code": "100000164", "name": "Plastic Moulding Comp SX002J", "origin": "TH", "hs": "3901.2000"},
    ]},
]

_slug_re = re.compile(r"[^a-z0-9]+", re.IGNORECASE)


def _slug(s):
    return _slug_re.sub("-", str(s or ""))


ITEMS_BY_CATEGORY = {}
CATEGORY_LABELS = {}
for cd in CATEGORY_DEFS:
    for i, it in enumerate(cd["items"]):
        it["uid"] = f"{cd['key']}__{i}__{_slug(it.get('code') or it.get('name'))}"
        it["category"] = cd["key"]
        it.setdefault("plant", cd["label"])
    ITEMS_BY_CATEGORY[cd["key"]] = cd["items"]
    CATEGORY_LABELS[cd["key"]] = cd["label"]

CATEGORY_KEYS = [cd["key"] for cd in CATEGORY_DEFS]

FILE_TYPES = [
    {"key": "import", "label": "Import Customs Data", "desc": "Pakistan Customs import declarations (your company's imports)",
     "roles": [("hs", "HS Code"), ("desc", "Item Description"), ("gd", "GD Number"), ("importer", "Importer / Consignee"),
               ("supplier", "Supplier / Exporter"), ("origin", "Country of Origin"), ("qty", "Quantity"),
               ("price", "Unit Price"), ("currency", "Currency"), ("date", "Date")]},
    {"key": "export", "label": "Exporter Customs Data", "desc": "Customs data for exporters shipping this HS code (competing suppliers)",
     "roles": [("hs", "HS Code"), ("desc", "Item Description"), ("gd", "GD Number"), ("exporter", "Exporter Name"),
               ("expcountry", "Exporting Country"), ("buyer", "Buyer / Consignee"), ("qty", "Quantity"),
               ("price", "Unit Price"), ("currency", "Currency"), ("date", "Date")]},
    {"key": "wits", "label": "Global WITS Data", "desc": "World Bank WITS / Comtrade trade statistics by HS heading",
     "roles": [("hs", "HS Code"), ("desc", "Item Description"), ("reporter", "Reporter Country"), ("partner", "Partner Country"),
               ("flow", "Trade Flow (import/export)"), ("qty", "Quantity"), ("price", "Unit Price"),
               ("currency", "Currency"), ("year", "Year")]},
]
FILE_TYPES_BY_KEY = {ft["key"]: ft for ft in FILE_TYPES}


def all_items(custom_items):
    out = []
    for k in CATEGORY_KEYS:
        out.extend(ITEMS_BY_CATEGORY[k])
        out.extend(custom_items.get(k, []))
    return out


def find_item(uid, custom_items):
    for it in all_items(custom_items):
        if it["uid"] == uid:
            return it
    return None


def get_items_for_category(cat, removed_items, custom_items):
    removed = set(removed_items.get(cat, []))
    base = [i for i in ITEMS_BY_CATEGORY[cat] if i["uid"] not in removed]
    return base + custom_items.get(cat, [])


def removed_items_for_category(cat, removed_items):
    removed = set(removed_items.get(cat, []))
    return [i for i in ITEMS_BY_CATEGORY[cat] if i["uid"] in removed]
