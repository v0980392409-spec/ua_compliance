app_name = "ua_compliance"
app_title = "UA Compliance"
app_publisher = "Riverside"
app_description = "Український шар законодавства: офіційний курс НБУ, законодавчі параметри з датою дії, підписаний канал оновлень"
app_email = "v0980392409@gmail.com"
app_license = "GPL-3.0-or-later"
required_apps = ["frappe"]

# Налаштування, які живуть у базі, але мають приїжджати із застосунком.
fixtures = [
	{"dt": "Custom Field", "filters": [["fieldname", "like", "ua\\_%"]]},
	{"dt": "Role", "filters": [["name", "in", ["Відповідальний за законодавство"]]]},
]

after_install = "ua_compliance.setup.install.after_install"
after_migrate = "ua_compliance.setup.install.after_migrate"

# Два запуски на добу: ранковий добирає курс на сьогодні, вечірній забирає курс,
# встановлений джерелом на завтра (воно встановлює його після 15:30).
scheduler_events = {
	"cron": {
		# Такт курсу: самі часи запусків — у налаштуваннях, задання їх лише звіряє.
		"*/15 * * * *": ["ua_compliance.rates.job.scheduled_tick"],
		# Раз на добу — забір пакетів з каналу роздачі; до попередження, щоб воно бачило свіже.
		"0 8 * * *": ["ua_compliance.packages.jobs.poll_packages"],
		# Раз на добу — попередження про давність оновлень і прострочені пакети.
		"15 8 * * *": ["ua_compliance.packages.jobs.warn_about_updates"],
		# Щороку 1 грудня — календар наступного року (лише майбутні дати).
		"0 6 1 12 *": ["ua_compliance.calendar.build.build_next_year"],
	}
}
