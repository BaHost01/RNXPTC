"""
Syntax Executor v1 – Roblox Luau bytecode injector.

Injection strategy (ported from original C++ Xeno codebase):
  1. Attach to RobloxPlayerBeta.exe via pymem.
  2. Wait for memory >= 550 MB (game fully loaded).
  3. Resolve DataModel via FakeDataModel global pointer.
  4. Wait for LocalPlayer to be valid.
  5. Navigate: DataModel → CoreGui → RobloxGui → Modules → Common → Url
     (Url is always-loaded — the correct injection target per Xeno C++).
  6. Unlock the Url module (clear IsCoreScript + reset loadedStatus).
  7. Write init bytecode into the Url module's embedded bytecode struct,
     using VirtualProtectEx to gain write access.
  8. Get Roblox HWND → SetForegroundWindow → send VK_ESCAPE to trigger reload.
  9. Verify by polling for a "Syntax" folder under CoreGui.

Set DEBUG = True for verbose logging.
Set DEBUG_FILE = True to write debug.log to disk.
"""

import os
import sys
import time
import threading
import ctypes
from ctypes import wintypes
from datetime import datetime
from typing import Optional, List, Tuple

import pymem
import pymem.process

import rbxbcd
import rbxinit


from typing import Optional

# ─────────────────────────────────────────────────────────────
# Windows API setup
# ─────────────────────────────────────────────────────────────
kernel32 = ctypes.windll.kernel32
ntdll     = ctypes.windll.ntdll
user32    = ctypes.windll.user32
psapi     = ctypes.windll.psapi

PROCESS_ALL_ACCESS         = 0x1F0FFF
PROCESS_SUSPEND_RESUME     = 0x0800
PAGE_EXECUTE_READWRITE     = 0x40
PAGE_READWRITE             = 0x04
MEM_COMMIT                 = 0x1000
MEM_RESERVE                = 0x2000
VK_ESCAPE                  = 0x1B
KEYEVENTF_SCANCODE         = 0x0008
KEYEVENTF_KEYUP            = 0x0002

# PROCESS_MEMORY_COUNTERS
class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb",                          wintypes.DWORD),
        ("PageFaultCount",              wintypes.DWORD),
        ("PeakWorkingSetSize",          ctypes.c_size_t),
        ("WorkingSetSize",              ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage",     ctypes.c_size_t),
        ("QuotaPagedPoolUsage",         ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage",  ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage",      ctypes.c_size_t),
        ("PagefileUsage",               ctypes.c_size_t),
        ("PeakPagefileUsage",           ctypes.c_size_t),
    ]

# ─────────────────────────────────────────────────────────────
# Debug switches
# ─────────────────────────────────────────────────────────────
DEBUG:      bool = True
DEBUG_FILE: bool = True

# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────
_log_lock = threading.Lock()
_start_ts = time.time()


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _elapsed() -> float:
    return time.time() - _start_ts


def _write_log(line: str) -> None:
    if DEBUG_FILE:
        try:
            with open("debug.log", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def debug(msg: str) -> None:
    if not DEBUG:
        return
    line = f"[DBG {_ts()} +{_elapsed():.1f}s] {msg}"
    with _log_lock:
        print(line)
        _write_log(line)


def info(msg: str) -> None:
    line = f"[*] {msg}"
    with _log_lock:
        print(line)
        _write_log(line)


def warn(msg: str) -> None:
    line = f"[!] {msg}"
    with _log_lock:
        print(line)
        _write_log(line)


def error(msg: str) -> None:
    line = f"[ERROR] {msg}"
    with _log_lock:
        print(line)
        _write_log(line)


# ─────────────────────────────────────────────────────────────
# Process helpers
# ─────────────────────────────────────────────────────────────
def get_working_set(handle: int) -> int:
    """Return the process working set size in bytes."""
    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(pmc)
    # K32GetProcessMemoryInfo is the modern export in kernel32 (Win 7+)
    # Fallback to psapi.GetProcessMemoryInfo for older systems
    fn = getattr(kernel32, "K32GetProcessMemoryInfo", None) or getattr(psapi, "GetProcessMemoryInfo", None)
    if fn and fn(handle, ctypes.byref(pmc), pmc.cb):
        return pmc.WorkingSetSize
    return 0


def get_hwnd_from_pid(pid: int) -> int:
    """Find the main HWND for a given PID via EnumWindows."""
    result = ctypes.c_void_p(0)

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _enum_proc(hwnd, _lparam):
        lpdw = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw))
        if lpdw.value == pid:
            result.value = hwnd
            return False  # stop
        return True

    cb = EnumWindowsProc(_enum_proc)
    user32.EnumWindows(cb, None)
    return result.value or 0


def send_key(hwnd: int, vk: int) -> None:
    """Bring Roblox to foreground and send a keypress."""
    prev = user32.GetForegroundWindow()

    # Bring Roblox to front
    for _ in range(20):
        user32.SetForegroundWindow(hwnd)
        if user32.GetForegroundWindow() == hwnd:
            break
        time.sleep(0.005)

    scan = user32.MapVirtualKeyW(vk, 0)
    kernel32.keybd_event(vk, scan, KEYEVENTF_SCANCODE, 0)
    time.sleep(0.05)
    kernel32.keybd_event(vk, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)
    time.sleep(0.05)

    if prev:
        user32.SetForegroundWindow(prev)


def protected_write_ptr(handle: int, address: int, value: int) -> bool:
    """Write a 64-bit pointer with VirtualProtectEx to bypass write protection."""
    old_prot = wintypes.DWORD(0)
    if not kernel32.VirtualProtectEx(handle, ctypes.c_void_p(address), 8, PAGE_READWRITE, ctypes.byref(old_prot)):
        return False
    buf = ctypes.c_ulonglong(value)
    written = ctypes.c_size_t(0)
    ok = kernel32.WriteProcessMemory(handle, ctypes.c_void_p(address), ctypes.byref(buf), 8, ctypes.byref(written))
    kernel32.VirtualProtectEx(handle, ctypes.c_void_p(address), 8, old_prot, ctypes.byref(old_prot))
    return bool(ok) and written.value == 8


def protected_write_bytes(handle: int, address: int, data: bytes) -> bool:
    """Write arbitrary bytes with VirtualProtectEx."""
    old_prot = wintypes.DWORD(0)
    n = len(data)
    if not kernel32.VirtualProtectEx(handle, ctypes.c_void_p(address), n, PAGE_READWRITE, ctypes.byref(old_prot)):
        return False
    buf = (ctypes.c_char * n)(*data)
    written = ctypes.c_size_t(0)
    ok = kernel32.WriteProcessMemory(handle, ctypes.c_void_p(address), buf, n, ctypes.byref(written))
    kernel32.VirtualProtectEx(handle, ctypes.c_void_p(address), n, old_prot, ctypes.byref(old_prot))
    return bool(ok) and written.value == n


def freeze_process(pid: int) -> bool:
    hproc = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not hproc:
        return False
    result = ntdll.NtSuspendProcess(hproc)
    kernel32.CloseHandle(hproc)
    return result == 0


def unfreeze_process(pid: int) -> bool:
    hproc = kernel32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not hproc:
        return False
    result = ntdll.NtResumeProcess(hproc)
    kernel32.CloseHandle(hproc)
    return result == 0


# ─────────────────────────────────────────────────────────────
class SyntaxExecutor:
    MAX_CHILDREN_SCAN = 2000

    def __init__(self):
        self.pm:           Optional[pymem.Pymem] = None
        self.base_module:  Optional[object]       = None
        self.base_address: int  = 0
        self.offsets:      dict = {}
        self.is_injected:  bool = False

        # Navigation cache
        self._dm:          int = 0
        self._core_gui:    int = 0
        self._roblox_gui:  int = 0
        self._modules:     int = 0

    # ─────────────────────────────────────────────────────────
    # Offset loading
    # ─────────────────────────────────────────────────────────
    def load_offsets(self) -> None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NewestOffsets.txt")
        if not os.path.exists(path):
            error(f"Offsets file not found: {path}")
            return
        count = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                try:
                    self.offsets[key.strip()] = int(val.strip(), 16)
                    count += 1
                except ValueError:
                    continue
        info(f"Loaded {count} offsets")

    def off(self, key: str, default: int = 0) -> int:
        return self.offsets.get(key, default)

    # ─────────────────────────────────────────────────────────
    # Process attach
    # ─────────────────────────────────────────────────────────
    def attach(self) -> bool:
        try:
            self.pm = pymem.Pymem("RobloxPlayerBeta.exe")
        except pymem.exception.ProcessNotFound:
            return False
        self.base_module = pymem.process.module_from_name(
            self.pm.process_handle, "RobloxPlayerBeta.exe"
        )
        if self.base_module is None:
            error("Could not resolve base module")
            return False
        self.base_address = self.base_module.lpBaseOfDll
        info(f"Attached to Roblox (PID: {self.pm.process_id})")
        info(f"Base: 0x{self.base_address:X}  Size: 0x{self.base_module.SizeOfImage:X}")
        return True

    def wait_for_load(self) -> None:
        """Wait until Roblox working set >= 550 MB (matching C++ check)."""
        target = 550_000_000
        ws = get_working_set(self.pm.process_handle)
        if ws >= target:
            return
        info(f"Waiting for Roblox to fully load (working set: {ws // 1_000_000} MB / 550 MB)...")
        while ws < target:
            time.sleep(0.1)
            ws = get_working_set(self.pm.process_handle)
            if ws == 0:
                raise pymem.exception.ProcessNotFound("Process lost during load wait")
        info(f"Roblox fully loaded ({ws // 1_000_000} MB)")

    # ─────────────────────────────────────────────────────────
    # Memory helpers
    # ─────────────────────────────────────────────────────────
    def read_ptr(self, addr: int) -> int:
        if not addr:
            return 0
        try:
            return self.pm.read_longlong(addr) & 0xFFFFFFFFFFFFFFFF
        except Exception:
            return 0

    def read_u8(self, addr: int) -> int:
        try:
            return self.pm.read_uchar(addr)
        except Exception:
            return 0xFF

    def read_u64(self, addr: int) -> int:
        try:
            return self.pm.read_ulonglong(addr)
        except Exception:
            return 0

    def read_string(self, addr: int, max_len: int = 512) -> str:
        """
        Read a Roblox std::string at addr.
        Layout: [0x00] buf/ptr union, [0x10] size (8 bytes), [0x18] capacity.
        Short strings (len < 16) are stored inline in the buf; long strings via ptr.
        """
        if not addr:
            return ""
        try:
            length = self.pm.read_longlong(addr + 0x10)
            if length <= 0 or length > max_len:
                return ""
            if length < 16:
                raw = self.pm.read_bytes(addr, length)
            else:
                ptr = self.read_ptr(addr)
                if not ptr:
                    return ""
                raw = self.pm.read_bytes(ptr, length)
            return raw.decode("utf-8", errors="replace").strip("\x00")
        except Exception:
            return ""

    def get_instance_name(self, inst: int) -> str:
        str_ptr = self.read_ptr(inst + self.off("Instance::Name", 0x98))
        return self.read_string(str_ptr)

    def get_class_name(self, inst: int) -> str:
        desc     = self.read_ptr(inst + self.off("Instance::ClassDescriptor", 0x18))
        if not desc:
            return ""
        cn_ptr   = self.read_ptr(desc + self.off("Instance::ClassName", 0x8))
        return self.read_string(cn_ptr)

    def is_valid_ptr(self, ptr: int) -> bool:
        return 0x10000 <= ptr <= 0x7FFFFFFFFFFF

    def is_valid_instance(self, ptr: int) -> bool:
        if not self.is_valid_ptr(ptr):
            return False
        desc = self.read_ptr(ptr + self.off("Instance::ClassDescriptor", 0x18))
        return self.is_valid_ptr(desc)

    # ─────────────────────────────────────────────────────────
    # DataModel resolution
    # ─────────────────────────────────────────────────────────
    def get_datamodel():
    """Resolves and validates the RealDataModel pointer."""
    fake_dm_off = self.off("FakeDataModel::Pointer")
    if not fake_dm_off:
        error("FakeDataModel::Pointer offset is missing/0 — check NewestOffsets.txt")
        return None

    fake_ptr = self.read_ptr(self.base_address + fake_dm_off)
    if not fake_ptr:
        debug("Failed to read FakeDataModel pointer (evaluated to null)")
        return None

    debug(f"FakeDataModel ptr = 0x{fake_ptr:X}")

    real_dm_off = self.off("FakeDataModel::RealDataModel", 0x1D0)
    dm = self.read_ptr(fake_ptr + real_dm_off)
    if not dm:
        debug("Failed to read RealDataModel pointer (evaluated to null)")
        return None

    debug(f"RealDataModel     = 0x{dm:X}")

    name = self.get_instance_name(dm)
    children = self.get_children(dm)
    child_count = len(children)

    debug(f"DataModel: name='{name}' children={child_count}")

    if child_count < 5:
        error(f"DataModel only has {child_count} children — game engine not ready yet")
        return None

    info(f"DataModel resolved: '{name}' @ 0x{dm:X} ({child_count} children)")
    return dm
    # ─────────────────────────────────────────────────────────
    # Instance tree
    # ─────────────────────────────────────────────────────────
    def get_children(self, instance: int) -> List[int]:
        """
        Walk the children vector:
          instance + ChildrenStart(0x70) → heap vec ptr
          vec[+0x00] = _Myfirst, vec[+0x08] = _Mylast
          each slot = shared_ptr<Instance> = 16 bytes → raw ptr at [0]
        """
        if not instance:
            return []
        children_off = self.off("Instance::ChildrenStart", 0x70)
        try:
            vec   = self.read_ptr(instance + children_off)
            if not vec:
                return []
            start = self.read_ptr(vec)
            end   = self.read_ptr(vec + 8)
            if not start or end <= start:
                return []
            count = min((end - start) // 16, self.MAX_CHILDREN_SCAN)
            if count <= 0:
                return []
            out = []
            for i in range(count):
                child = self.read_ptr(start + i * 16)
                if child:
                    out.append(child)
            return out
        except Exception:
            return []

    def find_child_by_class(self, parent: int, class_name: str) -> int:
        for child in self.get_children(parent):
            if self.get_class_name(child) == class_name:
                return child
        return 0

    def find_child_by_name(self, parent: int, name: str) -> int:
        for child in self.get_children(parent):
            if self.get_instance_name(child) == name:
                return child
        return 0

    def find_child_of_class_addr(self, parent: int, class_name: str) -> int:
        """Alias matching C++ FindFirstChildOfClassAddress."""
        return self.find_child_by_class(parent, class_name)

    # ─────────────────────────────────────────────────────────
    # Navigation cache
    # ─────────────────────────────────────────────────────────
    def cache_navigation(self, dm: int) -> bool:
        if not self.is_valid_instance(dm):
            error("DataModel not a valid instance")
            return False

        core_gui = self.find_child_by_class(dm, "CoreGui")
        if not core_gui:
            error("CoreGui not found under DataModel")
            return False
        debug(f"CoreGui @ 0x{core_gui:X} ({len(self.get_children(core_gui))} children)")

        roblox_gui = self.find_child_by_name(core_gui, "RobloxGui")
        if not roblox_gui:
            error("RobloxGui not found under CoreGui")
            return False
        debug(f"RobloxGui @ 0x{roblox_gui:X} ({len(self.get_children(roblox_gui))} children)")

        modules = self.find_child_by_name(roblox_gui, "Modules")
        if not modules:
            error("Modules not found under RobloxGui")
            return False
        debug(f"Modules @ 0x{modules:X} ({len(self.get_children(modules))} children)")

        self._dm         = dm
        self._core_gui   = core_gui
        self._roblox_gui = roblox_gui
        self._modules    = modules
        return True

    # ─────────────────────────────────────────────────────────
    # LocalPlayer wait (matching C++ wait loop)
    # ─────────────────────────────────────────────────────────
    def wait_for_local_player(self) -> str:
        """Wait until LocalPlayer is valid and has a real username."""
        players_off    = self.off("LocalPlayer", 0x0)  # from offsets if present
        players_inst   = self.find_child_of_class_addr(self._dm, "Players")
        if not players_inst:
            error("Players service not found")
            return ""

        # LocalPlayer offset — if not in file, use a standard scan
        local_player_off = self.off("LocalPlayer", 0x0)
        if not local_player_off:
            # fallback: scan children for a Player instance
            for child in self.get_children(players_inst):
                cls = self.get_class_name(child)
                if cls == "Player":
                    name = self.get_instance_name(child)
                    if name and name != "Player":
                        info(f"LocalPlayer: '{name}'")
                        return name
            return ""

        local_player = self.read_ptr(players_inst + local_player_off)
        deadline = time.time() + 30.0
        while time.time() < deadline:
            if self.is_valid_ptr(local_player):
                username = self.get_instance_name(local_player)
                if username and username != "Player":
                    info(f"LocalPlayer: '{username}'")
                    return username
            time.sleep(0.05)
            local_player = self.read_ptr(players_inst + local_player_off)

        warn("LocalPlayer not found within 30s — continuing anyway")
        return ""

    # ─────────────────────────────────────────────────────────
    # Find injection target: Modules → Common → Url
    # ─────────────────────────────────────────────────────────
    def find_url_module(self) -> int:
        """
        Navigate Modules → Common → Url.
        This is the always-loaded target used by the original C++ Xeno.
        Returns the instance address or 0.
        """
        common = self.find_child_by_name(self._modules, "Common")
        if not common:
            error("Modules->Common not found")
            return 0
        debug(f"Common @ 0x{common:X}")

        url_mod = self.find_child_by_name(common, "en-us")
        if not url_mod:
            error("Common->Url not found")
            return 0
        debug(f"Url module @ 0x{url_mod:X}")
        return url_mod

    # ─────────────────────────────────────────────────────────
    # Module unlock (matches C++ UnlockModule)
    # ─────────────────────────────────────────────────────────
    def unlock_module(self, module_addr: int) -> bool:
        """
        Clear the IsCoreScript flag and reset loadedStatus so the module re-executes.
        From C++ UnlockModule: write 0 to IsCoreScript offset and loadedStatus offset.
        """
        handle = self.pm.process_handle

        is_core_off   = self.off("ModuleScript::IsCoreScript", 0x0)
        loaded_off    = 0x188  # loadedStatus byte (consistent across versions)

        changed = False

        # Clear IsCoreScript if offset is known
        if is_core_off:
            try:
                old = self.read_u8(module_addr + is_core_off)
                if old != 0:
                    ok = protected_write_bytes(handle, module_addr + is_core_off, b"\x00")
                    debug(f"IsCoreScript: 0x{old:02X} → 0x00  (write ok={ok})")
                    changed = True
            except Exception as e:
                debug(f"IsCoreScript write failed: {e}")

        # Reset loadedStatus to 0 so the module will be re-required
        try:
            old_status = self.read_u8(module_addr + loaded_off)
            if old_status != 0x00:
                ok = protected_write_bytes(handle, module_addr + loaded_off, b"\x00")
                debug(f"loadedStatus: 0x{old_status:02X} → 0x00  (write ok={ok})")
                changed = True
            else:
                debug(f"loadedStatus already 0x00")
        except Exception as e:
            debug(f"loadedStatus write failed: {e}")

        return True  # non-fatal if individual writes fail

    # ─────────────────────────────────────────────────────────
    # Bytecode injection (matches C++ SetBytecode)
    # ─────────────────────────────────────────────────────────
    def inject_bytecode(self, module_addr: int, bytecode: bytes) -> bool:
        """
        Matches C++ SetBytecode:
          1. Read embeddedPtr at module + ModuleScript::ByteCode (0x138)
          2. Allocate remote memory for bytecode
          3. Use VirtualProtectEx to write the new ptr and size into embedded struct:
               embedded + 0x10 = bytecodePtr
               embedded + 0x20 = bytecodeSize
        """
        if not module_addr:
            error("Module address is null")
            return False

        handle   = self.pm.process_handle
        bcode_off = self.off("ModuleScript::ByteCode", 0x138)

        try:
            embedded = self.read_ptr(module_addr + bcode_off)
            if not self.is_valid_ptr(embedded):
                error(f"Invalid embedded bytecode struct pointer: 0x{embedded:X}")
                return False

            old_ptr  = self.read_ptr(embedded + 0x10)
            old_size = self.read_u64(embedded + 0x20)
            debug(f"Old bytecode: ptr=0x{old_ptr:X} size={old_size}")

            # Allocate remote memory (PAGE_EXECUTE_READWRITE)
            remote_mem = kernel32.VirtualAllocEx(
                handle,
                None,
                len(bytecode),
                MEM_COMMIT | MEM_RESERVE,
                PAGE_EXECUTE_READWRITE,
            )
            if not remote_mem:
                error(f"VirtualAllocEx failed: {ctypes.GetLastError()}")
                return False

            # Write bytecode into remote memory
            buf     = (ctypes.c_char * len(bytecode))(*bytecode)
            written = ctypes.c_size_t(0)
            ok = kernel32.WriteProcessMemory(handle, ctypes.c_void_p(remote_mem), buf, len(bytecode), ctypes.byref(written))
            if not ok or written.value != len(bytecode):
                error(f"WriteProcessMemory (bytecode) failed: wrote {written.value}/{len(bytecode)}")
                return False

            # Swap pointer & size using VirtualProtectEx
            if not protected_write_ptr(handle, embedded + 0x10, remote_mem):
                error("Failed to write bytecode pointer")
                return False
            if not protected_write_ptr(handle, embedded + 0x20, len(bytecode)):
                error("Failed to write bytecode size")
                return False

            info(f"Injected bytecode @ 0x{remote_mem:X} ({len(bytecode)} bytes) into module 0x{module_addr:X}")
            return True

        except Exception as e:
            error(f"inject_bytecode exception: {e}")
            import traceback; traceback.print_exc()
            return False

    # ─────────────────────────────────────────────────────────
    # ESC trigger (matches C++ keybd_event thread)
    # ─────────────────────────────────────────────────────────
    def trigger_esc(self) -> bool:
        """
        Get Roblox HWND, bring it to foreground, press ESC to trigger module reload.
        Matches the C++ keybd_event(VK_ESCAPE, ...) thread.
        """
        hwnd = get_hwnd_from_pid(self.pm.process_id)
        if not hwnd:
            error("Could not find Roblox HWND")
            return False

        info(f"Sending ESC to Roblox window (HWND=0x{hwnd:X})...")
        send_key(hwnd, VK_ESCAPE)
        return True

    # ─────────────────────────────────────────────────────────
    # Verify injection
    # ─────────────────────────────────────────────────────────
    def verify_injection(self) -> bool:
        """Check if the Syntax folder appeared in CoreGui."""
        if not self._core_gui:
            return False
        existing = self.find_child_by_name(self._core_gui, "Syntax")
        if existing:
            info("[VERIFY] Syntax folder found in CoreGui — injection confirmed!")
            return True
        return False

    # ─────────────────────────────────────────────────────────
    # Reset state on process loss
    # ─────────────────────────────────────────────────────────
    def _reset(self) -> None:
        self.pm           = None
        self.base_module  = None
        self.base_address = 0
        self.is_injected  = False
        self._dm          = 0
        self._core_gui    = 0
        self._roblox_gui  = 0
        self._modules     = 0

    # ─────────────────────────────────────────────────────────
    # Main loop
    # ─────────────────────────────────────────────────────────
    def run(self) -> None:
        if DEBUG_FILE:
            try:
                open("debug.log", "w").close()
            except OSError:
                pass

        self.load_offsets()

        # Start Flask bridge in background
        threading.Thread(
            target=lambda: rbxbcd.app.run(
                host="127.0.0.1", port=19283, threaded=True, use_reloader=False
            ),
            daemon=True,
        ).start()
        info("UNC bridge on http://127.0.0.1:19283")
        info("Waiting for RobloxPlayerBeta.exe...")

        while True:
            try:
                # ── 1. Attach ──
                if not self.pm:
                    if not self.attach():
                        time.sleep(2.0)
                        continue

                # ── 2. Wait for game to load (>550 MB) ──
                if not self.is_injected:
                    self.wait_for_load()

                # ── 3. Resolve DataModel ──
                if not self.is_injected:
                    dm = self.get_datamodel()
                    if not dm:
                        time.sleep(2.0)
                        continue

                    # ── 4. Build navigation cache ──
                    if not self.cache_navigation(dm):
                        time.sleep(2.0)
                        continue

                    # ── 5. Wait for LocalPlayer ──
                    self.wait_for_local_player()

                    # ── 6. Find Url module ──
                    url_module = self.find_url_module()
                    if not url_module:
                        error("Url module not found — cannot inject")
                        time.sleep(5.0)
                        continue

                    # ── 7. Compile init payload ──
                    info("Compiling init payload...")
                    payload = rbxinit.get()
                    info(f"Payload: {len(payload)} bytes")

                    # ── 8. Unlock + inject ──
                    self.unlock_module(url_module)
                    if not self.inject_bytecode(url_module, payload):
                        error("Bytecode injection failed — retrying in 5s")
                        time.sleep(5.0)
                        continue

                    # ── 9. ESC trigger ──
                    time.sleep(0.8)   # small delay matching C++ Sleep(800)
                    if not self.trigger_esc():
                        warn("ESC trigger failed — injection may still work")

                    # ── 10. Verify ──
                    info("[VERIFY] Waiting up to 15s for Syntax folder...")
                    deadline = time.time() + 15.0
                    verified = False
                    while time.time() < deadline:
                        if self.verify_injection():
                            verified = True
                            break
                        time.sleep(0.5)

                    if verified:
                        self.is_injected = True
                        info("SUCCESS — Syntax Executor v1 active!")
                        info("POST scripts → http://127.0.0.1:19283/execute")
                    else:
                        warn("[VERIFY] Syntax folder not detected within 15s")
                        warn("[VERIFY] Injection may have worked — try POST to /execute")
                        # Mark as injected anyway so we don't loop forever
                        self.is_injected = True

            except pymem.exception.ProcessNotFound:
                warn("Roblox process lost — reconnecting...")
                self._reset()

            except Exception as e:
                error(f"Unexpected error: {e}")
                import traceback; traceback.print_exc()

            time.sleep(2.0)


if __name__ == "__main__":
    try:
        SyntaxExecutor().run()
    except KeyboardInterrupt:
        print("\n[*] Shutting down")
