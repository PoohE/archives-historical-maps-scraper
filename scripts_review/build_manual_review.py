# -*- coding: utf-8 -*-
"""Сборка единого листа ручной проверки: Пермь v9.5 + НЭБ.

Зачем. Две очереди ждут решения человека, и обе разбросаны по разным наборам с разными
схемами полей. Скрипт сводит их в один CSV и одну HTML-страницу с кликабельными ссылками,
кнопками «берём / не берём / не знаю» и сохранением решений в localStorage — чтобы проверку
можно было делать порциями, не теряя ранее отмеченное.

Вход : output/permkrai_catalog_maps_20261003_v9_5_final_offline/records_full.jsonl
       output/neb_final_20261003/records.jsonl  (нужны только needs_human=true)
Выход: output/manual_review_20261004/ — review.csv, РУЧНАЯ_ПРОВЕРКА.html
"""
import csv
import html
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
PERM = BASE / "output" / "permkrai_catalog_maps_20261003_v9_5_final_offline" / "records_full.jsonl"
NEB = BASE / "output" / "neb_final_20261003" / "records.jsonl"
OUT = BASE / "output" / "manual_review_20261004"

COLS = ["n", "source", "territory", "title", "year", "scale", "question", "evidence", "url"]


def jload(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def question_perm(ev: dict) -> str:
    """Человеческая формулировка: что именно решить по этой записи."""
    s, t = str(ev.get("subject", "")), str(ev.get("territory", ""))
    if "atlas_link" in s:
        return "Связан с атласом — считать картографическим источником?"
    if "fieldwork_plan" in s:
        return "План полевых работ — брать как источник?"
    if "cartographic" in s and "unknown" in t:
        return "Карта есть, территория не определена — наша губерния?"
    if "cartographic" in s and "other_region" in t:
        return "Карта по чужой территории — точно не наша?"
    if "unconfirmed" in s and "target_region" in t:
        return "Наша территория, но предмет не подтверждён — это карта/план?"
    if "unconfirmed" in s and "other_region" in t:
        return "Чужая территория и предмет не подтверждён — отсекаем?"
    return "Проверить предмет и территорию"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    for r in jload(PERM):
        if str(r.get("needs_human")).lower() not in ("true", "1"):
            continue
        rec = r.get("record") or {}
        ev = r.get("evidence") or {}
        rows.append({
            "source": "Пермь (lib.permkrai)",
            "territory": r.get("territory") or "",
            "title": rec.get("title") or str(rec)[:200],
            "year": rec.get("year") or rec.get("date") or "",
            "scale": rec.get("scale") or "",
            "question": question_perm(ev),
            "evidence": f"предмет: {ev.get('subject','')}; территория: {ev.get('territory','')}; уровень: {ev.get('level','')}",
            "url": rec.get("url") or rec.get("link") or "",
        })

    for r in jload(NEB):
        if str(r.get("needs_human")).lower() not in ("true", "1"):
            continue
        reason = r.get("needs_human_reason") or ""
        q = ("Год источником не указан («б. г.») — датировать по содержанию?"
             if "no_year" in reason else
             "Год унаследован от конволюта по полю «Входит в» — подтвердить?"
             if "inherited" in reason else "Проверить")
        rows.append({
            "source": "НЭБ (rusneb)",
            "territory": r.get("territory") or "",
            "title": r.get("title") or "",
            "year": f"{r.get('year_from','')}–{r.get('year_to','')}".strip("–"),
            "scale": r.get("scale_raw") or "",
            "question": q,
            "evidence": reason,
            "url": r.get("url") or "",
        })

    rows.sort(key=lambda x: (x["source"], x["territory"], x["title"]))
    for i, r in enumerate(rows, 1):
        r["n"] = i

    with (OUT / "review.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # ---- HTML
    cards = []
    for r in rows:
        link = (f'<a href="{html.escape(r["url"])}" target="_blank">открыть карточку источника</a>'
                if r["url"] else '<span class="nolink">ссылки нет</span>')
        cards.append(f"""
<div class="card" data-n="{r['n']}" data-source="{html.escape(r['source'])}">
  <div class="head"><span class="num">{r['n']}</span>
    <span class="src">{html.escape(r['source'])}</span>
    <span class="terr">{html.escape(r['territory'] or '— территория не определена')}</span></div>
  <div class="title">{html.escape(r['title'])}</div>
  <div class="meta">{'год: ' + html.escape(r['year']) if r['year'] else 'год не указан'}
     {' · масштаб: ' + html.escape(r['scale']) if r['scale'] else ''}</div>
  <div class="q">{html.escape(r['question'])}</div>
  <div class="ev">{html.escape(r['evidence'])}</div>
  <div class="actions">{link}
    <button class="y" onclick="mark({r['n']},'yes')">берём</button>
    <button class="n" onclick="mark({r['n']},'no')">не берём</button>
    <button class="s" onclick="mark({r['n']},'skip')">не знаю</button>
    <span class="state" id="s{r['n']}"></span></div>
</div>""")

    page = """<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Ручная проверка: Пермь + НЭБ</title>
<style>
 body{font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f6f4;color:#1a1a1a}
 header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:12px 20px;z-index:5}
 h1{font-size:18px;margin:0 0 6px}
 .bar{font-size:13px;color:#555}
 .bar b{color:#111}
 .filters{margin-top:8px}
 .filters button{margin-right:6px;padding:4px 10px;border:1px solid #ccc;background:#fff;border-radius:4px;cursor:pointer}
 .filters button.on{background:#1a1a1a;color:#fff;border-color:#1a1a1a}
 main{padding:16px 20px;max-width:980px}
 .card{background:#fff;border:1px solid #e2e2e0;border-radius:6px;padding:12px 14px;margin-bottom:10px}
 .card.done{opacity:.45}
 .head{font-size:12px;color:#666;display:flex;gap:10px;align-items:center}
 .num{font-weight:700;color:#111}
 .src{background:#eef;padding:1px 6px;border-radius:3px}
 .terr{background:#efe;padding:1px 6px;border-radius:3px}
 .title{font-size:15px;font-weight:600;margin:6px 0 4px}
 .meta{font-size:13px;color:#555}
 .q{margin:8px 0 4px;font-size:14px;color:#8a4b00;font-weight:600}
 .ev{font-size:12px;color:#888;font-family:ui-monospace,Consolas,monospace}
 .actions{margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
 .actions a{font-size:13px}
 .nolink{font-size:13px;color:#999}
 button.y{background:#0a7d32;color:#fff;border:0;padding:5px 12px;border-radius:4px;cursor:pointer}
 button.n{background:#9b1c1c;color:#fff;border:0;padding:5px 12px;border-radius:4px;cursor:pointer}
 button.s{background:#555;color:#fff;border:0;padding:5px 12px;border-radius:4px;cursor:pointer}
 .state{font-size:13px;font-weight:600}
 @media(max-width:560px){.head{flex-wrap:wrap}}
</style>
<header>
 <h1>Ручная проверка источников</h1>
 <div class="bar">решено <b id="done">0</b> из <b id="total">0</b> · берём <b id="cy">0</b> ·
   не берём <b id="cn">0</b> · не знаю <b id="cs">0</b>
   <button onclick="dump()" style="margin-left:10px">показать итог для Claude</button></div>
 <div class="filters">
   <button class="on" onclick="flt(this,'all')">все</button>
   <button onclick="flt(this,'Пермь (lib.permkrai)')">Пермь</button>
   <button onclick="flt(this,'НЭБ (rusneb)')">НЭБ</button>
   <button onclick="flt(this,'undone')">только нерешённые</button>
 </div>
</header>
<main id="list">
__CARDS__
</main>
<script>
const K='manual_review_20261004';
let st=JSON.parse(localStorage.getItem(K)||'{}');
function mark(n,v){st[n]=v;localStorage.setItem(K,JSON.stringify(st));render();}
function render(){
 let y=0,no=0,s=0;
 document.querySelectorAll('.card').forEach(c=>{
   const n=c.dataset.n,v=st[n];
   const el=document.getElementById('s'+n);
   el.textContent = v==='yes'?'берём':v==='no'?'не берём':v==='skip'?'не знаю':'';
   el.style.color = v==='yes'?'#0a7d32':v==='no'?'#9b1c1c':'#555';
   c.classList.toggle('done', !!v);
   if(v==='yes')y++; else if(v==='no')no++; else if(v==='skip')s++;
 });
 document.getElementById('cy').textContent=y;
 document.getElementById('cn').textContent=no;
 document.getElementById('cs').textContent=s;
 document.getElementById('done').textContent=y+no+s;
 document.getElementById('total').textContent=document.querySelectorAll('.card').length;
}
function flt(btn,v){
 document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('on'));
 btn.classList.add('on');
 document.querySelectorAll('.card').forEach(c=>{
   const n=c.dataset.n;
   let show = v==='all' ? true : v==='undone' ? !st[n] : c.dataset.source===v;
   c.style.display = show?'':'none';
 });
}
function dump(){
 const lines=Object.entries(st).map(([n,v])=>n+'='+v).join('; ');
 prompt('Скопируйте строку и пришлите её Claude:', lines||'решений пока нет');
}
render();
</script>
</html>"""
    (OUT / "РУЧНАЯ_ПРОВЕРКА.html").write_text(page.replace("__CARDS__", "\n".join(cards)),
                                              encoding="utf-8")

    from collections import Counter
    print(f"записей на проверку: {len(rows)}")
    print("по источникам:", dict(Counter(r["source"] for r in rows)))
    print("по вопросам:", dict(Counter(r["question"][:50] for r in rows)))
    print(f"\nвыход: {OUT}")


if __name__ == "__main__":
    main()
