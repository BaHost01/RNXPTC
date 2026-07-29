"""
Luau Bytecode Compiler for Python

Port of the Luau (https://luau.org/) bytecode builder and compiler to pure Python.
Produces valid Luau bytecode compatible with the Luau VM.

Usage:
    from luau import BytecodeBuilder, LuauOpcode, compile_source

    # Programmatic bytecode building
    bb = BytecodeBuilder()
    fid = bb.begin_function(numparams=0, is_vararg=False)
    bb.emit_abc(LuauOpcode.LOADK, 0, 0, bb.add_constant_number(42.0))
    bb.emit_abc(LuauOpcode.RETURN, 0, 1, 0)
    bb.end_function(maxstacksize=1, numupvalues=0)
    bb.set_main_function(fid)
    bb.finalize()
    bytecode = bb.get_bytecode()

    # Compile Luau source to bytecode
    bytecode = compile_source("return 42")
"""

from .bytecode import (
    LuauOpcode,
    LuauBytecodeTag,
    LuauBytecodeType,
    LuauBuiltinFunction,
    LuauCaptureType,
    LuauProtoFlag,
    LuauFeedbackType,
    insn_op,
    insn_a,
    insn_b,
    insn_c,
    insn_d,
    insn_e,
    insn_aux_a,
    insn_aux_b,
    insn_aux_kv,
    insn_aux_kb,
    insn_aux_not,
    insn_aux_kv16,
    insn_aux_slot,
    get_op_length,
    is_jump_d,
    is_skip_c,
    is_fastcall,
    is_fallthrough,
    is_loop_jump,
    get_jump_target,
    LBC_VERSION_TARGET,
    LBC_TYPE_VERSION_TARGET,
    LBC_FBSLOT_SEALED,
)

from .bytecode_builder import (
    BytecodeBuilder,
    BytecodeEncoder,
    RobloxBytecodeEncoder,
    TableShape,
    ClassShape,
    StringRef,
)

from .compiler import (
    CompileOptions,
    CompileError,
    compile_source,
    compile_or_throw,
    compile_roblox,
)

from .signing import (
    sign_bytecode,
    pack_bytecode,
    encode_roblox_bytecode,
)

__all__ = [
    "BytecodeBuilder", "BytecodeEncoder", "RobloxBytecodeEncoder",
    "TableShape", "ClassShape", "StringRef",
    "LuauOpcode", "LuauBytecodeTag", "LuauBytecodeType",
    "LuauBuiltinFunction", "LuauCaptureType", "LuauProtoFlag",
    "LuauFeedbackType",
    "CompileOptions", "CompileError",
    "compile_source", "compile_or_throw", "compile_roblox",
    "sign_bytecode", "pack_bytecode", "encode_roblox_bytecode",
]
