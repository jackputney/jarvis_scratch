"""tools/system_info.py — CPU/RAM/disk, process list, and active window title."""

from __future__ import annotations

import platform

_NOT_WINDOWS = "Active window is Windows only."


def system_info() -> str:
    """Return CPU, memory, and disk usage for the local machine."""
    import psutil

    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    root = "C:\\" if platform.system() == "Windows" else "/"
    try:
        disk = psutil.disk_usage(root)
    except OSError:
        disk = psutil.disk_usage("/")

    lines = [
        f"CPU: {cpu:.1f}%",
        f"RAM: {mem.percent:.1f}% used ({_fmt_bytes(mem.used)} / {_fmt_bytes(mem.total)})",
        (
            f"Disk ({root}): {disk.percent:.1f}% used "
            f"({_fmt_bytes(disk.used)} / {_fmt_bytes(disk.total)})"
        ),
    ]
    return "\n".join(lines)


def list_processes() -> str:
    """List the top 20 running processes by CPU usage."""
    import psutil

    procs: list[tuple[float, int, str]] = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent"]):
        try:
            info = proc.info
            cpu = float(info.get("cpu_percent") or 0.0)
            procs.append((cpu, int(info["pid"]), str(info.get("name") or "?")))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if not procs:
        return "No running processes found."

    procs.sort(key=lambda item: item[0], reverse=True)
    lines = ["Top processes by CPU:"]
    for cpu, pid, name in procs[:20]:
        lines.append(f"  {name} (pid {pid}): {cpu:.1f}%")
    return "\n".join(lines)


def active_window() -> str:
    """Return the title of the currently focused window (Windows)."""
    if platform.system() != "Windows":
        return _NOT_WINDOWS

    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "No active window."

    length = user32.GetWindowTextLengthW(hwnd) + 1
    buf = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buf, length)
    title = buf.value.strip()
    return title or "Active window has no title."


def _fmt_bytes(num: int) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < step:
            return f"{num:.1f} {unit}"
        num /= step
    return f"{num:.1f} PB"
