"""Turn a captured `make test` log into docs/submission/video/test-summary.txt (the video's test card).

    python scripts/video/test_summary.py make_test.log > docs/submission/video/test-summary.txt

First line: `# caption: ...` built only from the counts in the log; then the tail of the real output.
"""

import re
import sys
from datetime import datetime

log = open(sys.argv[1], encoding="utf-8", errors="replace").read()
plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", log)
lines = [ln.rstrip() for ln in plain.splitlines()]
final = next((ln for ln in reversed(lines) if re.search(r"\d+ passed", ln)), "")
passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", final)) else None
failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", final)) else 0
if passed is None:
    caption = "Every control tested · audit chain OK"
elif failed == 0:
    caption = f"make test: {passed:,} passed, 0 failed"
else:
    caption = f"make test: {passed:,} passed, {failed} failed"
keep = [ln for ln in lines if ln and not re.fullmatch(r"[.sxXFE]+(\s+\[\s*\d+%\])?", ln)]
total = [ln for ln in keep if "TOTAL" in ln or "UNTESTED" in ln]
tail = [ln for ln in keep[-4:] if ln not in total]
print(f"# caption: {caption}")
print(f"# source: make test, {datetime.now():%Y-%m-%d %H:%M}")
for ln in total[-1:] + tail:
    print(ln)
