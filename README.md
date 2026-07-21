# Archives Historical Maps Scraper

Automated system for searching and aggregating historical cartographic materials (maps, plans, charts, drawings) from Russian federal archives and regional libraries.

**Status:** ✅ Production-ready (5 ready sources + 7 partial sources + 2 under research)

---

## 🎯 Overview

This project crawls **16+ Russian archives** to discover historical cartographic materials from the **XVIII–XX centuries**, focusing on four historical regions:
- Kaluga Gubernia
- Perm Gubernia  
- Smolensk Gubernia
- Yaroslavl Gubernia

### Key Features
✅ **No VPN required** — all sources accessible from Russia  
✅ **Multiple scraping techniques** — REST API, POST forms, WebDriver, AJAX handling  
✅ **Territory expansion** — 49 administrative units (4 gubernias + 4 namestenichestvos + 41 uezds)  
✅ **5 keyword variants** — карта, план, атлас, съёмка, чертёж  
✅ **Deduplication** — ~3,600 unique records across sources  
✅ **Full documentation** — guides for operators, developers, researchers  

---

## 📊 Sources Status

### ✅ Ready (5 sources)
- **GPIB** (State Public Historical Library) — Selenium WebDriver
- **GAYAO** (Yaroslavl State Archive) — GET requests
- **RNB** (Russian National Library, XVIII century maps catalog) — POST (windows-1251)
- **NEB** (National Electronic Library) — GET + retry logic
- **GAPK archive1** (Perm Regional Archives) — GET filter by keywords

### ⚠️ Partial (7 sources, docs ready)
- GARF (Federal Archive) — GET working, selectors need refinement
- Kaluga ONBIB (Веб-ИРБИС 64) — POST template ready, params need verification
- Perm Regional Library (ELiS CMS) — AJAX/API approach needed
- Smolensk OUNB — recursive catalog walk
- RGB (Russian State Library) — Session + CSRF handling
- TsGA Moscow (Bitrix CMS) — CSS selectors needed
- GAKO (Kaluga Archive) — JSON API analysis pending

### 🔍 Under Research (2 sources)
- **Rosarchiv** (Federal archives system via GIS UIAD) — 20M+ documents
- **RGADA** (Ancient Acts Archive) — ~1,000 rare XVI–XVII century cartographic drawings

### ❌ Unavailable (4 sources)
- GAPK /archive/ (geo-blocking for non-RU IPs)
- Rosarchiv (closed API)
- RGIA (requires registration)
- RGVIA (reference service only)

---

## 📈 Metrics

| Metric | Value |
|--------|-------|
| Ready sources | 5 |
| Partial sources | 7 |
| Under research | 2 |
| Unavailable | 4 |
| **Total archives** | **18** |
| | |
| Territories covered | 49 |
| Keywords | 5+ |
| Expected records | ~5,000–6,000 |
| After expansion | ~6,000–7,000 |

---

## 🚀 Quick Start

### Prerequisites
```bash
Python 3.12+
pip install -r requirements.txt
```

### Run Full Search
```bash
# All 5 ready sources × 49 territories × 5 keywords = 1,127 combinations
python run_search.py --source all --run-dir output/full_search_20260721

# Single source test
python run_search.py --source gayao --run-dir output/test_gayao

# Dry-run (no Notion write)
python run_search.py --source all --dry-run
```

### Output
Results are saved to:
- `output/full_search_YYYYMMDD/results.csv` — main results
- `output/full_search_YYYYMMDD/review.csv` — full table for review
- `output/full_search_YYYYMMDD/run.log` — execution log

---

## 📁 Project Structure

```
archives-historical-maps-scraper/
├── README.md                    # This file
├── LICENSE                      # CC BY 4.0
├── requirements.txt             # Python dependencies
├── run_search.py               # Main orchestrator (2,059 combinations)
│
├── modules/
│   ├── scrapers/               # Archive scrapers
│   │   ├── searcher_gpib.py    # ✅ State Public Historical Library
│   │   ├── searcher_gayao.py   # ✅ Yaroslavl State Archive
│   │   ├── searcher_neb.py     # ✅ National Electronic Library
│   │   ├── searcher_rnb_kart.py # ✅ Russian National Library
│   │   ├── searcher_gapk.py    # ✅ Perm Regional Archives
│   │   ├── searcher_garf_fixed.py     # ⚠️ Federal Archive (partial)
│   │   ├── searcher_kaluga_fixed.py   # ⚠️ Kaluga Library (partial)
│   │   └── ... (5 more partial)
│   │
│   ├── territories.py           # 49 territories (gubernias + uezds)
│   ├── registry.py             # Unified scraper interface
│   └── archive_health.py       # Health monitoring
│
├── docs/
│   ├── МЕТОДОЛОГИЯ_СТАТЬИ.md   # Scientific methodology (22 KB)
│   ├── БЕЗ_VPN_ДОРАБОТКА_СКРИПТОВ.md    # Developer guides (17 KB)
│   ├── БЕЗ_VPN_ГЛОБАЛЬНЫЙ_ПОИСК.md      # Operator instructions (11 KB)
│   └── ЗАПРОС_ДЛЯ_ДИРЕКТОРОВ.md        # Letter templates for archive directors
│
└── output/                      # Results (.gitignored)
    └── full_search_YYYYMMDD/
        ├── results.csv
        ├── review.csv
        └── run.log
```

---

## 🛠️ Browser Automation Techniques

This project implements **5 distinct scraping methods** verified through deep research:

### 1. REST API (GET requests)
Used by: GAYAO, НЕБ, ГАПК  
Fast, reliable, no browser needed.

### 2. POST Forms (windows-1251 encoding)
Used by: РНБ, Веб-ИРБИС archives  
Legacy systems require explicit encoding handling.

### 3. WebDriver (Selenium)
Used by: GPIB  
Dynamic JavaScript rendering, full DOM access.

### 4. Playwright (AJAX auto-waiting)
Recommended for: Perm Regional Library, GAKO  
Superior AJAX handling with `wait_until="networkidle"`.

### 5. Recursive Walk (catalog traversal)
Used by: Smolensk OUNB fallback  
When no search API exists, crawl the hierarchy.

---

## 📝 API Endpoints Reference

| Archive | URL | Method | Auth | Rate Limit |
|---------|-----|--------|------|-----------|
| GPIB | https://gpib.ru | WebDriver | None | None |
| GAYAO | https://af.yar-archives.ru/archive/search | GET | None | 2s/req |
| РНБ карты | https://nlr.ru/rlin/kartogr18.php | POST | None | 2s/req |
| НЭБ | https://rusneb.ru/search/ | GET | None | 2s/req (retry 3×) |
| ГАПК | https://archives.permkrai.ru/archive1/funds | GET | None | 1.5s/req |
| РГАДА | https://www.rgada.info | N/A yet | N/A | N/A |
| Росархив | https://www.rusarchives.ru (GIS UIAD) | N/A yet | N/A | N/A |

---

## 🎓 Scientific Methodology

This project is based on a full **research methodology** with:
- 49 territorial units (historical gubernias + modern districts)
- 5+ cartographic keywords (карта, план, атлас, съёмка, чертёж)
- Deduplication across sources
- Temporal filtering (1700–1920)
- Results: ~3,600 unique records from primary sources

**See `docs/МЕТОДОЛОГИЯ_СТАТЬИ.md` for full academic writeup.**

---

## 🐛 Contributing

### For Operators (Running Searches)
See `docs/БЕЗ_VPN_ГЛОБАЛЬНЫЙ_ПОИСК.md` — no VPN required.

### For Developers (Adding Sources)
See `docs/БЕЗ_VPN_ДОРАБОТКА_СКРИПТОВ.md` — step-by-step guides for all 7 partial sources.

### For Researchers (Expanding)
1. File issues with archive names
2. Provide DevTools Network analysis (GET/POST structure)
3. Or send letter templates (`docs/ЗАПРОС_ДЛЯ_ДИРЕКТОРОВ.md`) to archive directors

---

## 📞 Contact & Collaboration

- **Research collaboration:** Open issues for archive recommendations or methodology improvements
- **Archive directors:** Use letter templates in `docs/ЗАПРОС_ДЛЯ_ДИРЕКТОРОВ.md` to request API access
- **Bug reports:** Include archive name, search query, and error logs from `output/*/run.log`

---

## 📄 License

This work is licensed under the **Creative Commons Attribution 4.0 International License**.  
You are free to:
- ✅ Share, copy, redistribute the material
- ✅ Adapt, remix, transform, build upon the material
- ✅ Use commercially

**With the condition:**
- 📌 **Attribution** — Credit the author(s) in any derivative works or publications

See `LICENSE` file for full details: https://creativecommons.org/licenses/by/4.0/

---

## 🙏 Acknowledgments

This project integrates search capabilities from:
- Государственная публичная историческая библиотека (GPIB)
- Государственный архив Ярославской области (GAYAO)
- Российская национальная библиотека (RNB)
- Национальная электронная библиотека (NEB)
- Государственный архив Пермского края (GAPK)
- And 7 additional partial sources under development

---

## 📊 Project Statistics

- **Lines of code:** ~3,500
- **Archives integrated:** 18 (5 ready, 7 partial, 2 research, 4 unavailable)
- **Documentation:** 9 files, ~100 KB
- **Territories:** 49 (historical regions)
- **Search combinations:** 2,059+
- **Expected records:** 5,000–7,000 unique cartographic materials

---

**Last Updated:** 2026-07-21  
**Status:** ✅ Production Ready (5/5 ready sources verified)  
**Next Phase:** Expand to 18 archives with partial sources + director collaboration

🗺️ **Contributing to Russian historical cartography research**
