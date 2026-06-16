"""
tools/device_control.py — Local device control: volume, brightness, DND, lock.

Per-platform branches live inside each function (protocol: no separate
per-platform files). Windows is implemented via PowerShell; macOS gets a
best-effort branch where there's a clean one-liner (volume, lock). Everything
returns a short plain-text result string, like the other Jarvis tools.

Low-risk and reversible, so these are auto-allow (no confirm gate) for smooth
voice UX — you don't want to approve "set volume to 30".
"""

from __future__ import annotations

import platform
import subprocess

PS_TIMEOUT = 15

# Core Audio (IAudioEndpointVolume) shim — the standard dependency-free way to
# set absolute master volume / mute from PowerShell.
_AUDIO_CSHARP = r'''
using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
  int NotImpl1(); int NotImpl2();
  int GetChannelCount(out int c);
  int SetMasterVolumeLevel(float l, System.Guid e);
  int SetMasterVolumeLevelScalar(float l, System.Guid e);
  int GetMasterVolumeLevel(out float l);
  int GetMasterVolumeLevelScalar(out float l);
  int SetChannelVolumeLevel(uint i, float l, System.Guid e);
  int SetChannelVolumeLevelScalar(uint i, float l, System.Guid e);
  int GetChannelVolumeLevel(uint i, out float l);
  int GetChannelVolumeLevelScalar(uint i, out float l);
  int SetMute([MarshalAs(UnmanagedType.Bool)] bool m, System.Guid e);
  int GetMute(out bool m);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice { int Activate(ref System.Guid id, int ctx, System.IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator { int NotImpl(); int GetDefaultAudioEndpoint(int flow, int role, out IMMDevice ep); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class MMDeviceEnumeratorComObject { }
public class JarvisAudio {
  static IAudioEndpointVolume Endpoint() {
    var en = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
    IMMDevice dev; en.GetDefaultAudioEndpoint(0, 1, out dev);
    System.Guid g = typeof(IAudioEndpointVolume).GUID; object o;
    dev.Activate(ref g, 1, System.IntPtr.Zero, out o);
    return (IAudioEndpointVolume)o;
  }
  public static void SetVolume(float v) { Endpoint().SetMasterVolumeLevelScalar(v, System.Guid.Empty); }
  public static void SetMute(bool m) { Endpoint().SetMute(m, System.Guid.Empty); }
}
'''


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def _run_powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=PS_TIMEOUT,
    )


def _ps_error(result: subprocess.CompletedProcess) -> str:
    return (result.stderr or result.stdout or "unknown error").strip().splitlines()[0] \
        if (result.stderr or result.stdout) else "unknown error"


# ---------------------------------------------------------------------------
# Volume
# ---------------------------------------------------------------------------

def set_volume(level: int) -> str:
    """Set the system master volume to `level` percent (0–100)."""
    try:
        level = _clamp(int(level))
    except (TypeError, ValueError):
        return f"Refused: volume level {level!r} is not a number 0–100."

    system = platform.system()
    try:
        if system == "Windows":
            script = f"Add-Type -TypeDefinition @'\n{_AUDIO_CSHARP}\n'@\n[JarvisAudio]::SetVolume({level / 100:.4f})"
            result = _run_powershell(script)
            if result.returncode != 0:
                return f"Couldn't set volume: {_ps_error(result)}"
            return f"Volume set to {level}%."
        if system == "Darwin":
            result = subprocess.run(
                ["osascript", "-e", f"set volume output volume {level}"],
                capture_output=True, text=True, timeout=PS_TIMEOUT,
            )
            if result.returncode != 0:
                return f"Couldn't set volume: {(result.stderr or '').strip()}"
            return f"Volume set to {level}%."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't set volume: {exc}"
    return f"Setting volume isn't supported on {system} yet."


def set_mute(muted: bool) -> str:
    """Mute or unmute the system master volume."""
    system = platform.system()
    flag = "$true" if muted else "$false"
    word = "Muted" if muted else "Unmuted"
    try:
        if system == "Windows":
            script = f"Add-Type -TypeDefinition @'\n{_AUDIO_CSHARP}\n'@\n[JarvisAudio]::SetMute({flag})"
            result = _run_powershell(script)
            if result.returncode != 0:
                return f"Couldn't change mute: {_ps_error(result)}"
            return f"{word} the system audio."
        if system == "Darwin":
            mac_flag = "true" if muted else "false"
            result = subprocess.run(
                ["osascript", "-e", f"set volume output muted {mac_flag}"],
                capture_output=True, text=True, timeout=PS_TIMEOUT,
            )
            if result.returncode != 0:
                return f"Couldn't change mute: {(result.stderr or '').strip()}"
            return f"{word} the system audio."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't change mute: {exc}"
    return f"Muting isn't supported on {system} yet."


# ---------------------------------------------------------------------------
# Brightness
# ---------------------------------------------------------------------------

def set_brightness(level: int) -> str:
    """Set the main display brightness to `level` percent (0–100)."""
    try:
        level = _clamp(int(level))
    except (TypeError, ValueError):
        return f"Refused: brightness level {level!r} is not a number 0–100."

    system = platform.system()
    try:
        if system == "Windows":
            script = (
                "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                f".WmiSetBrightness(1,{level})"
            )
            result = _run_powershell(script)
            if result.returncode != 0:
                return (
                    f"Couldn't set brightness ({_ps_error(result)}). "
                    "This usually means the display doesn't support WMI brightness "
                    "(common on desktop monitors)."
                )
            return f"Brightness set to {level}%."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't set brightness: {exc}"
    return f"Setting brightness isn't supported on {system} yet."


# ---------------------------------------------------------------------------
# Do Not Disturb (notification suppression)
# ---------------------------------------------------------------------------

def set_do_not_disturb(enabled: bool) -> str:
    """Toggle Do Not Disturb. On Windows this suppresses toast notifications."""
    system = platform.system()
    try:
        if system == "Windows":
            value = 0 if enabled else 1  # ToastEnabled: 0 = notifications off
            script = (
                "New-Item -Path "
                "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications' "
                "-Force | Out-Null; Set-ItemProperty -Path "
                "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications' "
                f"-Name ToastEnabled -Type DWord -Value {value}"
            )
            result = _run_powershell(script)
            if result.returncode != 0:
                return f"Couldn't change Do Not Disturb: {_ps_error(result)}"
            return (
                "Do Not Disturb on — notifications suppressed."
                if enabled else
                "Do Not Disturb off — notifications back on."
            )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't change Do Not Disturb: {exc}"
    return f"Do Not Disturb isn't supported on {system} yet."


# ---------------------------------------------------------------------------
# Lock screen
# ---------------------------------------------------------------------------

def lock_screen() -> str:
    """Lock the workstation."""
    system = platform.system()
    try:
        if system == "Windows":
            result = subprocess.run(
                ["rundll32.exe", "user32.dll,LockWorkStation"],
                capture_output=True, text=True, timeout=PS_TIMEOUT,
            )
            if result.returncode != 0:
                return f"Couldn't lock the screen: {(result.stderr or '').strip()}"
            return "Locked the screen."
        if system == "Darwin":
            result = subprocess.run(
                ["pmset", "displaysleepnow"],
                capture_output=True, text=True, timeout=PS_TIMEOUT,
            )
            if result.returncode != 0:
                return f"Couldn't lock the screen: {(result.stderr or '').strip()}"
            return "Locked the screen."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't lock the screen: {exc}"
    return f"Locking isn't supported on {system} yet."


# ---------------------------------------------------------------------------
# macOS-only extras (Jack sprint 2)
# ---------------------------------------------------------------------------

def set_appearance_mode(mode: str) -> str:
    """Switch between dark and light mode. mode: 'dark' or 'light'."""
    if platform.system() != "Darwin":
        return "Appearance mode control is macOS only."
    m = (mode or "").strip().lower()
    if m not in ("dark", "light"):
        return f"Refused: mode must be 'dark' or 'light', not {mode!r}."
    try:
        flag = "true" if m == "dark" else "false"
        script = (
            'tell application "System Events" to tell appearance preferences '
            f"to set dark mode to {flag}"
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=PS_TIMEOUT,
        )
        if result.returncode != 0:
            return f"Couldn't change appearance mode: {(result.stderr or result.stdout or '').strip()}"
        return f"Switched to {m} mode."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't change appearance mode: {exc}"


def get_battery_status() -> str:
    """Get current battery percentage and charging status."""
    if platform.system() != "Darwin":
        return "Battery status is macOS only."
    try:
        result = subprocess.run(
            ["pmset", "-g", "batt"],
            capture_output=True,
            text=True,
            timeout=PS_TIMEOUT,
        )
        if result.returncode != 0:
            return f"Couldn't read battery status: {(result.stderr or '').strip()}"
        return result.stdout.strip() or "Could not read battery status."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't read battery status: {exc}"


def set_screen_saver(action: str) -> str:
    """Start the screen saver. action: 'start'."""
    if platform.system() != "Darwin":
        return "Screen saver control is macOS only."
    if (action or "").strip().lower() != "start":
        return f"Refused: screen saver action must be 'start', not {action!r}."
    try:
        result = subprocess.run(
            ["open", "-a", "ScreenSaverEngine"],
            capture_output=True,
            text=True,
            timeout=PS_TIMEOUT,
        )
        if result.returncode != 0:
            return f"Couldn't start screen saver: {(result.stderr or '').strip()}"
        return "Screen saver started."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't start screen saver: {exc}"


def get_system_info() -> str:
    """Get Mac system info: macOS version, chip, RAM."""
    if platform.system() != "Darwin":
        return "System info is macOS only."
    try:
        result = subprocess.run(
            ["system_profiler", "SPSoftwareDataType", "SPHardwareDataType"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return f"Couldn't read system info: {(result.stderr or '').strip()}"
        keywords = ("System Version", "Chip", "Memory", "Model Name")
        lines = [
            line.strip()
            for line in result.stdout.split("\n")
            if any(k in line for k in keywords)
        ]
        return "\n".join(lines[:6]) if lines else "Could not read system info."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't read system info: {exc}"


def set_wifi(action: str) -> str:
    """Turn WiFi on or off. action: 'on' or 'off'."""
    if platform.system() != "Darwin":
        return "WiFi control is macOS only."
    state = (action or "").strip().lower()
    if state not in ("on", "off"):
        return f"Refused: WiFi action must be 'on' or 'off', not {action!r}."
    try:
        result = subprocess.run(
            ["networksetup", "-setairportpower", "en0", state],
            capture_output=True,
            text=True,
            timeout=PS_TIMEOUT,
        )
        if result.returncode != 0:
            return f"Couldn't change WiFi: {(result.stderr or result.stdout or '').strip()}"
        return f"WiFi turned {state}."
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"Couldn't change WiFi: {exc}"
