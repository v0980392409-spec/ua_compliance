"""Розбір відповіді джерела курсів.

Головне правило (FR-007): успішний код відповіді ще не означає даних. Джерело
відповідає кодом 200 і на порожню дату (`[]`), і на помилку (`[{ Wrong date format }]`,
що навіть не є коректним JSON). Тому успіхом вважається лише розібрана відповідь,
у якій є курс.
"""

import json


class SourceAnswerError(Exception):
	"""Відповідь джерела не містить курсу."""


def parse(body, on_date):
	"""Повертає {код валюти: {"rate": float, "multiplicity": int, "name": str}}.

	Кидає SourceAnswerError, якщо відповідь не розібрана або порожня.
	"""
	message = f"Джерело повернуло відповідь без курсу на {on_date.strftime('%d.%m.%Y')}"
	try:
		data = json.loads(body)
	except ValueError:
		raise SourceAnswerError(message) from None

	if not isinstance(data, list) or not data:
		raise SourceAnswerError(message)

	rates = {}
	for row in data:
		if not isinstance(row, dict):
			raise SourceAnswerError(message)
		code, rate = row.get("cc"), row.get("rate")
		if not code or rate in (None, ""):
			continue
		# Джерело наводить курс до однієї одиниці валюти (перевірено 21.09.2026:
		# єна 0,28301, форинт 0,140563), тому кратність дорівнює 1. Поле лишається,
		# бо воно є в as-is регістрі «Курси валют», а інші сервіси завантаження
		# котирують за 10 і 100 одиниць.
		rates[code] = {"rate": float(rate), "multiplicity": 1, "name": row.get("txt") or code}

	if not rates:
		raise SourceAnswerError(message)
	return rates
