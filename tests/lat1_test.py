"""Video Manager — slice 1 guards: true status, honest writes, no token leak, dashboard theme.

Run:  python data/extensions_external/video_manager/tests/lat1_test.py   (exit 0 = pass)

Four personas scored the previous UI 21.5/100. The defects this file locks in
are the ones slice 1 fixes:

  1. Every finished YouTube video showed a red "PROCESSED" badge because the
     provider treated only uploadStatus="uploaded" as finished, while YouTube's
     terminal state is "processed". The edit modal then pre-filled its privacy
     <select> with a value it had no option for and saved privacy "".
  2. PUT/DELETE/thumbnail resolved the token from email/cred_id only, while the
     UI sends token_id — so with several accounts a write could run under a
     different account than the one on screen.
  3. GET /channels returned each Facebook Page's access_token verbatim inside
     extra — every Page token was handed to the browser.
  4. The page defined 16 private hex tokens the dashboard never injects, so it
     rendered dark cards with dark text inside the light theme.
"""
import os
import re
import sys
from pathlib import Path

EXT = Path(__file__).resolve().parent.parent
ROOT = EXT.parents[2]
for p in (str(ROOT), str(EXT)):
    if p not in sys.path:
        sys.path.insert(0, p)

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    if not ok:
        failures.append(f"{label}: {detail}")


print("=" * 70)
print("VIDEO MANAGER — SLICE 1")
print("=" * 70)

# ── 0. one version format ──────────────────────────────────────────────────
# compare_versions() (tubecli/core/extension_manager.py) compares each
# dot-segment as an integer, so mixing HH with HHMMSS inside one day INVERTS
# the order: 2026.08.28.14 (14:00) reads as older than 2026.08.28.081729
# (08:17), because 14 < 81729. This manifest has already worn three formats
# (1.0.0 semver, then .HHMM, then .HH), so the convention is asserted here and
# written down in README.md, not left to memory.
import json as _json                                    # noqa: E402

_manifest = _json.loads((EXT / "tubecli-extension.json").read_text(encoding="utf-8-sig"))
_ver = str(_manifest.get("version", ""))
check("the manifest version is YYYY.MM.DD.HHMMSS, zero-padded",
      re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.\d{6}", _ver) is not None, _ver)

# ── 1. status mapping ───────────────────────────────────────────────────────
from providers.youtube import video_manager as ytvm   # noqa: E402

def _item(upload_status, privacy="public"):
    return {"id": "abc", "snippet": {"title": "t"}, "statistics": {},
            "status": {"uploadStatus": upload_status, "privacyStatus": privacy},
            "contentDetails": {"duration": "PT1M"}}

parse = getattr(ytvm, "_parse_video_item", None) or getattr(ytvm, "_parse_video", None)
if parse is None:
    # find the module-level function that builds the unified dict
    for name in dir(ytvm):
        fn = getattr(ytvm, name)
        if callable(fn) and "unified" in (getattr(fn, "__code__", None).co_names if getattr(fn, "__code__", None) else ()):
            parse = fn
            break
check("the YouTube item parser is importable", parse is not None, dir(ytvm))
if parse:
    check("a PROCESSED (finished) video reports its privacy, not 'processed'",
          parse(_item("processed", "private"))["status"] == "private",
          parse(_item("processed", "private"))["status"])
    check("an UPLOADED video reports its privacy too",
          parse(_item("uploaded", "unlisted"))["status"] == "unlisted")
    check("a video still processing is reported as 'processing'",
          parse(_item("uploading", "public"))["status"] == "processing",
          parse(_item("uploading", "public"))["status"])
    for bad in ("failed", "rejected", "deleted"):
        check(f"'{bad}' stays a distinct state", parse(_item(bad, "public"))["status"] == bad)
    check("the raw privacy is still available in extra for older clients",
          parse(_item("processed", "public"))["extra"]["privacy_status"] == "public")

# ── 2. write routes resolve token_id like the reads ────────────────────────
import inspect                                          # noqa: E402
import routes as vm_routes                              # noqa: E402

for fn_name in ("update_video", "delete_video", "set_thumbnail"):
    fn = getattr(vm_routes, fn_name)
    params = inspect.signature(fn).parameters
    check(f"{fn_name} accepts token_id", "token_id" in params, list(params))
    src = inspect.getsource(fn)
    check(f"{fn_name} resolves cred_id or token_id (same as the reads)",
          "cred_id or token_id" in src, "resolves cred_id only")

# ── 3. Page access tokens never leave the server ───────────────────────────
pub = vm_routes._public_channel
d = pub({"id": "p1", "title": "Page", "extra": {"access_token": "EAAB-secret", "category": "Media"}})
check("_public_channel strips extra.access_token", "access_token" not in d["extra"], d)
check("…but keeps the harmless keys", d["extra"].get("category") == "Media", d)
check("_public_channel tolerates a channel with no extra", pub({"id": "x"})["id"] == "x")
src_routes = inspect.getsource(vm_routes)
check("every channel serialisation goes through _public_channel",
      "c.to_dict() for c in channels]" not in src_routes.replace("_public_channel(c.to_dict())", ""),
      "a raw to_dict() list survived")

# ── 4. the page uses the dashboard theme ───────────────────────────────────
# The contract moved on 28/8, when the dashboard stopped merely injecting a
# palette and started TELLING each iframe its theme (webui/static/app.js:
# themedSrc appends ?theme=, and syncThemeToIframe now OFFERS its tokens
# instead of imposing them, precisely so a page that declares light values of
# its own may keep them). This page answers that contract: a dark base :root,
# a full light override, and a pre-paint script that pins data-theme before
# the stylesheet applies.
#
# So these checks no longer allowlist hex VALUES — the light theme legitimately
# needs darker greens/oranges/reds than the dark one. The original defect, and
# what stays banned, is a colour literal sitting inside a RULE, where no theme
# block can reach it.
html = (EXT / "static" / "index.html").read_text(encoding="utf-8")


def _block(src, opener):
    """Return (block, src-without-block) for one brace-matched CSS block."""
    i = src.find(opener)
    if i < 0:
        return "", src
    depth, k = 0, src.find("{", i)
    while k < len(src):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    return src[i:k + 1], src[:i] + src[k + 1:]


def _tokens(block):
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block)}


style = re.search(r"<style>(.*?)</style>", html, re.S)
check("the page has a <style> block", style is not None)
css = style.group(1) if style else ""

dark_block, rest = _block(css, ":root {")
light_attr, rest = _block(rest, ':root[data-theme="light"] {')
light_media, rules = _block(rest, "@media (prefers-color-scheme: light) {")

check("a dark base :root exists", dark_block.startswith(":root {"), dark_block[:40])
check("a light override keyed on data-theme exists", bool(light_attr),
      'no :root[data-theme="light"] block')
check("a light media query covers the standalone page", bool(light_media),
      "no @media (prefers-color-scheme: light)")
check("the media query yields to an explicitly pinned dark theme",
      ':root:not([data-theme="dark"])' in light_media, light_media[:120])

# Colour literals left outside the theme blocks. These four are theme-neutral
# by nature: two brand-primary washes, white on the brand button, and the black
# duration chip that always sits over a video thumbnail.
NEUTRAL = {"#fff", "rgba(82,118,235,0.25)", "rgba(82,118,235,0.2)", "rgba(0,0,0,0.75)"}
literals = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)", rules)
stray = sorted({s.lower().replace(" ", "") for s in literals} - NEUTRAL)
check("no colour literal is baked into a rule — no theme block can reach one",
      not stray, stray)

# A token defined only on the light side resolves to nothing in the dark.
dark_tokens, light_tokens = _tokens(dark_block), _tokens(light_attr)
orphans = sorted(set(light_tokens) - set(dark_tokens))
check("every token the light theme overrides also has a dark value", not orphans, orphans)

# The file states the two light blocks are verbatim copies that must be edited
# together; CSS cannot share a declaration list, so this is the only guard.
check("the two light blocks stay in sync", _tokens(light_media) == light_tokens,
      sorted(set(_tokens(light_media).items()) ^ set(light_tokens.items())))

# color-scheme drives the UA chrome: scrollbars, <select> popups, date pickers.
check("the dark base declares color-scheme: dark", "color-scheme: dark" in dark_block,
      "dark page would keep light scrollbars and select popups")
check("both light paths declare color-scheme: light",
      "color-scheme: light" in light_attr and "color-scheme: light" in light_media)

check("the page relies on injected --bg/--bg2/--bg3/--text/--border tokens",
      all(f"var(--{t})" in html for t in ("bg", "bg2", "bg3", "text", "text-muted", "border", "primary")))

# Pre-paint. Without it an embedded page flashes dark inside a light dashboard,
# because syncThemeToIframe can only stamp data-theme after load.
# The pre-paint comment itself says "Runs BEFORE the page's <style>", so match
# the real tag at the start of a line, not the first mention of it.
head = html[:re.search(r"^<style>", html, re.M).start()]
check("a pre-paint script reads ?theme= before the stylesheet",
      "data-theme" in head and "location.search" in head, head[-160:])
check("…and it answers the dashboard's three spellings (glass/light/dark)",
      all(v in head for v in ("'glass'", "'light'", "'dark'")), "missing a theme value")
check("no emoji in the UI", not re.search(r"[\U0001F300-\U0001FAFF]", html))
check("provider tabs are real buttons with tab roles", 'role="tablist"' in html and 'role="tab"' in html)
check("dialogs are native <dialog> (Esc + focus trap for free)", html.count("<dialog") >= 3, html.count("<dialog"))
check("the prev/next pager is gone (it duplicated rows on the way back)",
      "loadPrevPage" not in html and "Trước" not in html)
check("load-more replaces it", "Tải thêm" in html and "page_token=" in html)
check("status pills read the real privacy with a fallback to extra.privacy_status",
      "extra.privacy_status" in html and "PROCESSED" not in html)
check("saveEdit sends only changed fields", "_editSnapshot" in html and "Object.keys(body).length" in html)
check("thumbnail POST result is checked, not fire-and-forget",
      "await apiJson(API(`/videos/${encodeURIComponent(id)}/thumbnail" in html)
check("delete uses a confirm dialog and removes the row without a full reload",
      "S.videos = S.videos.filter(v => v.id !== id)" in html)
check("upload cancel actually calls DELETE /upload/tasks", "/upload/tasks/${S.uploadTaskId}`), { method: 'DELETE' }" in html)
check("provider switch fully resets state", "function switchProvider" in html and "resetToAccount();" in html)
check("Auth Manager opens in a new tab, never window.location inside the iframe",
      'href="/auth-manager" target="_blank"' in html and "window.location.href='/auth-manager'" not in html)
check("toast uses textContent, not innerHTML", "span.textContent = msg" in html and "el.innerHTML = msg" not in html)
check("grid/table views both exist and the choice is remembered",
      "renderGrid" in html and "renderTable" in html and "localStorage.setItem('vm_view'" in html)
check("zero counts are shown (formatNumber never hides 0)", "Number(n || 0).toLocaleString" in html)
check("dialogs are centred — the universal margin:0 reset must not win over the UA dialog margin",
      re.search(r"^dialog \{[^}]*margin: auto", html, re.M) is not None,
      "dialog rule has no margin:auto -> box sits top-left")

# ── 5. served through the real app ─────────────────────────────────────────
os.environ.setdefault("TUBECLI_QUIET", "1")
from fastapi.testclient import TestClient               # noqa: E402
from tubecli.core import auth                           # noqa: E402
auth.check_request = lambda *a, **k: None
from tubecli.api.server import app                      # noqa: E402
client = TestClient(app, base_url="http://127.0.0.1:5295")
r = client.get("/video_manager")
check("the page is served", r.status_code == 200 and "Video Manager" in r.text, r.status_code)
check("…and it is the new page", "Đăng bằng tài khoản" in r.text and "PROCESSED" not in r.text)
r = client.get("/api/v1/video_manager/providers")
check("/providers answers", r.status_code == 200 and r.json().get("success") is True, r.status_code)
r = client.get("/api/v1/video_manager/accounts?provider=youtube")
check("/accounts answers (empty is fine on a box with no tokens)", r.status_code == 200, r.status_code)

print()
for f in failures:
    print("  FAIL", f)
print(f"{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
