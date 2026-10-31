"""Build the profile README's stats cards as SVGs (light and dark).

Uses only public GitHub data, so it needs no personal token:
  - the contribution calendar at github.com/users/<user>/contributions
  - the REST API for repos, languages and the commit count

    python scripts/cards.py <username> <out_dir>
"""
import datetime as dt
import json
import os
import re
import sys
import urllib.request
from html import escape

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

THEMES = {
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "title": "#1e5a52", "ink": "#1f2328",
        "muted": "#59636e", "bar": "#1e5a52", "axis": "#d0d7de", "empty": "#e8eeec",
        "langs": ["#2a78d6", "#eb6834", "#1baf7a"], "other": "#898781",
        "heat": ["#eef1f0", "#b9dfc9", "#6dbb94", "#2f8a6a", "#1e5a52"],
    },
    "dark": {
        "bg": "#0d1117", "border": "#30363d", "title": "#79c7b8", "ink": "#e6edf3",
        "muted": "#9198a1", "bar": "#79c7b8", "axis": "#30363d", "empty": "#21262d",
        "langs": ["#3987e5", "#d95926", "#199e70"], "other": "#898781",
        "heat": ["#161b22", "#1b4239", "#2a6e5d", "#47a389", "#79c7b8"],
    },
}
# Colour follows the language, not its rank, so a re-ranking never repaints a bar.
PREFERRED = ["Python", "TypeScript", "JavaScript"]
# Notebook outputs inflate byte counts without reflecting code written.
SKIP_LANGS = {"Jupyter Notebook"}


def fetch(url, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "profile-cards"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def contributions(user):
    """({date: count}, {date: level 0-4}) for the last year, from the public contribution calendar.
    Levels are GitHub's own buckets, so the heatmap shades match the profile's graph."""
    html = fetch(f"https://github.com/users/{user}/contributions", accept="text/html")
    cells = re.findall(r'data-date="(\d{4}-\d\d-\d\d)" id="([^"]+)" data-level="(\d)"', html)
    by_id = {}
    for for_id, text in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)</tool-tip>', html):
        m = re.match(r"([\d,]+) contribution", text)
        by_id[for_id] = int(m.group(1).replace(",", "")) if m else 0
    return {d: by_id.get(i, 0) for d, i, _ in cells}, {d: int(lv) for d, _, lv in cells}


def streaks(days):
    ordered = sorted(days)
    longest = run = 0
    for d in ordered:
        run = run + 1 if days[d] else 0
        longest = max(longest, run)
    current = 0
    # today may not have activity yet, so the streak can end yesterday
    for i, d in enumerate(reversed(ordered)):
        if days[d]:
            current += 1
        elif i > 0:
            break
    return current, longest


def repo_stats(user):
    repos = json.loads(fetch(f"https://api.github.com/users/{user}/repos?per_page=100&type=owner"))
    own = [r for r in repos if not r["fork"]]
    langs = {}
    for r in own:
        for lang, n in json.loads(fetch(r["languages_url"])).items():
            if lang not in SKIP_LANGS:
                langs[lang] = langs.get(lang, 0) + n
    commits = json.loads(fetch(f"https://api.github.com/search/commits?q=author:{user}"))["total_count"]
    return {
        "repos": len(own),
        "stars": sum(r["stargazers_count"] for r in own),
        "commits": commits,
        "langs": langs,
    }


def frame(t, w, h, title, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'font-family="{FONT}" role="img" aria-label="{escape(title)}">'
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}"/>'
        f'<text x="24" y="38" font-size="16" font-weight="600" fill="{t["title"]}">{escape(title)}</text>'
        f"{body}</svg>"
    )


def stats_card(t, s, days):
    current, longest = streaks(days)
    tiles = [
        (f"{sum(days.values()):,}", "contributions, last year"),
        (f"{s['commits']:,}", "commits in public repos"),
        (f"{s['repos']}", "public repositories"),
        (f"{current} day{'s' if current != 1 else ''}", "current streak"),
        (f"{longest} day{'s' if longest != 1 else ''}", "longest streak"),
    ]
    if s["stars"]:
        tiles.insert(3, (f"{s['stars']}", "stars earned"))
        tiles.pop()
    w, step = 920, 896 / len(tiles)
    body = ""
    for i, (value, label) in enumerate(tiles):
        x = 24 + i * step
        body += (
            f'<text x="{x:.0f}" y="88" font-size="28" font-weight="700" fill="{t["ink"]}">{escape(value)}</text>'
            f'<text x="{x:.0f}" y="112" font-size="13" fill="{t["muted"]}">{escape(label)}</text>'
        )
    return frame(t, w, 138, "GitHub at a glance", body)


def languages_card(t, langs):
    total = sum(langs.values()) or 1
    ranked = sorted(langs.items(), key=lambda kv: -kv[1])
    top = ranked[:3]
    other = total - sum(n for _, n in top)
    free = [c for name, c in zip(PREFERRED, t["langs"]) if name not in dict(top)]
    colour = {}
    for name, _ in top:
        if name in PREFERRED:
            colour[name] = t["langs"][PREFERRED.index(name)]
        else:
            colour[name] = free.pop(0)
    parts = [(name, n, colour[name]) for name, n in top]
    if other > 0:
        parts.append(("Other", other, t["other"]))

    w, x0, bar_w, gap = 920, 24, 872, 2
    usable = bar_w - gap * (len(parts) - 1)
    body, x = "", x0
    for i, (name, n, c) in enumerate(parts):
        seg = max(4, usable * n / total)
        body += f'<rect x="{x:.1f}" y="58" width="{seg:.1f}" height="12" rx="3" fill="{c}"/>'
        x += seg + gap
    lx = x0
    for name, n, c in parts:
        label = f"{name}  {100 * n / total:.1f}%"
        body += (
            f'<rect x="{lx}" y="92" width="10" height="10" rx="2" fill="{c}"/>'
            f'<text x="{lx + 16}" y="101.5" font-size="13" fill="{t["ink"]}">{escape(label)}</text>'
        )
        lx += 16 + int(len(label) * 7.6) + 28
    return frame(t, w, 124, "Languages across my repositories (by code size)", body)


def activity_card(t, days, span=30):
    today = dt.date.fromisoformat(max(days))
    window = [(today - dt.timedelta(days=span - 1 - i)) for i in range(span)]
    counts = [days.get(d.isoformat(), 0) for d in window]
    peak = max(counts) or 1

    w, h = 920, 236
    left, right, top, base = 24, 896, 64, 196
    slot = (right - left) / span
    bw = slot - 4
    body = f'<line x1="{left}" y1="{base + 0.5}" x2="{right}" y2="{base + 0.5}" stroke="{t["axis"]}"/>'
    for i, (d, n) in enumerate(zip(window, counts)):
        x = left + i * slot + 2
        if n:
            bh = max(4, (base - top) * n / peak)
            # rounded at the data end, square on the baseline
            body += (
                f'<path d="M{x:.1f},{base} V{base - bh + 4:.1f} Q{x:.1f},{base - bh:.1f} {x + 4:.1f},{base - bh:.1f} '
                f'H{x + bw - 4:.1f} Q{x + bw:.1f},{base - bh:.1f} {x + bw:.1f},{base - bh + 4:.1f} V{base} Z" '
                f'fill="{t["bar"]}"><title>{d:%b %d}: {n} contribution{"s" if n != 1 else ""}</title></path>'
            )
        else:
            body += f'<rect x="{x:.1f}" y="{base - 2}" width="{bw:.1f}" height="2" fill="{t["empty"]}"/>'
    i_peak = counts.index(max(counts))
    if max(counts):
        px = left + i_peak * slot + slot / 2
        py = base - (base - top) * counts[i_peak] / peak - 8
        body += f'<text x="{px:.1f}" y="{py:.1f}" font-size="12" text-anchor="middle" fill="{t["ink"]}">{counts[i_peak]}</text>'
    for i in (0, span // 2, span - 1):
        anchor = "start" if i == 0 else "end" if i == span - 1 else "middle"
        x = left + i * slot + (2 if i == 0 else slot - 2 if i == span - 1 else slot / 2)
        body += f'<text x="{x:.1f}" y="{base + 22}" font-size="12" text-anchor="{anchor}" fill="{t["muted"]}">{window[i]:%b %d}</text>'
    total = sum(counts)
    body += f'<text x="{right}" y="38" font-size="13" text-anchor="end" fill="{t["muted"]}">{total} in the last {span} days</text>'
    return frame(t, w, h, "Contributions per day", body)


def heatmap_card(t, days, levels):
    dates = sorted(days)
    first, last = dt.date.fromisoformat(dates[0]), dt.date.fromisoformat(dates[-1])
    start = first - dt.timedelta(days=(first.weekday() + 1) % 7)  # weeks start on Sunday
    cols = (last - start).days // 7 + 1

    w, x0, y0 = 920, 60, 74
    step = min(16, (w - x0 - 24) / cols)
    cell = step - 3
    body = ""
    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        body += f'<text x="24" y="{y0 + row * step + cell - 2:.1f}" font-size="11" fill="{t["muted"]}">{name}</text>'
    last_label = -3
    for d in dates:
        day = dt.date.fromisoformat(d)
        col, row = (day - start).days // 7, (day.weekday() + 1) % 7
        x, y = x0 + col * step, y0 + row * step
        n = days[d]
        tip = f"{n} contribution{'s' if n != 1 else ''} on {day:%b %d, %Y}"
        body += (
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="2.5" '
            f'fill="{t["heat"][levels[d]]}"><title>{tip}</title></rect>'
        )
        # label a month on the first week that contains its 1st
        if row == 0 and day.day <= 7 and col - last_label >= 3:
            body += f'<text x="{x:.1f}" y="{y0 - 10}" font-size="11" fill="{t["muted"]}">{day:%b}</text>'
            last_label = col
    ly = y0 + 7 * step + 16
    lx = x0 + cols * step - 3 - 5 * step - 30
    body += f'<text x="{lx - 6:.1f}" y="{ly + cell - 2:.1f}" font-size="11" text-anchor="end" fill="{t["muted"]}">Less</text>'
    for i, c in enumerate(t["heat"]):
        body += f'<rect x="{lx + i * step:.1f}" y="{ly:.1f}" width="{cell:.1f}" height="{cell:.1f}" rx="2.5" fill="{c}"/>'
    body += f'<text x="{lx + 5 * step + 3:.1f}" y="{ly + cell - 2:.1f}" font-size="11" fill="{t["muted"]}">More</text>'
    total = sum(days.values())
    return frame(t, w, int(ly + cell + 20), f"{total:,} contributions in the last year", body)


def main():
    user, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    days, levels = contributions(user)
    stats = repo_stats(user)
    for mode, t in THEMES.items():
        suffix = "" if mode == "light" else "-dark"
        for name, svg in (
            ("stats", stats_card(t, stats, days)),
            ("languages", languages_card(t, stats["langs"])),
            ("activity", activity_card(t, days)),
            ("contributions", heatmap_card(t, days, levels)),
        ):
            with open(os.path.join(out, f"{name}{suffix}.svg"), "w") as f:
                f.write(svg)
    print(f"{len(days)} days, {sum(days.values())} contributions, {stats['commits']} commits, langs={stats['langs']}")


if __name__ == "__main__":
    main()
