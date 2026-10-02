"""Юніт-тести розбору відповіді джерела курсів.

Без бази й без платформи: перевіряємо саме те місце, де джерело вводить в оману —
воно відповідає кодом 200 і на порожню дату, і на помилку.
"""

from datetime import date

import pytest

from ua_compliance.rates import parse, source

ON_DATE = date(2026, 9, 18)
OK_BODY = (
	'[{"r030":840,"txt":"Долар США","rate":44.6648,"cc":"USD","exchangedate":"18.09.2026"},'
	'{"r030":392,"txt":"Єна","rate":0.28301,"cc":"JPY","exchangedate":"18.09.2026"}]'
)


def test_valid_answer_keeps_six_decimals():
	rates = parse.parse(OK_BODY, ON_DATE)
	assert rates["USD"]["rate"] == 44.6648
	assert rates["JPY"]["rate"] == 0.28301


def test_source_normalises_to_one_unit():
	"""Джерело наводить курс до однієї одиниці, тому кратність дорівнює 1."""
	assert parse.parse(OK_BODY, ON_DATE)["JPY"]["multiplicity"] == 1


@pytest.mark.parametrize(
	"body",
	[
		"[\n{ \nWrong date format\n }\n]",  # помилка формату дати: навіть не JSON
		"[]",  # курс на дату ще не встановлено
		"[{}]",  # рядок без курсу
		'[{"cc":"USD"}]',
		'{"cc":"USD","rate":44.6}',  # об'єкт замість списку
		"",
	],
)
def test_answer_without_rate_is_not_data(body):
	with pytest.raises(parse.SourceAnswerError) as error:
		parse.parse(body, ON_DATE)
	assert "без курсу на 18.09.2026" in str(error.value)


def test_request_date_format_is_yyyymmdd():
	"""На YYYY-MM-DD джерело відповідає кодом 200 і тілом «Wrong date format»."""
	url = source.build_url(ON_DATE)
	assert "date=20260918" in url
	assert "2026-09-18" not in url
