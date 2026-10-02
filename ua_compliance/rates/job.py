"""Завантаження офіційного курсу: вікно дат, перелік валют, журнал.

Функція не робить `commit` — це справа того, хто викликає. Інакше перевірки, які
створюють документи й відкочують транзакцію, лишали б сміття на стенді й ламалися
про власний успіх (урок фічі 019).
"""

import frappe
from frappe.utils import add_days, getdate, now_datetime

from ua_compliance.rates import parse as rates_parse
from ua_compliance.rates import source as rates_source
from ua_compliance.rates.writer import LOCAL_CURRENCY, upsert_rate

DEFAULT_CURRENCIES = ("USD", "EUR")
DEFAULT_BACKFILL_DAYS = 7


def target_currencies(settings=None):
	"""Валюти, у яких у компанії є документи або залишки, плюс долар і євро (FR-010).

	Налаштований перелік має пріоритет; поки він порожній, беремо умовчання плюс
	валюти, які вже зустрічаються в записах курсу.
	"""
	settings = settings or frappe.get_single("UA Compliance Settings")
	chosen = [row.currency for row in (settings.get("currencies") or []) if row.currency]
	if chosen:
		return sorted(set(chosen))

	# Поки перелік не налаштований, беремо валюти, у яких у компанії є залишки
	# (валютні рахунки й валюта компанії), плюс долар і євро.
	#
	# Навмисно НЕ виводимо перелік із наявних записів курсу: тоді будь-який
	# випадковий запис починає щодня тягнути за собою нову валюту, і завантаження
	# годує саме себе. Спіймано харнесом 02.10.2026: пісочна валюта перевірки
	# одразу потрапила в щоденний прогін.
	from_accounts = frappe.get_all("Account", pluck="account_currency", distinct=True)
	from_companies = frappe.get_all("Company", pluck="default_currency", distinct=True)
	used = {c for c in (from_accounts or []) + (from_companies or []) if c and c != LOCAL_CURRENCY}
	return sorted(set(DEFAULT_CURRENCIES) | used)


def load_rates(days=None, write_log=True, triggered_by=None):
	"""Вантажить курс за вікном останніх днів і за завтра.

	Повертає зведення: скільки дат перевірено, скільки записів створено й оновлено,
	перелік дат без курсу та текст помилки, якщо вона була.
	"""
	settings = frappe.get_single("UA Compliance Settings")
	days = int(days or settings.backfill_days or DEFAULT_BACKFILL_DAYS)
	currencies = target_currencies(settings)

	today = getdate()
	# Джерело встановлює курс напередодні: 18.09.2026 було встановлено курс на 21.09.2026,
	# тому вікно включає завтра.
	dates = [add_days(today, -offset) for offset in range(days - 1, -1, -1)] + [add_days(today, 1)]

	started = now_datetime()
	summary = {
		"checked": 0,
		"created": 0,
		"updated": 0,
		"unchanged": 0,
		"missing": [],
		"errors": [],
		"changes": [],
		"currencies": currencies,
		"period_from": dates[0],
		"period_to": dates[-1],
	}

	for on_date in dates:
		summary["checked"] += 1
		try:
			rates = rates_parse.parse(rates_source.fetch(on_date), on_date)
		except rates_parse.SourceAnswerError as error:
			# Для завтрашньої дати порожня відповідь — нормально: курс ще не встановлено.
			if on_date > today:
				summary["missing"].append(str(on_date))
			else:
				summary["errors"].append(str(error))
			continue
		except Exception as error:  # мережа, таймаут, код відповіді
			summary["errors"].append(f"{on_date}: {error}")
			continue

		for currency in currencies:
			row = rates.get(currency)
			if not row:
				continue
			action, previous = upsert_rate(on_date, currency, row["rate"], row["multiplicity"])
			if action == "created":
				summary["created"] += 1
			elif action == "updated":
				summary["updated"] += 1
				summary["changes"].append(f"{currency} на {on_date}: {previous} → {row['rate']}")
			else:
				summary["unchanged"] += 1

	if write_log:
		_write_log(summary, started, triggered_by)
	return summary


def _write_log(summary, started, triggered_by):
	parts = []
	if summary["changes"]:
		parts.append("Курс змінено джерелом: " + "; ".join(summary["changes"]))
	if summary["missing"]:
		parts.append("Курс ще не встановлено на: " + ", ".join(summary["missing"]))
	if summary["errors"]:
		parts.append("Помилки: " + "; ".join(summary["errors"]))
	parts.append("Валюти: " + ", ".join(summary["currencies"]))

	frappe.get_doc(
		{
			"doctype": "UA Operation Log",
			"kind": "Завантаження курсу",
			"result": "Помилка" if summary["errors"] else "Успішно",
			"started_at": started,
			"finished_at": now_datetime(),
			"period_from": summary["period_from"],
			"period_to": summary["period_to"],
			"checked_count": summary["checked"],
			"created_count": summary["created"],
			"updated_count": summary["updated"],
			"message": "\n".join(parts),
			"triggered_by": triggered_by or frappe.session.user,
		}
	).insert(ignore_permissions=True)


def scheduled_load_rates():
	"""Точка входу розкладу. Вимикач — у налаштуваннях."""
	settings = frappe.get_single("UA Compliance Settings")
	if not settings.rates_enabled:
		return
	load_rates(triggered_by="Administrator")
