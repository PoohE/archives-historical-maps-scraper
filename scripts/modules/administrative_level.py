"""Conservative administrative-level inference with an auditable archive-territory fallback."""
import re

RULES = {
    'Губерния': r'губерни(?:я|и|ю|ей|ею|ям|ями|ях)|губ\.',
    'Уезд': r'уезд(?:а|у|ом|е|ы|ов|ам|ами|ах)?|уез\.',
    'Волость': r'волост(?:ь|и|ью|ей|ям|ями|ях)|вол\.',
    'Нас. пункт': r'город(?:а|у|ом|е|ов|ам|ами|ах)?|гор\.|сел(?:о|а|у|ом|е|ам|ами|ах)|деревн(?:я|и|ю|ей|е|ям|ями|ях)|местечк(?:о|а|у|ом|е|ам|ами|ах)',
    'Дача': r'дач(?:а|и|у|ей|е|ам|ами|ах)',
}
UNSUPPORTED = r'област(?:ь|и|ью|ей|ям|ами|ях)|район(?:а|у|ом|е|ы|ов|ам|ами|ах)?|округ(?:а|у|ом|е|и|ов|ам|ами|ах)?|наместничеств(?:о|а|у|ом|е)'


def _normalize(text):
    normalized = text.lower().replace('ё', 'е').replace('ѣ', 'е').replace('і', 'и')
    return re.sub(r'ъ\b', '', normalized)


def _matches(text):
    hits = []
    for level, pattern in RULES.items():
        for match in re.finditer(r'(?<!\w)(?:' + pattern + r')(?!\w)', text):
            hits.append({'level': level, 'matched_text': match[0], 'span': list(match.span())})
    return hits


def apply_level(row, options, issues, *, territory=''):
    """Title evidence wins; a saved archive query territory is a last resort."""
    title = row.get('Название источника', '')
    normalized = _normalize(title)
    hits = _matches(normalized)
    unsupported = [m[0] for m in re.finditer(r'(?<!\w)(?:' + UNSUPPORTED + r')(?!\w)', normalized)]
    levels = {hit['level'] for hit in hits}
    audit = {
        'rule_version': '2026-09-23.2',
        'locator': 'record.title',
        'title': title,
        'normalized_title': normalized,
        'matches': hits,
        'unsupported_terms': unsupported,
        'territory': territory,
        'territory_matches': [],
        'status': 'no_evidence',
    }
    reason = None
    if unsupported:
        reason = 'administrative_level_unsupported'
    elif len(levels) > 1:
        reason = 'administrative_level_ambiguous'
    elif len(levels) == 1:
        level = next(iter(levels))
        if level not in options:
            reason = 'administrative_level_schema_mismatch'
        elif row.get('Административный уровень') not in ('', None, level):
            reason = 'administrative_level_conflict'
        else:
            row['Административный уровень'] = level
            audit.update(status='candidate', value=level)

    # This fallback uses the exact saved query territory, not a place-name stem.
    # It is limited by notion_export to records from archival adapters.
    if territory and (not levels or reason in {"administrative_level_unsupported", "administrative_level_ambiguous"}):
        audit["title_reason"] = reason
        reason = None
        territory_hits = _matches(_normalize(territory))
        territory_levels = {hit['level'] for hit in territory_hits}
        audit['territory_matches'] = territory_hits
        if len(territory_levels) == 1:
            level = next(iter(territory_levels))
            if level not in options:
                reason = 'administrative_level_schema_mismatch'
            elif row.get('Административный уровень') not in ('', None, level):
                reason = 'administrative_level_conflict'
            else:
                row['Административный уровень'] = level
                audit.update(
                    locator='entry.territory',
                    status='candidate',
                    value=level,
                    basis='explicit_query_territory',
                )
        elif len(territory_levels) > 1:
            reason = 'administrative_level_ambiguous'
    if reason:
        issues.append(reason)
        audit.update(
            status='review_required',
            reason=reason,
            question='Какой административный уровень описывает основной объект в названии «' + title + '»?',
        )
    return audit
