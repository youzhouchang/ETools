"""Lightweight i18n for ETools UI (zh-CN default, en optional)."""

from __future__ import annotations

from etools.config import get_config, save_config
from etools.i18n_catalog import CATALOGS

LANG_ZH = "zh"
LANG_EN = "en"


def _merge_catalogs() -> dict[str, dict[str, str]]:
    zh: dict[str, str] = {}
    en: dict[str, str] = {}
    for catalog in CATALOGS:
        zh.update(catalog.ZH)
        en.update(catalog.EN)
    return {LANG_ZH: zh, LANG_EN: en}


_STRINGS: dict[str, dict[str, str]] = _merge_catalogs()


def current_language() -> str:
    lang = (get_config().language or LANG_ZH).lower()
    return LANG_EN if lang.startswith("en") else LANG_ZH


def set_language(lang: str) -> None:
    lang = LANG_EN if str(lang).lower().startswith("en") else LANG_ZH
    cfg = get_config()
    if cfg.language != lang:
        cfg.language = lang
        save_config()


def tr(key: str, **kwargs) -> str:
    lang = current_language()
    table = _STRINGS.get(lang, _STRINGS[LANG_ZH])
    text = table.get(key) or _STRINGS[LANG_ZH].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
