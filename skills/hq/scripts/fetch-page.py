#!/usr/bin/env python3
"""Fetch a public web page through curl and print its title and plain text. Read-only.

  fetch-page.py <URL> [max chars, default 6000]

Why: in cloud sessions with a limited network policy, the host's built-in fetch tool (e.g. WebFetch) may not go
through the session's HTTPS proxy and fails to resolve hosts that curl can reach. Research sub-sessions open
sources with this script instead. Exit codes: 0 fetched (HTTP < 400 and some text), 1 empty or HTTP error,
2 bad arguments, 3 network failure (curl could not connect).
"""
import html
import re
import subprocess
import sys

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def extract(raw):
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    body = re.sub(r"<(script|style|noscript|template)[^>]*>.*?</\1>", " ", raw, flags=re.S | re.I)
    body = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>|</li>", "\n", body, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    # navigation menus become runs of very short lines; drop them so the article text fits the limit
    text = "\n".join(l.strip() for l in text.split("\n") if len(l.strip()) >= 8).strip()
    return (html.unescape(title.group(1)).strip() if title else ""), text


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or not re.match(r"^https?://", argv[0]):
        print("用法: fetch-page.py <http(s) URL> [最多字符数]", file=sys.stderr)
        return 2
    url, limit = argv[0], int(argv[1]) if len(argv) > 1 else 6000
    r = subprocess.run(["curl", "-sL", "--compressed", "-m", "25", "-A", UA, "--noproxy", "127.0.0.1,localhost",
                        "-w", "\n__HQ_META__%{url_effective} %{http_code}", url], capture_output=True)
    out = r.stdout.decode("utf-8", "replace")
    m = re.search(r"\n__HQ_META__(\S+) (\d+)\s*$", out)
    final, code = (m.group(1), int(m.group(2))) if m else (url, 0)
    raw = out[:m.start()] if m else out
    if code == 0:
        print("URL: %s | 连不上（网络策略拒绝或域名解析失败）" % url)
        return 3
    title, text = extract(raw)
    print("URL: %s | HTTP: %d" % (final, code))
    print("TITLE: %s" % title)
    print("TEXT: %s" % (text[:limit] if text else "(空：可能需要 JavaScript 渲染，或站点拒绝访问；不能当来源)"))
    return 0 if code < 400 and text else 1


if __name__ == "__main__":
    sys.exit(main())
