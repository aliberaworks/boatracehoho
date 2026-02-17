# -*- coding: utf-8 -*-
import sys, os, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))

from src.utils.helpers import fetch_page, safe_float
from src.utils.constants import URLS

url = URLS["racelist"].format(rno=1, jcd="04", hd="20260217")
soup = fetch_page(url)

tbodies = soup.select("div.table1 table tbody")
print(f"tbody count: {len(tbodies)}")

# Check tbody[1] (boat 1) in detail
tb = tbodies[1]
rows = tb.select("tr")
print(f"\ntbody[1] has {len(rows)} rows")

for i, row in enumerate(rows):
    tds = row.select("td")
    print(f"\n  row[{i}] has {len(tds)} tds")
    for j, td in enumerate(tds):
        text = td.get_text(strip=True)
        classes = td.get("class", [])
        print(f"    td[{j}] class={classes} text=[{text[:40]}]")

# Check name link
link = tb.select_one("a[href*='racersearch/profile']")
if link:
    print(f"\nName link: [{link.get_text(strip=True)}]")
    print(f"Name link href: {link.get('href', '')}")
else:
    print("\nNo name link found!")
    # Check all links in tbody
    all_links = tb.select("a")
    print(f"All links in tbody: {len(all_links)}")
    for l in all_links[:5]:
        print(f"  href={l.get('href','')[:50]} text=[{l.get_text(strip=True)[:30]}]")

# Check all X.XX patterns
print(f"\nAll X.XX values in tbody[1]:")
for td in tb.select("td"):
    text = td.get_text(strip=True)
    if re.match(r'^\d\.\d{2}$', text):
        print(f"  {text}")
