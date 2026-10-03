"""Ключі, якими підписуються пакети даних.

Відкриті ключі й поріг живуть **у коді застосунку** і змінюються лише релізом коду:
це аналог ролі root у The Update Framework. У самому пакеті ключів немає — інакше
той, хто підмінив пакет, підмінив би й ключі.

Формат — відкритий ключ minisign (рядок base64 без коментаря).
"""

# Випущені 03.10.2026; секретні частини — на трьох окремих носіях мейнтейнера.
# Ідентифікатор ключа в коментарі — як його друкує minisign.
TRUSTED_KEYS: list[str] = [
	"RWRtZNh1PRywk/8JH0cpKZcCqmEmgqL4HXex3fyQeUGkWGHVKbg+HXit",  # 1: 93B01C3D75D8646D
	"RWQ6q2gR8wY07+5GjC9pVuAYLeSCYGTq2s/vhSredqp9Kx+Hxyreirs7",  # 2: EF3406F31168AB3A
	"RWQhF6Nto+340OTY2yWxxhZjXkuAvGxI3yQ+wHlcYg+GGRBnimiFHuR5",  # 3: D0F8EDA36DA31721
]

# Скільки різних ключів мають підписати маніфест.
THRESHOLD = 2


def trusted_keys():
	return list(TRUSTED_KEYS)
