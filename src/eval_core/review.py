"""Rebuildable private report catalog; snapshots and evaluation evidence are immutable."""

from collections import Counter
from html import escape
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .html_report import render_html, write_html
from .store import digest, exclusive, now, read_json, write_json


MARKER = "<!-- eval-review-index:v1 -->"
RUN_MARKER = "<!-- eval-run-report:v1 -->"
HOME_MARKER = "<!-- eval-review-home:v1 -->"


def _catalog(directory):
    index, path = directory / "index.html", directory / "catalog.json"
    if any(item.is_symlink() for item in (index, path, directory / "snapshots")):
        raise ValueError("review files must not be symbolic links")
    if index.exists() and not index.read_text(encoding="utf-8").startswith(MARKER):
        raise ValueError("refusing to replace an unmanaged review index")
    if not path.exists():
        if index.exists():
            raise ValueError("review catalog is missing; restore it before rebuilding")
        return {"schema_version": 1, "kind": "eval_review_catalog", "reports": []}
    catalog = read_json(path)
    if (not isinstance(catalog, dict) or catalog.get("schema_version") != 1
            or catalog.get("kind") != "eval_review_catalog" or not isinstance(catalog.get("reports"), list)):
        raise ValueError("invalid review catalog")
    for record in catalog["reports"]:
        if (not isinstance(record, dict) or not isinstance(record.get("filename"), str)
                or not re.fullmatch(r"[0-9a-f]{32}\.html", record["filename"])
                or not isinstance(record.get("source_key"), str)
                or type(record.get("latest")) is not bool
                or not all(isinstance(record.get(key), str) for key in ("title", "generated_at", "kind"))
                or not isinstance(record.get("counts"), dict)):
            raise ValueError("invalid review record")
        snapshot = directory / "snapshots" / record["filename"]
        if (snapshot.is_symlink() or not snapshot.is_file()
                or not snapshot.resolve().is_relative_to((directory / "snapshots").resolve())):
            raise ValueError("missing or unsafe review snapshot; restore it before rebuilding")
    return catalog


def _render_index(catalog):
    records = list(reversed(catalog["reports"]))

    def card(record):
        filename = record["filename"]  # Validated/generated basename, never a user URL.
        counts = " · ".join(f"{key}: {value}" for key, value in record["counts"].items())
        return (f'<li><a href="snapshots/{filename}">{escape(record["title"])}</a>'
                f'<p>{escape(record["generated_at"])} · {escape(record["kind"])}</p>'
                f'<p>{escape(counts or "无任务条目")}</p></li>')

    current = [record for record in records if record["latest"]]
    latest = card(current[0]) if current else ""
    others = "".join(card(record) for record in current[1:])
    history = "".join(card(record) for record in records)
    return MARKER + "\n" + '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>评测报告 · 统一入口</title>
<style>
:root{color-scheme:light;font-family:system-ui,"Microsoft YaHei",sans-serif;color:#172635;background:#f5f5f2}
*{box-sizing:border-box}body{max-width:1080px;margin:0 auto;padding:32px 24px;font-size:16px;line-height:1.65}
h1{font-size:30px;margin:0}h2{font-size:21px}a{color:#174f86;display:inline-block;padding:8px 0;overflow-wrap:anywhere}
a:focus-visible,summary:focus-visible{outline:3px solid #174f86;outline-offset:4px}
section,details{background:white;border:1px solid #c7cfd6;border-radius:10px;padding:24px;margin-top:24px}
ul{padding-left:24px}li+li{border-top:1px solid #c7cfd6;margin-top:16px;padding-top:16px}
p{margin:4px 0;color:#536171;overflow-wrap:anywhere}.notice{padding:16px;background:#fff5df;color:#764604}
summary{cursor:pointer;font-weight:600;padding:8px 0}
</style></head><body><header><h1>评测报告 · 统一入口</h1>
<p>日常只看最近导出的报告；其他报告与技术历史默认折叠。</p></header>
<p class="notice">仅本地只读，不调用模型。包含私有内容，请勿直接外发。这里只列已收录的报告，不代表全部计划已完成；未知费用不是零。</p>
<main><section aria-labelledby="latest"><h2 id="latest">最近导出的报告</h2>''' + (
        "<ul>" + latest + "</ul>" if latest else "<p>还没有报告。使用 review --result 显式导入已保存结果，或完成一次新版评测。</p>"
    ) + '</section><details><summary>其他已收录报告（' + str(max(0, len(current) - 1)) + '）</summary><ul>' + others + '</ul></details><details><summary>历史快照（' + str(len(records)) + '）</summary><ul>' + history + '''</ul></details>
<p>这是可重建目录，不是原始证据。评测／重评／导出会更新入口；已打开的页面需要刷新，单独修改来源文件不会自动更新快照。</p>
</main></body></html>
'''


def _write_managed(path, content, marker):
    if path.is_symlink() or (path.exists() and not path.read_text(encoding="utf-8").startswith(marker)):
        raise ValueError("refusing to replace an unmanaged report entry")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".review-index-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def _write_index(directory, catalog):
    return _write_managed(directory / "index.html", _render_index(catalog), MARKER)


def publish_run_report(directory: Path, bundle: dict) -> Path:
    """Update only a managed, derived front page; frozen results remain untouched."""
    directory = Path(directory)
    with exclusive(directory / "details/.report.lock"):
        return _write_managed(directory / "report.html", RUN_MARKER + "\n" + render_html(bundle), RUN_MARKER)


def publish_workspace_home(directory: Path) -> Path:
    """A stable front door to the default catalog, without copying any reports."""
    directory = Path(directory)
    content = HOME_MARKER + '''
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>评测入口</title><style>
body{font:16px/1.65 system-ui,"Microsoft YaHei",sans-serif;max-width:800px;margin:48px auto;padding:24px;color:#172635;background:#f5f5f2}
a{color:#174f86;display:inline-block;padding:12px 0}a:focus-visible,summary:focus-visible{outline:3px solid #174f86;outline-offset:4px}
details{margin-top:32px}summary{cursor:pointer;padding:8px 0}
</style></head><body><main><h1>评测入口</h1>
<p>平时只从这里查看报告，无需寻找原始文件。</p>
<p><a href="review/index.html">查看最近测评报告</a></p>
<p>报告只读，不调用模型。原始材料保留在各次测评的详情目录。</p>
'''
    if (directory / "details/history.html").is_file():
        content += '<details><summary>历史复核与归档</summary><p><a href="details/history.html">查看历史记录</a></p></details>'
    content += "</main></body></html>\n"
    with exclusive(directory / "review/.home.lock"):
        return _write_managed(directory / "index.html", content, HOME_MARKER)


def refresh_review(directory: Path) -> Path:
    """Rebuild the managed entry only; never discover results or request a provider."""
    directory = Path(directory)
    with exclusive(directory / ".review.lock"):
        catalog = _catalog(directory)
        write_json(directory / "catalog.json", catalog)
        return _write_index(directory, catalog)


def publish_review(directory: Path, bundle: dict, sources: dict) -> Path:
    """Add a new snapshot and update this source's latest link under one writer lock."""
    directory = Path(directory)
    with exclusive(directory / ".review.lock"):
        catalog = _catalog(directory)
        source_key = digest({"kind": bundle["kind"], "sources": sources})
        content_hash = digest({key: value for key, value in bundle.items() if key != "generated_at"})
        for previous in reversed(catalog["reports"]):
            if (previous["source_key"] == source_key and previous["latest"]
                    and previous.get("content_hash") == content_hash):
                _write_index(directory, catalog)
                return directory / "snapshots" / previous["filename"]
        snapshot = directory / "snapshots" / (uuid4().hex + ".html")
        titles = []
        for entry in bundle["entries"]:
            title = (entry.get("case") or {}).get("title")
            title = title if isinstance(title, str) and title.strip() else entry["trial_id"]
            if title not in titles:
                titles.append(title)
        record = {"source_key": source_key, "content_hash": content_hash,
                  "filename": snapshot.name, "latest": True,
                  "generated_at": now(), "kind": bundle["kind"],
                  "title": " / ".join(titles[:3]) or "空报告",
                  "counts": dict(Counter(entry["status"] for entry in bundle["entries"]))}
        write_html(snapshot, bundle)
        for old in catalog["reports"]:
            if old["source_key"] == source_key:
                old["latest"] = False
        catalog["reports"].append(record)
        write_json(directory / "catalog.json", catalog)
        _write_index(directory, catalog)
        return snapshot
