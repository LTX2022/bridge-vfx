"""SideFX docs downloader with restricted recursive crawl."""

from __future__ import annotations

import json
import re
import hashlib
import time
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse
from uuid import uuid4

from _skill_runtime import (
    DOCS_USER_AGENT,
    check_robots_allowed,
    docs_base_url_for_version,
    fetch_url,
    validate_record,
)


UTC = timezone.utc
DEFAULT_DOWNLOAD_ROOT = Path(__file__).resolve().parents[1] / "downloads"
DEFAULT_ALLOWLIST = [
    "https://www.sidefx.com/docs/houdini/",
    "https://www.sidefx.com/docs/houdini/nodes/",
    "https://www.sidefx.com/docs/houdini/hom/",
    "https://www.sidefx.com/docs/houdini/vex/",
]
REQUEST_DELAY_SECONDS = 0.25
DEFAULT_MAX_PAGES = 500
DEFAULT_MAX_DEPTH = 8
MIN_COMPLETE_PAGES = 12
BLOCKED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".mp4", ".mov", ".zip", ".hip", ".pdf"}
DENYLIST_PATH_PARTS = (
    "/forum",
    "/tutorial",
    "/learn",
    "/products",
    "/login",
    "/cart",
    "/profile",
    "/download",
    "/gallery",
    "/store",
    "/account",
)


@dataclass(frozen=True)
class CleanedDocument:
    title: str
    markdown: str
    content: str
    headings: list[str]
    links: list[dict[str, str]]


class SideFXHTMLCleaner(HTMLParser):
    """Small stdlib cleaner for documentation pages."""

    def __init__(self, source_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.title = ""
        self.headings: list[str] = []
        self.links: list[dict[str, str]] = []
        self.blocks: list[tuple[str, str]] = []
        self._skip_depth = 0
        self._current_tag: str | None = None
        self._current_buffer: list[str] = []
        self._anchor_href: str | None = None
        self._anchor_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "noscript", "nav", "header", "footer", "aside"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return

        attr_map = {key.lower(): value or "" for key, value in attrs}
        if tag == "a" and attr_map.get("href"):
            self._anchor_href = urljoin(self.source_url, attr_map["href"])
            self._anchor_buffer = []
            return

        if self._current_tag is None and tag in {"title", "h1", "h2", "h3", "h4", "p", "li", "pre"}:
            self._current_tag = tag
            self._current_buffer = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._anchor_href:
            self._anchor_buffer.append(data)
            return
        if self._current_tag:
            self._current_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "noscript", "nav", "header", "footer", "aside"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return

        if tag == "a" and self._anchor_href:
            label = normalize_text(" ".join(self._anchor_buffer))
            if label:
                self.links.append({"label": label, "url": self._anchor_href})
                if self._current_tag:
                    self._current_buffer.append(f"[{label}]({self._anchor_href})")
            self._anchor_href = None
            self._anchor_buffer = []
            return

        if self._current_tag == tag:
            text = normalize_text(" ".join(self._current_buffer))
            if text:
                if tag == "title" and not self.title:
                    self.title = text
                elif tag.startswith("h"):
                    self.headings.append(text)
                    self.blocks.append((tag, text))
                    if tag == "h1" and not self.title:
                        self.title = text
                else:
                    self.blocks.append((tag, text))
            self._current_tag = None
            self._current_buffer = []


def normalize_text(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def fallback_title(source_url: str) -> str:
    stem = Path(urlparse(source_url).path).stem
    return stem.replace("-", " ").replace("_", " ").strip().title() or source_url


def slug_for_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    raw = f"{parsed.netloc}{parsed.path}".strip("/")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_").lower()
    return slug or uuid4().hex


def normalize_doc_url(source_url: str, base_url: str = "https://www.sidefx.com/docs/houdini/") -> str:
    joined = urljoin(base_url, source_url)
    normalized, _ = urldefrag(joined)
    return normalized


def is_houdini_docs_path(path: str) -> bool:
    normalized = path.lower().rstrip("/")
    return bool(
        normalized == "/docs/houdini"
        or normalized.startswith("/docs/houdini/")
        or re.match(r"^/docs/houdini\d+(?:\.\d+)?(?:/|$)", normalized)
    )


def is_sidefx_houdini_doc_url(source_url: str) -> bool:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc.lower() != "www.sidefx.com":
        return False
    path = parsed.path.lower()
    if not is_houdini_docs_path(path):
        return False
    if Path(path).suffix.lower() in BLOCKED_SUFFIXES:
        return False
    return not any(part in path for part in DENYLIST_PATH_PARTS)


def clean_html(html: str, source_url: str) -> CleanedDocument:
    parser = SideFXHTMLCleaner(source_url)
    parser.feed(html)
    title = parser.title or (parser.headings[0] if parser.headings else fallback_title(source_url))
    markdown_lines = [f"# {title}", "", f"Source: {source_url}", ""]
    for tag, text in parser.blocks:
        if tag in {"h1", "h2", "h3", "h4"}:
            markdown_lines.append(f"{'#' * int(tag[1])} {text}")
        elif tag == "li":
            markdown_lines.append(f"- {text}")
        elif tag == "pre":
            markdown_lines.extend(["```", text, "```"])
        else:
            markdown_lines.append(text)
        markdown_lines.append("")
    markdown = "\n".join(markdown_lines).strip() + "\n"
    content = normalize_text("\n".join(text for _, text in parser.blocks)) or title
    return CleanedDocument(title=title, markdown=markdown, content=content, headings=parser.headings, links=parser.links)


def extract_doc_links(html: str, source_url: str) -> list[str]:
    document = clean_html(html, source_url)
    urls = []
    for link in document.links:
        normalized = normalize_doc_url(link.get("url", ""), source_url)
        if is_sidefx_houdini_doc_url(normalized):
            urls.append(normalized)
    return list(dict.fromkeys(urls))


def make_jsonl_record(
    *,
    source_url: str,
    downloaded_at: str,
    online_version: str,
    document: CleanedDocument,
    raw_html_path: Path,
    markdown_path: Path,
) -> dict[str, Any]:
    content_hash = hashlib.sha256(document.content.encode("utf-8")).hexdigest()
    parsed = urlparse(source_url)
    return {
        "id": f"sidefx:{slug_for_url(source_url)}",
        "document_id": f"sidefx:{slug_for_url(source_url)}",
        "chunk_index": 0,
        "title": document.title,
        "source": source_url,
        "source_url": source_url,
        "content": document.content,
        "text": document.content,
        "version": online_version,
        "path": parsed.path,
        "headings": document.headings,
        "fetched_at": downloaded_at,
        "content_hash": content_hash,
        "metadata": {
            "type": "sidefx_online_doc",
            "source_url": source_url,
            "downloaded_at": downloaded_at,
            "online_version": online_version,
            "version": online_version,
            "path": parsed.path,
            "content_hash": content_hash,
            "raw_html_path": str(raw_html_path),
            "cleaned_markdown_path": str(markdown_path),
            "headings": document.headings,
            "links": document.links,
        },
    }


def ensure_allowlisted(urls: list[str], allowlist: list[str]) -> tuple[list[str], list[str]]:
    allowed = {normalize_doc_url(item) for item in allowlist}
    accepted: list[str] = []
    rejected: list[str] = []
    for url in urls:
        normalized = normalize_doc_url(url)
        if normalized in allowed or is_sidefx_houdini_doc_url(normalized):
            accepted.append(normalized)
        else:
            rejected.append(url)
    return accepted, rejected


def build_robots_summary(urls: list[str], robots_checker=check_robots_allowed) -> dict[str, Any]:
    summary: dict[str, Any] = {"checked": 0, "allowed": 0, "disallowed": 0, "unknown": 0, "items": []}
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        result = robots_checker(url)
        summary["checked"] += 1
        status = str(result.get("status") or "unknown")
        if result.get("allowed") is True:
            summary["allowed"] += 1
        elif result.get("allowed") is False:
            summary["disallowed"] += 1
        else:
            summary["unknown"] += 1
        summary["items"].append({"url": url, "status": status, "allowed": result.get("allowed"), "robots_url": result.get("robots_url")})
    return summary


def cached_robots_checker(robots_checker=check_robots_allowed):
    cache: dict[str, dict[str, Any]] = {}

    def check(url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        key = f"{parsed.scheme}://{parsed.netloc}"
        if key not in cache:
            cache[key] = robots_checker(url)
        return cache[key]

    return check


def discover_sidefx_doc_urls(
    seeds: list[str],
    *,
    fetcher=fetch_url,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    request_delay_seconds: float = REQUEST_DELAY_SECONDS,
    robots_checker=check_robots_allowed,
) -> dict[str, Any]:
    queue: list[tuple[str, int]] = [(normalize_doc_url(seed), 0) for seed in seeds]
    seen: set[str] = set()
    accepted: list[str] = []
    failed: list[dict[str, str]] = []
    current_url: str | None = None

    while queue and len(accepted) < max_pages:
        current_url, depth = queue.pop(0)
        if current_url in seen:
            continue
        seen.add(current_url)
        if not is_sidefx_houdini_doc_url(current_url):
            continue
        robots = robots_checker(current_url)
        if robots.get("allowed") is False:
            failed.append({"url": current_url, "code": "robots_disallowed", "error": "robots.txt disallows this URL"})
            continue
        accepted.append(current_url)
        if depth >= max_depth:
            continue
        try:
            html = fetcher(current_url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failed.append({"url": current_url, "error": str(exc)})
            continue
        for link in extract_doc_links(html, current_url):
            if link not in seen and all(link != queued_url for queued_url, _ in queue):
                queue.append((link, depth + 1))
        if request_delay_seconds > 0:
            time.sleep(request_delay_seconds)

    return {
        "status": "ok" if accepted else "failed",
        "urls": accepted,
        "discovered_count": len(accepted),
        "failed_discovery_count": len(failed),
        "failed_discovery": failed,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "current_url": current_url,
    }


def section_coverage(urls: list[str]) -> dict[str, bool]:
    lower_urls = [url.lower() for url in urls]
    return {
        "nodes": any("/nodes/" in url for url in lower_urls),
        "python_hom": any(any(marker in url for marker in ("/hom/", "/hou/")) for url in lower_urls),
        "vex": any("/vex/" in url for url in lower_urls),
        "render": any(any(marker in url for marker in ("/render/", "/karma/", "/mantra/")) for url in lower_urls),
        "simulation": any(any(marker in url for marker in ("/sim/", "/vellum/", "/flip/", "/pyro/", "/rbd/")) for url in lower_urls),
        "editor": any(any(marker in url for marker in ("/network/", "/editor/", "/pane/", "/ui/")) for url in lower_urls),
    }


def completeness_status(downloaded_urls: list[str], failed_count: int, discovered_count: int) -> dict[str, Any]:
    coverage = section_coverage(downloaded_urls)
    complete = len(downloaded_urls) >= MIN_COMPLETE_PAGES and all(coverage.values())
    if complete:
        return {
            "complete": True,
            "status": "complete",
            "reason": None,
            "coverage": coverage,
            "minimum_pages": MIN_COMPLETE_PAGES,
        }
    missing = [name for name, present in coverage.items() if not present]
    reason_parts = []
    if len(downloaded_urls) < MIN_COMPLETE_PAGES:
        reason_parts.append(f"下载页数不足：{len(downloaded_urls)} / {MIN_COMPLETE_PAGES}")
    if missing:
        reason_parts.append(f"缺少章节：{', '.join(missing)}")
    if failed_count:
        reason_parts.append("部分页面下载失败")
    if discovered_count <= len(downloaded_urls) and not complete:
        reason_parts.append("尚未发现更多子页面")
    return {
        "complete": False,
        "status": "incomplete",
        "reason": "；".join(reason_parts) or "文档集完整性不足",
        "coverage": coverage,
        "minimum_pages": MIN_COMPLETE_PAGES,
    }


def build_coverage_manifest(
    *,
    requested_urls: list[str],
    discovered_urls: list[str],
    downloaded_urls: list[str],
    failed_pages: list[dict[str, Any]],
    skipped_pages: list[dict[str, Any]],
    robots_summary: dict[str, Any],
    completeness: dict[str, Any],
    jsonl_path: Path,
    manifest_path: Path,
    request_delay_seconds: float,
    max_pages: int,
    max_depth: int,
) -> dict[str, Any]:
    robots_blocked = [item for item in failed_pages if item.get("code") == "robots_disallowed"]
    discovered_unique = list(dict.fromkeys(discovered_urls))
    cleaned_success_rate = round(len(downloaded_urls) / max(1, len(discovered_unique)), 4) if discovered_unique else 0.0
    return {
        "status": completeness.get("status", "incomplete"),
        "crawl_policy": "robots_respected_allowlisted_houdini_docs_only",
        "robots_note": "This downloader does not bypass robots.txt, login walls, anti-bot controls, or private content.",
        "requested": {"count": len(requested_urls), "urls": requested_urls[:200]},
        "discovered": {
            "count": len(discovered_unique),
            "duplicate_count": max(0, len(discovered_urls) - len(discovered_unique)),
            "urls_sample": discovered_unique[:50],
        },
        "downloaded": {"count": len(downloaded_urls), "urls_sample": downloaded_urls[:50]},
        "failed": {"count": len(failed_pages), "pages": failed_pages[:100]},
        "skipped": {"count": len(skipped_pages), "pages": skipped_pages[:100]},
        "robots_blocked": {
            "count": len(robots_blocked),
            "pages": robots_blocked[:100],
            "summary": robots_summary,
        },
        "cleaned": {
            "jsonl_path": str(jsonl_path),
            "records": len(downloaded_urls),
            "success_rate": cleaned_success_rate,
        },
        "limits": {
            "max_pages": max_pages,
            "max_depth": max_depth,
            "request_delay_seconds": request_delay_seconds,
            "max_concurrency": 1,
        },
        "completeness": completeness,
        "manifest_path": str(manifest_path),
        "fallbacks": [
            "Import local Houdini bundled docs from the installed SideFX directory.",
            "Import user-provided JSONL, Markdown, TXT, subtitles, or notes.",
            "Run another compliant batch from an allowed SideFX docs entry point.",
        ],
    }


def download_sidefx_docs(
    *,
    urls: list[str] | None = None,
    online_version: str | None = None,
    output_root: Path | str = DEFAULT_DOWNLOAD_ROOT,
    allowlist: list[str] | None = None,
    fetcher=fetch_url,
    robots_checker=check_robots_allowed,
    request_delay_seconds: float = REQUEST_DELAY_SECONDS,
    recursive: bool = True,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    selected_base_url: str | None = None,
) -> dict[str, Any]:
    robots_checker = cached_robots_checker(robots_checker)
    allowlist_urls = allowlist or DEFAULT_ALLOWLIST
    base_url = selected_base_url or docs_base_url_for_version(online_version)
    requested_urls = urls or (allowlist_urls if not recursive else [base_url])
    accepted_urls, rejected_urls = ensure_allowlisted(requested_urls, allowlist_urls)
    discovery = {
        "status": "disabled",
        "urls": accepted_urls,
        "discovered_count": len(accepted_urls),
        "failed_discovery_count": 0,
        "failed_discovery": [],
        "max_pages": max_pages,
        "max_depth": max_depth,
        "current_url": None,
    }
    if recursive and accepted_urls:
        discovery = discover_sidefx_doc_urls(
            accepted_urls,
            fetcher=fetcher,
            max_pages=max_pages,
            max_depth=max_depth,
            request_delay_seconds=request_delay_seconds,
            robots_checker=robots_checker,
        )
        accepted_urls = list(discovery["urls"])

    download_id = f"sidefx_docs_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    download_dir = Path(output_root) / download_id
    raw_dir = download_dir / "raw"
    cleaned_dir = download_dir / "cleaned"
    raw_dir.mkdir(parents=True, exist_ok=True)
    cleaned_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    errors = [f"URL is not in allowlist: {url}" for url in rejected_urls]
    failed_pages: list[dict[str, Any]] = []
    skipped_pages = [{"url": url, "reason": "not_allowlisted"} for url in rejected_urls]
    version = online_version or "unknown"
    robots_summary = build_robots_summary(accepted_urls[:max_pages], robots_checker=robots_checker)

    for index, source_url in enumerate(accepted_urls[:max_pages]):
        downloaded_at = datetime.now(UTC).isoformat()
        slug = slug_for_url(source_url)
        raw_html_path = raw_dir / f"{slug}.html"
        markdown_path = cleaned_dir / f"{slug}.md"
        try:
            robots = robots_checker(source_url)
            if robots.get("allowed") is False:
                raise PermissionError("robots_disallowed")
            html = fetcher(source_url)
            raw_html_path.write_text(html, encoding="utf-8")
            document = clean_html(html, source_url)
            markdown_path.write_text(document.markdown, encoding="utf-8")
            record = make_jsonl_record(
                source_url=source_url,
                downloaded_at=downloaded_at,
                online_version=version,
                document=document,
                raw_html_path=raw_html_path,
                markdown_path=markdown_path,
            )
            validation_error = validate_record(record)
            if validation_error:
                raise ValueError(validation_error)
            records.append(record)
            pages.append(
                {
                    "status": "ok",
                    "source_url": source_url,
                    "downloaded_at": downloaded_at,
                    "raw_html_path": str(raw_html_path),
                    "cleaned_markdown_path": str(markdown_path),
                    "title": document.title,
                }
            )
        except PermissionError as exc:
            errors.append(f"{source_url}: {exc}")
            failed_pages.append({"url": source_url, "code": "robots_disallowed", "error": str(exc)})
            pages.append(
                {
                    "status": "failed",
                    "source_url": source_url,
                    "downloaded_at": downloaded_at,
                    "raw_html_path": str(raw_html_path),
                    "cleaned_markdown_path": str(markdown_path),
                    "errors": [str(exc)],
                }
            )
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(f"{source_url}: {exc}")
            failed_pages.append({"url": source_url, "code": "download_failed", "error": str(exc)})
            pages.append(
                {
                    "status": "failed",
                    "source_url": source_url,
                    "downloaded_at": downloaded_at,
                    "raw_html_path": str(raw_html_path),
                    "cleaned_markdown_path": str(markdown_path),
                    "errors": [str(exc)],
                }
            )
        if index < len(accepted_urls) - 1 and request_delay_seconds > 0:
            time.sleep(request_delay_seconds)

    jsonl_path = cleaned_dir / "sidefx_docs.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records)
        + ("\n" if records else ""),
        encoding="utf-8",
    )

    downloaded_urls = [str(record["source"]) for record in records]
    completeness = completeness_status(downloaded_urls, len(errors), int(discovery.get("discovered_count") or len(accepted_urls)))
    if records and completeness["complete"] and not errors:
        status = "ok"
    elif records:
        status = "incomplete"
    else:
        status = "failed"

    if status == "ok":
        diagnostic = {
            "code": "ok",
            "message": f"已下载并清洗 {len(records)} 个 SideFX 文档页面。",
            "fix": "打开知识库创建候选版本，验证通过后再激活。当前激活知识库在验证前不会被改动。",
        }
    elif status == "incomplete":
        diagnostic = {
            "code": "sidefx_docs_download_incomplete",
            "message": f"已下载 {len(records)} 页，但文档集不完整：{completeness['reason']}",
            "fix": "查看失败 URL 和缺失章节后重试下载。也可以先使用本地 JSONL/Markdown/TXT 导入兜底；文档下载与向量检索相互独立。",
        }
    else:
        diagnostic = {
            "code": "sidefx_docs_download_failed",
            "message": errors[0] if errors else "没有成功下载任何 SideFX 文档页面。",
            "fix": "打开知识库，检查网络、代理和允许下载的 docs URL。若仍失败，使用本地 JSONL/Markdown/TXT 导入兜底；文档下载与向量检索相互独立。",
        }

    manifest_path = download_dir / "manifest.json"
    discovered_urls = list(discovery.get("urls") or accepted_urls)
    coverage_manifest = build_coverage_manifest(
        requested_urls=requested_urls,
        discovered_urls=discovered_urls,
        downloaded_urls=downloaded_urls,
        failed_pages=failed_pages,
        skipped_pages=skipped_pages,
        robots_summary=robots_summary,
        completeness=completeness,
        jsonl_path=jsonl_path,
        manifest_path=manifest_path,
        request_delay_seconds=request_delay_seconds,
        max_pages=max_pages,
        max_depth=max_depth,
    )

    payload: dict[str, Any] = {
        "status": status,
        "download_id": download_id,
        "download_dir": str(download_dir),
        "online_version": version,
        "version": version,
        "base_url": base_url,
        "allowlist": allowlist_urls,
        "requested_urls": requested_urls,
        "downloaded_count": len(records),
        "failed_count": len(errors),
        "skipped_count": len(skipped_pages),
        "failed_pages": failed_pages,
        "skipped_pages": skipped_pages,
        "robots_summary": robots_summary,
        "coverage_manifest": coverage_manifest,
        "discovered_count": int(discovery.get("discovered_count") or len(accepted_urls)),
        "current_url": discovery.get("current_url"),
        "recursive": recursive,
        "completeness": completeness,
        "incomplete": not completeness["complete"],
        "max_concurrency": 1,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "request_delay_seconds": request_delay_seconds,
        "raw_dir": str(raw_dir),
        "cleaned_dir": str(cleaned_dir),
        "jsonl_path": str(jsonl_path),
        "pages": pages,
        "errors": errors,
        "discovery": discovery,
        "failure": {"reason": errors[0] if errors else completeness.get("reason"), "errors": errors},
        "diagnostic": diagnostic,
        "active_kb_affected": False,
        "kb_activated": False,
    }
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["manifest_path"] = str(manifest_path)
    return payload
