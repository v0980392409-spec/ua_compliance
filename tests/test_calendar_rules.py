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


# Перенесення вихідного (ч. 3 ст. 67 КЗпП) і місце свята в році

from ua_compliance.calendar.rules import compose_days_off, slot_key  # noqa: E402

HOLIDAYS_2021 = [
	(date(2021, 5, 1), "День праці", True),  # субота
	(date(2021, 5, 2), "Пасха (Великдень)", True),  # неділя
	(date(2021, 5, 9), "День перемоги", True),  # неділя
	(date(2021, 6, 20), "Трійця", True),  # неділя
	(date(2021, 12, 25), "Різдво Христове", True),  # субота
	(date(2021, 8, 24), "День незалежності України", True),  # вівторок
]


def _kinds(entries, kind):
	return {day: names for day, entry_kind, names in entries if entry_kind == kind}


def test_holiday_on_weekend_moves_day_off_to_next_working_day():
	transfers = _kinds(compose_days_off(2021, HOLIDAYS_2021, lambda day: False), "transfer")
	# Саме так відпочивали 2021 року: 3 і 4 травня, 10 травня, 21 червня, 27 грудня
	assert transfers == {
		date(2021, 5, 3): ["День праці"],
		date(2021, 5, 4): ["Пасха (Великдень)"],
		date(2021, 5, 10): ["День перемоги"],
		date(2021, 6, 21): ["Трійця"],
		date(2021, 12, 27): ["Різдво Христове"],
	}


def test_weekday_holiday_is_day_off_without_transfer():
	entries = compose_days_off(2021, HOLIDAYS_2021, lambda day: False)
	assert _kinds(entries, "holiday") == {date(2021, 8, 24): ["День незалежності України"]}
	assert sum(1 for _day, kind, _names in entries if kind == "weekend") == 104


def test_martial_law_cancels_holidays_and_transfers():
	entries = compose_days_off(2021, HOLIDAYS_2021, lambda day: True)
	assert not _kinds(entries, "holiday") and not _kinds(entries, "transfer")


def test_martial_law_is_checked_on_each_holiday_date():
	# Воєнний стан закінчився 1 липня: травневі свята — ні, грудневе — так
	entries = compose_days_off(2021, HOLIDAYS_2021, lambda day: day < date(2021, 7, 1))
	assert set(_kinds(entries, "transfer")) == {date(2021, 12, 27)}
	assert set(_kinds(entries, "holiday")) == {date(2021, 8, 24)}


def test_two_holidays_on_one_date_are_one_day_with_both_names():
	# Порядок назв сталий (за абеткою), інакше повторна побудова бачила б «зміну» (FR-043)
	same_day = [(date(2016, 5, 2), "Пасха (Великдень)", True), (date(2016, 5, 2), "День праці", True)]
	assert _kinds(compose_days_off(2016, same_day, lambda day: False), "holiday") == {
		date(2016, 5, 2): ["День праці", "Пасха (Великдень)"]
	}


def test_not_day_off_rule_and_transfer_past_year_end_are_ignored():
	holidays = [(date(2022, 3, 9), "Робоче свято", False), (date(2022, 12, 31), "Субота в кінці року", True)]
	entries = compose_days_off(2022, holidays, lambda day: False)
	assert not _kinds(entries, "holiday") and not _kinds(entries, "transfer")


def test_slot_key_is_the_place_in_the_year():
	assert slot_key("Фіксована дата", "24", "8") == "24.08"
	assert slot_key("Великдень", None, None, "0") == "Великдень"
	assert slot_key("Трійця", None, None, 1) == "Трійця +1"
