"""
Luau Bytecode Builder in Pure Python

Port of Luau/Compiler/src/BytecodeBuilder.cpp and BytecodeBuilder.h.
Allows building valid Luau bytecode from scratch, emitting instructions, managing
constants, doing jump folding/expansion, and serializing to binary.
"""

import struct
from typing import List, Dict, Tuple, Optional, Set
from .bytecode import (
    LuauOpcode,
    LuauBytecodeTag,
    LuauBytecodeType,
    LuauBuiltinFunction,
    LuauFeedbackType,
    get_import_id,
    get_string_hash,
    encode_varint,
    get_op_length,
    is_jump_d,
    is_skip_c,
    is_fastcall,
    LBC_VERSION_TARGET,
    LBC_TYPE_VERSION_TARGET,
    _log2,
)


class BytecodeEncoder:
    """Interface to provide custom bytecode obfuscation/encoding if needed."""
    def encode(self, data: List[int]) -> List[int]:
        raise NotImplementedError


class RobloxBytecodeEncoder(BytecodeEncoder):
    """
    Encoder that encrypts opcodes using a multiplier of 227.
    Required for Roblox's Luau VM.
    """
    def encode(self, data: List[int]) -> List[int]:
        encoded = list(data)
        i = 0
        while i < len(encoded):
            insn = encoded[i]
            op = LuauOpcode(insn & 0xFF)
            
            # Encrypt opcode: (opcode * 227) & 0xFF
            new_op = (int(op) * 227) & 0xFF
            encoded[i] = (insn & 0xFFFFFF00) | new_op
            
            i += get_op_length(op)
        return encoded


class StringRef:
    """Wrapper around string data for Luau compatibility."""
    def __init__(self, data: bytes):
        if isinstance(data, str):
            data = data.encode('utf-8', errors='surrogateescape')
        self.data = data
        self.length = len(data)

    def __eq__(self, other):
        if not isinstance(other, StringRef):
            return False
        return self.data == other.data

    def __hash__(self):
        return hash(self.data)


class TableShape:
    """Defines pre-allocated table shapes (used in DUPTABLE / LBC_CONSTANT_TABLE)."""
    def __init__(self, keys: List[int], constants: Optional[List[int]] = None):
        self.keys = list(keys)
        self.constants = list(constants) if constants else []
        self.length = len(keys)
        self.has_constants = bool(constants)

    def __eq__(self, other):
        if not isinstance(other, TableShape):
            return False
        if self.length != other.length or self.has_constants != other.has_constants:
            return False
        if self.keys != other.keys:
            return False
        if self.has_constants and self.constants != other.constants:
            return False
        return True

    def __hash__(self):
        h = 2166136261
        for k in self.keys:
            h = ((h ^ k) * 16777619) & 0xFFFFFFFF
        if self.has_constants:
            for c in self.constants:
                h = ((h ^ c) * 16777619) & 0xFFFFFFFF
        h = ((h ^ int(self.has_constants)) * 16777619) & 0xFFFFFFFF
        return h


class ClassShape:
    """Defines class shapes (experimental Luau feature)."""
    def __init__(self, class_name: int = -1, property_names: Optional[List[int]] = None, method_names: Optional[List[int]] = None):
        self.class_name = class_name
        self.property_names = list(property_names) if property_names else []
        self.method_names = list(method_names) if method_names else []


class Constant:
    """Representation of a constant table entry."""
    def __init__(self, ctype: int, value):
        self.ctype = ctype
        self.value = value  # Can be bool, float, str/bytes, list (vector), int


class ConstantKey:
    """Hashable key for constant deduplication."""
    def __init__(self, ctype: int, value, extra=None):
        self.ctype = ctype
        self.value = value
        self.extra = extra

    def __eq__(self, other):
        if not isinstance(other, ConstantKey):
            return False
        return self.ctype == other.ctype and self.value == other.value and self.extra == other.extra

    def __hash__(self):
        if self.ctype == LuauBytecodeTag.LBC_CONSTANT_VECTOR:
            # Replicate vector coordinates spatial hash
            # value contains (x, y), extra contains (z, w)
            x, y = self.value
            z, w = self.extra
            # convert floats to raw float binary bytes, then pack as uint32s
            i0, i1 = struct.unpack('<II', struct.pack('<ff', x, y))
            i2, i3 = struct.unpack('<II', struct.pack('<ff', z, w))
            i0 ^= i0 >> 17
            i1 ^= i1 >> 17
            i2 ^= i2 >> 17
            i3 ^= i3 >> 17
            h = (i0 * 73856093) ^ (i1 * 19349663) ^ (i2 * 83492791) ^ (i3 * 39916801)
            return h & 0xFFFFFFFF
        else:
            return hash((self.ctype, self.value, self.extra))


class Function:
    """State of an in-progress function prototype."""
    def __init__(self):
        self.data = bytearray()
        self.maxstacksize = 0
        self.numparams = 0
        self.numupvalues = 0
        self.isvararg = False
        self.debugname = 0
        self.debuglinedefined = 0
        self.dump = ""
        self.dumpname = ""
        self.dumpinstoffs: List[int] = []
        self.typeinfo = bytearray()


class DebugLocal:
    def __init__(self, name: int, reg: int, startpc: int, endpc: int):
        self.name = name
        self.reg = reg
        self.startpc = startpc
        self.endpc = endpc


class DebugUpval:
    def __init__(self, name: int):
        self.name = name


class TypedLocal:
    def __init__(self, type_tag: int, reg: int, startpc: int, endpc: int):
        self.type_tag = type_tag
        self.reg = reg
        self.startpc = startpc
        self.endpc = endpc


class TypedUpval:
    def __init__(self, type_tag: int):
        self.type_tag = type_tag


class UserdataType:
    def __init__(self, name: str):
        self.name = name
        self.name_ref = 0
        self.used = False


class Jump:
    def __init__(self, source: int, target: int):
        self.source = source
        self.target = target


class BytecodeBuilder:
    """Constructs valid Luau bytecode blobs."""
    def __init__(self, encoder: Optional[BytecodeEncoder] = None):
        self.encoder = encoder
        self.functions: List[Function] = []
        self.current_function: int = 0xFFFFFFFF
        self.main_function: int = 0xFFFFFFFF

        self.total_instruction_count = 0
        self.insns: List[int] = []
        self.lines: List[int] = []
        self.constants: List[Constant] = []
        self.protos: List[int] = []
        self.jumps: List[Jump] = []

        self.table_shapes: List[TableShape] = []
        self.class_shapes: List[ClassShape] = []
        self.fb_slots: List[int] = []

        self.has_long_jumps = False

        self.constant_map: Dict[ConstantKey, int] = {}
        self.table_shape_map: Dict[TableShape, int] = {}
        self.proto_map: Dict[int, int] = {}

        self.debug_line = 0

        self.debug_locals: List[DebugLocal] = []
        self.debug_upvals: List[DebugUpval] = []

        self.typed_locals: List[TypedLocal] = []
        self.typed_upvals: List[TypedUpval] = []

        self.userdata_types: List[UserdataType] = []

        # stringTable maps from raw bytes key to its 1-based index
        self.string_table: Dict[bytes, int] = {}
        self.debug_strings: List[bytes] = []

        self.debug_remarks: List[Tuple[int, int]] = []
        self.debug_remark_buffer = bytearray()

        self.bytecode = bytearray()
        self.dump_flags = 0
        self.temp_type_info = bytearray()

        # Reserve empty string
        self.add_string_table_entry(b"")

    def begin_function(self, numparams: int, is_vararg: bool = False) -> int:
        assert self.current_function == 0xFFFFFFFF

        fid = len(self.functions)
        func = Function()
        func.numparams = numparams
        func.isvararg = is_vararg
        self.functions.append(func)
        self.current_function = fid

        self.has_long_jumps = False
        self.debug_line = 0
        return fid

    def end_function(self, maxstacksize: int, numupvalues: int, flags: int = 0, cost_model: int = 0):
        assert self.current_function != 0xFFFFFFFF

        func = self.functions[self.current_function]
        func.maxstacksize = maxstacksize
        func.numupvalues = numupvalues

        # fold / expand jumps
        self.fold_jumps()
        self.expand_jumps()

        if self.encoder:
            # apply bytecode encoding if provided
            self.insns = self.encoder.encode(self.insns)

        # serialize function proto state
        self.write_function(func.data, self.current_function, flags)

        self.current_function = 0xFFFFFFFF
        self.total_instruction_count += len(self.insns)

        # clear state for next function
        self.insns.clear()
        self.lines.clear()
        self.constants.clear()
        self.protos.clear()
        self.jumps.clear()
        self.table_shapes.clear()
        self.class_shapes.clear()
        self.fb_slots.clear()
        self.debug_locals.clear()
        self.debug_upvals.clear()
        self.typed_locals.clear()
        self.typed_upvals.clear()
        self.constant_map.clear()
        self.table_shape_map.clear()
        self.proto_map.clear()
        self.debug_remarks.clear()
        self.debug_remark_buffer.clear()

    def set_main_function(self, fid: int):
        assert fid < len(self.functions)
        self.main_function = fid

    def add_constant(self, key: ConstantKey, value: Constant) -> int:
        if key in self.constant_map:
            return self.constant_map[key]

        id_val = len(self.constants)
        if id_val >= (1 << 23):
            return -1

        self.constant_map[key] = id_val
        self.constants.append(value)
        return id_val

    def add_string_table_entry(self, value: bytes) -> int:
        if isinstance(value, str):
            value = value.encode('utf-8', errors='surrogateescape')
        if value in self.string_table:
            return self.string_table[value]

        index = len(self.string_table) + 1  # 1-based index
        self.string_table[value] = index
        self.debug_strings.append(value)
        return index

    def add_constant_nil(self) -> int:
        c = Constant(LuauBytecodeTag.LBC_CONSTANT_NIL, None)
        k = ConstantKey(LuauBytecodeTag.LBC_CONSTANT_NIL, None)
        return self.add_constant(k, c)

    def add_constant_boolean(self, value: bool) -> int:
        c = Constant(LuauBytecodeTag.LBC_CONSTANT_BOOLEAN, value)
        k = ConstantKey(LuauBytecodeTag.LBC_CONSTANT_BOOLEAN, value)
        return self.add_constant(k, c)

    def add_constant_number(self, value: float) -> int:
        # standard number constants are stored as double precision
        c = Constant(LuauBytecodeTag.LBC_CONSTANT_NUMBER, float(value))
        k = ConstantKey(LuauBytecodeTag.LBC_CONSTANT_NUMBER, float(value))
        return self.add_constant(k, c)

    def add_constant_vector(self, x: float, y: float, z: float, w: float) -> int:
        c = Constant(LuauBytecodeTag.LBC_CONSTANT_VECTOR, [x, y, z, w])
        k = ConstantKey(LuauBytecodeTag.LBC_CONSTANT_VECTOR, (x, y), (z, w))
        return self.add_constant(k, c)

    def add_constant_string(self, value: bytes) -> int:
        if isinstance(value, str):
            value = value.encode('utf-8', errors='surrogateescape')
        index = self.add_string_table_entry(value)
        c = Constant(LuauBytecodeTag.LBC_CONSTANT_STRING, index)
        k = ConstantKey(LuauBytecodeTag.LBC_CONSTANT_STRING, index)
        return self.add_constant(k, c)

    def add_import(self, iid: int) -> int:
        c = Constant(LuauBytecodeTag.LBC_CONSTANT_IMPORT, iid)
        k = ConstantKey(LuauBytecodeTag.LBC_CONSTANT_IMPORT, iid)
        return self.add_constant(k, c)

    def add_constant_table(self, shape: TableShape) -> int:
        if shape in self.table_shape_map:
            return self.table_shape_map[shape]

        id_val = len(self.constants)
        if id_val >= (1 << 23):
            return -1

        value = Constant(LuauBytecodeTag.LBC_CONSTANT_TABLE, len(self.table_shapes))
        self.table_shape_map[shape] = id_val
        self.table_shapes.append(shape)
        self.constants.append(value)
        return id_val

    def add_class_shape(self, shape: ClassShape) -> int:
        id_val = len(self.constants)
        if id_val >= (1 << 23):
            return -1

        c_index = len(self.class_shapes)
        self.class_shapes.append(shape)

        c = Constant(LuauBytecodeTag.LBC_CONSTANT_CLASS_SHAPE, c_index)
        k = ConstantKey(LuauBytecodeTag.LBC_CONSTANT_CLASS_SHAPE, c_index)
        return self.add_constant(k, c)

    def add_constant_closure(self, fid: int) -> int:
        c = Constant(LuauBytecodeTag.LBC_CONSTANT_CLOSURE, fid)
        k = ConstantKey(LuauBytecodeTag.LBC_CONSTANT_CLOSURE, fid)
        return self.add_constant(k, c)

    def add_constant_integer(self, value: int) -> int:
        c = Constant(LuauBytecodeTag.LBC_CONSTANT_INTEGER, value)
        k = ConstantKey(LuauBytecodeTag.LBC_CONSTANT_INTEGER, value)
        return self.add_constant(k, c)

    def add_fb_slot(self, feedback_type: int) -> int:
        slot = len(self.fb_slots)
        self.fb_slots.append(feedback_type)
        return slot

    def add_child_function(self, fid: int) -> int:
        if fid in self.proto_map:
            return self.proto_map[fid]

        id_val = len(self.protos)
        if id_val >= (1 << 15):
            return -1

        self.proto_map[fid] = id_val
        self.protos.append(fid)
        return id_val

    def emit_abc(self, op: LuauOpcode, a: int, b: int, c: int):
        insn = int(op) | (a << 8) | (b << 16) | (c << 24)
        self.insns.append(insn)
        self.lines.append(self.debug_line)

    def emit_ad(self, op: LuauOpcode, a: int, d: int):
        insn = int(op) | (a << 8) | ((d & 0xFFFF) << 16)
        self.insns.append(insn)
        self.lines.append(self.debug_line)

    def emit_e(self, op: LuauOpcode, e: int):
        insn = int(op) | ((e & 0xFFFFFF) << 8)
        self.insns.append(insn)
        self.lines.append(self.debug_line)

    def emit_aux(self, aux: int):
        self.insns.append(aux & 0xFFFFFFFF)
        self.lines.append(self.debug_line)

    def patch_aux(self, aux_label: int, value: int):
        assert aux_label < len(self.insns)
        self.insns[aux_label] = value & 0xFFFFFFFF

    def undo_emit(self, op: LuauOpcode):
        assert self.insns
        assert (self.insns[-1] & 0xFF) == int(op)
        self.insns.pop()
        self.lines.pop()

    def emit_label(self) -> int:
        return len(self.insns)

    def patch_jump_d(self, jump_label: int, target_label: int) -> bool:
        assert jump_label < len(self.insns)
        jump_insn = self.insns[jump_label]
        op = LuauOpcode(jump_insn & 0xFF)
        assert is_jump_d(op)
        assert ((jump_insn >> 16) & 0xFFFF) == 0

        assert target_label <= len(self.insns)
        offset = target_label - jump_label - 1

        if -32768 <= offset <= 32767:
            self.insns[jump_label] |= (offset & 0xFFFF) << 16
        elif abs(offset) < (1 << 23):
            self.has_long_jumps = True
        else:
            return False

        self.jumps.append(Jump(jump_label, target_label))
        return True

    def patch_skip_c(self, jump_label: int, target_label: int) -> bool:
        assert jump_label < len(self.insns)
        jump_insn = self.insns[jump_label]
        op = LuauOpcode(jump_insn & 0xFF)
        assert is_skip_c(op) or is_fastcall(op)
        assert ((jump_insn >> 24) & 0xFF) == 0

        offset = target_label - jump_label - 1
        if not (0 <= offset <= 255):
            return False

        self.insns[jump_label] |= offset << 24
        return True

    def fold_jumps(self):
        if self.has_long_jumps:
            return

        for jump in self.jumps:
            jump_label = jump.source
            jump_insn = self.insns[jump_label]
            target_label = jump_label + 1 + (((jump_insn & 0xFFFF0000) >> 16) if (jump_insn & 0x80000000) == 0 else (((jump_insn >> 16) & 0xFFFF) - 0x10000))
            assert target_label < len(self.insns)
            target_insn = self.insns[target_label]

            # Follow target if it is forward unconditional jump
            while (target_insn & 0xFF) == int(LuauOpcode.JUMP):
                offset_d = ((target_insn & 0xFFFF0000) >> 16) if (target_insn & 0x80000000) == 0 else (((target_insn >> 16) & 0xFFFF) - 0x10000)
                if offset_d >= 0:
                    target_label = target_label + 1 + offset_d
                    assert target_label < len(self.insns)
                    target_insn = self.insns[target_label]
                else:
                    break

            offset = target_label - jump_label - 1
            if (jump_insn & 0xFF) == int(LuauOpcode.JUMP) and (target_insn & 0xFF) == int(LuauOpcode.RETURN):
                self.insns[jump_label] = target_insn
            elif -32768 <= offset <= 32767:
                self.insns[jump_label] &= 0xFFFF
                self.insns[jump_label] |= (offset & 0xFFFF) << 16

            jump.target = target_label

    def expand_jumps(self):
        if not self.has_long_jumps:
            return

        self.jumps.sort(key=lambda j: j.source)
        remap = [0] * len(self.insns)
        new_insns = []
        new_lines = []

        current_jump = 0
        pending_trampolines = 0
        const_max_jump_conservative = 32767 // 3

        i = 0
        while i < len(self.insns):
            op = self.insns[i] & 0xFF
            if current_jump < len(self.jumps) and self.jumps[current_jump].source == i:
                offset = self.jumps[current_jump].target - self.jumps[current_jump].source - 1
                if abs(offset) > const_max_jump_conservative:
                    new_insns.append(int(LuauOpcode.JUMP) | (1 << 16))
                    new_insns.append(int(LuauOpcode.JUMPX))
                    new_lines.append(self.lines[i])
                    new_lines.append(self.lines[i])
                    pending_trampolines += 1
                current_jump += 1

            oplen = get_op_length(LuauOpcode(op))
            for j in range(oplen):
                remap[i] = len(new_insns)
                new_insns.append(self.insns[i])
                new_lines.append(self.lines[i])
                i += 1

        assert current_jump == len(self.jumps)

        # Repatch offsets
        for jump in self.jumps:
            offset = jump.target - jump.source - 1
            new_offset = remap[jump.target] - remap[jump.source] - 1

            if abs(offset) > const_max_jump_conservative:
                insnt_idx = remap[jump.source] - 1
                insnj_idx = remap[jump.source]

                # Patch JUMPX
                self.insns[jump.source]  # ensure bound check in logical sense
                insnt = new_insns[insnt_idx]
                assert (insnt & 0xFF) == int(LuauOpcode.JUMPX)

                insnt &= 0xFF
                insnt |= ((new_offset + 1) & 0xFFFFFF) << 8
                new_insns[insnt_idx] = insnt

                # Patch original instruction to jump offset -2 (back to JUMPX)
                new_insns[insnj_idx] &= 0xFFFF
                new_insns[insnj_idx] |= ((-2) & 0xFFFF) << 16

                pending_trampolines -= 1
            else:
                insn = new_insns[remap[jump.source]]
                new_insns[remap[jump.source]] &= 0xFFFF
                new_insns[remap[jump.source]] |= (new_offset & 0xFFFF) << 16

        assert pending_trampolines == 0
        self.insns = new_insns
        self.lines = new_lines

        # remap debug symbols
        for l in self.debug_locals:
            if l.startpc != l.endpc:
                l.endpc = remap[l.endpc - 1] + 1
            else:
                l.endpc = remap[l.endpc]
            l.startpc = remap[l.startpc]

        for l in self.typed_locals:
            if l.startpc != l.endpc:
                l.endpc = remap[l.endpc - 1] + 1
            else:
                l.endpc = remap[l.endpc]
            l.startpc = remap[l.startpc]

    def set_function_type_info(self, value: bytes):
        self.functions[self.current_function].typeinfo = bytearray(value)

    def push_local_type_info(self, type_tag: int, reg: int, startpc: int, endpc: int):
        self.typed_locals.append(TypedLocal(type_tag, reg, startpc, endpc))

    def push_upval_type_info(self, type_tag: int):
        self.typed_upvals.append(TypedUpval(type_tag))

    def add_userdata_type(self, name: str) -> int:
        self.userdata_types.append(UserdataType(name))
        return len(self.userdata_types) - 1

    def use_userdata_type(self, index: int):
        self.userdata_types[index].used = True

    def set_debug_function_name(self, name: bytes):
        if isinstance(name, str):
            name = name.encode('utf-8', errors='surrogateescape')
        idx = self.add_string_table_entry(name)
        self.functions[self.current_function].debugname = idx

    def set_debug_function_line_defined(self, line: int):
        self.functions[self.current_function].debuglinedefined = line

    def set_debug_line(self, line: int):
        self.debug_line = line

    def push_debug_local(self, name: bytes, reg: int, startpc: int, endpc: int):
        if isinstance(name, str):
            name = name.encode('utf-8', errors='surrogateescape')
        idx = self.add_string_table_entry(name)
        self.debug_locals.append(DebugLocal(idx, reg, startpc, endpc))

    def push_debug_upval(self, name: bytes):
        if isinstance(name, str):
            name = name.encode('utf-8', errors='surrogateescape')
        idx = self.add_string_table_entry(name)
        self.debug_upvals.append(DebugUpval(idx))

    def get_instruction_count(self) -> int:
        return len(self.insns)

    def get_total_instruction_count(self) -> int:
        return self.total_instruction_count

    def get_debug_pc(self) -> int:
        return len(self.insns)

    def add_debug_remark(self, format_str: str, *args):
        # We can implement a simplified version of remark storage if needed
        pass

    def finalize(self):
        assert not self.bytecode

        for ty in self.userdata_types:
            if ty.used:
                ty.name_ref = self.add_string_table_entry(ty.name.encode('utf-8'))

        # Header
        self.bytecode.append(LBC_VERSION_TARGET)
        self.bytecode.append(LBC_TYPE_VERSION_TARGET)

        # String Table
        self.write_string_table(self.bytecode)

        # Userdata Types mapping
        for i, ty in enumerate(self.userdata_types):
            if ty.used:
                self.bytecode.append(i + 1)
                self.bytecode.extend(encode_varint(ty.name_ref))
        self.bytecode.append(0)  # termination marker

        # Protos count
        self.bytecode.extend(encode_varint(len(self.functions)))

        # Proto blobs
        for func in self.functions:
            self.bytecode.extend(func.data)

        # Main function id
        assert self.main_function < len(self.functions)
        self.bytecode.extend(encode_varint(self.main_function))

    def write_function(self, ss: bytearray, fid: int, flags: int):
        func = self.functions[fid]

        ss.append(func.maxstacksize)
        ss.append(func.numparams)
        ss.append(func.numupvalues)
        ss.append(1 if func.isvararg else 0)
        ss.append(flags)

        # Types info
        if func.typeinfo or self.typed_upvals or self.typed_locals:
            temp = bytearray()
            temp.extend(encode_varint(len(func.typeinfo)))
            temp.extend(encode_varint(len(self.typed_upvals)))
            temp.extend(encode_varint(len(self.typed_locals)))
            temp.extend(func.typeinfo)

            for l in self.typed_upvals:
                temp.append(l.type_tag)

            for l in self.typed_locals:
                temp.append(l.type_tag)
                temp.append(l.reg)
                temp.extend(encode_varint(l.startpc))
                assert l.endpc >= l.startpc
                temp.extend(encode_varint(l.endpc - l.startpc))

            ss.extend(encode_varint(len(temp)))
            ss.extend(temp)
        else:
            ss.extend(encode_varint(0))

        # Instructions
        ss.extend(encode_varint(len(self.insns)))
        for insn in self.insns:
            ss.extend(struct.pack('<I', insn))

        # Constants
        ss.extend(encode_varint(len(self.constants)))
        for c in self.constants:
            ss.append(c.ctype)
            if c.ctype == LuauBytecodeTag.LBC_CONSTANT_BOOLEAN:
                ss.append(1 if c.value else 0)
            elif c.ctype == LuauBytecodeTag.LBC_CONSTANT_NUMBER:
                ss.extend(struct.pack('<d', c.value))
            elif c.ctype == LuauBytecodeTag.LBC_CONSTANT_VECTOR:
                ss.extend(struct.pack('<ffff', c.value[0], c.value[1], c.value[2], c.value[3]))
            elif c.ctype == LuauBytecodeTag.LBC_CONSTANT_STRING:
                ss.extend(encode_varint(c.value))
            elif c.ctype == LuauBytecodeTag.LBC_CONSTANT_IMPORT:
                ss.extend(struct.pack('<I', c.value))
            elif c.ctype == LuauBytecodeTag.LBC_CONSTANT_TABLE:
                shape = self.table_shapes[c.value]
                if shape.has_constants:
                    # Switch tag to TABLE_WITH_CONSTANTS
                    ss[-1] = LuauBytecodeTag.LBC_CONSTANT_TABLE_WITH_CONSTANTS
                    ss.extend(encode_varint(shape.length))
                    for i in range(shape.length):
                        ss.extend(encode_varint(shape.keys[i]))
                        ss.extend(encode_varint(shape.constants[i]))
                else:
                    ss.extend(encode_varint(shape.length))
                    for i in range(shape.length):
                        ss.extend(encode_varint(shape.keys[i]))
            elif c.ctype == LuauBytecodeTag.LBC_CONSTANT_CLOSURE:
                ss.extend(encode_varint(c.value))
            elif c.ctype == LuauBytecodeTag.LBC_CONSTANT_INTEGER:
                ss.extend(struct.pack('<q', c.value))
            elif c.ctype == LuauBytecodeTag.LBC_CONSTANT_CLASS_SHAPE:
                shape = self.class_shapes[c.value]
                ss.extend(encode_varint(shape.class_name))
                ss.extend(encode_varint(len(shape.property_names)))
                for name in shape.property_names:
                    ss.extend(encode_varint(name))
                ss.extend(encode_varint(len(shape.method_names)))
                for name in shape.method_names:
                    ss.extend(encode_varint(name))

        # Child protos
        ss.extend(encode_varint(len(self.protos)))
        for child in self.protos:
            ss.extend(encode_varint(child))

        # Debug info
        ss.extend(encode_varint(func.debuglinedefined))
        ss.extend(encode_varint(func.debugname))

        # Line info
        has_lines = True
        for line in self.lines:
            if line == 0:
                has_lines = False
                break

        if has_lines and self.lines:
            ss.append(1)
            self.write_line_info(ss)
        else:
            ss.append(0)

        # Debug locals/upvals
        has_debug = bool(self.debug_locals or self.debug_upvals)
        if has_debug:
            ss.append(1)
            ss.extend(encode_varint(len(self.debug_locals)))
            for l in self.debug_locals:
                ss.extend(encode_varint(l.name))
                ss.extend(encode_varint(l.startpc))
                ss.extend(encode_varint(l.endpc))
                ss.append(l.reg)
            ss.extend(encode_varint(len(self.debug_upvals)))
            for l in self.debug_upvals:
                ss.extend(encode_varint(l.name))
        else:
            ss.append(0)

    def write_line_info(self, ss: bytearray):
        # Port of BytecodeBuilder::writeLineInfo delta encoding
        assert self.lines
        span = 1 << 24

        # First pass: determine span length
        offset = 0
        while offset < len(self.lines):
            next_idx = offset
            min_l = self.lines[offset]
            max_l = self.lines[offset]

            while next_idx < len(self.lines) and next_idx < offset + span:
                min_l = min(min_l, self.lines[next_idx])
                max_l = max(max_l, self.lines[next_idx])
                if max_l - min_l > 255:
                    break
                next_idx += 1

            if next_idx < len(self.lines) and (next_idx - offset) < span:
                span = 1 << _log2(next_idx - offset)

            offset += span

        # Second pass: compute span base
        baseline_size = (len(self.lines) - 1) // span + 1
        baseline = [0] * baseline_size

        offset = 0
        while offset < len(self.lines):
            next_idx = offset
            min_l = self.lines[offset]
            while next_idx < len(self.lines) and next_idx < offset + span:
                min_l = min(min_l, self.lines[next_idx])
                next_idx += 1
            baseline[offset // span] = min_l
            offset += span

        # Third pass: write resulting data
        logspan = _log2(span)
        ss.append(logspan)

        last_offset = 0
        for i in range(len(self.lines)):
            delta = self.lines[i] - baseline[i >> logspan]
            assert 0 <= delta <= 255
            ss.append((delta - last_offset) & 0xFF)
            last_offset = delta & 0xFF

        last_line = 0
        for b in baseline:
            ss.extend(struct.pack('<i', b - last_line))
            last_line = b

    def write_string_table(self, ss: bytearray):
        # Sort string entries by index
        strings = [b""] * len(self.string_table)
        for val, idx in self.string_table.items():
            strings[idx - 1] = val

        ss.extend(encode_varint(len(strings)))
        for s in strings:
            ss.extend(encode_varint(len(s)))
            ss.extend(s)

    def get_bytecode(self) -> bytes:
        assert self.bytecode
        return bytes(self.bytecode)
