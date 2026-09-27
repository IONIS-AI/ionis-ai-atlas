"""Guards on README.md claims that would otherwise go stale without anyone noticing. No database needed.

The ADIF badge is static: there is no public Atlas for it to query. So it is checked against the
version the database image points the database at (ADIF_CURRENT in db/load/atlas-db-lib.sh). When
that moves to a new ADIF release, this fails until the badge moves with it.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_adif_badge_matches_the_current_adif_version():
    lib = (ROOT / "db/load/atlas-db-lib.sh").read_text()
    current = re.search(r"^ADIF_CURRENT=([0-9.]+)", lib, re.M)
    assert current, "ADIF_CURRENT not found in db/load/atlas-db-lib.sh"

    badge = re.search(r"img\.shields\.io/badge/ADIF-([0-9.]+)-", (ROOT / "README.md").read_text())
    assert badge, "README.md has no ADIF badge"

    assert badge.group(1) == current.group(1), (
        f"README ADIF badge says {badge.group(1)}, the database image serves {current.group(1)}")
