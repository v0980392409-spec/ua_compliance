"""Правила календаря без платформи: місце свята в році й перенесення вихідного.

Чисті функції — їх перевіряють модульні тести без сайту.
"""

from datetime import date, timedelta

WEEKEND_WEEKDAYS = (5, 6)  # субота і неділя
RULE_TYPES = ("Фіксована дата", "Великдень", "Трійця")


def slot_key(rule_type, day=None, month=None, offset_days=None):
	"""Місце свята в році: «24.08», «Великдень», «Трійця +1».

	За ним пакет зіставляє правило з наявним. Не за назвою — закон перейменовує свята
	(9 травня перейменовували, а потім перенесли), і не за датами дії — ручний запис і
	пакет можуть почати відлік з різних днів.
	"""
	if rule_type == "Фіксована дата":
		return f"{int(day):02d}.{int(month):02d}"
	offset = int(offset_days or 0)
	return rule_type if not offset else f"{rule_type} {offset:+d}"


def compose_days_off(year, holidays, martial_law_on):
	"""Дні відпочинку року: [(дата, вид, назви)], вид — weekend | holiday | transfer.

	holidays — [(дата, назва, вихідний)] правил, чинних того року;
	martial_law_on(дата) — чи діє воєнний стан на цю дату.

	Поки діє воєнний стан, свята не є вихідними й перенесення немає (ч. 6 ст. 6 Закону
	2136-IX). Поза ним свято, що випало на вихідний, переносить вихідний на найближчий
	наступний робочий день (ч. 3 ст. 67 КЗпП): 2021 року 1 травня (субота) дало вихідний
	3 травня, а Великдень 2 травня — 4 травня. Пасха й Трійця — завжди неділя, тож
	вихідними вони стають саме через перенесення.
	"""
	start, end = date(year, 1, 1), date(year, 12, 31)
	holiday_names = {}
	for occurrence, name, is_day_off in sorted(holidays):
		if not is_day_off or martial_law_on(occurrence):
			continue
		names = holiday_names.setdefault(occurrence, [])
		if name not in names:
			names.append(name)

	transfers = {}
	for occurrence in sorted(holiday_names):
		if occurrence.weekday() not in WEEKEND_WEEKDAYS:
			continue
		candidate = occurrence + timedelta(days=1)
		while candidate.weekday() in WEEKEND_WEEKDAYS or candidate in holiday_names or candidate in transfers:
			candidate += timedelta(days=1)
		if candidate <= end:
			transfers[candidate] = holiday_names[occurrence]

	result = []
	current = start
	while current <= end:
		if current.weekday() in WEEKEND_WEEKDAYS:
			result.append((current, "weekend", []))
		elif current in holiday_names:
			result.append((current, "holiday", holiday_names[current]))
		elif current in transfers:
			result.append((current, "transfer", transfers[current]))
		current += timedelta(days=1)
	return result


# 40 годин на п'ятиденному тижні — нормальна тривалість (ст. 50 КЗпП)
NORMAL_HOURS_PER_DAY = 8


def pre_holiday_days(year, holidays, off_days, martial_law_on):
	"""Дати року, коли робочий день на годину коротший (ч. 1 ст. 53 КЗпП).

	Це робочий день, наступний за яким — святковий або неробочий день (ст. 73). Перед
	перенесеним вихідним скорочення немає: він не свято. Поки діє воєнний стан, ст. 53
	не застосовується (ч. 6 ст. 6 Закону 2136-IX). holidays — правила цього року й
	1 січня наступного: напередодні Нового року — 31 грудня.
	"""
	result = set()
	for occurrence, _name, is_day_off in holidays:
		if not is_day_off:
			continue
		eve = occurrence - timedelta(days=1)
		if eve.year != year or eve in off_days or eve.weekday() in WEEKEND_WEEKDAYS:
			continue
		if martial_law_on(eve):
			continue
		result.add(eve)
	return sorted(result)


def norm_by_month(year, off_days, eves, hours_per_day):
	"""Норма робочого часу помісячно: робочі дні, передсвяткові дні, години.

	Скорочення на годину — лише за нормальної тривалості (8 годин на день). За скороченої
	тривалості передсвятковий день не скорочується (ч. 1 ст. 53 КЗпП, «крім працівників,
	зазначених у статті 51»): так рахує й Мінекономіки — на 2021 рік 1994 години за
	40-годинного тижня, але рівно 250 × 7,2 = 1800 за 36-годинного.
	"""
	shorten = float(hours_per_day) >= NORMAL_HOURS_PER_DAY
	eves = set(eves)
	months = []
	for month in range(1, 13):
		days = short = 0
		current = date(year, month, 1)
		while current.month == month:
			if current not in off_days:
				days += 1
				if shorten and current in eves:
					short += 1
			current += timedelta(days=1)
		months.append(
			{
				"month": month,
				"working_days": days,
				"pre_holiday_days": short,
				"hours": round(days * float(hours_per_day) - short, 2),
			}
		)
	return months
