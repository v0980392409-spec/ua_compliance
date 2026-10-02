"""Переходящі свята рахуються, а не зберігаються списком на кожен рік."""

from datetime import date

import pytest

from ua_compliance.calendar.easter import orthodox_easter, trinity


@pytest.mark.parametrize(
	"year,expected",
	[
		(2024, date(2024, 5, 5)),
		(2025, date(2025, 4, 20)),
		(2026, date(2026, 4, 12)),
		(2027, date(2027, 5, 2)),
	],
)
def test_orthodox_easter(year, expected):
	assert orthodox_easter(year) == expected


def test_trinity_is_forty_nine_days_after_easter():
	assert (trinity(2026) - orthodox_easter(2026)).days == 49
	assert trinity(2026) == date(2026, 5, 31)
