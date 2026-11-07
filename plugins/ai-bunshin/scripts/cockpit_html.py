#!/usr/bin/env python3
"""コックピット（ターミナルの右のパネル）と同じ中身の HTML を、1ファイルで作る（デスクトップ版のタスク表）。

- 読むだけ：本人のフォルダの 00_タスク管理/data/tasks.json・forecast.json・calendar_cache.json、設定/config.json、04_ナレッジ/改善ログ.md
- 書くのは 00_タスク管理/コックピット.html の1つだけ（.コックピット.html.tmp に書いてから置き換える）。出力先は引数で変えられない（引数は取らない）
- 本人のフォルダ（設定/config.json と 00_タスク管理/data/tasks.json がある所）でないときは、何も書かずに1行出して終わる（終了コード1）
- 中身の決まりは hooks/register.tsx（パネル）と同じ。**パネルを変えたら、ここも見る**（tests/test_cockpit_html.py が register.test.tsx の主な期待を写している）
- 外の読み込みなし・JavaScript なし。tasks.json などの文字は、全部 html.escape(quote=True) を通す（外の資料の文字が混じることがある）
使い方：python3 scripts/cockpit_html.py（本人のフォルダの中で。AI_BUNSHIN_HOME があればそのフォルダだけを見る）
"""
import html
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

OUT_REL = ("00_タスク管理", "コックピット.html")
TMP_NAME = ".コックピット.html.tmp"
UNCAT = "未分類"
APPROVAL = "ルール変更の承認"
APPROVAL_MARK = "承認"
MAX_UP = 6
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}\Z", re.ASCII)
STATE_WAIT = "見積もり待ち"
STATE_LOOP = "依存の輪"
WEEK = "月火水木金土日"
NO_HOME = ("本人のフォルダ（設定/config.json と 00_タスク管理/data/tasks.json がある所）の中ではないので、"
           "コックピットの HTML は作りませんでした。")
USAGE = "引数は取りません（出力先は 00_タスク管理/コックピット.html に決まっています）。何も作っていません。"


def esc(s):
    """HTML に入れる文字は、全部これを通す（属性の中も）。"""
    return html.escape(str(s), quote=True)


def fmt(v):
    """パネルの fmt：一覧は「、」でつなぎ、None は空、{ } は JSON の文字、ほかは文字にする。"""
    if isinstance(v, list):
        return "、".join(fmt(x) for x in v)
    if v is None:
        return ""
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def truthy(v):
    """JavaScript の !!v（空の {} や [] は true）。"""
    return not (v is None or v is False or v == 0 or v == "")


def md(d):
    """M/D。空は空。ISO の形でない文字は、そのまま（パネルは NaN/NaN になる）。"""
    if not d:
        return ""
    if isinstance(d, str) and ISO.match(d):
        return f"{int(d[5:7])}/{int(d[8:10])}"
    return str(d)


def jst_now(now_utc=None):
    """日本時間の「いま」（パネルの dayOf と同じ +9 時間）。"""
    base = now_utc if now_utc is not None else datetime.now(timezone.utc)
    return (base + timedelta(hours=9)).replace(tzinfo=None)


# ---------- 本人のフォルダ ----------

def _read_config(cfg_path):
    """config.json を BOM を除いて読む。読めない・壊れている・辞書でないなら None（パネルの findMe と同じ）。"""
    try:
        c = json.loads(Path(cfg_path).read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, ValueError, RecursionError):
        return None
    return c if isinstance(c, dict) else None


def find_home():
    """本人のフォルダ（設定/config.json と 00_タスク管理/data/tasks.json の両方がある所）。
    AI_BUNSHIN_HOME があれば、そのフォルダだけを見る。無ければ CLAUDE_PROJECT_DIR とカレントから上へ最大6段。
    見つかれば (フォルダ, 設定の辞書)、無ければ None。"""
    def ok(d):
        cfg = d / "設定" / "config.json"
        if cfg.is_file() and (d / "00_タスク管理" / "data" / "tasks.json").is_file():
            c = _read_config(cfg)
            return (d, c) if c is not None else None
        return None

    env = os.environ.get("AI_BUNSHIN_HOME")
    if env:
        return ok(Path(env).resolve())
    for start in (os.environ.get("CLAUDE_PROJECT_DIR"), os.getcwd()):
        if not start:
            continue
        d = Path(start).resolve()
        for _ in range(MAX_UP + 1):
            found = ok(d)
            if found:
                return found
            if d.parent == d:
                break
            d = d.parent
    return None


def owner_names(cfg):
    owner = cfg.get("owner")
    owner = owner.strip() if isinstance(owner, str) and owner.strip() else "本人"
    call = cfg.get("owner_call")
    call = call.strip() if isinstance(call, str) and call.strip() else f"{owner}さん"
    return owner, call


# ---------- tasks.json → 区切り（hooks/register.tsx の build） ----------

def cat_of(t):
    c = t.get("category")
    return c.strip() if isinstance(c, str) and c.strip() else UNCAT


def due_of(t):
    d = t.get("due")
    return d if isinstance(d, str) else ""


def pri_of(t):
    p = t.get("priority")
    return p if isinstance(p, (int, float)) and not isinstance(p, bool) else 999


def is_approval(t, owner):
    return t.get("status") != "完了" and t.get("assignee") == owner and isinstance(t.get("title"), str) \
        and t["title"].startswith(APPROVAL)


def build(data, today, owner):
    """パネルの build()。今日まで・近日・AI の今日の計画・AI のこれから・全部の一覧・お願いの件数。形が違えば例外。"""
    if not isinstance(data, dict):
        raise ValueError("shape")
    raw = data.get("tasks")
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError("shape")
    tasks = [t for t in raw if isinstance(t, dict)]
    sprints = data.get("daily_sprints")
    if sprints is None:
        sprints = []
    if not isinstance(sprints, list):
        raise ValueError("shape")
    opened = [t for t in tasks if t.get("status") != "完了"]

    def row(t, mark):
        return {"id": fmt(t.get("id")), "title": fmt(t.get("title")), "due": md(due_of(t)), "mark": mark,
                "category": cat_of(t)}

    # 今日まで：期日の順。承認待ちは一番上（同じ仲間の中は期日の順のまま）
    mine_tasks = sorted([t for t in opened if t.get("assignee") == owner and due_of(t) and due_of(t) <= today],
                        key=due_of)
    mine_sorted = [t for t in mine_tasks if is_approval(t, owner)] + [t for t in mine_tasks if not is_approval(t, owner)]
    mine = [row(t, APPROVAL_MARK if is_approval(t, owner) else ("超過" if due_of(t) < today else "今日"))
            for t in mine_sorted]

    limit = (date.fromisoformat(today) + timedelta(days=4)).isoformat()
    soon = [row(t, APPROVAL_MARK if is_approval(t, owner) else "")
            for t in sorted([t for t in opened if t.get("assignee") == owner and due_of(t) and today < due_of(t) <= limit],
                            key=due_of)[:6]]

    sprint = next((s for s in sprints if isinstance(s, dict) and s.get("date") == today), None) or {}
    planned = []
    for k in ("planned", "added", "pulled"):
        v = sprint.get(k)
        if isinstance(v, list):
            planned += v
    by_id = {fmt(t.get("id")): t for t in tasks}
    ai = [row(by_id[i], "済" if by_id[i].get("status") == "完了" else fmt(by_id[i].get("status")))
          for i in (fmt(x) for x in planned) if i in by_id]

    # AI のこれから：今日の計画に入っていない、未完了の AI のタスク（順位の順）
    in_plan = set(fmt(x) for x in planned)
    nxt = sorted([t for t in opened if truthy(t.get("assignee")) and t.get("assignee") != owner
                  and fmt(t.get("id")) not in in_plan], key=pri_of)
    ai_next = [row(t, fmt(t.get("status"))) for t in nxt[:6]]

    # 全部のタスク：未完了をカテゴリごと（カテゴリの順は一番順位が高いタスクの順。未分類は最後）→ 完了を新しい順
    def all_row(t):
        done = t.get("status") == "完了"
        mark = "済" if done else APPROVAL_MARK if is_approval(t, owner) else fmt(t.get("status"))
        r = row(t, mark)
        r["who"] = fmt(t.get("assignee"))
        r["done"] = done
        return r

    sorted_open = sorted(opened, key=lambda t: (pri_of(t), fmt(t.get("id"))))
    order = []
    for t in sorted_open:
        if cat_of(t) != UNCAT and cat_of(t) not in order:
            order.append(cat_of(t))

    def rank(t):
        return len(order) if cat_of(t) == UNCAT else order.index(cat_of(t))

    open_sorted = sorted(sorted_open, key=rank)   # 安定ソート：カテゴリの中は順位の順のまま
    done_sorted = sorted([t for t in tasks if t.get("status") == "完了"], key=lambda t: fmt(t.get("id")), reverse=True)
    all_rows = [all_row(t) for t in open_sorted + done_sorted]

    open_requests = len([t for t in opened if t.get("assignee") == owner and t.get("kind") != "自分"])
    return {"today": today, "mine": mine, "ai": ai, "ai_next": ai_next, "ai_next_more": len(nxt) - len(ai_next),
            "all": all_rows, "soon": soon, "open_requests": open_requests, "error": ""}


def empty_board(today, error):
    return {"today": today, "mine": [], "ai": [], "ai_next": [], "ai_next_more": 0, "all": [], "soon": [],
            "open_requests": 0, "error": error}


def group_by_cat(rows):
    """区切りの中をカテゴリごとに。カテゴリの順は「その区切りで最初に出てくる順」、未分類は最後。"""
    groups = []
    for r in rows:
        g = next((x for x in groups if x[0] == r["category"]), None)
        if g:
            g[1].append(r)
        else:
            groups.append((r["category"], [r]))
    return [g for g in groups if g[0] != UNCAT] + [g for g in groups if g[0] == UNCAT]


def all_lines(all_rows):
    """全部の一覧：「■ カテゴリ（N）」「■ 完了（N）」の見出しと、その下の行（ページ分けはしない）。"""
    def key(r):
        return "\0done" if r["done"] else "c:" + r["category"]

    out = []
    i = 0
    while i < len(all_rows):
        j = i
        while j < len(all_rows) and key(all_rows[j]) == key(all_rows[i]):
            j += 1
        name = "完了" if all_rows[i]["done"] else all_rows[i]["category"]
        out.append((name, all_rows[i]["done"], all_rows[i:j]))
        i = j
    return out


# ---------- 試し中の Try（04_ナレッジ/改善ログ.md の「## 実施中の Try」の表） ----------

TRY_HEAD = re.compile(r"^##\s+実施中の\s*Try")
TRY_COLS = ("ID", "良くするもの", "内容", "確かめ方", "開始日")


def split_row(line):
    s = re.sub(r"(?<!\\)\|\Z", "", re.sub(r"^\|", "", line.strip(), count=1))
    cells, cur, i = [], "", 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if s[i] == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += s[i]
        i += 1
    cells.append(cur.strip())
    return cells


def skip_note(body):
    """内容の先頭の「（…）」の注記を飛ばして右をそのまま返す。閉じ括弧が無い・飛ばすと何も残らないときは飛ばさない。"""
    if not body.startswith("（"):
        return body
    depth = 0
    for i, ch in enumerate(body):
        if ch == "（":
            depth += 1
        elif ch == "）":
            depth -= 1
            if depth == 0:
                rest = body[i + 1:].lstrip()
                return body if rest == "" else rest
    return body


def start_of(s):
    return md(s) if ISO.match(s) else s


def parse_tries(text):
    lines = re.split(r"\r?\n", text)
    frm = next((i for i, l in enumerate(lines) if TRY_HEAD.match(l)), -1)
    if frm < 0:
        return []
    to = next((i for i, l in enumerate(lines) if i > frm and re.match(r"^##\s", l)), len(lines))
    rows = [l.strip() for l in lines[frm + 1:to]]
    t0 = next((i for i, l in enumerate(rows) if l.startswith("|")), -1)
    if t0 < 0 or t0 + 1 >= len(rows):
        return []
    sep = rows[t0 + 1]
    if not sep.startswith("|") or not re.match(r"^[\s|:-]+\Z", sep) or "-" not in sep:
        return []
    head = split_row(rows[t0])
    col = [next((i for i, h in enumerate(head) if h.startswith(name)), -1) for name in TRY_COLS]
    if any(i < 0 for i in col):
        return []
    tries = []
    i = t0 + 2
    while i < len(rows) and rows[i].startswith("|"):
        c = split_row(rows[i])

        def cell(k):
            return c[col[k]] if col[k] < len(c) else ""

        if cell(0).upper().startswith("Y"):
            tries.append({"id": cell(0), "body": cell(2), "start": cell(4)})
        i += 1
    return tries


# ---------- ガント（forecast.json を読むだけ。計算し直さない） ----------

def iso_or_none(v):
    return v if isinstance(v, str) and ISO.match(v) else None


def load_gantt(text, today):
    """forecast.json の中身（読めなかったときは None）から {ok, message, days, tasks, waiting}。
    無い・壊れている・古い（今日の日付でない）ときは ok=False と、パネルと同じ1行の案内。"""
    if text is None:
        return {"ok": False, "message": "forecast.json がまだありません（読めませんでした）。update_dashboard.py を動かすと出ます"}
    try:
        f = json.loads(text)
        if not isinstance(f, dict):
            raise ValueError("shape")
        days = [{"date": d["date"], "off": d.get("off") is True}
                for d in (f["days"] if isinstance(f.get("days"), list) else [])
                if isinstance(d, dict) and iso_or_none(d.get("date"))]
        made = iso_or_none(f.get("today"))
        if not made or not days or not isinstance(f.get("tasks"), list):
            raise ValueError("shape")
        if made != today:
            return {"ok": False, "message": f"forecast.json が古いです（{md(made)} 作成）。update_dashboard.py を動かすと出ます"}
        tasks = [{"id": t["id"], "title": fmt(t.get("title")), "who": fmt(t.get("who")), "start": iso_or_none(t.get("start")),
                  "end": iso_or_none(t.get("end")), "state": fmt(t.get("state"))}
                 for t in f["tasks"] if isinstance(t, dict) and isinstance(t.get("id"), str)]
        w = f.get("waiting")
        waiting = w if isinstance(w, (int, float)) and not isinstance(w, bool) and w >= 0 \
            else len([t for t in tasks if t["state"] == STATE_WAIT])
        return {"ok": True, "message": "", "days": days, "tasks": tasks, "waiting": waiting}
    except (ValueError, KeyError, TypeError, RecursionError):
        return {"ok": False, "message": "forecast.json を読めませんでした（壊れています）。update_dashboard.py を動かし直すと出ます"}


def gantt_split(g):
    """棒（または印）の行にできるタスクと、期限を過ぎた本人のタスクの件数（行にせず件数だけ出す）に分ける。"""
    ok = [t for t in g["tasks"] if t["end"] and t["state"] != STATE_WAIT and t["state"] != STATE_LOOP
          and (t["who"] == "本人" or t["start"])]
    today = g["days"][0]["date"] if g["days"] else ""
    over = [t for t in ok if t["who"] == "本人" and (t["end"] or "") < today]
    return [t for t in ok if t not in over], len(over)


def gantt_cells(t, days):
    """1行ぶんの列。AI は着手見込み〜完了予定を棒（休みの日は飛ばす）、本人は期日の日に印。2週間より先は右端に →。"""
    last = len(days) - 1
    own = t["who"] == "本人"
    end = t["end"] or ""
    beyond = end > days[last]["date"]
    mark = [""] * len(days)    # "" ・"own"・"bar"
    if own:
        if not beyond:
            at = max(0, next((i for i, d in enumerate(days) if d["date"] >= end), -1))
            mark[at] = "own"
    else:
        key = t["start"] if t["start"] is not None else end
        s = next((i for i, d in enumerate(days) if d["date"] >= key), -1)
        if s >= 0:
            e = last
            if not beyond:
                idx = [i for i, d in enumerate(days) if d["date"] <= end]
                e = max(s, idx[-1] if idx else -1)
            for i in range(s, e + 1):
                if not days[i]["off"]:
                    mark[i] = "bar"
    return mark, beyond


# ---------- 予定（calendar_cache.json。config に calendar があるときだけ） ----------

def load_cal(text, today):
    """{fetched, events, error}。読めなかった（text が None）・壊れている → 「予定を読めませんでした」。
    今日より前に取った予定しか無いときは「予定を読めていません（…）」（「予定なし」と見せない）。"""
    try:
        if text is None:
            raise ValueError("none")
        c = json.loads(text)
        if c is None:
            raise ValueError("null")
        if not isinstance(c, dict):
            c = {}
        evs = c.get("events")
        events = []
        for e in (evs if evs is not None else []):
            if e.get("date") == today:
                events.append({"start": fmt(e.get("start")), "end": fmt(e.get("end")), "title": fmt(e.get("title")),
                               "allday": truthy(e.get("allday")), "unknown": e.get("time_unknown") is True})
        fetched = fmt(c.get("fetched"))
        stale = fetched[:10] < today
        err = f"予定を読めていません（最後の取得 {md(fetched[:10])} {fetched[11:]}）" if stale else ""
        return {"fetched": fetched, "events": events, "error": err}
    except (ValueError, TypeError, AttributeError, RecursionError):
        return {"fetched": "", "events": [], "error": "予定を読めませんでした"}


def when_of(e):
    if e["unknown"]:
        return "時刻不明"
    if e["allday"]:
        return "終日"
    return f"{e['start']}〜{e['end']}" if e["end"] else e["start"]


# ---------- HTML ----------

CSS = r"""
:root{
  color-scheme: light dark;
  --bg:#EEF0F3; --surface:#FFFFFF; --ink:#17202E; --ink-2:#505B6E; --line:#D5D9E0;
  --bar:#0B6B6A; --today-bg:#E7F3F3; --off-bg:#E4E7EC; --hatch:#C9CED7;
  --apv-bg:#17202E; --apv-fg:#FFFFFF;
  --over-fg:#B42318; --over-bg:#FDECEA;
  --now-fg:#8A4B00; --now-bg:#FFF1D6;
  --done-fg:#1F6B3A; --done-bg:#E3F3E8;
  --focus:#0B6B6A;
}
@media (prefers-color-scheme: dark){ :root{
  --bg:#0F141C; --surface:#171E29; --ink:#E6EAF0; --ink-2:#A3AEC0; --line:#2B3544;
  --bar:#4FC3C0; --today-bg:#14292B; --off-bg:#1F2733; --hatch:#2E3948;
  --apv-bg:#E6EAF0; --apv-fg:#0F141C;
  --over-fg:#FF9C94; --over-bg:#3A1A1A;
  --now-fg:#FFC266; --now-bg:#3A2C10;
  --done-fg:#7DD39B; --done-bg:#17301F;
  --focus:#4FC3C0;
}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.7 "Hiragino Sans","Hiragino Kaku Gothic ProN","BIZ UDPGothic","Yu Gothic UI","Meiryo","Noto Sans JP",system-ui,sans-serif;
  font-variant-numeric:tabular-nums;overflow-wrap:anywhere}
a{color:inherit} a:focus-visible,summary:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:4px}
.page{max-width:1080px;margin:0 auto;padding:20px 16px 56px}
.head{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 20px;margin:0 0 6px}
h1{margin:0;font-size:30px;line-height:1.3;font-weight:700;letter-spacing:.01em}
.req{font-size:14px;font-weight:700;border:1px solid var(--ink);border-radius:999px;padding:1px 12px}
.made{margin:0 0 14px;font-size:13px;color:var(--ink-2)}
.nav{display:flex;gap:4px 18px;flex-wrap:wrap;margin:0 0 20px;padding:0;list-style:none;font-size:14px;border-bottom:1px solid var(--line)}
.nav a{display:inline-block;padding:6px 0;text-decoration:none;font-weight:600}
.nav a:hover{text-decoration:underline}
.err{margin:0 0 16px;padding:8px 12px;border-left:4px solid var(--over-fg);background:var(--over-bg);color:var(--over-fg);font-weight:600}
.cols{display:grid;grid-template-columns:minmax(0,1fr);gap:0 28px}
@media (min-width:860px){.cols{grid-template-columns:minmax(0,1fr) minmax(0,1fr)}}
.sec{margin:0 0 24px}
h2{margin:0 0 6px;font-size:17px;line-height:1.5;font-weight:700}
h3{margin:14px 0 2px;font-size:14px;line-height:1.5;font-weight:700;color:var(--ink-2)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:4px 14px}
.empty,.more{margin:0;padding:8px 0;color:var(--ink-2);font-size:14px}
ul.rows{list-style:none;margin:0;padding:0}
.row{display:grid;grid-template-columns:5.2em 4.2em minmax(0,1fr) auto;gap:0 8px;align-items:baseline;padding:7px 0;border-top:1px solid var(--line)}
ul.rows>.row:first-child,h3+ul.rows>.row:first-child{border-top:0}
.id{font-weight:700;color:var(--ink-2);font-size:13px}
.due{color:var(--ink-2);font-size:13px;white-space:nowrap}
.who{color:var(--ink-2);font-size:13px}
.mark{justify-self:start;font-size:12px;line-height:1.5;font-weight:700;padding:0 7px;border-radius:4px;border:1px solid var(--line);color:var(--ink-2);white-space:nowrap}
.mark.apv{background:var(--apv-bg);color:var(--apv-fg);border-color:var(--apv-bg)}
.mark.over{background:var(--over-bg);color:var(--over-fg);border-color:var(--over-fg)}
.mark.now{background:var(--now-bg);color:var(--now-fg);border-color:var(--now-fg)}
.mark.done{background:var(--done-bg);color:var(--done-fg);border-color:var(--done-fg)}
.row.is-done .title{color:var(--ink-2)}
.row.is-apv{background:linear-gradient(90deg,var(--over-bg),transparent 70%);margin:0 -14px;padding-left:14px;padding-right:14px}
@media (max-width:520px){
  .row{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 8px}
  .row>.nomark{display:none}.row>.due{order:2;margin-left:auto}.row>.title{order:3;flex:1 0 100%}
}
.cal{list-style:none;margin:0;padding:0}
.cal li{display:grid;grid-template-columns:7.6em minmax(0,1fr);gap:0 8px;padding:6px 0;border-top:1px solid var(--line)}
.cal li:first-child{border-top:0}.cal time{color:var(--ink-2);font-size:13px;white-space:nowrap}
/* gantt */
.gantt{padding:10px 14px 14px}
.callout{margin:0 0 10px;padding:6px 10px;border-left:4px solid var(--over-fg);background:var(--over-bg);color:var(--over-fg);font-weight:600;font-size:14px}
.legend{display:flex;flex-wrap:wrap;gap:2px 16px;margin:0 0 8px;padding:0;list-style:none;font-size:13px;color:var(--ink-2)}
.legend li{display:flex;align-items:center;gap:6px}
.sw{display:inline-block;width:22px;height:10px;border-radius:3px}
.sw.bar{background:var(--bar)}
.sw.off{background:repeating-linear-gradient(135deg,var(--hatch) 0 2px,var(--off-bg) 2px 5px);border:1px solid var(--line)}
.grow{display:grid;grid-template-columns:minmax(0,1fr);align-items:center;border-top:1px solid var(--line)}
.glabel{padding:4px 0 0;font-size:13.5px;line-height:1.5;min-width:0}
.glabel .t{display:block}
.cells{display:grid;grid-template-columns:repeat(14,minmax(0,1fr)) 1.4em;height:26px;align-items:stretch;padding:4px 0}
.cells>span{display:flex;align-items:center;justify-content:center;font-size:12px;line-height:1;position:relative}
.cells>.today{background:var(--today-bg)}
.cells>.off{background:repeating-linear-gradient(135deg,var(--hatch) 0 2px,var(--off-bg) 2px 5px)}
.cells>.bar{background:var(--bar);margin:4px 0}
.cells>.bar.s{border-radius:6px 0 0 6px}.cells>.bar.e{border-radius:0 6px 6px 0}.cells>.bar.s.e{border-radius:6px}
.cells>.own{color:var(--bar);font-size:15px;font-weight:700}
.cells>.beyond{color:var(--ink-2);font-weight:700}
.axis .cells{height:auto;padding:0 0 2px}
.axis .cells>span{flex-direction:column;font-size:11.5px;line-height:1.35;color:var(--ink-2);padding:2px 0;white-space:nowrap}
@media (max-width:520px){.axis .cells>span{font-size:10px}}
.axis .cells>.today{color:var(--ink);font-weight:700}
.axis .glabel{display:none}
.ghead{margin:12px 0 0;font-size:14px;font-weight:700}
@media (min-width:700px){
  .grow{grid-template-columns:minmax(12em,17em) minmax(0,1fr);gap:0 12px}
  .glabel{padding:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .glabel .t{display:inline;overflow:hidden;text-overflow:ellipsis}
  .axis .glabel{display:block}
}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
details.done>summary{cursor:pointer;font-weight:700;padding:8px 0;color:var(--ink-2)}
"""

MARK_CLASS = {"承認": "apv", "超過": "over", "今日": "now", "済": "done"}


def mark_html(m):
    if not m:
        return '<span class="nomark"></span>'
    cls = MARK_CLASS.get(m, "")
    return f'<span class="mark {cls}">{esc(m)}</span>' if cls else f'<span class="mark">{esc(m)}</span>'


def row_html(r, with_who=False):
    m = r["mark"]
    cls = " is-apv" if m == APPROVAL_MARK else " is-done" if m == "済" else ""
    who = f' <span class="who">・{esc(r["who"])}</span>' if with_who and r.get("who") else ""
    due = f'<span class="due">（{esc(r["due"])}）</span>' if r["due"] and m not in ("今日", "済") \
        else '<span class="due"></span>'
    return (f'<li class="row{cls}">{mark_html(m)}<span class="id">{esc(r["id"])}</span>'
            f'<span class="title">{esc(r["title"])}{who}</span>{due}</li>')


def rows_html(rows, with_who=False):
    return '<ul class="rows">' + "".join(row_html(r, with_who) for r in rows) + "</ul>"


def grouped_html(rows):
    """区切りの中を「◇ カテゴリ」の小見出しで分ける。全部「未分類」なら小見出しなしで行だけ。"""
    if all(r["category"] == UNCAT for r in rows):
        return rows_html(rows)
    return "".join(f'<h3>◇ {esc(cat)}</h3>{rows_html(rs)}' for cat, rs in group_by_cat(rows))


def section(sid, title, body, extra=""):
    return f'<section class="sec" id="{sid}"><h2>{esc(title)}</h2><div class="card">{body}{extra}</div></section>'


def empty_p(text):
    return f'<p class="empty">{esc(text)}</p>'


def cal_section(c):
    title = "今日の予定" + (f"（{c['fetched'][11:]} 取得）" if c["fetched"] and not c["error"] else "")
    body = ""
    if c["error"]:
        body += f'<p class="callout">{esc(c["error"])}</p>'
    if not c["error"] and not c["events"]:
        body += empty_p("予定なし")
    if c["events"]:
        body += '<ul class="cal">' + "".join(
            f'<li><time>{esc(when_of(e))}</time><span>{esc(e["title"])}</span></li>' for e in c["events"]) + "</ul>"
    return section("cal", title, body)


def try_section(tries):
    items = []
    for t in tries:
        body = skip_note(t["body"])
        start = start_of(t["start"])
        if ISO.match(t["start"]):
            lead, pre = f'<span class="mark">{esc(start)}</span>', ""
        else:
            # 日付の形でない開始日は、パネルと同じ並び [開始日, ID, 内容]（空のものは飛ばす）
            lead, pre = '<span class="nomark"></span>', (esc(start) + " " if start else "")
        items.append(f'<li class="row">{lead}<span class="title" style="grid-column:2 / 4">'
                     f'{pre}<span class="id">{esc(t["id"])}</span> {esc(body)}</span><span class="due"></span></li>')
    return section("try", f"試し中の Try（{len(tries)}）", '<ul class="rows">' + "".join(items) + "</ul>")


def gantt_section(g, all_rows, call):
    if not g["ok"]:
        return ('<section class="sec" id="gantt"><h2>これから2週間</h2><div class="card gantt">'
                f'<p class="callout">{esc(g["message"])}</p></div></section>')
    days = g["days"]
    draw, overdue = gantt_split(g)
    head = f"これから2週間（{md(days[0]['date'])}〜{md(days[-1]['date'])}）"
    cat_by_id = {}
    order = []
    for r in all_rows:
        if r["done"]:
            continue
        cat_by_id[r["id"]] = r["category"]
        if r["category"] != UNCAT and r["category"] not in order:
            order.append(r["category"])
    order.append(UNCAT)
    sets = [(name, [t for t in draw if cat_by_id.get(t["id"], UNCAT) == name]) for name in order]
    sets = [s for s in sets if s[1]]

    out = ""
    if overdue > 0:
        out += f'<p class="callout">{esc(f"期限超過 {overdue} 件（{call}・今日より前）")}</p>'
    out += ('<ul class="legend"><li><span class="sw bar"></span>AI</li>'
            '<li><span style="color:var(--bar);font-weight:700">◆</span>期日</li>'
            '<li><span class="sw off"></span>休み</li>'
            '<li><span style="font-weight:700">→</span>先</li></ul>')
    ax = ""
    for i, d in enumerate(days):
        try:
            wd = WEEK[date.fromisoformat(d["date"]).weekday()]
        except ValueError:
            wd = ""
        cls = " ".join(x for x in ("today" if i == 0 else "", "off" if d["off"] else "") if x)
        inner = "<span>今日</span>" if i == 0 else f'<span>{int(d["date"][8:10])}</span><span>{wd}</span>'
        ax += f'<span class="{cls}">{inner}</span>'
    out += f'<div class="grow axis"><div class="glabel"></div><span class="cells" aria-hidden="true">{ax}<span></span></span></div>'
    if not draw:
        out += empty_p("棒にできるタスクなし")
    for name, lst in sets:
        out += f'<h3 class="ghead">■ {esc(name)}（{len(lst)}）</h3>'
        for t in lst:
            mark, beyond = gantt_cells(t, days)
            cells = ""
            for i, d in enumerate(days):
                cls = ["today" if i == 0 else "", "off" if d["off"] else ""]
                txt = ""
                if mark[i] == "bar":
                    cls.append("bar")
                elif mark[i] == "own":
                    cls.append("own")
                    txt = "◆"
                cells += f'<span class="{" ".join(c for c in cls if c)}">{txt}</span>'
            cells += f'<span class="beyond">{"→" if beyond else ""}</span>'
            if t["who"] == "本人":
                desc = f"期日 {md(t['end'])}" + ("（2週間より先）" if beyond else "")
            else:
                desc = f"AI 着手 {md(t['start'] or t['end'])} から " + ("2週間より先" if beyond else f"完了予定 {md(t['end'])}")
            out += (f'<div class="grow"><div class="glabel"><span class="id">{esc(t["id"])}</span> '
                    f'<span class="t" title="{esc(t["title"])}">{esc(t["title"])}</span><span class="sr">{esc(desc)}</span></div>'
                    f'<span class="cells" aria-hidden="true">{cells}</span></div>')
    loops = len([t for t in g["tasks"] if t["state"] == STATE_LOOP])
    parts = [x for x in (f"{STATE_WAIT} {g['waiting']}" if g["waiting"] > 0 else "",
                         f"{STATE_LOOP} {loops}" if loops > 0 else "") if x]
    if parts:
        out += f'<p class="more">{esc("・".join(parts) + "（棒なし）")}</p>'
    return f'<section class="sec" id="gantt"><h2>{esc(head)}</h2><div class="card gantt">{out}</div></section>'


def all_section(b):
    n_open = len([r for r in b["all"] if not r["done"]])
    body = ""
    if not b["all"]:
        body = empty_p("なし")
    for name, done, rs in all_lines(b["all"]):
        if done:
            body += f'<details class="done"><summary>{esc(f"■ 完了（{len(rs)}）")}</summary>{rows_html(rs, True)}</details>'
        else:
            body += f'<h3>■ {esc(f"{name}（{len(rs)}）")}</h3>{rows_html(rs, True)}'
    return section("all", f"全部のタスク {len(b['all'])} 件（未完了 {n_open}）", body)


def render(ctx):
    """ctx（load_context の答え）から HTML の文字を作る。"""
    b, call, today, now = ctx["board"], ctx["call"], ctx["today"], ctx["now"]
    made = now.strftime("%Y-%m-%d %H:%M")
    made_attr = now.strftime("%Y-%m-%dT%H:%M") + "+09:00"
    req = "" if b["error"] else f'<span class="req">お願い 残り {b["open_requests"]} 件</span>'
    head = (f'<header><div class="head"><h1>{esc(md(today))} の予定</h1>{req}</div>'
            f'<p class="made"><time datetime="{esc(made_attr)}">{esc(made)}</time> に作成。新しくするには「コックピット見せて」</p>'
            '<ul class="nav"><li><a href="#today">今日のやること</a></li><li><a href="#gantt">これから2週間</a></li>'
            '<li><a href="#all">全部のタスク</a></li></ul></header>')
    if b["error"]:
        head += f'<p class="err">{esc(b["error"])}</p>'
    cal = cal_section(ctx["cal"]) if ctx["has_cal"] else ""
    if b["error"]:
        left, right = cal, ""
    else:
        left = (section("mine", f"{call}（今日まで）", grouped_html(b["mine"]) if b["mine"] else empty_p("なし"))
                + cal
                + section("soon", f"近いうちに（{call}）", grouped_html(b["soon"]) if b["soon"] else empty_p("なし")))
        right = (section("plan", "AI（今日の計画）", grouped_html(b["ai"]) if b["ai"] else empty_p("計画なし"))
                 + section("next", "AI（これから）", grouped_html(b["ai_next"]) if b["ai_next"] else empty_p("なし"),
                           f'<p class="more">ほか {b["ai_next_more"]} 件</p>' if b["ai_next_more"] > 0 else "")
                 + (try_section(ctx["tries"]) if ctx["tries"] else ""))
    main = f'<main id="today"><div class="cols"><div class="col-me">{left}</div><div class="col-ai">{right}</div></div></main>'
    body = head + main + gantt_section(ctx["gantt"], b["all"], call) + ("" if b["error"] else all_section(b))
    return ('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark">'
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            f"<title>今日のやること</title><style>{CSS}</style></head><body><div class=\"page\">{body}</div></body></html>\n")


# ---------- 読む・書く ----------

def _read(path):
    """読めたら文字、読めなければ None。"""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def load_context(home, cfg, now):
    """本人のフォルダから、画面に必要なものを読む（読むだけ）。now は日本時間の datetime（tzinfo なし）。"""
    owner, call = owner_names(cfg)
    today = now.date().isoformat()
    data_dir = home / "00_タスク管理" / "data"
    text = _read(data_dir / "tasks.json")
    if text is None:
        board = empty_board(today, "tasks.json が見つかりません" if not (data_dir / "tasks.json").exists()
                            else "tasks.json を読めませんでした")
    else:
        try:
            board = build(json.loads(text), today, owner)
        except (ValueError, TypeError, AttributeError, RecursionError):
            board = empty_board(today, "tasks.json を読めませんでした")
    has_cal = truthy(cfg.get("calendar"))
    cal = load_cal(_read(data_dir / "calendar_cache.json"), today) if has_cal else None
    log = _read(home / "04_ナレッジ" / "改善ログ.md")
    return {"owner": owner, "call": call, "today": today, "now": now, "board": board, "has_cal": has_cal, "cal": cal,
            "tries": parse_tries(log) if log is not None else [],
            "gantt": load_gantt(_read(data_dir / "forecast.json"), today)}


def write_page(home, text):
    """00_タスク管理/コックピット.html に書く（一時ファイル → 置き換え）。出力先は固定。書いたパスを返す。"""
    out_dir = home / OUT_REL[0]
    tmp = out_dir / TMP_NAME
    out = out_dir / OUT_REL[1]
    try:
        Path(os.path.realpath(out_dir)).relative_to(os.path.realpath(home))
    except ValueError:
        raise OSError(f"{OUT_REL[0]} が本人のフォルダの外を指しているので書きません")
    if tmp.is_symlink():
        raise OSError(f"{TMP_NAME} がリンクなので書きません")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(tmp, flags, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, out)
    return out


def main(argv=None, now_utc=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    if argv:
        print(USAGE)
        return 2
    found = find_home()
    if not found:
        print(NO_HOME)
        return 1
    home, cfg = found
    try:
        out = write_page(home, render(load_context(home, cfg, jst_now(now_utc))))
    except OSError as e:
        print(f"コックピットの HTML を書けませんでした（{e.__class__.__name__}）。")
        return 1
    except RecursionError:
        print("コックピットの HTML を作る途中で、データを読めませんでした（入れ子が深すぎます）。")
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
