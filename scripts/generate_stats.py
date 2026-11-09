#!/usr/bin/env python3
"""Generate fully static, self-hosted SVG stat cards for a GitHub profile README.

Why this exists
---------------
Dynamic cards served by third-party renderers (github-readme-stats,
github-profile-summary-cards, ...) depend on someone else's Vercel deployment
and on a shared GitHub API quota. When the deployment is down, rate limited or
blocked by a network proxy, the README images break.

This script reads public data from the GitHub REST API and writes plain SVG
files into this repository. The README then points at those files on
raw.githubusercontent.com, so the images are served by GitHub itself and stay
visible even if this script ever fails to run: the last committed SVG remains.

Usage:
    python scripts/generate_stats.py --out assets

Environment:
    STATS_USERNAME   GitHub username (default: YanQuan-dozzy)
    GITHUB_TOKEN     optional; raises the API rate limit (used in Actions)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import escape as esc

API = "https://api.github.com"
USERNAME = os.environ.get("STATS_USERNAME", "YanQuan-dozzy")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
FONT = "Verdana,Geneva,DejaVu Sans,sans-serif"

THEMES = {
    "light": {
        "bg": "#ffffff", "title": "#028f7a", "text": "#24292f",
        "muted": "#57606a", "track": "#eaeef2", "accent": "#03c9a9",
        "line": "#d0d7de",
    },
    "dark": {
        "bg": "#0d1117", "title": "#03c9a9", "text": "#c9d1d9",
        "muted": "#8b949e", "track": "#21262d", "accent": "#03c9a9",
        "line": "#30363d",
    },
}

LANG_COLORS = {
    "TypeScript": "#3178c6", "JavaScript": "#f1e05a", "Python": "#3572A5",
    "Java": "#b07219", "PHP": "#4F5D95", "C": "#555555", "C++": "#f34b7d",
    "C#": "#178600", "Go": "#00ADD8", "Rust": "#dea584", "Ruby": "#701516",
    "Shell": "#89e051", "HTML": "#e34c26", "CSS": "#563d7c", "Vue": "#41b883",
    "Kotlin": "#A97BFF", "Swift": "#F05138", "Dart": "#00B4AB",
    "Jupyter Notebook": "#DA5B0B", "PowerShell": "#012456", "Lua": "#000080",
    "Assembly": "#33AA00", "Other": "#8b949e",
}


def api(path, params=None, extra_headers=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "profile-static-stats-generator",
    }
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def search_count(query, extra_headers=None):
    """Total count of a search query; returns None on failure (optional metric)."""
    try:
        return api("/search/issues", {"q": query, "per_page": 1}, extra_headers)["total_count"]
    except Exception as exc:  # noqa: BLE001 - a missing optional metric must not break the cards
        print("optional metric unavailable (%s): %s" % (query, exc), file=sys.stderr)
        return None


def fetch_data():
    user = api("/users/" + USERNAME)

    repos = []
    for page in range(1, 11):
        batch = api("/users/" + USERNAME + "/repos",
                    {"type": "owner", "per_page": 100, "page": page})
        repos.extend(batch)
        if len(batch) < 100:
            break

    own = [r for r in repos if not r.get("fork")]
    stars = sum(r.get("stargazers_count", 0) or 0 for r in own)
    forks = sum(r.get("forks_count", 0) or 0 for r in own)

    # Size (KB) is used as a lightweight proxy for language bytes, avoiding
    # one extra /languages request per repository (and its rate-limit cost).
    lang_sizes = {}
    for r in own:
        lang = r.get("language") or "Other"
        lang_sizes[lang] = lang_sizes.get(lang, 0) + max(r.get("size", 0) or 0, 1)
    total_size = sum(lang_sizes.values()) or 1
    languages = sorted(
        ((name, size, size * 100.0 / total_size) for name, size in lang_sizes.items()),
        key=lambda item: item[1], reverse=True,
    )[:5]

    prs = search_count("author:%s type:pr" % USERNAME)
    issues = search_count("author:%s type:issue" % USERNAME)
    commits = None
    try:
        commits = api("/search/commits", {"q": "author:" + USERNAME, "per_page": 1},
                      {"Accept": "application/vnd.github+json"})["total_count"]
    except Exception as exc:  # noqa: BLE001
        print("commits metric unavailable: %s" % exc, file=sys.stderr)

    return {
        "user": user,
        "username": user.get("login", USERNAME),
        "repos": len(own),
        "public_repos": user.get("public_repos", len(own)),
        "stars": stars,
        "forks": forks,
        "followers": user.get("followers", 0),
        "following": user.get("following", 0),
        "gists": user.get("public_gists", 0),
        "prs": prs,
        "issues": issues,
        "commits": commits,
        "languages": languages,
        "created_at": (user.get("created_at") or "")[:10],
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def header(width, height, theme, label):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" role="img" aria-label="%s">\n'
        '<rect x="0" y="0" width="%d" height="%d" rx="8" fill="%s"/>\n'
        % (width, height, width, height, esc(label, quote=True),
           width, height, theme["bg"])
    )


def title(text, theme, width):
    return (
        '<text x="22" y="31" font-family="%s" font-size="17" font-weight="700" '
        'fill="%s">%s</text>\n'
        '<line x1="22" y1="42" x2="%d" y2="42" stroke="%s" stroke-width="1"/>\n'
        % (FONT, theme["title"], esc(text), width - 22, theme["line"])
    )


def footer(text, theme, y, width):
    return (
        '<text x="%d" y="%d" text-anchor="end" font-family="%s" font-size="9" '
        'fill="%s">%s</text>\n'
        % (width - 22, y, FONT, theme["muted"], esc(text))
    )


def fmt(value):
    return "n/a" if value is None else "{:,}".format(value)


def svg_stats(data, theme):
    w, h = 480, 180
    items = [
        ("Total Stars Earned", data["stars"]),
        ("Total Forks", data["forks"]),
        ("Public Repos", data["public_repos"]),
        ("Followers", data["followers"]),
        ("Pull Requests", data["prs"]),
        ("Issues", data["issues"]),
    ]
    out = [header(w, h, theme, "%s's GitHub Stats" % data["username"]),
           title("%s's GitHub Stats" % data["username"], theme, w)]
    for i, (label, value) in enumerate(items):
        col, row = i % 2, i // 2
        x = 24 + col * 230
        y = 72 + row * 32
        out.append(
            '<text x="%d" y="%d" font-family="%s" font-size="11" fill="%s">%s</text>\n'
            '<text x="%d" y="%d" text-anchor="end" font-family="%s" font-size="13" '
            'font-weight="700" fill="%s">%s</text>\n'
            % (x, y, FONT, theme["muted"], esc(label),
               x + 200, y, FONT, theme["text"], fmt(value))
        )
    out.append(footer("static SVG - updated " + data["updated"], theme, 170, w))
    out.append("</svg>\n")
    return "".join(out)


def svg_langs(data, theme):
    w, h = 320, 180
    out = [header(w, h, theme, "Top Languages"), title("Top Languages", theme, w)]
    langs = data["languages"]
    if not langs:
        out.append('<text x="22" y="80" font-family="%s" font-size="12" fill="%s">No language data</text>\n'
                   % (FONT, theme["muted"]))
    for i, (name, _size, pct) in enumerate(langs):
        y = 58 + i * 23
        color = LANG_COLORS.get(name, theme["accent"])
        bar_w = max(3, round(276 * pct / 100.0))
        pct_text = "<0.1%" if pct < 0.1 else "%.1f%%" % pct
        out.append(
            '<text x="22" y="%d" font-family="%s" font-size="11" fill="%s">%s</text>\n'
            '<text x="%d" y="%d" text-anchor="end" font-family="%s" font-size="10" '
            'fill="%s">%s</text>\n'
            '<rect x="22" y="%d" width="276" height="6" rx="3" fill="%s"/>\n'
            '<rect x="22" y="%d" width="%d" height="6" rx="3" fill="%s"/>\n'
            % (y + 1, FONT, theme["text"], esc(name),
               w - 22, y + 1, FONT, theme["muted"], esc(pct_text),
               y + 7, theme["track"],
               y + 7, bar_w, color)
        )
    out.append(footer("static SVG - updated " + data["updated"], theme, 170, w))
    out.append("</svg>\n")
    return "".join(out)


def svg_profile(data, theme):
    w, h = 700, 165
    items = [
        ("Followers", data["followers"]),
        ("Public Repos", data["public_repos"]),
        ("Total Stars", data["stars"]),
        ("Pull Requests", data["prs"]),
        ("Issues", data["issues"]),
    ]
    out = [header(w, h, theme, "Profile Snapshot"), title("Profile Snapshot", theme, w)]
    slot = (w - 44) / len(items)
    for i, (label, value) in enumerate(items):
        cx = 22 + slot * (i + 0.5)
        if i:
            out.append('<line x1="%.1f" y1="62" x2="%.1f" y2="118" stroke="%s" stroke-width="1"/>\n'
                       % (22 + slot * i, 22 + slot * i, theme["line"]))
        out.append(
            '<text x="%.1f" y="90" text-anchor="middle" font-family="%s" font-size="19" '
            'font-weight="700" fill="%s">%s</text>\n'
            '<text x="%.1f" y="112" text-anchor="middle" font-family="%s" font-size="10" '
            'fill="%s">%s</text>\n'
            % (cx, FONT, theme["accent"], fmt(value),
               cx, FONT, theme["muted"], esc(label))
        )
    note = "Member since %s" % (data["created_at"] or "—")
    if data["commits"] is not None:
        note += "  |  %s commits" % fmt(data["commits"])
    out.append('<text x="22" y="145" font-family="%s" font-size="10" fill="%s">%s</text>\n'
               % (FONT, theme["muted"], esc(note)))
    out.append(footer("static SVG - updated " + data["updated"], theme, 145, w))
    out.append("</svg>\n")
    return "".join(out)


def build_all(data):
    files = {}
    for name, theme in THEMES.items():
        files["github-stats-%s.svg" % name] = svg_stats(data, theme)
        files["top-langs-%s.svg" % name] = svg_langs(data, theme)
        files["profile-details-%s.svg" % name] = svg_profile(data, theme)
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="assets", help="output directory for SVG files")
    args = parser.parse_args()

    # Fetch and render everything in memory first. If any API call fails, the
    # script exits without touching the existing SVGs (previous good cards stay).
    data = fetch_data()
    files = build_all(data)
    os.makedirs(args.out, exist_ok=True)
    for name, content in sorted(files.items()):
        with open(os.path.join(args.out, name), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        print("wrote %s (%d bytes)" % (os.path.join(args.out, name), len(content)))
    print("stats: repos=%d stars=%d forks=%d followers=%d prs=%s issues=%s" % (
        data["repos"], data["stars"], data["forks"], data["followers"],
        fmt(data["prs"]), fmt(data["issues"])))


if __name__ == "__main__":
    main()
