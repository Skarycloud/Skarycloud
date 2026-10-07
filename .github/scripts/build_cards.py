"""Render the profile's stats and activity cards as animated SVGs.

Usage: python build_cards.py <github-login> <output-dir>

Uses GITHUB_TOKEN (GraphQL) when set; otherwise falls back to the public
contribution calendar page and the unauthenticated REST API, which is
handy for previewing locally.
"""

import datetime as dt
import json
import os
import random
import re
import sys
import urllib.request
from html import escape

GOLD = "#ECC47E"
TEXT = "#e6edf3"
MUTED = "#8b949e"
FAINT = "#30363d"
BG = "#0d1117"
LANG_SHADES = ["#ECC47E", "#C9A25F", "#A3834A", "#7D6538", "#8b949e", "#6e7681", "#484f58"]
FONT = "-apple-system, 'Segoe UI', Inter, Helvetica, Arial, sans-serif"
TOKEN = os.environ.get("GITHUB_TOKEN")


def request(url, data=None):
    headers = {"User-Agent": "profile-cards", "Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"bearer {TOKEN}"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode()


def fetch_calendar(login):
    """Return [(date, count)] for the past year, oldest first."""
    if TOKEN:
        query = """query($login: String!) { user(login: $login) { contributionsCollection {
            contributionCalendar { weeks { contributionDays { date contributionCount } } } } } }"""
        body = json.dumps({"query": query, "variables": {"login": login}}).encode()
        weeks = json.loads(request("https://api.github.com/graphql", body))["data"]["user"][
            "contributionsCollection"]["contributionCalendar"]["weeks"]
        days = [(d["date"], d["contributionCount"]) for w in weeks for d in w["contributionDays"]]
    else:
        html = request(f"https://github.com/users/{login}/contributions")
        dates = dict(re.findall(r'data-date="([\d-]+)" id="(contribution-day-component-[\d-]+)"', html))
        ids = {v: k for k, v in dates.items()}
        days = []
        for cell, label in re.findall(r'for="(contribution-day-component-[\d-]+)"[^>]*>([^<]*)', html):
            m = re.match(r"(\d+) contribution", label)
            days.append((ids[cell], int(m.group(1)) if m else 0))
    return sorted((dt.date.fromisoformat(d), c) for d, c in days)


def fetch_repos(login):
    repos, page = [], 1
    while True:
        batch = json.loads(request(f"https://api.github.com/users/{login}/repos?per_page=100&page={page}&type=owner"))
        repos += [r for r in batch if not r["fork"]]
        if len(batch) < 100:
            return repos
        page += 1


def fetch_languages(repos):
    totals = {}
    for repo in repos:
        for name, size in json.loads(request(repo["languages_url"])).items():
            totals[name] = totals.get(name, 0) + size
    return sorted(totals.items(), key=lambda kv: -kv[1])


def streaks(days):
    longest = run = 0
    longest_end = None
    for day, count in days:
        run = run + 1 if count else 0
        if run > longest:
            longest, longest_end = run, day
    # Today being empty doesn't break the streak yet.
    tail = days[:-1] if days and days[-1][1] == 0 else days
    current = 0
    for _, count in reversed(tail):
        if not count:
            break
        current += 1
    return current, longest, longest_end


def fmt_date(day):
    return f"{day:%b} {day.day}"


def stats_card(days, languages, stars, repo_count):
    total = sum(c for _, c in days)
    current, longest, longest_end = streaks(days)
    best_day, best = max(days, key=lambda d: d[1])
    longest_range = (
        f"{fmt_date(longest_end - dt.timedelta(days=longest - 1))} – {fmt_date(longest_end)}" if longest else "—"
    )
    tiles = [
        (f"{total:,}", "contributions", f"{fmt_date(days[0][0])}, {days[0][0].year} – now", TEXT),
        (f"{current}", "day current streak", "keep it going" if current else "starting fresh", GOLD),
        (f"{longest}", "day longest streak", longest_range, TEXT),
        (f"{best}", "on my best day", fmt_date(best_day) + f", {best_day.year}", TEXT),
    ]

    width, pad, gap = 860, 28, 16
    tile_w = (width - 2 * pad - 3 * gap) / 4
    out = []
    for i, (value, label, sub, color) in enumerate(tiles):
        x = pad + i * (tile_w + gap)
        flame = ""
        if i == 1:
            # The CSS animation would override a transform attribute, so translate on an outer group.
            flame = (f'<g transform="translate({x + tile_w - 30:.1f} 116)"><g class="flame">'
                     f'<path d="M0 0 C-11 0 -14 -12 -6 -21 C-5 -15 -1 -14 0 -17 C1 -23 -1 -28 4 -32 '
                     f'C5 -24 13 -19 11 -8 C10 -3 6 0 0 0 Z" fill="{GOLD}"/>'
                     f'<path d="M0 0 C-5 0 -6 -6 -2 -10 C-1 -7 1 -7 2 -9 C5 -6 5 0 0 0 Z" fill="#fff4dc"/></g></g>')
        out.append(f"""
    <g class="in" style="animation-delay:{0.15 + i * 0.12:.2f}s">
      <rect x="{x:.1f}" y="58" width="{tile_w:.1f}" height="92" rx="10" fill="#161b22" stroke="{FAINT}"/>
      <text x="{x + 18:.1f}" y="100" font-size="32" font-weight="700" fill="{color}">{value}</text>
      <text x="{x + 18:.1f}" y="122" font-size="13" fill="{TEXT}">{escape(label)}</text>
      <text x="{x + 18:.1f}" y="139" font-size="11" fill="{MUTED}">{escape(sub)}</text>{flame}
    </g>""")

    top = languages[:6]
    rest = sum(s for _, s in languages[6:])
    if rest:
        top.append(("Other", rest))
    lang_total = sum(s for _, s in top) or 1
    bar_w = width - 2 * pad
    bar, legend, x, lx = [], [], pad, pad
    for i, (name, size) in enumerate(top):
        w = bar_w * size / lang_total
        bar.append(f'<rect x="{x:.1f}" y="190" width="{w:.1f}" height="10" fill="{LANG_SHADES[i]}"/>')
        x += w
        pct = f"{100 * size / lang_total:.1f}%"
        legend.append(f'<circle cx="{lx + 5}" cy="226" r="5" fill="{LANG_SHADES[i]}"/>'
                      f'<text x="{lx + 15}" y="230" font-size="12" fill="{TEXT}">{escape(name)} '
                      f'<tspan fill="{MUTED}">{pct}</tspan></text>')
        lx += 15 + 7.2 * (len(name) + len(pct) + 1) + 22

    updated = dt.date.today()
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="252" viewBox="0 0 {width} 252" role="img" aria-label="{total} contributions in the past year, current streak {current} days, longest streak {longest} days">
  <style>
    text {{ font-family: {FONT}; }}
    .in {{ opacity: 0; animation: in .5s ease-out forwards; }}
    @keyframes in {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: none; }} }}
    .flame {{ transform-box: fill-box; transform-origin: bottom center; animation: flick .9s ease-in-out infinite alternate; }}
    @keyframes flick {{ from {{ transform: scale(.9) rotate(-4deg); opacity: .75; }} to {{ transform: scale(1.08) rotate(3deg); opacity: 1; }} }}
    .grow {{ transform-box: fill-box; transform-origin: left center; animation: grow 1.2s .7s cubic-bezier(.2,.8,.2,1) both; }}
    @keyframes grow {{ from {{ transform: scaleX(0); }} to {{ transform: scaleX(1); }} }}
    @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; opacity: 1 !important; }} }}
  </style>
  <defs><clipPath id="bar"><rect x="{pad}" y="190" width="{bar_w}" height="10" rx="5"/></clipPath></defs>
  <rect x=".5" y=".5" width="{width - 1}" height="251" rx="12" fill="{BG}" stroke="{FAINT}"/>
  <text x="{pad}" y="38" font-size="15" font-weight="700" fill="{GOLD}">GitHub activity</text>
  <text x="{width - pad}" y="38" font-size="12" fill="{MUTED}" text-anchor="end">{repo_count} public repos · {stars} stars · updated {fmt_date(updated)}, {updated.year}</text>
  {"".join(out)}
  <text x="{pad}" y="179" font-size="12" fill="{MUTED}">most used languages</text>
  <g clip-path="url(#bar)"><g class="grow">{"".join(bar)}</g></g>
  <g class="in" style="animation-delay:1.3s">{"".join(legend)}</g>
</svg>
"""


def activity_card(days, window=60):
    days = days[-window:]
    width, height = 860, 270
    left, right, top, bottom = 52, 832, 66, 222
    peak = max(c for _, c in days)
    ceiling = max(4, -(-peak // 4) * 4)
    step = (right - left) / (len(days) - 1)

    def pt(i, c):
        return left + i * step, bottom - (bottom - top) * c / ceiling

    pts = [pt(i, c) for i, (_, c) in enumerate(days)]
    line = "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    area = f"{line} L{right} {bottom} L{left} {bottom} Z"

    grid = []
    for k in range(5):
        value = ceiling * k // 4
        y = bottom - (bottom - top) * k / 4
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{FAINT}" stroke-dasharray="{"0" if k == 0 else "3 4"}"/>'
                    f'<text x="{left - 10}" y="{y + 4:.1f}" font-size="11" fill="{MUTED}" text-anchor="end">{value}</text>')
    for i in range(0, len(days), 10):
        x, _ = pt(i, 0)
        grid.append(f'<text x="{x:.1f}" y="{bottom + 22}" font-size="11" fill="{MUTED}" text-anchor="middle">{fmt_date(days[i][0])}</text>')

    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{GOLD}"/>' for (x, y), (_, c) in zip(pts, days) if c
    )
    pi = max(range(len(days)), key=lambda i: days[i][1])
    px, py = pts[pi]
    anchor = "end" if px > width - 160 else "start"
    nudge = -10 if anchor == "end" else 10
    total = sum(c for _, c in days)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{total} contributions in the last {window} days, peaking at {peak} on {fmt_date(days[pi][0])}">
  <style>
    text {{ font-family: {FONT}; }}
    .line {{ stroke-dasharray: 1; stroke-dashoffset: 1; animation: draw 2.4s .3s cubic-bezier(.4,0,.2,1) forwards; }}
    @keyframes draw {{ to {{ stroke-dashoffset: 0; }} }}
    .fade {{ opacity: 0; animation: fade .8s ease-out forwards; }}
    @keyframes fade {{ to {{ opacity: 1; }} }}
    .ping {{ transform-box: fill-box; transform-origin: center; animation: ping 2s 2.8s ease-out infinite; opacity: 0; }}
    @keyframes ping {{ 0% {{ transform: scale(1); opacity: .6; }} 100% {{ transform: scale(3.2); opacity: 0; }} }}
    @media (prefers-reduced-motion: reduce) {{ .line {{ animation: none; stroke-dashoffset: 0; }} .fade {{ animation: none; opacity: 1; }} .ping {{ display: none; }} }}
  </style>
  <defs>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{GOLD}" stop-opacity=".35"/>
      <stop offset="1" stop-color="{GOLD}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="12" fill="{BG}" stroke="{FAINT}"/>
  <text x="28" y="38" font-size="15" font-weight="700" fill="{GOLD}">Contribution activity</text>
  <text x="{width - 28}" y="38" font-size="12" fill="{MUTED}" text-anchor="end">{total} contributions · last {window} days</text>
  {"".join(grid)}
  <path class="fade" style="animation-delay:1.6s" d="{area}" fill="url(#area)"/>
  <path class="line" d="{line}" pathLength="1" fill="none" stroke="{GOLD}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
  <g class="fade" style="animation-delay:2.2s">{dots}
    <text x="{px + nudge:.1f}" y="{max(py - 10, top - 6):.1f}" font-size="12" font-weight="700" fill="{TEXT}" text-anchor="{anchor}">{peak} on {fmt_date(days[pi][0])}</text>
  </g>
  <circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{GOLD}" class="fade" style="animation-delay:2.4s"/>
  <circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{GOLD}" class="ping"/>
</svg>
"""


DROID = [  # pixel sprite, 12 x 14, facing right
    ".....GG.....",
    ".....WW.....",
    "..WWWWWWWW..",
    ".WDDDDDDDDW.",
    ".WDKKKKKKDW.",
    ".WDKKGKKGDW.",
    ".WDKKGKKGDW.",
    ".WDKKKKKKDW.",
    ".WDDDDDDDDW.",
    "..WWWWWWWW..",
    "...WDGGDW...",
    "..WWDDDDWW..",
    "...WDDDDW...",
    "...WWWWWW...",
]
DROID_LEGS = ["...W....W...", "....W..W...."]
BUG = [".R....R.", "..RRRR..", ".RWRRWR.", "RRRRRRRR", "RRRRRRRR"]
BUG_LEGS = ["R.R..R.R", ".R.RR.R."]
PIXEL = {"W": TEXT, "D": "#161b22", "K": BG, "G": GOLD, "R": "#f85149"}


def sprite(rows, x=0, y=0, scale=2):
    """Pixel rows -> rects, merging horizontal runs of one colour."""
    out = []
    for r, row in enumerate(rows):
        c = 0
        while c < len(row):
            ch, start = row[c], c
            while c < len(row) and row[c] == ch:
                c += 1
            if ch != ".":
                out.append(f'<rect x="{x + start * scale}" y="{y + r * scale}" width="{(c - start) * scale}" '
                           f'height="{scale}" fill="{PIXEL[ch]}"/>')
    return "".join(out)


def keyframes(name, frames):
    return f"@keyframes {name} {{ " + " ".join(f"{p:.2f}% {{ {css} }}" for p, css in frames) + " }"


def platformer_card(days):
    """A pixel droid runs through the last 12 months, bumping a block per month and stomping bugs."""
    months = {}
    for day, count in days:
        months[(day.year, day.month)] = months.get((day.year, day.month), 0) + count
    months = sorted(months.items())[-12:]

    width, height, ground = 860, 256, 206
    cycle, run_end = 18, 82.0  # seconds per loop, % of the loop spent running
    x0, x1 = 16, 790  # droid's left edge at start / finish
    first, last = 92, 732
    centers = [first + i * (last - first) / (len(months) - 1) for i in range(len(months))]

    def at(cx):  # loop % when the droid's centre passes cx
        return (cx - 18 - x0) / (x1 - x0) * run_end

    half = 1.4  # % of the loop for half a jump
    jumps, css, blocks, bugs = [], [], [], []

    for i, (((year, month), count), cx) in enumerate(zip(months, centers)):
        label = dt.date(year, month, 1).strftime("%b")
        bx = cx - 12
        blocks.append(f'<text x="{cx:.1f}" y="{ground + 30}" font-size="11" fill="{MUTED}" text-anchor="middle">{label}</text>')
        if not count:  # empty month: a plain brick, nothing to hit
            blocks.append(f'<g><rect x="{bx:.1f}" y="98" width="24" height="24" fill="#21262d" stroke="{FAINT}"/>'
                          f'<path d="M{bx:.1f} 110 h24 M{bx + 12:.1f} 98 v12 M{bx + 6:.1f} 110 v12 M{bx + 18:.1f} 110 v12" stroke="{FAINT}"/></g>')
            continue
        p = at(cx)
        jumps.append((p, 36))
        css.append(keyframes(f"bump{i}", [(0, "transform: translateY(0)"), (p, "transform: translateY(0)"),
                                          (p + .8, "transform: translateY(-8px)"), (p + 1.8, "transform: translateY(0)"),
                                          (100, "transform: translateY(0)")]))
        css.append(keyframes(f"used{i}", [(0, "opacity: 0"), (p, "opacity: 0"), (p + .3, "opacity: 1"),
                                          (95, "opacity: 1"), (97, "opacity: 0"), (100, "opacity: 0")]))
        css.append(keyframes(f"coin{i}", [(0, "opacity: 0; transform: translateY(0)"),
                                          (p, "opacity: 0; transform: translateY(0)"),
                                          (p + .5, "opacity: 1; transform: translateY(-4px)"),
                                          (p + 7, "opacity: 0; transform: translateY(-34px)"),
                                          (100, "opacity: 0; transform: translateY(-34px)")]))
        blocks.append(f"""
    <g style="animation-name: bump{i}">
      <rect x="{bx:.1f}" y="98" width="24" height="24" rx="3" fill="{GOLD}" stroke="#8a6d3b" stroke-width="2"/>
      <text x="{cx:.1f}" y="116" font-size="15" font-weight="800" fill="#5c4520" text-anchor="middle" font-family="ui-monospace, Menlo, Consolas, monospace">?</text>
      <g style="animation-name: used{i}"><rect x="{bx:.1f}" y="98" width="24" height="24" rx="3" fill="#4a3c22" stroke="#8a6d3b" stroke-width="2"/>
        <rect x="{bx + 4:.1f}" y="102" width="3" height="3" fill="#8a6d3b"/><rect x="{bx + 17:.1f}" y="102" width="3" height="3" fill="#8a6d3b"/></g>
    </g>
    <text style="animation-name: coin{i}" x="{cx:.1f}" y="90" font-size="13" font-weight="800" fill="{GOLD}" text-anchor="middle">+{count}</text>""")

    for n, gap in enumerate((2, 6, 9)):  # bugs sit between blocks
        mx = (centers[gap] + centers[gap + 1]) / 2
        p = at(mx)
        jumps.append((p, 34))
        hit = p + half * .75
        css.append(keyframes(f"squash{n}", [(0, "transform: scaleY(1); opacity: 1"), (hit, "transform: scaleY(1); opacity: 1"),
                                            (hit + .3, "transform: scaleY(.25); opacity: 1"), (hit + 3, "transform: scaleY(.25); opacity: 1"),
                                            (hit + 4, "transform: scaleY(.25); opacity: 0"), (96, "transform: scaleY(.25); opacity: 0"),
                                            (97, "transform: scaleY(1); opacity: 1"), (100, "transform: scaleY(1); opacity: 1")]))
        css.append(keyframes(f"pop{n}", [(0, "opacity: 0; transform: translateY(0)"), (hit, "opacity: 0; transform: translateY(0)"),
                                         (hit + .4, "opacity: 1; transform: translateY(-6px)"),
                                         (hit + 6, "opacity: 0; transform: translateY(-26px)"),
                                         (100, "opacity: 0; transform: translateY(-26px)")]))
        bx = mx - 12
        bugs.append(f"""
    <g class="squash" style="animation-name: squash{n}"><g class="crawl" style="animation-delay: -{n * .2:.1f}s">
      {sprite(BUG, bx, ground - 21, 3)}
      <g class="legA">{sprite([BUG_LEGS[0]] * 2, bx, ground - 6, 3)}</g><g class="legB">{sprite([BUG_LEGS[1]] * 2, bx, ground - 6, 3)}</g>
    </g></g>
    <text style="animation-name: pop{n}" x="{mx:.1f}" y="{ground - 30}" font-size="12" font-weight="800" fill="#f85149" text-anchor="middle">squashed!</text>""")

    jumps.append((run_end + 2.5, 20))  # victory hop at the flag
    hop = [(0, "transform: translateY(0)")]
    for p, h in sorted(jumps):
        hop += [(p - half, "transform: translateY(0); animation-timing-function: cubic-bezier(.2,.7,.4,1)"),
                (p, f"transform: translateY(-{h}px); animation-timing-function: cubic-bezier(.6,0,.8,.3)"),
                (p + half, "transform: translateY(0)")]
    hop.append((100, "transform: translateY(0)"))
    css.append(keyframes("hop", hop))
    css.append(keyframes("run", [(0, f"transform: translateX({x0}px)"), (run_end, f"transform: translateX({x1}px)"),
                                 (100, f"transform: translateX({x1}px)")]))
    css.append(keyframes("show", [(0, "opacity: 0"), (1.5, "opacity: 1"), (93, "opacity: 1"), (96, "opacity: 0"), (100, "opacity: 0")]))
    css.append(keyframes("flag", [(0, "transform: translateY(0)"), (run_end + .5, "transform: translateY(0)"),
                                  (run_end + 4, "transform: translateY(-70px)"), (95, "transform: translateY(-70px)"),
                                  (97, "transform: translateY(0)"), (100, "transform: translateY(0)")]))
    css.append(keyframes("cheer", [(0, "opacity: 0"), (run_end + 3, "opacity: 0"), (run_end + 5, "opacity: 1"),
                                   (94, "opacity: 1"), (96, "opacity: 0"), (100, "opacity: 0")]))

    rng = random.Random(7)
    stars = "".join(
        f'<rect class="star" x="{rng.randint(20, 840)}" y="{rng.randint(50, 150)}" width="2" height="2" fill="{TEXT}" '
        f'style="animation-delay: -{rng.random() * 3:.2f}s"/>' for _ in range(26))
    bricks = "".join(
        f'<rect x="{x}" y="{ground + (r * 10)}" width="20" height="10" fill="#1c1f26" stroke="{FAINT}"/>'
        for r in range(4) for x in range(-10 + (r % 2) * 10, width, 20))
    total = sum(c for _, c in months)
    pole = width - 26

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="Pixel droid platformer: {total} contributions over the last 12 months, one block per month">
  <style>
    text {{ font-family: {FONT}; }}
    g[style*="animation-name"], text[style*="animation-name"] {{ animation-duration: {cycle}s; animation-timing-function: linear; animation-iteration-count: infinite; }}
    .run {{ animation: run {cycle}s linear infinite, show {cycle}s linear infinite; }}
    .hop {{ animation: hop {cycle}s linear infinite; }}
    .squash {{ transform-box: fill-box; transform-origin: bottom center; }}
    .legA {{ animation: legA .28s step-end infinite; }}
    .legB {{ animation: legB .28s step-end infinite; }}
    @keyframes legA {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0; }} }}
    @keyframes legB {{ 0% {{ opacity: 0; }} 50% {{ opacity: 1; }} }}
    .crawl {{ animation: crawl 1.2s ease-in-out infinite alternate; }}
    @keyframes crawl {{ from {{ transform: translateX(-5px); }} to {{ transform: translateX(5px); }} }}
    .star {{ animation: twinkle 3s ease-in-out infinite; }}
    @keyframes twinkle {{ 0%, 100% {{ opacity: .15; }} 50% {{ opacity: .8; }} }}
    {chr(10).join("    " + c for c in css)}
    @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}
  </style>
  <defs><clipPath id="card"><rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="12"/></clipPath></defs>
  <g clip-path="url(#card)">
    <rect width="{width}" height="{height}" fill="{BG}"/>
    {stars}
    {bricks}
    <line x1="0" y1="{ground}" x2="{width}" y2="{ground}" stroke="#8a6d3b" stroke-width="2"/>
  </g>
  <rect x=".5" y=".5" width="{width - 1}" height="{height - 1}" rx="12" fill="none" stroke="{FAINT}"/>
  <text x="28" y="34" font-size="15" font-weight="700" fill="{GOLD}">Contribution run</text>
  <text x="{width - 28}" y="34" font-size="12" fill="{MUTED}" text-anchor="end">{total} contributions · last 12 months · 3 bugs squashed</text>
  {"".join(blocks)}
  {"".join(bugs)}
  <rect x="{pole - 1}" y="70" width="3" height="{ground - 70}" fill="{TEXT}"/>
  <circle cx="{pole + .5}" cy="68" r="4" fill="{GOLD}"/>
  <g style="animation-name: flag"><path d="M{pole + 2} 146 l22 8 l-22 8 z" fill="{GOLD}"/></g>
  <text style="animation-name: cheer" x="{pole - 10}" y="62" font-size="12" font-weight="800" fill="{GOLD}" text-anchor="end">shipped!</text>
  <g class="run"><g class="hop">
    {sprite(DROID, 0, ground - 48, 3)}
    <g class="legA">{sprite([DROID_LEGS[0]] * 2, 0, ground - 6, 3)}</g><g class="legB">{sprite([DROID_LEGS[1]] * 2, 0, ground - 6, 3)}</g>
  </g></g>
</svg>
"""


def main():
    login, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    days = fetch_calendar(login)
    repos = fetch_repos(login)
    stars = sum(r["stargazers_count"] for r in repos)
    cards = {
        "stats.svg": stats_card(days, fetch_languages(repos), stars, len(repos)),
        "activity.svg": activity_card(days),
        "run.svg": platformer_card(days),
    }
    for name, svg in cards.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(svg)
        print("wrote", name)


if __name__ == "__main__":
    main()
