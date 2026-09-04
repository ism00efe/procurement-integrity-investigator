import json
import sys
from collections import Counter

path = "data/raw/nigeria_bpp_full.jsonl"

n = 0
buyers = set()
suppliers = set()
methods = Counter()
statuses_tender = Counter()
statuses_award = Counter()
min_date, max_date = None, None
sample = None
field_presence = Counter()
has_tender = 0
has_awards = 0
has_parties = 0
num_bidders_dist = Counter()
currencies = Counter()

with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        n += 1
        if sample is None:
            sample = rec

        date = rec.get("date")
        if date:
            if min_date is None or date < min_date:
                min_date = date
            if max_date is None or date > max_date:
                max_date = date

        parties = rec.get("parties") or []
        if parties:
            has_parties += 1
        for p in parties:
            roles = p.get("roles") or []
            name = p.get("name")
            if "buyer" in roles or "procuringEntity" in roles:
                buyers.add(name)
            if "supplier" in roles:
                suppliers.add(name)

        tender = rec.get("tender")
        if tender:
            has_tender += 1
            m = tender.get("procurementMethod") or tender.get("procurementMethodDetails")
            methods[m] += 1
            statuses_tender[tender.get("status")] += 1
            tenderers = tender.get("tenderers") or []
            if tenderers:
                num_bidders_dist[len(tenderers)] += 1
            value = tender.get("value") or {}
            if value.get("currency"):
                currencies[value["currency"]] += 1
            for k in tender.keys():
                field_presence["tender." + k] += 1

        awards = rec.get("awards") or []
        if awards:
            has_awards += 1
        for a in awards:
            statuses_award[a.get("status")] += 1
            for k in a.keys():
                field_presence["award." + k] += 1

        for k in rec.keys():
            field_presence[k] += 1

        if n % 20000 == 0:
            print(f"...{n} processed", file=sys.stderr)

print("TOTAL RECORDS:", n)
print("DATE RANGE:", min_date, "to", max_date)
print("UNIQUE BUYERS:", len(buyers))
print("UNIQUE SUPPLIERS:", len(suppliers))
print("HAS TENDER:", has_tender, "HAS AWARDS:", has_awards, "HAS PARTIES:", has_parties)
print("TOP-LEVEL FIELD PRESENCE:", {k: v for k, v in field_presence.items() if "." not in k})
print()
print("PROCUREMENT METHODS:", methods.most_common(20))
print()
print("TENDER STATUSES:", statuses_tender.most_common(20))
print("AWARD STATUSES:", statuses_award.most_common(20))
print()
print("NUM BIDDERS DIST (top 15):", num_bidders_dist.most_common(15))
print("CURRENCIES:", currencies.most_common(10))
print()
print("TENDER FIELD PRESENCE:", {k: v for k, v in field_presence.items() if k.startswith("tender.")})
print()
print("AWARD FIELD PRESENCE:", {k: v for k, v in field_presence.items() if k.startswith("award.")})
print()
print("SAMPLE RECORD:")
print(json.dumps(sample, indent=2)[:4000])
