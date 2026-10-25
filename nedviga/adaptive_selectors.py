"""
Zero-dependency Адаптивный экстрактор селекторов (Фаза 3, задача P3-3).
Использует нативный html.parser из стандартной библиотеки Python (без сторонних зависимостей).
Устойчив к изменениям CSS-классов и динамической обфускации.
"""

from html.parser import HTMLParser
import re
from typing import Optional, List, Dict, Any

PRICE_CLEAN_RE = re.compile(r'[^\d]')
# P3-3 fix (2026-10-20): цена = ПОСЛЕДНЯЯ денежная группа с якорем ₽/руб,
# а не слепая склейка всех цифр текста («2-к … 8 700 000 ₽» раньше давало 28700000).
_MONEY_GROUP_RE = re.compile(r'(?<![\d.])(\d{1,3}(?:[ \u00a0]\d{3})+|\d{5,12})(?=\s*(?:₽|руб))', re.IGNORECASE)

class AdaptiveHTMLScanner(HTMLParser):
    def __init__(self):
        super().__init__()
        self.prices: List[float] = []
        self.titles: List[str] = []
        self._current_tag = ""
        self._current_attrs: Dict[str, str] = {}
        self._in_h1 = False
        self._in_price_tag = False

    def handle_starttag(self, tag: str, attrs: List[tuple]):
        self._current_tag = tag
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        self._current_attrs = attr_dict

        if tag == "h1":
            self._in_h1 = True

        # Проверка itemprop=price
        if attr_dict.get("itemprop") == "price":
            content = attr_dict.get("content")
            if content:
                clean = PRICE_CLEAN_RE.sub("", content)
                if clean:
                    self.prices.append(float(clean))
            self._in_price_tag = True

        # Проверка data-name / data-marker на упоминание price
        for k, v in attr_dict.items():
            if "price" in k or "price" in v.lower():
                self._in_price_tag = True

    def handle_endtag(self, tag: str):
        if tag == "h1":
            self._in_h1 = False
        self._in_price_tag = False

    def handle_data(self, data: str):
        clean_text = data.strip()
        if not clean_text:
            return

        if self._in_h1:
            self.titles.append(clean_text)

        if self._in_price_tag or "₽" in clean_text:
            if "/м²" not in clean_text and "/мес" not in clean_text:
                matches = _MONEY_GROUP_RE.findall(clean_text)
                if matches:
                    self.prices.append(float(matches[-1].replace(" ", "").replace("\u00a0", "")))
                elif self._in_price_tag:
                    # fallback для старых маркеров без якоря валюты (itemprop-текст)
                    clean_num = PRICE_CLEAN_RE.sub("", clean_text)
                    if clean_num and len(clean_num) >= 5:
                        self.prices.append(float(clean_num))

def extract_price_adaptive(html_content: str) -> Optional[float]:
    scanner = AdaptiveHTMLScanner()
    scanner.feed(html_content)
    if scanner.prices:
        return scanner.prices[0]
    return None

def extract_title_adaptive(html_content: str) -> Optional[str]:
    scanner = AdaptiveHTMLScanner()
    scanner.feed(html_content)
    if scanner.titles:
        return scanner.titles[0]
    return None

if __name__ == "__main__":
    html_v1 = "<div class='dynamic_hash_98712'><span itemprop='price' content='12500000'>12.5 млн ₽</span></div>"
    html_v2 = "<div data-name='PriceInfo'><span class='obfuscated_123'>14 800 000 ₽</span></div>"
    html_v3 = "<div><h1>2-комн. квартира, 64 м²</h1><p class='random'>21 000 000 ₽</p></div>"

    p1 = extract_price_adaptive(html_v1)
    p2 = extract_price_adaptive(html_v2)
    p3 = extract_price_adaptive(html_v3)
    t3 = extract_title_adaptive(html_v3)

    assert p1 == 12500000.0, f"P1 failed: {p1}"
    assert p2 == 14800000.0, f"P2 failed: {p2}"
    assert p3 == 21000000.0, f"P3 failed: {p3}"
    assert t3 == "2-комн. квартира, 64 м²"
    print("[PASS] Native zero-dep adaptive parser successfully extracted all dynamic targets.")
