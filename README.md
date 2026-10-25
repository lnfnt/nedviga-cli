# nedviga-cli

![license](https://img.shields.io/badge/license-AGPL--3.0-orange) ![python](https://img.shields.io/badge/python-3.11%2B-blue) ![release](https://img.shields.io/badge/release-v0.1.0-informational) ![MCP](https://img.shields.io/badge/MCP-ready-brightgreen) ![artifacts](https://img.shields.io/badge/artifacts-GPG--signed-green)

<p align="center"><img src="assets/poster.jpg" width="820" alt="nedviga-cli poster"></p>

CLI и Python SDK для подбора и анализа жилой недвижимости Москвы. Рабочий цикл: поиск,
карточка решения, сравнение, торг, проверка новостроек/застройщиков, инфраструктура,
мониторинг изменений, отчёт. Для ИИ-агентов: MCP-сервер, JSON-конверты, роли, аудит.

**Русский** · [<img src="assets/flags/gb.svg" height="16" align="top" alt="EN"> English](README.en.md)

## Установка

```bash
pip install git+https://github.com/lnfnt/nedviga-cli.git
nedviga-cli wizard doctor
```

На PyPI пакет не опубликован. Checkout: `python3.11 -m venv .venv && source .venv/bin/activate
&& pip install -e ".[cli,dev]"`. Python >= 3.11.
Один раз подготовить браузерный рантайм для live-адаптеров:

```bash
XDG_CACHE_HOME="$HOME/.cache/nedviga-py" python3 -m camoufox fetch
```

## Возможности

- **Источники:** ЦИАН, Авито, Домклик (только через ваш egress `NEDVIGA_EGRESS_PROXY`), открытые
  данные Москвы (досья домов, ЖКХ, реестр новостроек, застройщики по ИНН с банками и судами,
  шум-мониторинг). ЕГРН не используется — модуль приёма и проверки выписки от собственника.
- **Аналитика решения:** семейная карта объекта, сравнительная матрица, медианы торга по
  комплексу (`insufficient_sample` при малой выборке), антиприманочные флаги, risk-скоринг,
  юридические триаж-маркеры (11 флагов).
- **Цикл сделки:** пайплайн статусов (shortlist→offer→…), watch цены/снятия/перевыставления,
  дайджесты, автоподбор по профилю, цепочки альтернатив, скоринг соответствия.
- **Артефакты:** PDF/HTML-каталог, PPTX-презентации (`deck`), план показов, прозвон-листы,
  чек-листы передачи юристу.
- **Инфраструктура:** POI в пешей доступности, загруженность дорог и почасовой прогноз
  (web-оценка, помечена как таковая), замеры шума с датами и дистанциями.
- **Безопасность:** fail-closed сетевой страж, spotlighting внешнего текста
  `<external_untrusted_data>`, роли и per-record аудит, ПДн-минимизация (контакты — только по
  явному флагу с указанной целью), идемпотентный purge.

## Быстрый старт

```bash
nedviga-cli wizard init --profile family --out ./kit
nedviga-cli search --source cian --rooms 2 --price-max 20000000 \
  --geo-districts "ЮАО,ЮЗАО" --out cards.json
nedviga-cli compare --file cards.json --format telegram
nedviga-cli card cards.json --format all --out ./out
nedviga-cli watch add --file cards.json
nedviga-cli watch check --offline fresh.json
nedviga-cli noise sync && nedviga-cli noise --lat 55.72 --lon 37.61
nedviga-cli dossier match --address "улица Эталонная, дом 4"
nedviga-cli source
```

Примеры по каждой команде — в `--help`.

### Конфигурация

| Переменная | Назначение |
|---|---|
| `NEDVIGA_EGRESS_PROXY` | HTTP-выход для браузерных адаптеров; без него живые источники = `source_disabled` |
| `NEDVIGA_MOS_TOKEN_FILE` | файл ключа api.mos.ru (не значение в env) |
| `NEDVIGA_STATE_DIR` | каталог состояния |
| `NEDVIGA_FEED_URL` | опциональный сервер манифестов свежести адаптеров |

## Контракт вывода

Один JSON-конверт в stdout (`ok/status/reason/source/data/metadata`), логи в stderr.

| Код | Значение |
|---|---|
| 0 | данные получены, контракт валиден |
| 1 | критично для окружения (нет браузерного рантайма/кэша) |
| 2 | деградация источника (WAF, капча, rate-limit) |
| 3 | ошибка источника/парсера (изменение DOM, `source_disabled`, `source_blocked`) |
| 4 | невалидные аргументы CLI |

## Ограничения

- Данные московские; для других городов адаптеров нет.
- Прогноза цен нет: медианы и watch-дельты — факты с датой.
- Прогноз транспорта — web-оценка, помечается как негарантийная.
- Контакты ПДн извлекаются только по явному флагу.

## Python API

```python
from nedviga.sources_avito import parse_livetext
from nedviga.deck import deck_from_cards
cards = parse_livetext(open("avito_text.txt").read())
deck_from_cards(cards, "подборка.pptx", title="ЮАО, двушки")
```

## Лицензия и проверка релиза

AGPL-3.0-only; сетевой сервис на этом коде обязан предоставить исходники (§13,
`nedviga-cli source`). Артефакты: `sha256sum -c SHA256SUMS`, `gpg --verify *.asc` (ключ в релизе).

Автор и правообладатель: [lnfnt](mailto:lnfnt@proton.me).
