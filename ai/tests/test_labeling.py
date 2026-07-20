from pathlib import Path

import pytest

from labeling.generate_batch import _read_od_rows, _reviewer_ids


def test_initial_template_meets_grouped_validation_minimum():
    rows = _read_od_rows(Path(__file__).resolve().parents[1] / "data" / "training" / "od_template.csv")
    assert len(rows) >= 3
    assert len({(row["origin_name"], row["dest_name"]) for row in rows}) >= 3


def test_labeling_requires_all_nine_reviewers():
    assert _reviewer_ids(9) == [f"reviewer_{number:02d}" for number in range(1, 10)]
    with pytest.raises(ValueError, match="최소 9명"):
        _reviewer_ids(8)
