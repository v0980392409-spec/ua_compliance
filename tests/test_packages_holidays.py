"""Розбір каналу «Календар»: битий рядок відхиляє пакет ще до затвердження."""

import pytest

from ua_compliance.packages.parse import parse_holidays
from ua_compliance.packages.reader import PackageError

HEADER = "holiday_name,rule_type,day,month,offset_days,is_day_off,valid_from,valid_to,basis_type,basis_number,basis_date,basis_url\n"
GOOD = (
	HEADER
	+ "День незалежності України,Фіксована дата,24,8,,1,1992-07-01,,Закон,2417-XII,1992-06-05,https://zakon.rada.gov.ua/laws/show/2417-12\n"
	+ "Пасха (Великдень),Великдень,,,0,1,1991-05-11,,Закон,871-XII,1991-03-20,https://zakon.rada.gov.ua/laws/show/871-12\n"
)


def test_rows_get_their_place_in_the_year():
	rows = parse_holidays("data/calendar.csv", GOOD.encode())
	assert [row["code"] for row in rows] == ["24.08", "Великдень"]


@pytest.mark.parametrize(
	"line,error",
	[
		("Свято,Щорічне,1,1,,1,2020-01-01,,Закон,1,2020-01-01,https://x", "невідомий вид правила"),
		("Свято,Фіксована дата,31,2,,1,2020-01-01,,Закон,1,2020-01-01,https://x", "не розпізнано"),
		("Свято,Фіксована дата,1,1,,так,2020-01-01,,Закон,1,2020-01-01,https://x", "0 або 1"),
		("Свято,Фіксована дата,1,1,,1,2020-01-01,2019-12-31,Закон,1,2020-01-01,https://x", "раніша"),
		("Свято,Фіксована дата,1,1,,1,01.01.2020,,Закон,1,2020-01-01,https://x", "не розпізнано"),
	],
)
def test_broken_row_rejects_package(line, error):
	with pytest.raises(PackageError, match=error):
		parse_holidays("data/calendar.csv", (HEADER + line + "\n").encode())


def test_same_holiday_twice_from_same_date_is_rejected():
	line = "Новий рік,Фіксована дата,1,1,,1,1972-06-01,,Закон,322-VIII,1971-12-10,https://x\n"
	with pytest.raises(PackageError, match="уже є в пакеті"):
		parse_holidays("data/calendar.csv", (HEADER + line + line).encode())
