# -*- coding: utf-8 -*-
"""НЭБ: HTML-открывалка для ручного сохранения карточек.

Из cards_to_open.csv делает страницу со ссылками: отметка «сохранено» (хранится
в браузере), кнопка «открыть следующие N», счётчик прогресса по губерниям.
"""
import csv
import html
import io
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = Path(r"D:\Yandex.Disk\History&Geography\БД\Поиск онлайн архив")
SRC = BASE / "output" / "neb_manual_20261003" / "cards_to_open.csv"
OUT = BASE / "output" / "neb_manual_20261003" / "КАРТОЧКИ_НЭБ_открывалка.html"

rows = list(csv.DictReader(SRC.open(encoding="utf-8-sig")))
by_t = Counter(r["territory"] for r in rows)

items = "".join(
    f'<li data-t="{html.escape(r["territory"])}" data-url="{html.escape(r["url"])}">'
    f'<input type="checkbox" class="done" id="c{i}"><label for="c{i}"></label>'
    f'<a href="{html.escape(r["url"])}" target="_blank" rel="noopener">{html.escape(r["title"])}</a>'
    f'<span class="meta">{html.escape(r["territory"])} · {html.escape(r["access"])}</span></li>'
    for i, r in enumerate(rows)
)
tabs = "".join(f'<button class="tab" data-f="{html.escape(t)}">{html.escape(t)} '
               f'<b>{n}</b></button>' for t, n in sorted(by_t.items()))

OUT.write_text(f"""<!doctype html><html lang="ru"><meta charset="utf-8">
<title>НЭБ — карточки на сохранение</title>
<style>
 body{{font:15px/1.5 system-ui,Segoe UI,sans-serif;margin:0;padding:24px;background:#fafaf9;color:#1c1917}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#57534e;margin-bottom:18px}}
 .bar{{position:sticky;top:0;background:#fafaf9;padding:12px 0;border-bottom:1px solid #e7e5e4;margin-bottom:12px;z-index:5}}
 button{{font:inherit;padding:7px 13px;border:1px solid #d6d3d1;background:#fff;border-radius:7px;cursor:pointer;margin-right:6px}}
 button:hover{{background:#f5f5f4}} .tab.on{{background:#1c1917;color:#fff;border-color:#1c1917}}
 .go{{background:#1d4ed8;color:#fff;border-color:#1d4ed8;font-weight:600}} .go:hover{{background:#1e40af}}
 ol{{list-style:none;padding:0;margin:0}}
 li{{display:grid;grid-template-columns:26px 1fr;gap:2px 8px;padding:9px 10px;border-bottom:1px solid #eee;align-items:start}}
 li.hide{{display:none}} li.ok{{opacity:.42}} li.ok a{{text-decoration:line-through}}
 input.done{{position:absolute;opacity:0}} label{{width:19px;height:19px;border:2px solid #a8a29e;border-radius:5px;display:block;cursor:pointer;margin-top:2px}}
 input.done:checked + label{{background:#16a34a;border-color:#16a34a}}
 input.done:checked + label::after{{content:"✓";color:#fff;display:block;text-align:center;line-height:17px;font-size:13px}}
 a{{color:#1d4ed8;text-decoration:none}} a:hover{{text-decoration:underline}}
 .meta{{grid-column:2;color:#78716c;font-size:12.5px}}
 #stat{{font-weight:600;margin-left:8px}}
</style>
<h1>НЭБ — карточки на сохранение</h1>
<div class="sub">Открыть ссылку → <b>Ctrl+S</b> → «Веб-страница, полностью» → папка
<code>input_neb_manual\..\input_neb_cards</code>. Отметка сохраняется в браузере.</div>
<div class="bar">
 <button class="tab on" data-f="">Все <b>{len(rows)}</b></button>{tabs}
 <button class="go" id="open5">Открыть 5 следующих</button>
 <button class="go" id="open10">Открыть 10</button>
 <span id="stat"></span>
</div>
<ol id="list">{items}</ol>
<script>
const KEY="neb_cards_done", list=document.getElementById("list");
let done=new Set(JSON.parse(localStorage.getItem(KEY)||"[]"));
const lis=[...list.children];
lis.forEach(li=>{{
  const cb=li.querySelector(".done"), u=li.dataset.url;
  if(done.has(u)){{cb.checked=true;li.classList.add("ok");}}
  cb.addEventListener("change",()=>{{
    cb.checked?done.add(u):done.delete(u);
    li.classList.toggle("ok",cb.checked);
    localStorage.setItem(KEY,JSON.stringify([...done])); stat();
  }});
}});
let filter="";
document.querySelectorAll(".tab").forEach(b=>b.addEventListener("click",()=>{{
  document.querySelectorAll(".tab").forEach(x=>x.classList.remove("on"));
  b.classList.add("on"); filter=b.dataset.f;
  lis.forEach(li=>li.classList.toggle("hide",!!filter&&li.dataset.t!==filter)); stat();
}}));
function pending(){{return lis.filter(li=>!li.classList.contains("hide")&&!li.classList.contains("ok"));}}
function stat(){{
  const vis=lis.filter(li=>!li.classList.contains("hide"));
  document.getElementById("stat").textContent=
    `сохранено ${{vis.length-pending().length}} из ${{vis.length}}`;
}}
function openN(n){{pending().slice(0,n).forEach((li,i)=>setTimeout(()=>window.open(li.dataset.url,"_blank"),i*350));}}
document.getElementById("open5").onclick=()=>openN(5);
document.getElementById("open10").onclick=()=>openN(10);
stat();
</script></html>""", encoding="utf-8")

print(f"строк: {len(rows)} | по губерниям: {dict(by_t)}")
print(f"файл: {OUT}")
