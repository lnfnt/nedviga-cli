# Changelog

Формат Keep a Changelog; версии — semver публичного пакета.

## Статус файла и практика ведения (07.11)

**Историческая часть — архив с обрыва.** Секции ниже «Unreleased» —
архив; запись 0.1.1 последняя, версии 0.2.x–0.5.x в файл не заносились.
Факты этих версий несут коммит-сообщения (feat(vX.Y.Z)) и FIXLOG'и в
docs/. Обрыв задним числом не восстанавливается.

**Практика с 07.11:** текущие изменения копятся в «Unreleased» — фактами
волн починки (что, почему, счётчики тестов, хэши коммитов). При бампе
версии секция переименовывается в номер версии одним коммитом с бампом.

## Unreleased (fixlog 2026-11-07)

- **Браузерные live-адаптеры читают стандартные proxy-переменные.**
  `browser_native.py` на старте camoufox-адаптера маппит
  `HTTPS_PROXY`/`https_proxy`/`HTTP_PROXY`/`http_proxy` в прокси браузера,
  когда явный `NEDVIGA_EGRESS_PROXY` (или `NEDVIGA_EGRESS_PROXY`/
  `SUD_EGRESS_PROXY`) не задан. Резолв — единая точка политики
  `nedviga.net_guard._egress_proxy`: явный прокси продукта приоритетен
  над стандартными переменными. Прямого режима у браузерного адаптера нет —
  killswitch `NEDVIGA_ALLOW_DIRECT=0` уважается тем, что без прокси
  поднимается прежний честный fail-closed `FetchError("source_disabled:
  egress proxy required")`. Тесты: TestEgressProxyMapping (6 тестов,
  tests/test_browser_native.py).
- **Live-сеть — штатный функционал: default-deny гейт egress развёрнут в
  default-enabled (решение проекта 07.11).** Точка политики —
  `nedviga/net_guard.py` (shim Д6): прямой выход разрешён по умолчанию,
  `NEDVIGA_ALLOW_DIRECT=0/false/no/off` возвращает fail-closed; при явном
  `NEDVIGA_EGRESS_PROXY` (или `NEDVIGA_EGRESS_PROXY`) весь HTTP-трафик идёт через
  CONNECT-туннель; стандартные `HTTPS_PROXY`/`HTTP_PROXY` используются как
  egress, когда явный прокси не задан. SSRF-гейт, DNS-pinning, breaker и
  spotlighting не тронуты. Браузерные live-адаптеры (camoufox) по-прежнему
  требуют `NEDVIGA_EGRESS_PROXY`. README приведён к факту.
- **Факт версии: 0.1.3** (pyproject.toml, `__init__.py`, MANIFEST.json
  согласованы; метка «v0.1.3» в коммите a8394ce — ошибочная, бамп не делался).
- Починен time-bomb `test_v13b_med2` (абсолютная дата-фикстура выпала из
  окна digest days=7). Полный сьют: 621 passed.

## 0.1.1

- Установка из PyPI: `pip install nedviga-cli`.

## 0.1.0
- Первый публичный релиз: офлайн-анализ объявлений (цены/площади/доходность) по синтетическим и загруженным пользователем данным.
- Парсеры источников с fail-closed конвертами, нормализация карточек, стабильные ID (hash/synthetic), детект исчезновений.
- Egress-guard: fail-closed политика исходящего трафика, DNS pinning, приватные сети запрещены; прокси-выходы только через env, без захардкоженных адресов.
- MCP tools; модули batch/wizard/deck/rush; §13-интерфейс `license` и проверка подписи релиза.

## Лицензия
AGPL-3.0-only —см. LICENSE.
