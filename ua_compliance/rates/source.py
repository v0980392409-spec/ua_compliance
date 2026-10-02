"""Єдина точка звернення назовні: офіційний курс НБУ.

Тут немає жодного правила — лише запит і сира відповідь. Розбір і рішення, що
вважати даними, живуть у `parse.py`: джерело відповідає кодом 200 навіть на помилку.
"""

import requests

BASE_URL = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
TIMEOUT = 20


def build_url(on_date):
	"""Адреса запиту на дату. Формат дати — YYYYMMDD: на YYYY-MM-DD джерело
	відповідає кодом 200 і тілом «Wrong date format»."""
	return f"{BASE_URL}?date={on_date.strftime('%Y%m%d')}&json"


def fetch(on_date):
	"""Повертає сирий текст відповіді на дату. Один запит віддає всі валюти."""
	response = requests.get(build_url(on_date), timeout=TIMEOUT)
	response.raise_for_status()
	return response.text
