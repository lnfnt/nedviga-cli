"""PII sanitisers for raw dumps and generated reports.

v0.4.6 (the task brief F-13): fail-closed маскирование телефонов по умолчанию
во всех форматах вывода CLI (search stdout/--json, HTML-экспорт).
Открытие контактов — только явным флагом ``--with-contacts`` с маркером
``contacts_open`` в envelope/metadata.
"""

from __future__ import annotations

import re

# Единый плейсхолдер маски (ТЗ §2.1).
PHONE_MASK = "+7 *** ***-**-**"

# Российские мобильные/городские: +7 / 7 / 8 + 10 цифр (разделители опциональны).
_PHONE_PREFIXED_RE = re.compile(
    r"(?:\+7|7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
)
# «Голый» группированный номер без кода страны: 495 123-45-67 / 916 123 45 67.
# Требует разделители внутри — слитные длинные числа (id, цены) не трогает.
_PHONE_BARE_GROUPED_RE = re.compile(
    r"(?<![\dA-Za-z])\d{3}[\s\-]\d{3}[\s\-]\d{2}[\s\-]\d{2}(?!\d)"
)


def mask_phones(text: str) -> str:
    """Replace phone numbers with a masked placeholder."""
    masked = _PHONE_PREFIXED_RE.sub(PHONE_MASK, text)
    masked = _PHONE_BARE_GROUPED_RE.sub(PHONE_MASK, masked)
    return masked


def mask_phone_number(value: object) -> str:
    """Mask a single phone slot.

    Fail-closed: формат не распознан — значение полностью заменяется маской
    (в слоте телефонов неизвестную строку считаем номером).
    """
    raw = str(value if value is not None else "")
    if not raw.strip():
        return PHONE_MASK
    masked = mask_phones(raw)
    if masked != raw:
        return masked
    return PHONE_MASK


def mask_phones_in_obj(obj: object) -> object:
    """Recursively mask phone numbers inside strings in JSON-like structures."""
    if isinstance(obj, str):
        return mask_phones(obj)
    if isinstance(obj, list):
        return [mask_phones_in_obj(item) for item in obj]
    if isinstance(obj, dict):
        return {k: mask_phones_in_obj(v) for k, v in obj.items()}
    return obj


def sanitize_contacts(obj: object) -> object:
    """mask_phones_in_obj + fail-closed обработка телефонных слотов.

    Ключи ``phones`` (seller.phones и любые списки телефонов) маскируются
    поминутно через :func:`mask_phone_number`: нераспознанный формат
    заменяется полной маской, а не остаётся сырым.
    """
    if isinstance(obj, dict):
        out: dict = {}
        for key, value in obj.items():
            if key == "phones" and isinstance(value, list):
                out[key] = [
                    mask_phone_number(item)
                    for item in value
                    if str(item if item is not None else "").strip()
                ]
            elif key in {"phone", "tel", "contact_phone"} and isinstance(value, str):
                out[key] = mask_phone_number(value)
            else:
                out[key] = sanitize_contacts(value)
        return out
    if isinstance(obj, list):
        return [sanitize_contacts(item) for item in obj]
    if isinstance(obj, str):
        return mask_phones(obj)
    return obj
