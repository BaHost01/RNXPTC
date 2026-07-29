"""
Pymem Helper Framework
Encapsulates process connection, pointer path resolution, pattern scanning,
and strongly-typed memory operations.
"""

from typing import List, Optional, Union
import pymem
import pymem.exception
import pymem.pattern
import pymem.process


class PymemHelper:
    """
    Wrapper class around Pymem for easier process interaction, 
    multi-level pointer dereferencing, and memory manipulation.
    """

    def __init__(self, process_target: Union[str, int, None] = None):
        """
        Initialize the helper.
        :param process_target: Process name (str, e.g., 'ac_client.exe') or PID (int).
        """
        self.pm: Optional[pymem.Pymem] = None
        self.target: Union[str, int, None] = process_target

        if process_target:
            self.attach(process_target)

    # -------------------------------------------------------------------------
    # Context Manager & Lifecycle
    # -------------------------------------------------------------------------
    def __enter__(self):
        if not self.is_attached and self.target:
            self.attach(self.target)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.detach()

    @property
    def is_attached(self) -> bool:
        """Checks if Pymem is currently hooked to a running process."""
        if not self.pm or not self.pm.process_handle:
            return False
        try:
            # Simple check to confirm the handle is still valid
            return self.pm.running
        except Exception:
            return False

    def attach(self, target: Union[str, int]) -> bool:
        """
        Attaches Pymem to the target process by name or PID.
        """
        try:
            if isinstance(target, int):
                self.pm = pymem.Pymem(target)
            else:
                self.pm = pymem.Pymem(target)
            self.target = target
            return True
        except pymem.exception.ProcessNotFound:
            print(f"[PymemHelper] Process '{target}' not found.")
            self.pm = None
            return False
        except pymem.exception.CouldNotOpenProcess:
            print(f"[PymemHelper] Could not open process '{target}'. (Try running as Administrator)")
            self.pm = None
            return False

    def detach(self) -> None:
        """Closes the process handle."""
        if self.pm:
            try:
                self.pm.close_process()
            except Exception:
                pass
            finally:
                self.pm = None

    # -------------------------------------------------------------------------
    # Module & Base Address Helpers
    # -------------------------------------------------------------------------
    def get_module_base(self, module_name: str) -> Optional[int]:
        """Gets the base address of a module (e.g., 'engine.dll' or the main exe)."""
        if not self.is_attached:
            return None
        module = pymem.process.module_from_name(self.pm.process_handle, module_name)
        return module.lpBaseOfDll if module else None

    def get_module_size(self, module_name: str) -> Optional[int]:
        """Gets the memory size of a loaded module."""
        if not self.is_attached:
            return None
        module = pymem.process.module_from_name(self.pm.process_handle, module_name)
        return module.SizeOfImage if module else None

    # -------------------------------------------------------------------------
    # Multi-Level Pointer Resolution
    # -------------------------------------------------------------------------
    def resolve_pointer(self, base_address: int, offsets: List[int]) -> Optional[int]:
        """
        Resolves a multi-level pointer chain.
        
        Example:
            base = 0x00400000 + 0x10F4F4
            offsets = [0x3C, 0x14, 0x0]
            addr = helper.resolve_pointer(base, offsets)
        """
        if not self.is_attached:
            return None

        try:
            addr = self.pm.read_int(base_address)
            for offset in offsets[:-1]:
                addr = self.pm.read_int(addr + offset)
            return addr + offsets[-1] if offsets else addr
        except pymem.exception.MemoryReadError:
            return None

    # -------------------------------------------------------------------------
    # Pattern Scanning (AOB / Array of Bytes)
    # -------------------------------------------------------------------------
    def pattern_scan_module(self, module_name: str, pattern: bytes) -> Optional[int]:
        """
        Scans a specific module's memory region for a byte pattern.
        """
        if not self.is_attached:
            return None
        try:
            module = pymem.process.module_from_name(self.pm.process_handle, module_name)
            if not module:
                return None
            return pymem.pattern.pattern_scan_module(self.pm.process_handle, module, pattern)
        except Exception as e:
            print(f"[PymemHelper] Pattern scan failed: {e}")
            return None

    # -------------------------------------------------------------------------
    # Memory Reading Wrappers
    # -------------------------------------------------------------------------
    def read_int(self, address: int) -> Optional[int]:
        try:
            return self.pm.read_int(address) if self.is_attached else None
        except pymem.exception.MemoryReadError:
            return None

    def read_float(self, address: int) -> Optional[float]:
        try:
            return self.pm.read_float(address) if self.is_attached else None
        except pymem.exception.MemoryReadError:
            return None

    def read_double(self, address: int) -> Optional[float]:
        try:
            return self.pm.read_double(address) if self.is_attached else None
        except pymem.exception.MemoryReadError:
            return None

    def read_bool(self, address: int) -> Optional[bool]:
        try:
            return self.pm.read_bool(address) if self.is_attached else None
        except pymem.exception.MemoryReadError:
            return None

    def read_string(self, address: int, length: int = 50) -> Optional[str]:
        try:
            return self.pm.read_string(address, byte=length) if self.is_attached else None
        except pymem.exception.MemoryReadError:
            return None

    def read_bytes(self, address: int, length: int) -> Optional[bytes]:
        try:
            return self.pm.read_bytes(address, length) if self.is_attached else None
        except pymem.exception.MemoryReadError:
            return None

    # -------------------------------------------------------------------------
    # Memory Writing Wrappers
    # -------------------------------------------------------------------------
    def write_int(self, address: int, value: int) -> bool:
        try:
            if self.is_attached:
                self.pm.write_int(address, value)
                return True
        except pymem.exception.MemoryWriteError:
            pass
        return False

    def write_float(self, address: int, value: float) -> bool:
        try:
            if self.is_attached:
                self.pm.write_float(address, value)
                return True
        except pymem.exception.MemoryWriteError:
            pass
        return False

    def write_double(self, address: int, value: float) -> bool:
        try:
            if self.is_attached:
                self.pm.write_double(address, value)
                return True
        except pymem.exception.MemoryWriteError:
            pass
        return False

    def write_bool(self, address: int, value: bool) -> bool:
        try:
            if self.is_attached:
                self.pm.write_bool(address, value)
                return True
        except pymem.exception.MemoryWriteError:
            pass
        return False

    def write_string(self, address: int, value: str) -> bool:
        try:
            if self.is_attached:
                self.pm.write_string(address, value)
                return True
        except pymem.exception.MemoryWriteError:
            pass
        return False

    def write_bytes(self, address: int, value: bytes) -> bool:
        try:
            if self.is_attached:
                self.pm.write_bytes(address, value, len(value))
                return True
        except pymem.exception.MemoryWriteError:
            pass
        return False
