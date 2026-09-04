"""Video Manager — the upload queue and the providers must agree on one signature.

Run:  python data/extensions_external/video_manager/tests/upload_queue_contract_test.py
      (exit 0 = pass)

The bug this file exists to keep dead:

    UploadQueue passed page_id=task.channel_id into provider_obj.upload_video().
    Facebook and TikTok had grown that parameter on their own; YouTube had not,
    and neither had the abstract signature in core/base_provider.py. So EVERY
    YouTube upload through POST /api/v1/video_manager/upload raised

        TypeError: upload_video() got an unexpected keyword argument 'page_id'

    …which the worker caught into task.error_message while the route had already
    answered 200 OK with a task_id, and extension.py had already told the agent
    "Video da duoc xep vao hang doi upload!". The user's Upload button and the
    agent action both looked fine and never uploaded anything.

The fix put page_id in the base signature (see the WHY there) instead of teaching
the queue which platforms take it. That only stays true if something checks, so
this file checks two ways:

  A. STATIC — the kwarg list is read out of upload_queue's own AST, never
     hardcoded here, and bound against every registered provider with
     inspect.getcallargs(). Add a kwarg to the queue that a provider does not
     take, or drop one a provider requires, and this fails without anyone having
     to remember to update the test.

  B. DYNAMIC — the queue is actually driven once per provider through
     enqueue(), with a fake token and a stand-in provider that binds against the
     REAL provider signature. A TypeError lands in task.error_message, so the
     run asserts every task reaches DONE.

Plus the rest of the same family of swallowed failures found while in here:
a cancelled task that uploaded anyway, a worker thread that died before its
try block and left the task spinning at 0% forever, and a task dict that never
grew past its first 20 finished entries because nothing called clear_finished.
"""
import ast
import inspect
import os
import sys
import tempfile
import threading
import time
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
print("VIDEO MANAGER - UPLOAD QUEUE / PROVIDER SIGNATURE CONTRACT")
print("=" * 70)

from core import provider_registry                         # noqa: E402
from core import token_resolver                            # noqa: E402
from core.base_provider import VideoProvider               # noqa: E402
from core import upload_queue as UQ                        # noqa: E402

PROVIDER_IDS = ("youtube", "facebook", "tiktok")


# ── A. what the queue actually passes, read from its own source ─────────────

def _upload_call_kwargs():
    """Pull the kwargs of the `*.upload_video(...)` call out of upload_queue's AST.

    Read, never hardcoded: the point is that a future edit to the queue is
    picked up here automatically instead of quietly drifting from the providers.
    """
    tree = ast.parse(inspect.getsource(UQ))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "upload_video"
    ]
    return calls


calls = _upload_call_kwargs()
check("upload_queue still calls provider.upload_video exactly once", len(calls) == 1, len(calls))

QUEUE_KWARGS = []
if calls:
    call = calls[0]
    check("the queue passes every argument by keyword (positional args would "
          "silently reorder when a provider inserts a parameter)",
          not call.args, [ast.dump(a) for a in call.args])
    check("the queue does not splat **kwargs (that would hide a mismatch)",
          all(kw.arg is not None for kw in call.keywords),
          [kw.arg for kw in call.keywords])
    QUEUE_KWARGS = [kw.arg for kw in call.keywords if kw.arg]

check("the queue still sends the destination as page_id (the crashing kwarg)",
      "page_id" in QUEUE_KWARGS, QUEUE_KWARGS)
check("…and the payload the providers need",
      {"file_path", "access_token", "title", "description", "tags",
       "category_id", "privacy", "progress_callback"} <= set(QUEUE_KWARGS),
      QUEUE_KWARGS)

DUMMY = {
    "file_path": "x.mp4",
    "access_token": "tok",
    "title": "t",
    "description": "d",
    "tags": ["a"],
    "category_id": "22",
    "privacy": "private",
    "progress_callback": (lambda done, total: None),
    "page_id": "CH1",
}


def _bind(fn, *args, **kwargs):
    """(ok, detail) — did these arguments bind to this signature?"""
    try:
        inspect.getcallargs(fn, *args, **kwargs)
        return True, ""
    except TypeError as e:
        return False, str(e)


# The base class is the contract; if it does not accept the call, no provider has
# to, and the next provider anyone writes will crash exactly like YouTube did.
ok, why = _bind(VideoProvider.upload_video, None, **{k: DUMMY[k] for k in QUEUE_KWARGS})
check("VideoProvider.upload_video (the abstract contract) accepts the queue's call",
      ok, why)

base_params = set(inspect.signature(VideoProvider.upload_video).parameters)

PROVIDER_CLASSES = {}
for pid in PROVIDER_IDS:
    try:
        obj = provider_registry.get(pid)
        PROVIDER_CLASSES[pid] = type(obj)
    except Exception as e:
        check(f"provider '{pid}' loads", False, e)

check("all three providers are registered",
      set(PROVIDER_CLASSES) == set(PROVIDER_IDS), sorted(PROVIDER_CLASSES))

for pid, cls in PROVIDER_CLASSES.items():
    fn = cls.upload_video
    ok, why = _bind(fn, None, **{k: DUMMY[k] for k in QUEUE_KWARGS})
    check(f"{pid}.upload_video accepts exactly what the queue passes", ok, why)

    params = inspect.signature(fn).parameters
    has_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    check(f"{pid}.upload_video names its parameters instead of hiding behind **kwargs "
          f"(a catch-all would swallow real typos forever)",
          not has_var_kw, list(params))
    check(f"{pid}.upload_video honours the base contract (no missing parameter)",
          base_params <= set(params), sorted(base_params - set(params)))

    # A provider must never *require* something the queue does not send, or the
    # queue can only ever drive it by accident.
    required = [
        n for n, p in params.items()
        if n != "self"
        and p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    ]
    check(f"{pid}.upload_video requires nothing the queue withholds",
          set(required) <= set(QUEUE_KWARGS), sorted(set(required) - set(QUEUE_KWARGS)))


# ── B. drive the queue for real, once per provider ──────────────────────────

class _StandIn:
    """A provider that talks to nothing but binds against the REAL signature.

    Calling the real class would need network + OAuth; hand-writing a fake
    signature would test nothing. So the stand-in accepts anything and then
    replays the call against the real provider's signature — a mismatch raises
    the very TypeError the real upload would have raised.
    """

    def __init__(self, real_cls):
        self.real_cls = real_cls
        self.calls = []

    def upload_video(self, **kwargs):
        inspect.getcallargs(self.real_cls.upload_video, self, **kwargs)
        self.calls.append(kwargs)
        cb = kwargs.get("progress_callback")
        if cb:
            cb(5, 10)
            cb(10, 10)
        return {
            "status": "success",
            "video_id": "vid123",
            "url": "https://example.invalid/watch?v=vid123",
            "message": "ok",
            "channel_id": kwargs.get("page_id", ""),
        }

    def set_thumbnail(self, video_id, thumbnail_path, access_token):
        return {"status": "success"}


_orig_get = provider_registry.get
_orig_resolve = token_resolver.resolve_token
stand_ins = {}


def _fake_get(provider_id):
    return stand_ins[provider_id]


def _wait(task, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if task.finished_at:
            return True
        time.sleep(0.02)
    return False


tmpdir = tempfile.mkdtemp(prefix="vm_queue_test_")
video = os.path.join(tmpdir, "clip.mp4")
with open(video, "wb") as f:
    f.write(b"\0" * 2048)

provider_registry.get = _fake_get
token_resolver.resolve_token = lambda **kw: "fake-access-token"
try:
    q = UQ.UploadQueue(max_workers=3)
    tasks = {}
    for pid, cls in PROVIDER_CLASSES.items():
        stand_ins[pid] = _StandIn(cls)
        tasks[pid] = q.enqueue(
            provider=pid, email="a@b.c", cred_id="tok_1", channel_id="CH1",
            file_path=video, title="Title", description="Desc",
            tags=["x"], category_id="22", privacy="public",
        )

    for pid, t in tasks.items():
        check(f"the queue finishes a {pid} upload", _wait(t), "timed out")
        check(f"a {pid} upload reaches DONE, not ERROR "
              f"(a signature mismatch surfaces here as a TypeError)",
              t.status == UQ.UploadStatus.DONE,
              f"{t.status} / {t.error_message}")
        check(f"the {pid} provider was actually called once",
              len(stand_ins[pid].calls) == 1, len(stand_ins[pid].calls))
        if stand_ins[pid].calls:
            sent = stand_ins[pid].calls[0]
            check(f"the {pid} call carried the destination through",
                  sent.get("page_id") == "CH1", sent.get("page_id"))
        check(f"a finished {pid} task reports its video URL",
              t.video_url.endswith("vid123") and t.progress_pct == 100,
              (t.video_url, t.progress_pct))
        check(f"to_dict() of a {pid} task names the destination it aimed at",
              t.to_dict().get("channel_id") == "CH1", t.to_dict().get("channel_id"))

    # ── a provider that answers "error" must not be reported as done ─────────
    class _Refuses(_StandIn):
        def upload_video(self, **kwargs):
            inspect.getcallargs(self.real_cls.upload_video, self, **kwargs)
            return {"status": "error", "message": "quota exceeded"}

    stand_ins["youtube"] = _Refuses(PROVIDER_CLASSES["youtube"])
    t = q.enqueue(provider="youtube", email="a@b.c", cred_id="tok_1", channel_id="CH1",
                  file_path=video, title="T", description="")
    _wait(t)
    check("a provider-reported failure becomes ERROR", t.status == UQ.UploadStatus.ERROR, t.status)
    check("…and its reason reaches the user through to_dict().error_message "
          "(the UI renders exactly this field)",
          "quota exceeded" in t.to_dict().get("error_message", ""), t.to_dict())

    # ── a provider returning None must not crash the worker ─────────────────
    class _ReturnsNone(_StandIn):
        def upload_video(self, **kwargs):
            inspect.getcallargs(self.real_cls.upload_video, self, **kwargs)
            return None

    stand_ins["youtube"] = _ReturnsNone(PROVIDER_CLASSES["youtube"])
    t = q.enqueue(provider="youtube", email="a@b.c", cred_id="tok_1", channel_id="CH1",
                  file_path=video, title="T", description="")
    _wait(t)
    check("a provider returning None is an ERROR, not an AttributeError that "
          "kills the worker thread", t.status == UQ.UploadStatus.ERROR, t.status)

    # ── cancel before the first byte ─────────────────────────────────────────
    # cancel_task() used to only set a flag; the worker then overwrote the status
    # and uploaded anyway, because the flag is read inside progress_callback and a
    # small file is sent in one chunk before any progress fires.
    stand_ins["youtube"] = _StandIn(PROVIDER_CLASSES["youtube"])
    solo = UQ.UploadQueue(max_workers=1)
    blocked = threading.Event()
    released = threading.Event()

    class _Blocks(_StandIn):
        def upload_video(self, **kwargs):
            blocked.set()
            released.wait(10)
            return super().upload_video(**kwargs)

    stand_ins["facebook"] = _Blocks(PROVIDER_CLASSES["facebook"])
    hog = solo.enqueue(provider="facebook", email="a@b.c", cred_id="t", channel_id="P1",
                       file_path=video, title="hog", description="")
    blocked.wait(10)
    queued = solo.enqueue(provider="youtube", email="a@b.c", cred_id="t", channel_id="CH1",
                          file_path=video, title="queued", description="")
    check("the second task really is still QUEUED", queued.status == UQ.UploadStatus.QUEUED,
          queued.status)
    solo.cancel_task(queued.task_id)
    released.set()
    _wait(hog)
    _wait(queued)
    check("a task cancelled while queued stays CANCELLED",
          queued.status == UQ.UploadStatus.CANCELLED, queued.status)
    check("a task cancelled while queued never reaches the provider "
          "(it used to upload the whole video anyway)",
          len(stand_ins["youtube"].calls) == 0, stand_ins["youtube"].calls)
    solo.shutdown()

    # ── the worker's own setup must not be able to kill the thread ───────────
    # os.path.getsize() sat outside the try. Delete the file between enqueue and
    # the worker starting and the exception vanished into an un-awaited Future:
    # the task stayed UPLOADING at 0% forever, the SSE stream never closed
    # (it closes only on done/error/cancelled) and error_message stayed empty.
    gone = os.path.join(tmpdir, "vanished.mp4")
    ghost = UQ.UploadTask(task_id="ghost", provider="youtube", email="a@b.c",
                          cred_id="t", file_path=gone, title="T", channel_id="CH1")
    q._run_upload(ghost)
    check("a file that disappears after enqueue ends as ERROR, not a task wedged "
          "at 'uploading' with nothing to show",
          ghost.status == UQ.UploadStatus.ERROR, ghost.status)
    check("…with a message the user can read", bool(ghost.error_message), ghost.error_message)
    check("…and it is marked finished so the SSE stream closes",
          bool(ghost.finished_at), ghost.finished_at)

    # ── subscribers are read from a snapshot ────────────────────────────────
    # _broadcast() iterated task._subscribers while subscribe() appended to it
    # from the request thread; a RuntimeError thrown there kills the worker.
    src_bcast = inspect.getsource(UQ.UploadQueue._broadcast)
    check("_broadcast copies the subscriber list under the lock before iterating",
          "with self._lock" in src_bcast and "list(task._subscribers)" in src_bcast,
          src_bcast)

    # ── finished tasks are trimmed ──────────────────────────────────────────
    check("_run_upload trims the task dict (clear_finished had no caller at all)",
          "clear_finished" in inspect.getsource(UQ.UploadQueue._run_upload),
          "clear_finished is still dead code")
    check("the trim depth is at least the UI's page size, so nothing visible is cut",
          UQ.FINISHED_HISTORY >= 50, UQ.FINISHED_HISTORY)
    trimmer = UQ.UploadQueue(max_workers=1)
    for i in range(5):
        tk = UQ.UploadTask(task_id=f"t{i}", provider="youtube", email="", cred_id="",
                           file_path=video, title="x")
        tk.status = UQ.UploadStatus.DONE
        tk.finished_at = f"2026-09-04T00:00:0{i}"
        trimmer._tasks[tk.task_id] = tk
    trimmer.clear_finished(keep_last=2)
    check("clear_finished keeps the newest N and drops the rest",
          sorted(trimmer._tasks) == ["t3", "t4"], sorted(trimmer._tasks))
    trimmer.shutdown()

    q.shutdown()
finally:
    provider_registry.get = _orig_get
    token_resolver.resolve_token = _orig_resolve
    try:
        os.remove(video)
        os.rmdir(tmpdir)
    except OSError:
        pass


# ── C. the YouTube side of the original crash ───────────────────────────────
# YouTube cannot choose a channel (videos.insert has no destination field), so it
# accepts page_id and ignores it — but it must say where the video actually
# landed, or a misrouted upload is invisible to every caller.
from providers.youtube import uploader as yt_uploader       # noqa: E402

yt_params = inspect.signature(PROVIDER_CLASSES["youtube"].upload_video).parameters
check("YouTubeProvider.upload_video takes page_id (this is the regression)",
      "page_id" in yt_params, list(yt_params))
check("…and documents that it ignores it rather than dropping it silently",
      "ignore" in (PROVIDER_CLASSES["youtube"].upload_video.__doc__ or "").lower(),
      PROVIDER_CLASSES["youtube"].upload_video.__doc__)
check("…while the low-level uploader stays page_id-free (it is called directly "
      "by the auto-publish pipeline and has no use for it)",
      "page_id" not in inspect.signature(yt_uploader.upload_video).parameters,
      list(inspect.signature(yt_uploader.upload_video).parameters))
check("the YouTube uploader reports the channel the video really landed on",
      "channelId" in inspect.getsource(yt_uploader.upload_video)
      and '"channel_id"' in inspect.getsource(yt_uploader.upload_video),
      "no channel_id in the success dict")
check("the queue notices when the video landed on another channel",
      "landed_on" in inspect.getsource(UQ.UploadQueue._do_upload),
      "no post-upload channel check")

print()
for f in failures:
    print("  FAIL", f)
print(f"{checks - len(failures)}/{checks} PASS")
sys.exit(1 if failures else 0)
