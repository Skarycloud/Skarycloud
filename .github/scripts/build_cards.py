"""Render the profile's stats and activity cards as animated SVGs.

Usage: python build_cards.py <github-login> <output-dir>

Uses GITHUB_TOKEN (GraphQL) when set; otherwise falls back to the public
contribution calendar page and the unauthenticated REST API, which is
handy for previewing locally.
"""

import datetime as dt
import json
import os
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


def main():
    login, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)
    days = fetch_calendar(login)
    repos = fetch_repos(login)
    stars = sum(r["stargazers_count"] for r in repos)
    cards = {
        "stats.svg": stats_card(days, fetch_languages(repos), stars, len(repos)),
        "activity.svg": activity_card(days),
    }
    for name, svg in cards.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(svg)
        print("wrote", name)


if __name__ == "__main__":
    main()
