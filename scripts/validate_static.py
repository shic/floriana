#!/usr/bin/env python3
"""Validate the generated static export before deploying to GitHub Pages."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
HOST = "florianacelani.com"

DYNAMIC_PATTERNS = (
    "wp-admin/admin-ajax.php",
    "wp-admin\\/admin-ajax.php",
    "wp-json",
    "xmlrpc.php",
)

URL_ATTR_RE = re.compile(
    r"""(?:href|src|action|data-bg|data-src|data-orig-src|content)=["']([^"']+)["']""",
    re.IGNORECASE,
)
SRCSET_RE = re.compile(r"""(?:srcset|data-srcset)=["']([^"']+)["']""", re.IGNORECASE)
CSS_URL_RE = re.compile(r"url\(([^)]+)\)", re.IGNORECASE)


def iter_text_files() -> list[Path]:
    suffixes = {".css", ".html", ".js", ".json", ".svg", ".txt", ".xml"}
    return [
        path
        for path in PUBLIC.rglob("*")
        if path.is_file() and (path.suffix.lower() in suffixes or path.name == "CNAME")
    ]


def local_file_for_path(path: str) -> Path:
    if path == "/":
        return PUBLIC / "index.html"
    target = PUBLIC / path.lstrip("/")
    if path.endswith("/") or not target.suffix:
        target = target / "index.html"
    return target


def is_local_url(url: str) -> bool:
    if not url or url.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
        return False
    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"} and parsed.netloc != HOST:
        return False
    if parsed.netloc and parsed.netloc != HOST:
        return False
    return parsed.path.startswith("/")


def should_check_file(path: str) -> bool:
    if path.startswith(("/wp-admin/", "/wp-json", "/xmlrpc.php", "/feed", "/comments/feed")):
        return False
    if path in {"/static-noop.json"}:
        return True
    if "." in Path(path).name:
        return True
    return True


def collect_urls(text: str) -> set[str]:
    urls: set[str] = set()
    for match in URL_ATTR_RE.finditer(text):
        urls.add(match.group(1))
    for match in SRCSET_RE.finditer(text):
        for candidate in match.group(1).split(","):
            src = candidate.strip().split(" ")[0]
            if src:
                urls.add(src)
    for match in CSS_URL_RE.finditer(text):
        urls.add(match.group(1).strip().strip("\"'"))
    return urls


def validate_files() -> list[str]:
    errors: list[str] = []
    if not (PUBLIC / "index.html").exists():
        errors.append("missing public/index.html")
    if not (PUBLIC / ".nojekyll").exists():
        errors.append("missing public/.nojekyll")
    if (PUBLIC / "CNAME").read_text(encoding="utf-8", errors="replace").strip() != HOST:
        errors.append("public/CNAME must contain florianacelani.com")

    for path in iter_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(PUBLIC)
        for pattern in DYNAMIC_PATTERNS:
            if pattern in text:
                errors.append(f"{rel}: dynamic WordPress endpoint left in text: {pattern}")
        if "florianacelani.com/wp-" in text or "florianacelani.com\\/wp-" in text:
            errors.append(f"{rel}: absolute WordPress asset/API URL left in text")
        for url in collect_urls(text):
            if not is_local_url(url):
                continue
            parsed = urlparse(url)
            if not should_check_file(parsed.path):
                continue
            target = local_file_for_path(parsed.path)
            if not target.exists():
                errors.append(f"{rel}: missing local target {parsed.path}")
    return sorted(set(errors))


def http_check(base_url: str, paths: list[str]) -> list[str]:
    errors: list[str] = []
    for path in paths:
        url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
        request = Request(url, headers={"User-Agent": "floriana-static-validate/1.0"})
        try:
            with urlopen(request, timeout=15) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    errors.append(f"{url}: HTTP {status}")
        except Exception as exc:  # noqa: BLE001 - report all URL failures.
            errors.append(f"{url}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", help="Optional local preview URL to probe.")
    args = parser.parse_args()

    errors = validate_files()
    if args.base_url:
        errors.extend(
            http_check(
                args.base_url,
                [
                    "/",
                    "/opere/",
                    "/opere/page/2/",
                    "/about/",
                    "/contact/",
                    "/portfolio-item/7-elementi/",
                    "/assets/floriana-static.js",
                ],
            )
        )

    if errors:
        print("Static validation failed:", file=sys.stderr)
        for error in errors[:200]:
            print(f"- {error}", file=sys.stderr)
        if len(errors) > 200:
            print(f"- ... {len(errors) - 200} more", file=sys.stderr)
        return 1
    print("Static validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
