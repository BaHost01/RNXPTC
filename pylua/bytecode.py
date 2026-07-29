"""
Luau Bytecode Definitions

Direct port of Luau/Common/include/Luau/Bytecode.h and BytecodeUtils.h.
Contains all opcodes, constant types, bytecode types, builtin function IDs,
and instruction encoding/decoding helpers.

Bytecode format:
    Each instruction is one or many 32-bit words.
    First word = instruction header with opcode in LSB.
    Encoding variants: ABC, AD, E + optional AUX word.
"""

import enum
import struct
from typing import Tuple


# ─── Bytecode Version ────────────────────────────────────────────

LBC_VERSION_MIN = 3
LBC_VERSION_MAX = 12
LBC_VERSION_TARGET = 7

LBC_TYPE_VERSION_MIN = 1
LBC_TYPE_VERSION_MAX = 3
LBC_TYPE_VERSION_TARGET = 3

LBC_FBSLOT_SEALED = 0xFFFFFFFF


# ─── Opcodes ─────────────────────────────────────────────────────

class LuauOpcode(enum.IntEnum):
    """Luau bytecode opcodes. Values match the C++ enum exactly."""
    NOP = 0
    BREAK = 1
    LOADNIL = 2
    LOADB = 3
    LOADN = 4
    LOADK = 5
    MOVE = 6
    GETGLOBAL = 7
    SETGLOBAL = 8
    GETUPVAL = 9
    SETUPVAL = 10
    CLOSEUPVALS = 11
    GETIMPORT = 12
    GETTABLE = 13
    SETTABLE = 14
    GETTABLEKS = 15
    SETTABLEKS = 16
    GETTABLEN = 17
    SETTABLEN = 18
    NEWCLOSURE = 19
    NAMECALL = 20
    CALL = 21
    RETURN = 22
    JUMP = 23
    JUMPBACK = 24
    JUMPIF = 25
    JUMPIFNOT = 26
    JUMPIFEQ = 27
    JUMPIFLE = 28
    JUMPIFLT = 29
    JUMPIFNOTEQ = 30
    JUMPIFNOTLE = 31
    JUMPIFNOTLT = 32
    ADD = 33
    SUB = 34
    MUL = 35
    DIV = 36
    MOD = 37
    POW = 38
    ADDK = 39
    SUBK = 40
    MULK = 41
    DIVK = 42
    MODK = 43
    POWK = 44
    AND = 45
    OR = 46
    ANDK = 47
    ORK = 48
    CONCAT = 49
    NOT = 50
    MINUS = 51
    LENGTH = 52
    NEWTABLE = 53
    DUPTABLE = 54
    SETLIST = 55
    FORNPREP = 56
    FORNLOOP = 57
    FORGLOOP = 58
    FORGPREP_INEXT = 59
    FASTCALL3 = 60
    FORGPREP_NEXT = 61
    NATIVECALL = 62
    GETVARARGS = 63
    DUPCLOSURE = 64
    PREPVARARGS = 65
    LOADKX = 66
    JUMPX = 67
    FASTCALL = 68
    COVERAGE = 69
    CAPTURE = 70
    SUBRK = 71
    DIVRK = 72
    FASTCALL1 = 73
    FASTCALL2 = 74
    FASTCALL2K = 75
    FORGPREP = 76
    JUMPXEQKNIL = 77
    JUMPXEQKB = 78
    JUMPXEQKN = 79
    JUMPXEQKS = 80
    IDIV = 81
    IDIVK = 82
    GETUDATAKS = 83
    SETUDATAKS = 84
    NAMECALLUDATA = 85
    NEWCLASSMEMBER = 86
    CALLFB = 87
    CMPPROTO = 88
    __COUNT = 89


# ─── Bytecode Tags (constant types in serialized form) ────────────

class LuauBytecodeTag(enum.IntEnum):
    LBC_CONSTANT_NIL = 0
    LBC_CONSTANT_BOOLEAN = 1
    LBC_CONSTANT_NUMBER = 2
    LBC_CONSTANT_STRING = 3
    LBC_CONSTANT_IMPORT = 4
    LBC_CONSTANT_TABLE = 5
    LBC_CONSTANT_CLOSURE = 6
    LBC_CONSTANT_VECTOR = 7
    LBC_CONSTANT_TABLE_WITH_CONSTANTS = 8
    LBC_CONSTANT_INTEGER = 9
    LBC_CONSTANT_CLASS_SHAPE = 10


# ─── Bytecode Type Tags ──────────────────────────────────────────

class LuauBytecodeType(enum.IntEnum):
    LBC_TYPE_NIL = 0
    LBC_TYPE_BOOLEAN = 1
    LBC_TYPE_NUMBER = 2
    LBC_TYPE_STRING = 3
    LBC_TYPE_TABLE = 4
    LBC_TYPE_FUNCTION = 5
    LBC_TYPE_THREAD = 6
    LBC_TYPE_USERDATA = 7
    LBC_TYPE_VECTOR = 8
    LBC_TYPE_BUFFER = 9
    LBC_TYPE_INTEGER = 10
    LBC_TYPE_ANY = 15
    LBC_TYPE_TAGGED_USERDATA_BASE = 64
    LBC_TYPE_TAGGED_USERDATA_END = 96
    LBC_TYPE_OPTIONAL_BIT = 1 << 7
    LBC_TYPE_INVALID = 256


# ─── Builtin Function IDs ────────────────────────────────────────

class LuauBuiltinFunction(enum.IntEnum):
    NONE = 0
    ASSERT = 1
    # math.*
    MATH_ABS = 2
    MATH_ACOS = 3
    MATH_ASIN = 4
    MATH_ATAN2 = 5
    MATH_ATAN = 6
    MATH_CEIL = 7
    MATH_COSH = 8
    MATH_COS = 9
    MATH_DEG = 10
    MATH_EXP = 11
    MATH_FLOOR = 12
    MATH_FMOD = 13
    MATH_FREXP = 14
    MATH_LDEXP = 15
    MATH_LOG10 = 16
    MATH_LOG = 17
    MATH_MAX = 18
    MATH_MIN = 19
    MATH_MODF = 20
    MATH_POW = 21
    MATH_RAD = 22
    MATH_SINH = 23
    MATH_SIN = 24
    MATH_SQRT = 25
    MATH_TANH = 26
    MATH_TAN = 27
    # bit32.*
    BIT32_ARSHIFT = 28
    BIT32_BAND = 29
    BIT32_BNOT = 30
    BIT32_BOR = 31
    BIT32_BXOR = 32
    BIT32_BTEST = 33
    BIT32_EXTRACT = 34
    BIT32_LROTATE = 35
    BIT32_LSHIFT = 36
    BIT32_REPLACE = 37
    BIT32_RROTATE = 38
    BIT32_RSHIFT = 39
    TYPE = 40
    # string.*
    STRING_BYTE = 41
    STRING_CHAR = 42
    STRING_LEN = 43
    TYPEOF = 44
    STRING_SUB = 45
    # math.* continued
    MATH_CLAMP = 46
    MATH_SIGN = 47
    MATH_ROUND = 48
    # raw*
    RAWSET = 49
    RAWGET = 50
    RAWEQUAL = 51
    # table.*
    TABLE_INSERT = 52
    TABLE_UNPACK = 53
    VECTOR = 54
    BIT32_COUNTLZ = 55
    BIT32_COUNTRZ = 56
    SELECT_VARARG = 57
    RAWLEN = 58
    BIT32_EXTRACTK = 59
    GETMETATABLE = 60
    SETMETATABLE = 61
    TONUMBER = 62
    TOSTRING = 63
    BIT32_BYTESWAP = 64
    # buffer.*
    BUFFER_READI8 = 65
    BUFFER_READU8 = 66
    BUFFER_WRITEU8 = 67
    BUFFER_READI16 = 68
    BUFFER_READU16 = 69
    BUFFER_WRITEU16 = 70
    BUFFER_READI32 = 71
    BUFFER_READU32 = 72
    BUFFER_WRITEU32 = 73
    BUFFER_READF32 = 74
    BUFFER_WRITEF32 = 75
    BUFFER_READF64 = 76
    BUFFER_WRITEF64 = 77
    # vector.*
    VECTOR_MAGNITUDE = 78
    VECTOR_NORMALIZE = 79
    VECTOR_CROSS = 80
    VECTOR_DOT = 81
    VECTOR_FLOOR = 82
    VECTOR_CEIL = 83
    VECTOR_ABS = 84
    VECTOR_SIGN = 85
    VECTOR_CLAMP = 86
    VECTOR_MIN = 87
    VECTOR_MAX = 88
    MATH_LERP = 89
    VECTOR_LERP = 90
    MATH_ISNAN = 91
    MATH_ISINF = 92
    MATH_ISFINITE = 93
    # integer.*
    INTEGER_CREATE = 94
    INTEGER_TONUMBER = 95
    INTEGER_NEG = 96
    INTEGER_ADD = 97
    INTEGER_SUB = 98
    INTEGER_MUL = 99
    INTEGER_DIV = 100
    INTEGER_MIN = 101
    INTEGER_MAX = 102
    INTEGER_REM = 103
    INTEGER_IDIV = 104
    INTEGER_UDIV = 105
    INTEGER_UREM = 106
    INTEGER_MOD = 107
    INTEGER_CLAMP = 108
    INTEGER_BAND = 109
    INTEGER_BOR = 110
    INTEGER_BNOT = 111
    INTEGER_BXOR = 112
    INTEGER_LT = 113
    INTEGER_LE = 114
    INTEGER_ULT = 115
    INTEGER_ULE = 116
    INTEGER_GT = 117
    INTEGER_GE = 118
    INTEGER_UGT = 119
    INTEGER_UGE = 120
    INTEGER_LSHIFT = 121
    INTEGER_RSHIFT = 122
    INTEGER_ARSHIFT = 123
    INTEGER_LROTATE = 124
    INTEGER_RROTATE = 125
    INTEGER_EXTRACT = 126
    INTEGER_BTEST = 127
    INTEGER_COUNTRZ = 128
    INTEGER_COUNTLZ = 129
    INTEGER_BSWAP = 130
    # buffer read/write integer (int64_t)
    BUFFER_READINTEGER = 131
    BUFFER_WRITEINTEGER = 132


# ─── Capture Type ────────────────────────────────────────────────

class LuauCaptureType(enum.IntEnum):
    VAL = 0
    REF = 1
    UPVAL = 2


# ─── Proto Flags ─────────────────────────────────────────────────

class LuauProtoFlag(enum.IntEnum):
    NATIVE_MODULE = 1 << 0
    NATIVE_COLD = 1 << 1
    NATIVE_FUNCTION = 1 << 2
    INLINABLE = 1 << 3


# ─── Feedback Type ───────────────────────────────────────────────

class LuauFeedbackType(enum.IntEnum):
    CALLTARGET = 0


# ─── Instruction Encoding/Decoding ───────────────────────────────

def insn_op(insn: int) -> int:
    """Extract opcode byte from instruction word."""
    return insn & 0xFF


def insn_a(insn: int) -> int:
    """Extract A (bits 8-15) from ABC/AD encoding."""
    return (insn >> 8) & 0xFF


def insn_b(insn: int) -> int:
    """Extract B (bits 16-23) from ABC encoding."""
    return (insn >> 16) & 0xFF


def insn_c(insn: int) -> int:
    """Extract C (bits 24-31) from ABC encoding."""
    return (insn >> 24) & 0xFF


def insn_d(insn: int) -> int:
    """Extract D (signed 16-bit, bits 16-31) from AD encoding."""
    return (insn & 0xFFFF0000) >> 16 if (insn & 0x80000000) == 0 else ((insn >> 16) - 0x10000)


def _insn_d_raw(insn: int) -> int:
    """Extract D as raw unsigned 16-bit value."""
    return (insn >> 16) & 0xFFFF


def insn_e(insn: int) -> int:
    """Extract E (signed 24-bit, bits 8-31)."""
    val = (insn >> 8) & 0xFFFFFF
    if val & 0x800000:
        val -= 0x1000000
    return val


def insn_aux_a(aux: int) -> int:
    """Extract A from AUX word (bits 0-7)."""
    return aux & 0xFF


def insn_aux_b(aux: int) -> int:
    """Extract B from AUX word (bits 8-15)."""
    return (aux >> 8) & 0xFF


def insn_aux_kv(aux: int) -> int:
    """Extract 24-bit constant index from AUX (used in JUMPXEQK*)."""
    return aux & 0xFFFFFF


def insn_aux_kb(aux: int) -> int:
    """Extract 1-bit boolean from AUX (used in JUMPXEQKB)."""
    return aux & 0x1


def insn_aux_not(aux: int) -> int:
    """Extract negation flag from AUX bit 31."""
    return aux >> 31


def insn_aux_kv16(aux: int) -> int:
    """Extract 16-bit constant index from AUX (used in GETUDATAKS et al)."""
    return aux & 0xFFFF


def insn_aux_slot(aux: int) -> int:
    """Extract 16-bit slot from AUX (bits 16-31)."""
    return aux >> 16


# ─── Instruction Encoding Builders ───────────────────────────────

def encode_abc(op: LuauOpcode, a: int, b: int, c: int) -> int:
    """Build instruction word with ABC encoding."""
    return int(op) | (a << 8) | (b << 16) | (c << 24)


def encode_ad(op: LuauOpcode, a: int, d: int) -> int:
    """Build instruction word with AD encoding."""
    return int(op) | (a << 8) | ((d & 0xFFFF) << 16)


def encode_e(op: LuauOpcode, e: int) -> int:
    """Build instruction word with E encoding (signed 24-bit)."""
    return int(op) | ((e & 0xFFFFFF) << 8)


# ─── Opcode Classification ───────────────────────────────────────

# Opcodes that are 2 words long (have AUX)
_AUX_OPCODES = frozenset({
    LuauOpcode.GETGLOBAL,
    LuauOpcode.SETGLOBAL,
    LuauOpcode.GETIMPORT,
    LuauOpcode.GETTABLEKS,
    LuauOpcode.SETTABLEKS,
    LuauOpcode.NAMECALL,
    LuauOpcode.JUMPIFEQ,
    LuauOpcode.JUMPIFLE,
    LuauOpcode.JUMPIFLT,
    LuauOpcode.JUMPIFNOTEQ,
    LuauOpcode.JUMPIFNOTLE,
    LuauOpcode.JUMPIFNOTLT,
    LuauOpcode.NEWTABLE,
    LuauOpcode.SETLIST,
    LuauOpcode.FORGLOOP,
    LuauOpcode.LOADKX,
    LuauOpcode.FASTCALL2,
    LuauOpcode.FASTCALL2K,
    LuauOpcode.FASTCALL3,
    LuauOpcode.JUMPXEQKNIL,
    LuauOpcode.JUMPXEQKB,
    LuauOpcode.JUMPXEQKN,
    LuauOpcode.JUMPXEQKS,
    LuauOpcode.GETUDATAKS,
    LuauOpcode.SETUDATAKS,
    LuauOpcode.NAMECALLUDATA,
    LuauOpcode.NEWCLASSMEMBER,
    LuauOpcode.CALLFB,
    LuauOpcode.CMPPROTO,
})


def get_op_length(op: LuauOpcode) -> int:
    """Return number of 32-bit words for an opcode (1 or 2)."""
    return 2 if op in _AUX_OPCODES else 1


# Opcodes using D field for jump offsets
_JUMP_D = frozenset({
    LuauOpcode.JUMP,
    LuauOpcode.JUMPIF,
    LuauOpcode.JUMPIFNOT,
    LuauOpcode.JUMPIFEQ,
    LuauOpcode.JUMPIFLE,
    LuauOpcode.JUMPIFLT,
    LuauOpcode.JUMPIFNOTEQ,
    LuauOpcode.JUMPIFNOTLE,
    LuauOpcode.JUMPIFNOTLT,
    LuauOpcode.FORNPREP,
    LuauOpcode.FORNLOOP,
    LuauOpcode.FORGPREP,
    LuauOpcode.FORGLOOP,
    LuauOpcode.FORGPREP_INEXT,
    LuauOpcode.FORGPREP_NEXT,
    LuauOpcode.JUMPBACK,
    LuauOpcode.JUMPXEQKNIL,
    LuauOpcode.JUMPXEQKB,
    LuauOpcode.JUMPXEQKN,
    LuauOpcode.JUMPXEQKS,
    LuauOpcode.CMPPROTO,
})


def is_jump_d(op: LuauOpcode) -> bool:
    """Check if opcode uses D field for jump offset."""
    return op in _JUMP_D


_SKIP_C = frozenset({LuauOpcode.LOADB})


def is_skip_c(op: LuauOpcode) -> bool:
    """Check if opcode uses C field for skip offset (only LOADB)."""
    return op in _SKIP_C


_FASTCALL = frozenset({
    LuauOpcode.FASTCALL,
    LuauOpcode.FASTCALL1,
    LuauOpcode.FASTCALL2,
    LuauOpcode.FASTCALL2K,
    LuauOpcode.FASTCALL3,
})


def is_fastcall(op: LuauOpcode) -> bool:
    """Check if opcode is a FASTCALL variant."""
    return op in _FASTCALL


_NON_FALLTHROUGH = frozenset({
    LuauOpcode.RETURN,
    LuauOpcode.JUMP,
    LuauOpcode.JUMPBACK,
    LuauOpcode.JUMPX,
})


def is_fallthrough(op: LuauOpcode) -> bool:
    """Check if opcode can fall through to next instruction."""
    return op not in _NON_FALLTHROUGH


_LOOP_JUMPS = frozenset({
    LuauOpcode.JUMPBACK,
    LuauOpcode.FORGLOOP,
    LuauOpcode.FORNLOOP,
})


def is_loop_jump(op: LuauOpcode) -> bool:
    """Check if opcode represents a loop backedge."""
    return op in _LOOP_JUMPS


def get_jump_target(insn: int, pc: int) -> int:
    """
    Compute absolute PC of the jump target from an instruction word.

    Returns -1 if the instruction doesn't jump.
    """
    op = LuauOpcode(insn_op(insn))

    if is_jump_d(op):
        return pc + insn_d(insn) + 1
    elif is_fastcall(op):
        return pc + insn_c(insn) + 2
    elif is_skip_c(op) and insn_c(insn):
        return pc + insn_c(insn) + 1
    elif op == LuauOpcode.JUMPX:
        return pc + insn_e(insn) + 1
    else:
        return -1


# ─── Import ID Encoding ──────────────────────────────────────────

def get_import_id(id0: int, id1: int = -1, id2: int = -1) -> int:
    """
    Encode 1-3 string constant indices into a 32-bit import ID.

    Format: bits 30-31 = path length (1-3), remaining bits = 10-bit indices.
    """
    if id2 >= 0:
        return (3 << 30) | (id0 << 20) | (id1 << 10) | id2
    elif id1 >= 0:
        return (2 << 30) | (id0 << 20) | (id1 << 10)
    else:
        return (1 << 30) | (id0 << 20)


def decompose_import_id(import_id: int) -> Tuple[int, list]:
    """Decompose import ID into (count, [id0, id1, id2])."""
    count = import_id >> 30
    ids = []
    if count > 0:
        ids.append((import_id >> 20) & 1023)
    if count > 1:
        ids.append((import_id >> 10) & 1023)
    if count > 2:
        ids.append(import_id & 1023)
    return count, ids


# ─── String Hashing (Lua 5.1-compatible) ────────────────────────

def get_string_hash(data: bytes) -> int:
    """
    Compute Lua 5.1-compatible short string hash.

    Must match luaS_hash in VM/lstring.cpp for short inputs (<32 bytes).
    Embedded in GETTABLEKS/SETTABLEKS/NAMECALL to predict hash slot.
    """
    h = len(data)
    for i in range(len(data) - 1, -1, -1):
        h = (h ^ ((h << 5) + (h >> 2) + data[i])) & 0xFFFFFFFF
    return h


def get_string_hash_str(s: str) -> int:
    """Compute Lua 5.1 string hash from a Python string."""
    return get_string_hash(s.encode('utf-8', errors='surrogateescape'))


# ─── Variable-Integer Encoding ───────────────────────────────────

def encode_varint(value: int) -> bytes:
    """Encode unsigned integer as variable-length byte sequence."""
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        result.append(byte)
        if not value:
            break
    return bytes(result)


def decode_varint(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """Decode variable-length unsigned integer. Returns (value, new_offset)."""
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            break
    return value, offset


# ─── Log2 Utility ────────────────────────────────────────────────

def _log2(v: int) -> int:
    """Floor log2 for positive integers."""
    r = 0
    while v >= (2 << r):
        r += 1
    return r
