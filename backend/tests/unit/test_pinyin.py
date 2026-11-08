"""拼音生成与搜索条件的纯函数测试（不依赖数据库）。"""
from __future__ import annotations

import pytest

from app.services.search import search_filter, to_pinyin


@pytest.mark.parametrize(
    "name,full,initials",
    [
        ("鸡胸肉", "jixiongrou", "jxr"),
        ("牛奶", "niunai", "nn"),
        ("西兰花", "xilanhua", "xlh"),
        ("土豆", "tudou", "td"),
        ("可乐", "kele", "kl"),
    ],
)
def test_to_pinyin(name, full, initials):
    assert to_pinyin(name) == (full, initials)


@pytest.mark.parametrize("name", ["", "   ", None])
def test_to_pinyin_handles_empty(name):
    assert to_pinyin(name or "") == ("", "")


def test_to_pinyin_strips_punctuation_and_space():
    full, initials = to_pinyin("鸡 胸-肉")
    assert full == "jixiongrou"
    assert initials == "jxr"


def test_to_pinyin_keeps_digits_and_latin():
    full, initials = to_pinyin("A2牛奶")
    assert "a2" in full
    assert "nn" in initials


def test_search_filter_covers_three_paths():
    """搜索必须同时匹配中文名、全拼、首字母 —— 三条 OR 缺一不可。"""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy import column

    expr = search_filter(column("name"), column("name_pinyin"), column("name_initials"), "jxr")
    sql = str(expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "name ILIKE" in sql
    assert "name_pinyin ILIKE" in sql
    assert "name_initials ILIKE" in sql
    assert " OR " in sql.upper()
