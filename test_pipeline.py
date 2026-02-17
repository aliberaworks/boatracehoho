# -*- coding: utf-8 -*-
"""Quick validation of the multi-tier pipeline"""
import sys, os, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
from main import scan_all_races, filter_races, run_simulations

hd = "20260217"
venues = ["04"]  # 1 venue only for speed

t0 = time.time()
scanned = scan_all_races(hd, venues)
print(f"\nScanned: {len(scanned)} races")
for s in scanned:
    print(f"  {s['rno']}R: wr1={s['win_rate_1']}")

print()
targets = filter_races(scanned)
print(f"\nTargets: {len(targets)} races")

if targets:
    # Simulate just 2 to save time
    results = run_simulations(targets[:2])
    for jcd, vdata in results.items():
        for rno, race in vdata["races"].items():
            print(f"\n  {rno}R [{race.get('tier','')}] -> "
                  f"order={race['pred']['predicted_order']} "
                  f"conf={race['pred']['confidence']}%")

print(f"\nTotal: {time.time()-t0:.0f}s")
