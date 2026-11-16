"""Read Gemini conversations through a dedicated Chrome profile.

Why a dedicated profile
-----------------------
Google ties a signed-in session to the device/profile that created it
(Device Bound Session Credentials) and Chrome encrypts cookies with App-Bound
Encryption, so copying a profile logs you out.  Chrome 136+ also refuses
``--remote-debugging-port`` when the *default* user-data-dir is used.  The only
reliable automation path is therefore a profile that chatblog owns:

1. the user presses "登入 Gemini" in the GUI once; a normal Chrome window opens
   (no automation flags) and they sign in,
2. after that, every scan launches the same profile headless with a debugging
   port and drives it over CDP.

The profile lives outside the repository (``%LOCALAPPDATA%\\chatblog``) and is
never committed.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

from .models import Conversation, DialogNode, ImageAttachment

GEMINI_APP = "https://gemini.google.com/app"
DEFAULT_PORT = 9333
DEFAULT_TIMEOUT_MS = 45_000

_LOGIN_HOSTS = ("accounts.google.com",)


class GeminiError(RuntimeError):
    """Base error for the browser-backed Gemini source."""


class GeminiNotLoggedIn(GeminiError):
    """The managed profile has no usable Google session."""


class GeminiBrowserError(GeminiError):
    """Chrome could not be started or reached."""


# ---------------------------------------------------------------------------
# Paths and process management
# ---------------------------------------------------------------------------


def default_profile_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "chatblog" / "chrome-profile"
    return Path.home() / ".local" / "share" / "chatblog" / "chrome-profile"


def chrome_executable() -> str:
    override = os.environ.get("CHATBLOG_CHROME") or os.environ.get("CHROME_PATH")
    if override and Path(override).is_file():
        return override

    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    ]
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    found = shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium")
    if found:
        return found
    raise GeminiBrowserError("找不到 Chrome，請設定 CHATBLOG_CHROME 指到 chrome.exe")


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.6)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def cdp_version(port: int, timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


def free_port(preferred: int = DEFAULT_PORT) -> int:
    for port in range(preferred, preferred + 40):
        if _port_open(port):
            info = cdp_version(port)
            if info and "Chrome" in str(info.get("Browser", "")):
                return port  # someone else's Chrome, keep looking? no: reuse is unsafe
            continue
        return port
    return preferred


def launch_chrome(
    profile_dir: Path,
    port: int,
    url: str = "about:blank",
    *,
    headless: bool = False,
    width: int = 1440,
    height: int = 960,
    wait_seconds: float = 25.0,
) -> None:
    """Start Chrome with the chatblog profile and a CDP port."""
    if _port_open(port) and cdp_version(port):
        return
    profile_dir.mkdir(parents=True, exist_ok=True)
    executable = chrome_executable()
    args = [
        executable,
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-service-autorun",
        "--disable-search-engine-choice-screen",
        "--disable-features=Translate,MediaRouter",
        f"--window-size={width},{height}",
        "--window-position=80,60",
    ]
    if headless:
        args.append("--headless=new")
    args.append(url)

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if cdp_version(port):
            # Remember the PID so a headless instance can be killed even when
            # CDP refuses to shut it down; a forwarded launch exits at once and
            # must not clobber the PID of the process that owns the port.
            if process.poll() is None:
                try:
                    (profile_dir / PID_FILE).write_text(str(process.pid), encoding="utf-8")
                except OSError:
                    pass
            return
        time.sleep(0.35)
    raise GeminiBrowserError(
        "Chrome 沒有在 25 秒內開放除錯埠。"
        "如果已經有一個使用 chatblog profile 的 Chrome 視窗開著，請先關閉它再試。"
    )


PID_FILE = "chatblog.pid"


def _kill_by_pid_file(profile_dir: Path) -> bool:
    pid_file = profile_dir / PID_FILE
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        else:
            os.kill(pid, 15)
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            pid_file.unlink()
        except OSError:
            pass
    return True


def _kill_by_profile_scan(profile_dir: Path) -> bool:
    """Last resort: kill chrome.exe processes whose command line names our profile."""
    if os.name != "nt":
        return False
    needle = str(profile_dir).replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{needle}*' }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def stop_chrome(port: int, profile_dir: Path | None = None) -> bool:
    """Shut down the managed Chrome.

    Playwright's ``Browser.close()`` only *disconnects* from a browser obtained
    through ``connect_over_cdp``; it does not terminate it.  The CDP command
    does, and a PID/profile fallback covers the cases where it does not.
    """
    if not cdp_version(port):
        return False
    try:
        with _playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            try:
                session = browser.new_browser_cdp_session()
                session.send("Browser.close")
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 - fall through to the process fallbacks
        pass

    deadline = time.time() + 5
    while time.time() < deadline:
        if not cdp_version(port):
            return True
        time.sleep(0.2)

    if profile_dir is not None:
        _kill_by_pid_file(profile_dir) or _kill_by_profile_scan(profile_dir)
        deadline = time.time() + 6
        while time.time() < deadline:
            if not cdp_version(port):
                return True
            time.sleep(0.25)
    return False


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------


@contextmanager
def _playwright():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        yield playwright


@contextmanager
def browser_page(
    profile_dir: Path,
    port: int = DEFAULT_PORT,
    *,
    headless: bool = True,
    url: str = "about:blank",
) -> Iterator[object]:
    """Attach to the managed Chrome and yield one page (browser stays open)."""
    if not (cdp_version(port) or _port_open(port)):
        launch_chrome(profile_dir, port, url, headless=headless)
    elif not cdp_version(port):
        raise GeminiBrowserError(f"埠 {port} 被其他程式佔用")

    with _playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        contexts = browser.contexts
        context = contexts[0] if contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield page
        finally:
            # Dropping the CDP connection leaves the Chrome process alive.
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass


def open_for_login(profile_dir: Path, port: int = DEFAULT_PORT) -> None:
    """Open a visible Chrome window on Gemini so the user can sign in."""
    # A headless scan may still hold the profile/port; close it so a real
    # window can appear (a second launch with the same profile would just
    # forward the URL to the existing headless process).
    stop_chrome(port, profile_dir)
    launch_chrome(profile_dir, port, GEMINI_APP, headless=False)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@dataclass
class GeminiListItem:
    chat_id: str
    title: str
    group: str = ""
    approx_date: datetime | None = None
    #: Real last-modified time from the app's own conversation list RPC.
    updated_at: datetime | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.chat_id,
            "title": self.title,
            "group": self.group,
            "approx_date": self.approx_date.isoformat(timespec="seconds") if self.approx_date else "",
            "updated_at": self.updated_at.isoformat(timespec="seconds") if self.updated_at else "",
            "created_at": self.created_at.isoformat(timespec="seconds") if self.created_at else "",
        }


_SCROLL_JS = r"""
() => {
  const anchors = document.querySelectorAll('a[href*="/app/"]');
  const first = anchors[0];
  let el = first;
  let scroller = null;
  while (el && el !== document.body) {
    const style = getComputedStyle(el);
    if (/(auto|scroll)/.test(style.overflowY)) { scroller = el; break; }
    el = el.parentElement;
  }
  if (scroller) scroller.scrollTop = scroller.scrollHeight;
  window.scrollTo(0, document.body.scrollHeight);
  // Gemini sometimes hides the rest behind a "Show more" button.
  const more = Array.from(document.querySelectorAll('button'))
    .find(b => /(show more|顯示更多|显示更多|更多)/i.test((b.innerText || '').trim()));
  if (more) { try { more.click(); } catch (e) {} }
  return {items: anchors.length, scroller: !!scroller};
}
"""

_LIST_JS = r"""
() => {
  const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
  const anchors = Array.from(document.querySelectorAll('a[href*="/app/"]'));
  if (!anchors.length) return {items: [], sidebar: false};

  // Prefer the narrow scroll container that holds the anchors (the sidebar).
  let sidebar = anchors[0];
  while (sidebar && sidebar !== document.body) {
    const style = getComputedStyle(sidebar);
    const rect = sidebar.getBoundingClientRect();
    if (/(auto|scroll)/.test(style.overflowY) && rect.width > 120 && rect.width < 620) break;
    sidebar = sidebar.parentElement;
  }
  if (!sidebar || sidebar === document.body) sidebar = document.body;

  const nodes = Array.from(sidebar.querySelectorAll(
    'a[href*="/app/"], h1, h2, h3, h4, [role="heading"], [data-test-id*="section"]'
  ));
  let group = '';
  const seen = new Map();
  for (const node of nodes) {
    if (node.tagName !== 'A') {
      const text = clean(node.innerText);
      if (text && text.length < 40) group = text;
      continue;
    }
    const href = node.getAttribute('href') || '';
    const match = href.match(/\/app\/([0-9a-zA-Z_-]{8,})/);
    if (!match) continue;
    const id = match[1];
    const title = clean(node.getAttribute('aria-label') || node.innerText || node.textContent);
    if (!title || title.length > 300) continue;
    const existing = seen.get(id);
    if (!existing) seen.set(id, {id, title, group});
  }
  return {items: Array.from(seen.values()), sidebar: true};
}
"""


def _group_to_date(group: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now()
    text = (group or "").strip().lower()
    if not text:
        return None
    if "今天" in text or "today" in text:
        return now
    if "昨天" in text or "yesterday" in text:
        return now - timedelta(days=1)
    if "7" in text or "week" in text or "週" in text or "周" in text:
        return now - timedelta(days=3)
    if "30" in text or "month" in text or "個月" in text or "个月" in text:
        return now - timedelta(days=15)

    for pattern in ("%Y年%m月", "%Y年%-m月", "%B %Y", "%Y-%m"):
        try:
            parsed = datetime.strptime(group.strip(), pattern)
            return parsed.replace(day=15, hour=12)
        except ValueError:
            continue
    return None


_SIGNED_OUT_JS = """
() => {
  if (document.querySelector('[data-test-id="signed-out-disclaimer"]')) return true;
  if (document.querySelector('[data-test-id="sidenav-error-message"]')) return true;
  const link = document.querySelector('a[href*="accounts.google.com/ServiceLogin"]');
  return !!link && !document.querySelector('[data-test-id="chat-history-container"] a[href*="/app/"]');
}
"""


def is_logged_in(page) -> bool:
    """Signed-in detection that works for Gemini's signed-out app shell.

    A signed-out browser is *not* redirected to accounts.google.com: Gemini
    renders the normal app with a "Sign in to save activity" banner and a
    ``signed-out-disclaimer`` node.  Treating that shell as "logged in" is what
    made the first scan return zero conversations and claim success.
    """
    host = page.url.split("/")[2] if "//" in page.url else ""
    if any(host == login_host for login_host in _LOGIN_HOSTS):
        return False
    try:
        return not bool(page.evaluate(_SIGNED_OUT_JS))
    except Exception:  # noqa: BLE001 - if the probe fails, assume signed in
        return True


def _goto_app(page, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> None:
    page.goto(GEMINI_APP, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(2500)
    if not is_logged_in(page):
        raise GeminiNotLoggedIn(
            "Gemini 未登入（看到「Sign in to save activity」）。"
            "請在 GUI 按「登入 Gemini」，在彈出的 Chrome 視窗登入 Google 後再試。"
        )


#: The app's own conversation-list RPC (``MaZiqc``). Scrolling the sidebar is
#: lossy and carries no dates; this returns up to 100 rows with real
#: last-modified timestamps in one request.
_LIST_RPC_JS = """
async (count) => {
  const data = window.WIZ_global_data || {};
  const at = data.SNlM0e;
  if (!at) return null;
  const inner = JSON.stringify([
    count, null, [null, null, 1, null, null, null, null, null, null, 1],
  ]);
  const freq = JSON.stringify([[["MaZiqc", inner, null, "generic"]]]);
  const url =
    location.origin +
    "/_/BardChatUi/data/batchexecute?rpcids=MaZiqc&source-path=%2Fapp&rt=c";
  const body = new URLSearchParams({"f.req": freq, "at": at}).toString();
  const resp = await fetch(url, {
    method: "POST",
    headers: {"content-type": "application/x-www-form-urlencoded;charset=UTF-8"},
    body,
    credentials: "include",
  });
  if (!resp.ok) return null;
  return await resp.text();
}
"""


def _rpc_payload(text: str, rpc_id: str = "MaZiqc") -> str:
    """Pull one RPC's JSON string out of a ``batchexecute`` response."""
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("[["):
            continue
        try:
            entries = json.loads(line)
        except ValueError:
            continue
        for entry in entries:
            if (
                isinstance(entry, list)
                and len(entry) > 2
                and entry[1] == rpc_id
                and isinstance(entry[2], str)
            ):
                return entry[2]
    return ""


def _conversation_rows(node, found: list | None = None) -> list:
    found = [] if found is None else found
    if isinstance(node, list):
        if node and isinstance(node[0], str) and node[0].startswith("c_"):
            found.append(node)
            return found
        for child in node:
            _conversation_rows(child, found)
    return found


def parse_conversation_list(text: str) -> list[GeminiListItem]:
    """Turn a raw ``MaZiqc`` response into items with real timestamps."""
    payload = _rpc_payload(text)
    if not payload:
        return []
    try:
        data = json.loads(payload)
    except ValueError:
        return []
    items: list[GeminiListItem] = []
    seen: set[str] = set()
    for row in _conversation_rows(data):
        chat_id = str(row[0]).removeprefix("c_")
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        stamp = row[5] if len(row) > 5 and isinstance(row[5], list) else []
        seconds = stamp[0] if stamp and isinstance(stamp[0], (int, float)) else None
        updated = datetime.fromtimestamp(seconds) if seconds else None
        items.append(
            GeminiListItem(
                chat_id=chat_id,
                title=str(row[1] or "未命名對話"),
                updated_at=updated,
            )
        )
    return items


def list_conversations(
    page, *, limit: int = 100, max_rounds: int = 14, pause_ms: int = 700
) -> list[GeminiListItem]:
    """Scroll the Gemini sidebar until every conversation is loaded."""
    if not is_logged_in(page):
        raise GeminiNotLoggedIn(
            "Gemini 未登入，看不到對話列表。請先在 GUI 按「登入 Gemini」。"
        )
    try:
        raw = page.evaluate(_LIST_RPC_JS, max(limit, 100))
    except Exception:  # noqa: BLE001 - fall back to the sidebar
        raw = None
    if isinstance(raw, str) and raw:
        items = parse_conversation_list(raw)
        if items:
            items.sort(key=lambda item: item.updated_at or datetime.min, reverse=True)
            return items[:limit]

    stable = 0
    previous = -1
    for _ in range(max_rounds):
        try:
            page.evaluate(_SCROLL_JS)
        except Exception:  # noqa: BLE001 - sidebar may be re-rendered
            pass
        page.wait_for_timeout(pause_ms)
        try:
            payload = page.evaluate(_LIST_JS)
        except Exception:  # noqa: BLE001
            payload = {"items": []}
        count = len(payload.get("items") or [])
        if count == previous:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
            previous = count

    items: list[GeminiListItem] = []
    now = datetime.now()
    for raw in payload.get("items") or []:  # type: ignore[possibly-undefined]
        chat_id = str(raw.get("id") or "")
        if not chat_id:
            continue
        group = str(raw.get("group") or "")
        items.append(
            GeminiListItem(
                chat_id=chat_id,
                title=str(raw.get("title") or "未命名對話"),
                group=group,
                approx_date=_group_to_date(group, now),
            )
        )
    return items


# ---------------------------------------------------------------------------
# Conversation scraping
# ---------------------------------------------------------------------------

_REMOVE_SELECTORS = ",".join(
    [
        "source-footnote",
        "sources-carousel-inline",
        "source-inline-chip",
        "follow-up",
        ".follow-up-container",
        ".response-container-header",
        ".message-actions",
        "tts",
        "button",
        "mat-icon",
        "gem-icon",
        "script",
        "style",
    ]
)

_FETCH_JS = r"""
() => {
  const clean = (text) => (text || '').replace(/\u00a0/g, ' ').replace(/\u202f/g, ' ').trim();
  // innerText is layout dependent: in a background tab (or before paint) it
  // can be empty, which silently dropped the user's message. Fall back to
  // textContent, which only needs the DOM.
  const textOf = (node) => {
    if (!node) return '';
    const visible = node.innerText || '';
    return clean(visible.trim() ? visible : node.textContent || '');
  };
  const removeSelectors = __REMOVE__;

  const responseHtml = (response) => {
    if (!response) return '';
    const panel = response.querySelector('message-content .markdown')
      || response.querySelector('message-content')
      || response.querySelector('.markdown');
    if (!panel) return '';
    const clone = panel.cloneNode(true);
    clone.querySelectorAll(removeSelectors).forEach((node) => node.remove());
    return clone.innerHTML;
  };

  const readUser = (uq) => {
    const lines = Array.from(uq.querySelectorAll('p.query-text-line'))
      .map((node) => textOf(node)).filter(Boolean);
    if (lines.length) return lines.join('\n\n');
    return textOf(uq).replace(/^You said\s*/i, '').trim();
  };

  const readImages = (response) => {
    if (!response) return [];
    return Array.from(response.querySelectorAll('img')).map((img) => {
      const figure = img.closest('figure');
      const caption = figure && figure.querySelector('figcaption');
      return {
        url: img.currentSrc || img.src || '',
        alt: clean(img.alt || ''),
        caption: clean(textOf(caption) || img.alt || ''),
        width: img.naturalWidth || img.width || 0,
        height: img.naturalHeight || img.height || 0,
      };
    }).filter((image) => image.url && image.width >= 80 && image.height >= 60);
  };

  const userQueries = Array.from(document.querySelectorAll('user-query'));
  const responses = Array.from(document.querySelectorAll('model-response'));
  const turns = userQueries.map((uq, index) => {
    const response = responses[index] || null;
    return {
      user: readUser(uq),
      html: responseHtml(response),
      images: readImages(response),
    };
  }).filter((turn) => turn.user || turn.html);

  if (!turns.length) {
    const containers = Array.from(document.querySelectorAll('conversation-container'));
    for (const container of containers) {
      const uq = container.querySelector('user-query');
      const mr = container.querySelector('model-response');
      if (!uq && !mr) continue;
      turns.push({
        user: uq ? readUser(uq) : '',
        html: responseHtml(mr),
        images: readImages(mr),
      });
    }
  }

  return {
    title: document.title || '',
    url: location.href,
    turns,
    bodyLength: (document.body && document.body.innerText || '').length,
  };
}
""".replace("__REMOVE__", json.dumps(_REMOVE_SELECTORS))


def _load_all_turns(page, rounds: int = 10, pause_ms: int = 500) -> int:
    previous = -1
    stable = 0
    count = 0
    for _ in range(rounds):
        try:
            page.evaluate(
                """() => {
                  const scrollers = [];
                  document.querySelectorAll('*').forEach((el) => {
                    const style = getComputedStyle(el);
                    if (/(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 200
                        && el.querySelector('user-query')) scrollers.push(el);
                  });
                  scrollers.forEach((el) => { el.scrollTop = 0; });
                  window.scrollTo(0, 0);
                }"""
            )
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(pause_ms)
        try:
            count = page.evaluate("() => document.querySelectorAll('user-query').length")
        except Exception:  # noqa: BLE001
            count = 0
        if count == previous:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
            previous = count
    return count


def fetch_conversation(
    page,
    chat_id: str,
    *,
    approx_date: datetime | None = None,
    debug_dir: Path | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Conversation:
    """Open ``/app/<chat_id>`` and turn the rendered DOM into a Conversation."""
    url = f"https://gemini.google.com/app/{chat_id}"
    # ``domcontentloaded`` can hang for a minute on a busy profile (the app
    # streams long-lived requests). Waiting for the commit and then for the
    # transcript selector is both faster and steadier.
    for attempt in (1, 2):
        try:
            page.goto(url, wait_until="commit", timeout=timeout_ms)
            break
        except Exception:  # noqa: BLE001
            if attempt == 2:
                raise
    if any(host in page.url for host in _LOGIN_HOSTS):
        raise GeminiNotLoggedIn("Gemini 未登入，請先在 GUI 登入。")
    try:
        page.wait_for_selector("user-query", timeout=min(timeout_ms, 30_000))
    except Exception:  # noqa: BLE001 - empty/new conversations still need a chance
        pass
    page.wait_for_timeout(1500)
    _load_all_turns(page)
    page.wait_for_timeout(600)

    payload = page.evaluate(_FETCH_JS)
    if not payload.get("turns"):
        # A conversation created moments ago sometimes serves the app shell
        # first and fills the transcript on the second load. One reload is
        # cheap; a false "can't scrape" error is not.
        try:
            page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_selector("user-query", timeout=min(timeout_ms, 20_000))
            page.wait_for_timeout(1200)
            _load_all_turns(page)
            page.wait_for_timeout(600)
            payload = page.evaluate(_FETCH_JS)
        except Exception:  # noqa: BLE001 - keep the original, empty payload
            pass

    turns = payload.get("turns") or []
    if not turns:
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            (debug_dir / f"gemini-{stamp}-{chat_id}.html").write_text(
                page.content(), encoding="utf-8", errors="replace"
            )
        raise GeminiError(
            "抓不到對話內容（DOM 可能是空的或選確定變了）。已把 HTML 存到 .chatblog/debug 方便除錯。"
        )

    title = str(payload.get("title") or "").strip()
    for suffix in (" - Gemini", " - Google Gemini", " – Gemini"):
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    if not title or title.lower() in ("google gemini", "gemini"):
        title = "Gemini 對話"

    moments = [approx_date] if approx_date else []
    messages: dict[str, DialogNode] = {}
    previous_id: str | None = None
    images: list[ImageAttachment] = []

    def add(node_id: str, role: str, content: str, **extra) -> None:
        nonlocal previous_id
        messages[node_id] = DialogNode(
            id=node_id,
            role=role,
            content=content,
            parent_id=previous_id,
            children_ids=[],
            timestamp=approx_date,
            **extra,
        )
        if previous_id and previous_id in messages:
            messages[previous_id].children_ids = [node_id]
        previous_id = node_id

    for index, turn in enumerate(turns, 1):
        user_text = str(turn.get("user") or "").strip()
        html = str(turn.get("html") or "").strip()
        attachments = [
            ImageAttachment(
                url=str(image.get("url") or ""),
                alt=str(image.get("alt") or ""),
                caption=str(image.get("caption") or image.get("alt") or ""),
                source_url=str(image.get("url") or ""),
            )
            for image in turn.get("images") or []
            if str(image.get("url") or "").startswith(("http", "data:"))
        ]
        images.extend(attachments)
        # A turn can be half-rendered (the answer is still streaming, or the
        # reply is an image only). Only emit nodes that carry something, so
        # message_count matches the bubbles a reader sees.
        if user_text:
            add(f"turn-{index}-user", "user", user_text)
        if html or attachments:
            add(
                f"turn-{index}-assistant",
                "assistant",
                html,
                content_format="html",
                model_name="Gemini",
                attachments=attachments,
            )

    if not messages:
        raise GeminiError("對話沒有可用的訊息")

    return Conversation(
        source_provider="gemini",
        source_chat_id=chat_id,
        title=title,
        root_id="turn-1-user",
        created_at=approx_date,
        updated_at=approx_date,
        messages=messages,
        tags=["AI对话", "Gemini"],
    )


def download_images(page, conversation: Conversation, max_bytes: int = 8 * 1024 * 1024) -> int:
    """Inline authenticated Gemini images as data URLs for the asset writer."""
    import base64

    count = 0
    for node in conversation.messages.values():
        for attachment in node.attachments:
            url = attachment.url
            if url.startswith("data:"):
                count += 1
                continue
            try:
                response = page.request.get(url, timeout=30_000)
                if not response.ok:
                    continue
                body = response.body()
                if not body or len(body) > max_bytes:
                    continue
                mime = (response.headers.get("content-type") or "image/jpeg").split(";")[0]
                attachment.url = f"data:{mime};base64,{base64.b64encode(body).decode('ascii')}"
                count += 1
            except Exception:  # noqa: BLE001 - a missing image must not kill the post
                continue
    return count


def profile_status(profile_dir: Path, port: int = DEFAULT_PORT) -> dict:
    running = bool(cdp_version(port))
    return {
        "profile": str(profile_dir),
        "profile_exists": profile_dir.is_dir(),
        "port": port,
        "running": running,
        "chrome": "",
    }
