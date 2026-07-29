"""
Luau Bytecode Signing and Packing

Port of bytecode_signer.h and rsb1_encoder.h.
Implements Roblox-compatible bytecode signing (SHA256 footer) 
and packing (RBYT + ZSTD).
"""

import hashlib
import struct
from typing import Union, List

try:
    import zstandard as zstd
except ImportError:
    zstd = None


def sign_bytecode(bytecode: bytes) -> bytes:
    """
    Appends a 24-byte SHA256-derived signature footer to the bytecode.
    Required for Roblox VM execution.
    """
    if not bytecode:
        return b""

    # Step 1: SHA256 hash
    hasher = hashlib.sha256()
    hasher.update(bytecode)
    h = hasher.digest()

    # Step 2: Build 24-byte footer
    # hash[0:4] + hash[4:20] + transforms(hash[0:4])
    footer = bytearray(24)
    footer[0:4] = h[0:4]
    footer[4:20] = h[4:20]

    # Step 3: XOR transforms
    # uint16 w0 = h[0:2] ^ 0xC432
    w0 = struct.unpack('<H', h[0:2])[0] ^ 0xC432
    
    footer[20:22] = struct.pack('<H', w0)
    footer[22] = h[2] ^ 0x6A
    footer[23] = h[3] ^ 0x01

    return bytecode + footer


def pack_bytecode(payload: bytes) -> bytes:
    """
    Packs payload with RBYT header and ZSTD compression.
    Format: [4B MAGIC 'RBYT'] [4B Original Size] [ZSTD Data]
    """
    if zstd is None:
        raise ImportError("zstandard library is required for bytecode packing. Install it via 'pip install zstandard'.")

    MAGIC = b'RBYT'
    original_size = len(payload)
    
    # Compress with max level as in C++ (ZSTD_maxCLevel())
    cctx = zstd.ZstdCompressor(level=22)
    compressed = cctx.compress(payload)
    
    return MAGIC + struct.pack('<I', original_size) + compressed


def encode_roblox_bytecode(bytecode: bytes, pack: bool = True) -> bytes:
    """
    Full Roblox bytecode pipeline:
    1. Sign with SHA256 footer.
    2. (Optional) Pack with ZSTD and RBYT header.
    """
    signed = sign_bytecode(bytecode)
    if pack:
        return pack_bytecode(signed)
    return signed
