"""
Encoder – Luau compilation & signing pipeline for Roblox injection.

Provides single-step encoding for Roblox bytecode (compile + sign + pack)
as well as pure Luau compilation for local debugging.
"""

from typing import Optional
from luau import compile_roblox, compile_source, CompileOptions


def encode_script(source_code: str, pack: bool = True) -> bytes:
    """
    Compile, sign, and optionally pack Luau source into Roblox-ready bytecode.

    Args:
        source_code: Raw Luau / Lua source code string.
        pack: When True, prepend the RBYT header and compress with ZSTD.

    Returns:
        Signed (and packed) bytecode suitable for direct memory injection.

    Raises:
        luau.compiler.CompileError: If compilation fails.
    """
    return compile_roblox(source_code, pack=pack)


def encode_batch(*scripts: str, pack: bool = True) -> list[bytes]:
    """
    Compile multiple scripts in batch.

    Returns a list of compiled bytecode blobs in the same order.
    """
    return [compile_roblox(script, pack=pack) for script in scripts]


def compile_pure(source_code: str) -> bytes:
    """
    Standard Luau compilation without Roblox encryption or signing.

    Useful for offline testing / debugging the compiler output.
    """
    return compile_source(source_code)


def compile_with_options(source_code: str, options: Optional[CompileOptions] = None) -> bytes:
    """Compile with explicit compiler options (optimization, debug level, etc.)."""
    return compile_source(source_code, options)


def quick_test(source_code: str) -> bool:
    """
    Performs a dry-run compilation and returns True if the source is valid Luau,
    False otherwise. Does NOT sign or pack the result.
    """
    try:
        compile_source(source_code)
        return True
    except Exception:
        return False
