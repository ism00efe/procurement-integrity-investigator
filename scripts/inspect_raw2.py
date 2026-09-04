import json
from collections import Counter
import statistics

path = "data/raw/nigeria_bpp_full.jsonl"

method_details = Counter()
num_tenderers_vals = Counter()
tender_period_days = []
missing_tender_period = 0
value_vs_minvalue_diff = 0
award_value_vs_tender_value = []
contract_count = 0
supplier_award_counts = Counter()
buyer_supplier_pairs = Counter()
rationale_vals = Counter()
eligibility_len = []
items_count = Counter()
n_with_tender = 0
sample_full_record = None

with open(path, encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        tender = rec.get("tender")
        if not tender:
            continue
        n_with_tender += 1
        method_details[tender.get("procurementMethodDetails")] += 1
        nt = tender.get("numberOfTenderers")
        num_tenderers_vals[nt] += 1
        rationale_vals[tender.get("procurementMethodRationale")] += 1

        tp = tender.get("tenderPeriod")
        if tp and tp.get("startDate") and tp.get("endDate"):
            try:
                from datetime import datetime
                s = datetime.fromisoformat(tp["startDate"].replace("Z", "+00:00"))
                e = datetime.fromisoformat(tp["endDate"].replace("Z", "+00:00"))
                tender_period_days.append((e - s).days)
            except Exception:
                pass
        else:
            missing_tender_period += 1

        items = tender.get("items") or []
        items_count[len(items)] += 1

        tval = (tender.get("value") or {}).get("amount")
        awards = rec.get("awards") or []
        buyer_name = (rec.get("buyer") or {}).get("name")
        for a in awards:
            aval = (a.get("value") or {}).get("amount")
            if tval and aval:
                award_value_vs_tender_value.append(aval / tval if tval else None)
            for s in a.get("suppliers") or []:
                sname = s.get("name")
                supplier_award_counts[sname] += 1
                if buyer_name and sname:
                    buyer_supplier_pairs[(buyer_name, sname)] += 1

        contracts = rec.get("contracts") or []
        contract_count += len(contracts)

        if sample_full_record is None and awards and rec.get("contracts"):
            sample_full_record = rec

print("N WITH TENDER:", n_with_tender)
print()
print("PROCUREMENT METHOD DETAILS:", method_details.most_common(20))
print()
print("NUMBER OF TENDERERS DIST:", sorted(num_tenderers_vals.items(), key=lambda x: (x[0] is None, x[0]))[:30])
print()
print("PROCUREMENT METHOD RATIONALE (sample):", rationale_vals.most_common(10))
print()
print("MISSING TENDER PERIOD:", missing_tender_period, "of", n_with_tender)
if tender_period_days:
    print("TENDER PERIOD DAYS stats: min=%d max=%d median=%d mean=%.1f n=%d" % (
        min(tender_period_days), max(tender_period_days), statistics.median(tender_period_days),
        statistics.mean(tender_period_days), len(tender_period_days)))
    print("Distribution sample (sorted, every 5%):")
    st = sorted(tender_period_days)
    for p in [0,5,10,25,50,75,90,95,99,100]:
        idx = min(len(st)-1, int(len(st)*p/100))
        print(f"  p{p}: {st[idx]} days")

print()
print("ITEMS COUNT DIST:", items_count.most_common(10))
print()
print("TOTAL CONTRACTS:", contract_count)
print()
print("TOP 15 SUPPLIERS BY AWARD COUNT:", supplier_award_counts.most_common(15))
print()
print("TOP 15 BUYER-SUPPLIER PAIRS:", buyer_supplier_pairs.most_common(15))
print()
if award_value_vs_tender_value:
    ratios = [r for r in award_value_vs_tender_value if r is not None]
    print("AWARD/TENDER VALUE RATIO stats: n=%d min=%.3f max=%.3f median=%.3f" % (
        len(ratios), min(ratios), max(ratios), statistics.median(ratios)))

print()
print("SAMPLE FULL RECORD (with tender+award+contract):")
print(json.dumps(sample_full_record, indent=2)[:6000])
