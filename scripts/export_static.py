#!/usr/bin/env python3
"""Export florianacelani.com from WordPress HTML into a GitHub Pages bundle."""

from __future__ import annotations

import html
import os
import re
import shutil
import sys
import time
from collections import deque
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


SITE = "https://florianacelani.com"
HOST = "florianacelani.com"
ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
STATIC_ASSET = "/assets/floriana-static.js"
NOOP_ENDPOINT = "/static-noop.json"
CONTACT_EMAIL = "celanifloriana@gmail.com"
KNOWN_REDIRECTS = {
    "/portfolio-item/valerie-dicker/": "/opere/",
}
STATIC_SEED_ASSETS = (
    SITE + "/wp-content/plugins/revslider/public/css/preloaders/t2.css",
    SITE + "/wp-content/plugins/revslider/public/css/sr7.btns.css",
    SITE + "/wp-content/plugins/revslider/public/css/sr7.lp.css",
    SITE + "/wp-content/plugins/revslider/public/css/sr7.media.css",
)

USER_AGENT = "floriana-static-export/1.0 (+https://github.com/)"
MAX_PAGES = 300
MAX_ASSETS = 2500

SKIP_PATH_PREFIXES = (
    "/wp-admin",
    "/wp-json",
    "/xmlrpc.php",
    "/wp-login.php",
    "/wp-cron.php",
    "/feed",
    "/comments/feed",
)

ASSET_EXTENSIONS = {
    ".avif",
    ".css",
    ".eot",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".map",
    ".mp4",
    ".otf",
    ".pdf",
    ".png",
    ".svg",
    ".ttf",
    ".txt",
    ".webmanifest",
    ".webp",
    ".woff",
    ".woff2",
    ".xml",
}

SAME_DOMAIN_RE = re.compile(
    r"(?:(?:https?:)?//florianacelani\.com)(/[^\s\"'<>)]+)?",
    re.IGNORECASE,
)
ESCAPED_DOMAIN_RE = re.compile(
    r"https?:\\?/\\?/florianacelani\.com((?:\\?/[^\"'\\\s<>)]+)?)",
    re.IGNORECASE,
)
ROOT_RELATIVE_RE = re.compile(
    r"""(?:href|src|action|data-bg|data-src|data-orig-src|content)=["'](/[^"']+)["']""",
    re.IGNORECASE,
)
SRCSET_RE = re.compile(r"""(?:srcset|data-srcset)=["']([^"']+)["']""", re.IGNORECASE)
CSS_URL_RE = re.compile(r"url\(([^)]+)\)", re.IGNORECASE)


def normalize_url(url: str, base: str = SITE + "/") -> str | None:
    url = html.unescape(url).strip().strip("\"'")
    url = url.replace("\\/", "/")
    lower_url = url.lower()
    if "${" in url or "<svg" in lower_url or "%3csvg" in lower_url:
        return None
    if not url or url.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
        return None
    if url.startswith("//"):
        url = "https:" + url
    url = urljoin(base, url)
    parsed = urlparse(url)
    if parsed.netloc.lower() != HOST:
        return None
    path = quote(unquote(parsed.path or "/"), safe="/%._-~()!$,;:@&+=")
    query = parsed.query.replace("&amp;", "&")
    return urlunparse(("https", HOST, path, "", query, ""))


def should_skip_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or "/"
    suffix = Path(path).suffix.lower()
    lower_path = path.lower()
    if "${" in path or "%7b" in lower_path or "<svg" in lower_path or "%3csvg" in lower_path:
        return True
    if path in {"/wp-content", "/wp-content/", "/wp-includes", "/wp-includes/"}:
        return True
    if path.startswith(("/wp-content/", "/wp-includes/")) and not suffix:
        return True
    if path.endswith("/feed/") or path.endswith("/feed"):
        return True
    if any(path == prefix or path.startswith(prefix + "/") for prefix in SKIP_PATH_PREFIXES):
        return True
    if parsed.query:
        query_keys = {key for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        if query_keys & {"p", "page_id", "attachment_id", "preview"}:
            return True
    return False


def is_asset_url(url: str) -> bool:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if path.endswith("/") or (path.startswith(("/wp-content", "/wp-includes")) and not suffix):
        return False
    if suffix in ASSET_EXTENSIONS:
        return True
    return path.startswith(("/wp-content/", "/wp-includes/"))


def local_path_for_url(url: str, *, asset: bool = False) -> Path:
    parsed = urlparse(url)
    path = unquote(parsed.path or "/")
    if not asset and (path.endswith("/") or "." not in Path(path).name):
        path = path.rstrip("/") + "/index.html"
    elif asset and path.endswith("/"):
        path = path.rstrip("/") + "/index.html"
    elif not path or path == "/":
        path = "/index.html"
    return PUBLIC / path.lstrip("/")


def fetch(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                content_type = response.headers.get("content-type", "")
                return response.read(), content_type
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if isinstance(exc, HTTPError) and exc.code in {404, 410}:
                raise
            time.sleep(0.5 * (attempt + 1))
    assert last_error is not None
    raise last_error


def extract_sitemap_urls() -> set[str]:
    urls: set[str] = {SITE + "/"}
    queue: deque[str] = deque([SITE + "/wp-sitemap.xml"])
    seen: set[str] = set()

    while queue:
        sitemap = queue.popleft()
        if sitemap in seen:
            continue
        seen.add(sitemap)
        try:
            body, _ = fetch(sitemap)
        except Exception as exc:  # noqa: BLE001 - keep export resilient.
            print(f"warn: could not fetch sitemap {sitemap}: {exc}", file=sys.stderr)
            continue
        text = body.decode("utf-8", errors="replace")
        for loc in re.findall(r"<loc>(.*?)</loc>", text, flags=re.IGNORECASE):
            loc = html.unescape(loc)
            if loc.endswith(".xml") and "wp-sitemap" in loc:
                queue.append(loc)
                continue
            normalized = normalize_url(loc)
            if normalized and not should_skip_url(normalized):
                urls.add(normalized)
    return urls


def extract_urls(text: str, base_url: str, *, include_css_urls: bool = True) -> set[str]:
    urls: set[str] = set()
    normalized_text = html.unescape(text)
    normalized_text = normalized_text.replace("\\/", "/")

    for match in SAME_DOMAIN_RE.finditer(normalized_text):
        path = match.group(1) or "/"
        normalized = normalize_url(path, SITE + "/")
        if normalized and not should_skip_url(normalized):
            urls.add(normalized)

    for match in ESCAPED_DOMAIN_RE.finditer(text):
        path = (match.group(1) or "/").replace("\\/", "/")
        normalized = normalize_url(path, SITE + "/")
        if normalized and not should_skip_url(normalized):
            urls.add(normalized)

    for match in ROOT_RELATIVE_RE.finditer(normalized_text):
        normalized = normalize_url(match.group(1), base_url)
        if normalized and not should_skip_url(normalized):
            urls.add(normalized)

    for match in SRCSET_RE.finditer(normalized_text):
        if match.group(1).strip().lower().startswith("data:"):
            continue
        for candidate in match.group(1).split(","):
            src = candidate.strip().split(" ")[0]
            normalized = normalize_url(src, base_url)
            if normalized and not should_skip_url(normalized):
                urls.add(normalized)

    if include_css_urls:
        for match in CSS_URL_RE.finditer(normalized_text):
            src = match.group(1).strip().strip("\"'")
            normalized = normalize_url(src, base_url)
            if normalized and not should_skip_url(normalized):
                urls.add(normalized)

    return urls


def localize_internal_urls(text: str) -> str:
    replacements = {
        "https://florianacelani.com": "",
        "http://florianacelani.com": "",
        "//florianacelani.com": "",
        "https:\\/\\/florianacelani.com": "",
        "http:\\/\\/florianacelani.com": "",
        "/wp-admin/admin-ajax.php": NOOP_ENDPOINT,
        "\\/wp-admin\\/admin-ajax.php": NOOP_ENDPOINT.replace("/", "\\/"),
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    return text


def strip_wordpress_runtime(html_text: str) -> str:
    html_text = re.sub(
        r"\s*<link[^>]+rel=[\"'](?:alternate|EditURI|pingback|shortlink)[\"'][^>]*>\s*",
        "\n",
        html_text,
        flags=re.IGNORECASE,
    )
    html_text = re.sub(
        r"\s*<link[^>]+href=[\"'][^\"']*(?:wp-json|xmlrpc\.php|/feed/|comments/feed)[^\"']*[\"'][^>]*>\s*",
        "\n",
        html_text,
        flags=re.IGNORECASE,
    )
    html_text = re.sub(
        r"\s*<script[^>]+type=[\"']speculationrules[\"'][^>]*>.*?</script>\s*",
        "\n",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    html_text = re.sub(
        r"(SR7\.E\.(?:ajaxurl|resturl)\s*=\s*)['\"][^'\"]*['\"]",
        rf"\1'{NOOP_ENDPOINT}'",
        html_text,
    )
    html_text = re.sub(
        r"(var\s+ajaxurl\s*=\s*)['\"][^'\"]*['\"]",
        rf"\1'{NOOP_ENDPOINT}'",
        html_text,
    )
    html_text = html_text.replace(
        "&quot;nonce_method&quot;:&quot;ajax&quot;",
        "&quot;nonce_method&quot;:&quot;static&quot;",
    )
    html_text = html_text.replace(
        "&quot;form_type&quot;:&quot;ajax&quot;",
        "&quot;form_type&quot;:&quot;post&quot;",
    )
    html_text = re.sub(
        r'(<form\b(?=[^>]*class="[^"]*fusion-form)[^>]*?)\saction="[^"]*"',
        rf'\1 action="mailto:{CONTACT_EMAIL}"',
        html_text,
    )
    html_text = re.sub(
        r'(<form\b(?=[^>]*class="[^"]*fusion-form)[^>]*?)\smethod="[^"]*"',
        r'\1 method="post"',
        html_text,
    )
    html_text = re.sub(
        r'(<form\b(?=[^>]*class="[^"]*fusion-form)(?![^>]*enctype=)[^>]*)>',
        r'\1 enctype="text/plain">',
        html_text,
    )
    html_text = re.sub(
        r'(<form\b(?![^>]*data-static-form)[^>]*class="[^"]*fusion-form[^"]*"[^>]*)>',
        r'\1 data-static-form="mailto">',
        html_text,
    )
    return html_text


def inject_static_assets(html_text: str) -> str:
    script = f'<script src="{STATIC_ASSET}"></script>'
    if script in html_text:
        return html_text
    if "</body>" in html_text:
        return html_text.replace("</body>", f"{script}\n</body>")
    return html_text + "\n" + script + "\n"


def write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_text(path: Path, text: str) -> None:
    write_file(path, text.encode("utf-8"))


def process_html(raw: bytes, url: str) -> tuple[str, set[str]]:
    text = raw.decode("utf-8", errors="replace")
    discovered = extract_urls(text, url)
    text = strip_wordpress_runtime(text)
    text = localize_internal_urls(text)
    text = inject_static_assets(text)
    return text, discovered


def process_asset(raw: bytes, url: str, content_type: str) -> tuple[bytes, set[str]]:
    discovered: set[str] = set()
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if "text" in content_type or suffix in {".css", ".js", ".json", ".svg", ".xml"}:
        text = raw.decode("utf-8", errors="replace")
        discovered = extract_urls(text, url, include_css_urls=suffix == ".css")
        text = localize_internal_urls(text)
        return text.encode("utf-8"), discovered
    return raw, discovered


def write_support_files() -> None:
    write_text(PUBLIC / ".nojekyll", "")
    write_text(PUBLIC / "CNAME", HOST + "\n")
    write_text(PUBLIC / "static-noop.json", "{}\n")
    for source, target in KNOWN_REDIRECTS.items():
        write_redirect(local_path_for_url(SITE + source), target)
    icon_font_svg = (
        PUBLIC
        / "wp-content/uploads/fusion-icons/Galerie-Icon-Set-v1.0/fonts/Galerie-Icon-Set.svg"
    )
    if not icon_font_svg.exists():
        write_text(icon_font_svg, '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n')
    write_text(
        PUBLIC / "404.html",
        """<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pagina non trovata - Floriana Celani</title>
  <meta http-equiv="refresh" content="0; url=/">
</head>
<body>
  <p>Pagina non trovata. <a href="/">Torna alla home</a>.</p>
</body>
</html>
""",
    )
    write_text(
        PUBLIC / STATIC_ASSET.lstrip("/"),
        f"""(() => {{
  const CONTACT_EMAIL = "{CONTACT_EMAIL}";

  const fieldLabel = (field) => {{
    const id = field.id ? document.querySelector(`label[for="${{CSS.escape(field.id)}}"]`) : null;
    if (id) return id.textContent.replace("*", "").trim();
    if (field.name) return field.name.replace(/_/g, " ");
    return "Field";
  }};

  const collectFields = (form) => Array.from(form.querySelectorAll("input, textarea, select"))
    .filter((field) => field.name && !["hidden", "submit", "button"].includes(field.type))
    .map((field) => `${{fieldLabel(field)}}: ${{field.value || ""}}`)
    .join("\\n");

    document.querySelectorAll("form[data-static-form='mailto'], form.fusion-form").forEach((form) => {{
    form.setAttribute("novalidate", "novalidate");
    form.addEventListener("submit", (event) => {{
      event.preventDefault();
      event.stopImmediatePropagation();
      const subject = form.closest(".page-id-154") ? "Newsletter request" : "Messaggio da florianacelani.com";
      const body = collectFields(form);
      const mailto = `mailto:${{CONTACT_EMAIL}}?subject=${{encodeURIComponent(subject)}}&body=${{encodeURIComponent(body)}}`;
      window.location.href = mailto;
      const success = form.querySelector(".fusion-form-response-success");
      if (success) success.style.display = "block";
    }}, true);
  }});
}})();
""",
    )


def write_redirect(path: Path, target: str) -> None:
    write_text(
        path,
        f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Redirect - Floriana Celani</title>
  <meta http-equiv="refresh" content="0; url={target}">
  <link rel="canonical" href="{target}">
</head>
<body>
  <p><a href="{target}">Continua</a></p>
</body>
</html>
""",
    )


def export_site() -> None:
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    PUBLIC.mkdir(parents=True)

    page_queue: deque[str] = deque(sorted(extract_sitemap_urls()))
    asset_queue: deque[str] = deque(STATIC_SEED_ASSETS)
    seen_pages: set[str] = set()
    seen_assets: set[str] = set()

    while page_queue and len(seen_pages) < MAX_PAGES:
        url = page_queue.popleft()
        if url in seen_pages or should_skip_url(url):
            continue
        if urlparse(url).path in KNOWN_REDIRECTS:
            seen_pages.add(url)
            continue
        if is_asset_url(url):
            asset_queue.append(url)
            continue
        seen_pages.add(url)
        print(f"page  {url}")
        try:
            raw, content_type = fetch(url)
        except Exception as exc:  # noqa: BLE001 - keep export moving.
            print(f"warn: page failed {url}: {exc}", file=sys.stderr)
            continue
        text, discovered = process_html(raw, url)
        write_text(local_path_for_url(url), text)
        for discovered_url in sorted(discovered):
            if is_asset_url(discovered_url):
                if discovered_url not in seen_assets:
                    asset_queue.append(discovered_url)
            elif discovered_url not in seen_pages and not should_skip_url(discovered_url):
                page_queue.append(discovered_url)

    while asset_queue and len(seen_assets) < MAX_ASSETS:
        url = asset_queue.popleft()
        if url in seen_assets or should_skip_url(url):
            continue
        seen_assets.add(url)
        print(f"asset {url}")
        try:
            raw, content_type = fetch(url)
        except Exception as exc:  # noqa: BLE001 - keep export moving.
            print(f"warn: asset failed {url}: {exc}", file=sys.stderr)
            continue
        data, discovered = process_asset(raw, url, content_type)
        write_file(local_path_for_url(url, asset=True), data)
        for discovered_url in sorted(discovered):
            if is_asset_url(discovered_url) and discovered_url not in seen_assets:
                asset_queue.append(discovered_url)

    write_support_files()
    print(f"\nExported {len(seen_pages)} pages and {len(seen_assets)} assets to {PUBLIC}")


if __name__ == "__main__":
    export_site()
