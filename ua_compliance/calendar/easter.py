"""Пасхалія — чистий розрахунок без платформи, щоб його можна було перевірити окремо."""

from datetime import date, timedelta

TRINITY_OFFSET = 49


def orthodox_easter(year: int) -> date:
	"""Великдень за юліанською пасхалією, переведений у григоріанський календар."""
	a, b, c = year % 4, year % 7, year % 19
	d = (19 * c + 15) % 30
	e = (2 * a + 4 * b - d + 34) % 7
	month = (d + e + 114) // 31
	day = ((d + e + 114) % 31) + 1
	return date(year, month, day) + timedelta(days=13)


def trinity(year: int) -> date:
	"""Трійця — п'ятдесятий день від Великодня."""
	return orthodox_easter(year) + timedelta(days=TRINITY_OFFSET)
