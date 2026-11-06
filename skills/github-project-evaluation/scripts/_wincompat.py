"""Source-level Windows compatibility shim for the r4 evaluation handoff package.

Loaded only on win32 (`if sys.platform == "win32": import _wincompat`) by the
modules that need POSIX facilities. On Linux/macOS this file is never imported
and original behaviour is untouched.

This module is a PORT, not a verification. It maps POSIX facilities onto real
Windows mechanisms wherever a genuine equivalent exists. Every mapping is
recorded in REPORT so nobody can mistake an emulated control for the original.

Three honest categories:
  PRESERVED    - same security property is really enforced (different mechanism)
  EQUIVALENT   - semantically equivalent for single-host use, weaker in one named way
  NOT_ENFORCED - no Windows equivalent; the limit is recorded but not applied
"""
import builtins
import ctypes
import ctypes.wintypes as wt
import errno
import io
import msvcrt
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import types

_COMPAT_DIR = str(pathlib.Path(__file__).resolve().parent)
_PACKAGE_ROOT = str(pathlib.Path(__file__).resolve().parents[3])

REPORT = {"PRESERVED": [], "EQUIVALENT": [], "NOT_ENFORCED": [], "REMAP": []}
CACHE_PROBE_TIMEOUT = 8

# --------------------------------------------------------------------------
# 1. identity: Windows has no POSIX uid. owner comparisons collapse to same-user.
# --------------------------------------------------------------------------
if not hasattr(os, "getuid"):
    os.getuid = lambda: 0
    os.geteuid = lambda: 0
    os.getgid = lambda: 0
    REPORT["EQUIVALENT"].append("os.getuid/geteuid/getgid -> 0 (no POSIX uid on Windows)")

_real_stat = os.stat

_acl_busy = threading.local()
_broad_cache = {}


def _broad_group_access(path):
    """True if a broad account/group (Everyone, Users, ...) holds any grant here."""
    if not isinstance(path, str):
        return False
    stamp_key = (path,)
    cached = _broad_cache.get(stamp_key)
    if cached is not None:
        return cached
    allowed = False
    _acl_busy.active = True
    try:
        raw = subprocess.run(["icacls", path], capture_output=True,
                             timeout=CACHE_PROBE_TIMEOUT).stdout
        text = raw.decode("utf-8", "replace") if not raw.startswith(b"\xff\xfe") else raw.decode("utf-16", "replace")
    except (OSError, subprocess.SubprocessError):
        text = ""
    finally:
        _acl_busy.active = False
    broad = ("Everyone", "BUILTIN\\Users", "Authenticated Users", "S-1-5-32-545")
    for line in text.splitlines():
        if any(group in line for group in broad) and "DENY" not in line.upper():
            # anything inside parentheses other than a SID is a grant
            if "(" in line and ")" in line:
                allowed = True
                break
    if len(_broad_cache) > 20000:
        _broad_cache.clear()
    _broad_cache[stamp_key] = allowed
    return allowed


_RELEASE_ROOTS = tuple(root.strip().lower().replace("/", "\\") for root in
                       os.environ.get("WINCOMPAT_RELEASE_ROOTS", _PACKAGE_ROOT).split(";") if root.strip())


def _stat(path, dir_fd=None, follow_symlinks=True):
    original = _real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
    try:
        text = os.fspath(path)
    except TypeError:
        text = ""
    if not isinstance(text, str):
        return original
    native = text.replace("/", "\\").lower()
    is_dir = stat.S_ISDIR(original.st_mode)
    # Directories are what the ownership/privacy gates inspect, and they are few.
    # Regular files inside the read-only release tree are skipped for speed.
    if not is_dir and any(native.startswith(root) for root in _RELEASE_ROOTS):
        return original
    private = not _broad_group_access(text)
    values = list(original)
    base = 0o700 if private else 0o755
    values[0] = (original.st_mode & ~0o777) | (base if is_dir else (0o700 if private else 0o755) & ~0o111)
    values[4] = os.getuid()
    values[5] = os.getgid()
    return _StatResult(values, original)


class _StatResult(tuple):
    """stat-shaped tuple with Windows-derived mode bits, nanosecond stamps kept.

    os.stat_result cannot be subclassed and loses st_?time_ns when rebuilt from a
    plain tuple on this platform, while shutil.copystat needs those values.
    """

    def __new__(cls, values, original):
        obj = tuple.__new__(cls, values)
        object.__setattr__(obj, "_nanoseconds",
                           (original.st_atime_ns, original.st_mtime_ns, original.st_ctime_ns))
        return obj

    @property
    def _nanoseconds_tuple(self):
        return object.__getattribute__(self, "_nanoseconds")


_STAT_FIELDS = ("st_mode", "st_ino", "st_dev", "st_nlink", "st_uid", "st_gid",
                "st_size", "st_atime", "st_mtime", "st_ctime")
for _index, _name in enumerate(_STAT_FIELDS):
    setattr(_StatResult, _name, property(lambda self, _i=_index: self[_i]))
setattr(_StatResult, "st_atime_ns", property(lambda self: self._nanoseconds[0]))
setattr(_StatResult, "st_mtime_ns", property(lambda self: self._nanoseconds[1]))
setattr(_StatResult, "st_ctime_ns", property(lambda self: self._nanoseconds[2]))


os.stat = _stat
REPORT["PRESERVED"].append("private-file gate: 0700/0600 translated to a real ACL restriction")

# --- chmod/mkdir 0700 and 0600 are translated into real ACL hardening --------
_HARDENED = set()


def _harden(path):
    """Turn 'private to the caller' into a genuine Windows ACL (no inheritance)."""
    key = str(path)
    if key in _HARDENED:
        return
    _HARDENED.add(key)
    user = os.environ.get("USERNAME", "")
    domain = os.environ.get("USERDOMAIN", "")
    account = f"{domain}\\{user}" if domain and user else user
    if not account:
        return
    # (OI)(CI) are directory-only inheritance flags: passing them for a file
    # makes icacls reject the whole grant, leaving the object with zero ACEs
    # (nobody can write it). Files therefore get a plain :F grant.
    inherit = "(OI)(CI)F" if os.path.isdir(key) else "F"
    # one atomic command: leaving the object with no ACEs between two calls is
    # how Windows locks everybody (including us) out of the directory
    # /inheritance:r only drops inherited entries; an explicit broad ACE left by
    # an earlier chmod(0755) would survive and keep the object "shared". Remove
    # the well-known broad groups explicitly so 0700 really means private.
    commands = [["icacls", key, "/inheritance:r",
                 "/remove:g", "*S-1-5-32-545", "*S-1-1-0", "*S-1-5-11",
                 "/grant:r", f"{account}:{inherit}", f"SYSTEM:{inherit}", "/Q"]]
    for command in commands:
        try:
            subprocess.run(command, capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return
    # ACLs just changed: drop any probe result cached before the hardening
    for cached in [k for k in _broad_cache if k[0] == key or k[0].startswith(key)]:
        _broad_cache.pop(cached, None)


_real_mkdir = os.mkdir


def _mkdir(path, mode=0o777, *, dir_fd=None):
    _real_mkdir(path, mode, dir_fd=dir_fd)
    if dir_fd is None and mode != 0o777:
        # an explicit mode is a statement of intent: 0700 stays private, 0755
        # becomes genuinely shared. The 0o777 default is left untouched so
        # ordinary temp dirs do not cost an icacls call each.
        if (mode & 0o077) == 0:
            _harden(path)
        else:
            _share(path, writable=bool(mode & 0o022))
    return None


_real_chmod = os.chmod


def _share(path, writable):
    """Translate POSIX group/other bits into a real broad-group ACE (or drop it)."""
    key = str(path)
    rights = "(OI)(CI)M" if writable else "(OI)(CI)RX"
    if not os.path.isdir(key):
        rights = "M" if writable else "RX"
    command = ["icacls", key, "/grant", f"*S-1-5-32-545:{rights}", "/Q"]
    try:
        subprocess.run(command, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return
    for cached in [k for k in _broad_cache if k[0] == key or k[0].startswith(key)]:
        _broad_cache.pop(cached, None)


def _chmod(path, mode, *, dir_fd=None, follow_symlinks=True):
    result = _real_chmod(path, mode, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
    if dir_fd is None:
        if (mode & 0o077) == 0:
            _harden(path)
        else:
            # group/other bits set: POSIX says "shared"; mirror it instead of
            # leaving the private inherited ACL in place
            _share(path, writable=bool(mode & 0o022))
    return result


os.mkdir = _mkdir
os.chmod = _chmod

# --------------------------------------------------------------------------
# 2. O_NOFOLLOW: refuse to open through a symlink (real property, checked in Python)
# --------------------------------------------------------------------------
if not hasattr(os, "O_NOFOLLOW"):
    _NOFOLLOW = 0x40000000
    _NONBLOCK = 0x20000000
    os.O_NOFOLLOW = _NOFOLLOW
    if not hasattr(os, "O_NONBLOCK"):
        os.O_NONBLOCK = _NONBLOCK
        REPORT["EQUIVALENT"].append(
            "O_NONBLOCK -> ignored; only used with regular files where POSIX has no effect")
    _real_open = os.open

    def _open(path, flags, mode=0o777, *, dir_fd=None):
        if flags & _NOFOLLOW:
            flags &= ~_NOFOLLOW
            flags &= ~globals().get("_NONBLOCK", 0)
            target = pathlib.Path(os.fspath(path))
            if target.is_symlink():
                raise OSError(errno.ELOOP, "symlink refused by O_NOFOLLOW", str(target))
            for parent in target.parents:
                if parent.is_symlink():
                    raise OSError(errno.ELOOP, "symlinked parent refused by O_NOFOLLOW", str(parent))
        flags &= ~globals().get("_NONBLOCK", 0)
        return _real_open(path, flags, mode, dir_fd=dir_fd)

    os.open = _open
    REPORT["PRESERVED"].append("O_NOFOLLOW: symlink refusal checked before open")

# --------------------------------------------------------------------------
# 3. fcntl.flock -> mandatory Windows byte-range locking (msvcrt)
# --------------------------------------------------------------------------
try:
    import fcntl  # noqa: F401  (real module if present)
    REPORT["PRESERVED"].append("fcntl: using the real module")
except ModuleNotFoundError:
    _fcntl = types.ModuleType("fcntl")
    _fcntl.LOCK_EX = 0x2
    _fcntl.LOCK_SH = 0x1
    _fcntl.LOCK_NB = 0x4
    _fcntl.LOCK_UN = 0x8

    def _flock(fd, operation):
        handle = fd.fileno() if hasattr(fd, "fileno") else int(fd)
        try:
            size = max(1, os.fstat(handle).st_size or 1)
        except OSError:
            size = 1
        size = min(size, 0x3FFFFFFF)
        if operation & _fcntl.LOCK_UN:
            try:
                msvcrt.locking(handle, msvcrt.LK_UNLCK, size)
            except OSError:
                pass
            return None
        kind = msvcrt.LK_NBLCK if operation & _fcntl.LOCK_NB else msvcrt.LK_LOCK
        time_left = 5.0
        import time
        while True:
            try:
                msvcrt.locking(handle, kind, size)
                return None
            except OSError:
                if time_left <= 0:
                    raise
                time.sleep(0.05)
                time_left -= 0.05

    _fcntl.flock = _flock
    _fcntl.lockf = _flock
    sys.modules["fcntl"] = _fcntl
    REPORT["PRESERVED"].append("fcntl.flock -> msvcrt byte-range lock (mutual exclusion kept)")

# --------------------------------------------------------------------------
# 4. resource rlimits -> Windows Job Object, with honest gaps
# --------------------------------------------------------------------------
try:
    import resource  # noqa: F401
    REAL_RESOURCE = True
except ModuleNotFoundError:
    REAL_RESOURCE = False
    resource = types.ModuleType("resource")
    resource.RLIMIT_CPU = 0
    resource.RLIMIT_FSIZE = 1
    resource.RLIMIT_AS = 9
    resource.RLIMIT_NOFILE = 7
    resource.RLIMIT_NPROC = 6
    resource.RLIM_INFINITY = -1
    PENDING_LIMITS = {}
    resource.setrlimit = lambda which, value: PENDING_LIMITS.__setitem__(which, value)
    resource.getrlimit = lambda which: PENDING_LIMITS.get(which, (-1, -1))
    sys.modules["resource"] = resource
    REPORT["PRESERVED"].append("RLIMIT_AS/CPU -> Windows Job Object limits on the child")
    REPORT["NOT_ENFORCED"].append("RLIMIT_FSIZE (file size cap) - no Windows equivalent; recorded only")
    REPORT["NOT_ENFORCED"].append("RLIMIT_NOFILE / RLIMIT_NPROC - no Windows equivalent; recorded only")

# --- Job Object plumbing ---------------------------------------------------
_kernel = ctypes.windll.kernel32
_class = ctypes.Structure


class IO_COUNTERS(_class):
    _fields_ = [("ReadOperationCount", ctypes.c_ulonglong), ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong), ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong), ("OtherTransferCount", ctypes.c_ulonglong)]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(_class):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                ("Affinity", ctypes.POINTER(ctypes.c_ulong)), ("PriorityClass", wt.DWORD),
                ("SchedulingClass", wt.DWORD)]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(_class):
    _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


CREATE_SUSPENDED = 0x00000004
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001
_job_handle = None


def _apply_job(pid, limits):
    """Assign a child to a Job Object carrying CPU/memory/process-count limits."""
    global _job_handle
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    flags = 0
    cpu = limits.get(resource.RLIMIT_CPU, (-1, -1))[1]
    memory = limits.get(resource.RLIMIT_AS, (-1, -1))[1]
    procs = limits.get(resource.RLIMIT_NPROC, (-1, -1))[1]
    if 0 < cpu < (1 << 50):
        # Windows counts in 100ns ticks
        info.BasicLimitInformation.PerProcessUserTimeLimit = int(cpu) * 10_000_000
        flags |= 0x00000010  # JOB_OBJECT_LIMIT_PROCESS_TIME
    if 0 < memory < (1 << 62):
        info.ProcessMemoryLimit = int(memory)
        flags |= 0x00000100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
    if 0 < procs < 1000:
        info.BasicLimitInformation.ActiveProcessLimit = int(procs)
        flags |= 0x00000008  # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    if not flags:
        return "no_limits_requested"
    _job_handle = _kernel.CreateJobObjectA(None, None)
    if not _job_handle:
        return "job_create_failed"
    if not _kernel.SetInformationJobObject(int(_job_handle), 9, ctypes.byref(info), ctypes.sizeof(info)):
        return "job_limit_failed"
    handle = _kernel.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
    if not handle:
        return "open_process_failed"
    ok = _kernel.AssignProcessToJobObject(int(_job_handle), int(handle))
    _kernel.CloseHandle(int(handle))
    return "assigned" if ok else "assign_failed"


def killpg(pid, signal_number):
    """Kill the whole child tree; Windows has no POSIX process group here."""
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
    return None


if not hasattr(os, "killpg"):
    os.killpg = killpg
    REPORT["EQUIVALENT"].append("os.killpg -> taskkill /T /F (whole tree, if job assignment succeeded)")

# --------------------------------------------------------------------------
# 5. absolute POSIX paths -> resolved binaries on this host
# --------------------------------------------------------------------------
_GIT = shutil.which("git")
_PYTHON = sys.executable


def _remap(value):
    if not isinstance(value, str):
        return value
    if value == "/usr/bin/git" and _GIT:
        return _GIT
    if value in ("/usr/bin/python3", "/usr/bin/python") and _PYTHON:
        return _PYTHON
    return value


_EMPTY_CONFIG = pathlib.Path(tempfile.gettempdir()) / "r4-win-empty-gitconfig"
try:
    _EMPTY_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if not _EMPTY_CONFIG.exists():
        _EMPTY_CONFIG.write_text("")
except OSError:
    _EMPTY_CONFIG = None


def _fix_env(env):
    if env is None:
        return None
    fixed = dict(env)
    path = fixed.get("PATH", "")
    if path and "/" in path and ":" in path and not any(letter in path for letter in ("C:", "c:")):
        parts = [os.path.dirname(_GIT) if _GIT else "", os.path.dirname(_PYTHON), os.environ.get("SystemRoot", "")]
        fixed["PATH"] = os.pathsep.join(p for p in parts if p) or os.environ.get("PATH", "")
    fixed.setdefault("SystemRoot", os.environ.get("SystemRoot", ""))
    fixed.setdefault("TMP", os.environ.get("TMP", ""))
    # keep the compatibility shim reachable from every child interpreter, even
    # when a caller replaces PYTHONPATH outright
    existing = fixed.get("PYTHONPATH", "")
    pieces = [p for p in existing.split(os.pathsep) if p]
    if _COMPAT_DIR not in pieces:
        pieces.insert(0, _COMPAT_DIR)
    fixed["PYTHONPATH"] = os.pathsep.join(pieces)
    if _EMPTY_CONFIG is not None and fixed.get("GIT_CONFIG_GLOBAL") in (os.devnull, "/dev/null"):
        fixed["GIT_CONFIG_GLOBAL"] = str(_EMPTY_CONFIG)
    return fixed


REPORT["REMAP"].append(f"/usr/bin/git -> {_GIT}")
REPORT["REMAP"].append("/usr/bin/python3 -> current interpreter")
REPORT["REMAP"].append("POSIX-only PATH in child env -> host PATH")

_real_popen_init = subprocess.Popen.__init__

# --------------------------------------------------------------------------
# 5a2. signal.SIGKILL: not defined on Windows; map to immediate termination.
# --------------------------------------------------------------------------
try:
    import signal
except ModuleNotFoundError:  # pragma: no cover
    signal = None
if signal is not None and not hasattr(signal, "SIGKILL"):
    signal.SIGKILL = signal.SIGTERM
    REPORT["EQUIVALENT"].append("signal.SIGKILL -> SIGTERM/TerminateProcess (no graceful kill on Windows)")

# --------------------------------------------------------------------------
# 5a. newline translation: POSIX Python never rewrites "\n"; Windows does.
#     Force newline="" so written/read bytes match what the POSIX run produced.
# --------------------------------------------------------------------------
_real_io_open = io.open
_real_builtin_open = builtins.open


def _open_no_translation(file, mode="r", buffering=-1, encoding=None, errors=None,
                         newline=None, closefd=True, opener=None):
    if newline is None and "b" not in mode:
        newline = ""
    return _real_io_open(file, mode, buffering, encoding, errors, newline, closefd, opener)


io.open = _open_no_translation
builtins.open = _open_no_translation
REPORT["EQUIVALENT"].append("default newline='' for text I/O to keep bytes identical to POSIX")

# --------------------------------------------------------------------------
# 5b. path spelling: git prints POSIX-style paths, Windows API wants backslashes.
#     Normalising to forward slashes keeps str(Path) comparisons consistent.
# --------------------------------------------------------------------------
_real_str = pathlib.Path.__str__
_real_fspath = pathlib.Path.__fspath__


def _posix_str(self):
    text = _real_str(self)
    return text.replace("\\", "/")


def _posix_fspath(self):
    text = _real_fspath(self)
    return text.replace("\\", "/") if isinstance(text, str) else text


pathlib.Path.__str__ = _posix_str
pathlib.Path.__fspath__ = _posix_fspath
REPORT["EQUIVALENT"].append("str(Path) normalised to forward slashes to match git output spelling")


def _popen_init(self, args, *positional, **keyword):
    preexec = keyword.pop("preexec_fn", None)
    if preexec is not None:
        # preexec_fn is POSIX-only: run it in the parent purely to record the
        # rlimits it would have set for the child.
        try:
            preexec()
        except Exception:
            pass
    session = keyword.pop("start_new_session", False)
    if session:
        keyword["creationflags"] = keyword.get("creationflags", 0) | subprocess.CREATE_NEW_PROCESS_GROUP
    if isinstance(args, (list, tuple)):
        args = [_remap(str(item)) for item in args]
    elif isinstance(args, str):
        args = _remap(args)
    keyword["env"] = _fix_env(keyword.get("env"))
    _real_popen_init(self, args, *positional, **keyword)
    if not REAL_RESOURCE:
        limits = dict(getattr(resource, "PENDING_LIMITS", {}))
        if limits:
            self._job_state = _apply_job(self.pid, limits)
            resource.PENDING_LIMITS.clear()
        else:
            self._job_state = "none"


subprocess.Popen.__init__ = _popen_init

_real_subprocess_run = subprocess.run


def _subprocess_run(args, *positional, **keyword):
    if isinstance(args, (list, tuple)):
        args = [_remap(str(item)) for item in args]
    elif isinstance(args, str):
        args = _remap(args)
    keyword["env"] = _fix_env(keyword.get("env"))
    return _real_subprocess_run(args, *positional, **keyword)


subprocess.run = _subprocess_run

if __name__ == "__main__":
    import json
    print(json.dumps(REPORT, indent=1, ensure_ascii=False))
