# -*- coding: utf-8 -*-
"""Разбор заголовков дел УИАД: масштаб, размер листа, техника, годы.

Вынесено отдельным модулем БЕЗ побочных эффектов: и сборщик, и переразметка импортируют
отсюда. Раньше переразметка импортировала сборщик, тот при импорте переопределял
`sys.stdout`, и печать в вызывающем скрипте падала с «I/O operation on closed file».

Масштабы в этих фондах записаны тремя способами:
  «М-б 1:8400»                     — числовой;
  «Масштаб: в 1 дюйме 5 верст»     — основной в ф. 386 (обратный порядок!);
  «5 верст в дюйме», «100 саж.»    — старорусский прямой порядок.
Пересчёт: 1 верста в дюйме = 1:42 000, 1 сажень в дюйме = 1:84.
"""
import re

# числовой масштаб: «М-б 1:8400», «М. 1:84 000»
SCALE_NUM = re.compile(r"[МM][-\s.]*б?[\s.:]*(?:1\s*[:\s]\s*)?(\d[\d\s]{2,})", re.I)
# «5 верст в дюйме» и «в 1 дюйме 5 верст» — два порядка записи
SCALE_V = re.compile(r"(\d+(?:[.,]\d+)?)\s*вер[а-я]*\s*в\s*(?:1\s*)?(?:дюйм|д\.)", re.I)
SCALE_V_INV = re.compile(r"в\s*(?:1\s*)?дюйм[а-я]*\s*(\d+(?:[.,]\d+)?)\s*вер", re.I)
SCALE_SAZH = re.compile(r"(\d+)\s*саж", re.I)

SIZE = re.compile(r"(\d+[,.]?\d*)\s*[хx×]\s*(\d+[,.]?\d*)\s*см", re.I)
YEAR = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b")
TECH = re.compile(
    r"рукоп[а-я.]*|печ[а-я.]*|грав[а-я.]*|литогр[а-я.]*|в красках|цв\.|акварел[ья]|"
    r"тушь|ватман|фотокоп", re.I)
MAP_SUBJ = re.compile(
    r"карт|план|атлас|чертеж|чертёж|съемк|съёмк|топограф|глазомерн|рекогносцир|профил", re.I)

VERSTA_IN_INCH = 42000   # 1 верста в дюйме
SAZHEN_IN_INCH = 84      # 1 сажень в дюйме


def parse_scale(text: str) -> tuple[str, str]:
    """(как записано в заголовке, знаменатель) или ('', '')."""
    for rx in (SCALE_V, SCALE_V_INV):
        m = rx.search(text)
        if m:
            return m.group(0), str(int(float(m.group(1).replace(",", ".")) * VERSTA_IN_INCH))
    m = SCALE_SAZH.search(text)
    if m:
        return m.group(0), str(int(m.group(1)) * SAZHEN_IN_INCH)
    m = SCALE_NUM.search(text)
    if m:
        d = re.sub(r"\s", "", m.group(1))
        if d.isdigit() and 50 <= int(d) <= 10_000_000:
            return m.group(0), d
    return "", ""


def parse_size(text: str) -> str:
    m = SIZE.search(text)
    return f"{m.group(1)}x{m.group(2)}" if m else ""


def parse_tech(text: str) -> str:
    return "; ".join(sorted({m.group(0).lower() for m in TECH.finditer(text)}))


def parse_years(text: str) -> tuple[str, str]:
    ys = YEAR.findall(text)
    return (ys[0], ys[-1]) if ys else ("", "")


def is_cartographic(text: str) -> bool:
    return bool(MAP_SUBJ.search(text))


# Разбор строки элемента описи: «/ Фонд N. … / Опись M . … / Дело K . Заголовок».
# Номер дела бывает с томом — «Дело 3 т.1», «Дело 1742 т.2» (опись 16 ф. 846, Каталог ВУА):
# пробел внутри номера ломал прежнюю регулярку, 8 727 записей теряли и номер, и заголовок,
# а год брался из названия описи «Каталог ВУА (1803-1892гг.)» — то есть датировка была ложной.
CASE_RX = re.compile(r"Дело\s+(\d+[\w\-/]*(?:\s*т\.\s*\d+)?)\s*\.\s*(.*)$", re.S)


def split_case(text: str) -> tuple[str, str]:
    """(номер дела, заголовок) из строки элемента списка описи."""
    m = CASE_RX.search(text)
    if not m:
        return "", text.strip()
    return re.sub(r"\s+", " ", m.group(1)).strip(), m.group(2).strip()
