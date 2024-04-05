from abc import ABC
from dataclasses import dataclass
import dis
from enum import Enum
import sys
from types import CodeType
import typing as t

from ddtrace.internal.injection import HookType


if sys.version_info >= (3, 12):
    # Register the coverage tool with the low-impact monitoring system
    try:
        sys.monitoring.use_tool_id(sys.monitoring.COVERAGE_ID, "datadog")
    except ValueError:
        # TODO: Another coverage tool is already in use. Either warn the user
        # or free the tool and register ours.
        def instrument_all_lines(code: CodeType, _hook: HookType, _path: str) -> t.Tuple[CodeType, t.Set[int]]:
            # No-op
            return code, set()
    else:
        RESUME = dis.opmap["RESUME"]

        _CODE_HOOKS: t.Dict[CodeType, t.Tuple[HookType, str]] = {}

        def _line_event_handler(code: CodeType, line: int) -> t.Any:
            hook, path = _CODE_HOOKS[code]
            return hook((path, line))

        # Register the line callback
        sys.monitoring.register_callback(sys.monitoring.COVERAGE_ID, sys.monitoring.events.LINE, _line_event_handler)

        def instrument_all_lines(code: CodeType, hook: HookType, path: str) -> t.Tuple[CodeType, t.Set[int]]:
            # Enable local line events for the code object
            sys.monitoring.set_local_events(sys.monitoring.COVERAGE_ID, code, sys.monitoring.events.LINE)

            # Collect all the line numbers in the code object
            lines = {line for o, line in dis.findlinestarts(code) if code.co_code[o] != RESUME}

            # Recursively instrument nested code objects
            for nested_code in (_ for _ in code.co_consts if isinstance(_, CodeType)):
                _, nested_lines = instrument_all_lines(nested_code, hook, path)
                lines.update(nested_lines)

            # Register the hook and argument for the code object
            _CODE_HOOKS[code] = (hook, path)

            return code, lines

elif (3, 10) <= sys.version_info < (3, 12):

    class JumpDirection(int, Enum):
        FORWARD = 1
        BACKWARD = -1

        @classmethod
        def from_opcode(cls, opcode: int) -> "JumpDirection":
            return cls.BACKWARD if "BACKWARD" in dis.opname[opcode] else cls.FORWARD

    class Jump(ABC):
        def __init__(self, start: int, argbytes: list[int]) -> None:
            self.start = start
            self.end: t.Optional[int] = None
            self.arg = int.from_bytes(argbytes, "big", signed=False)
            self.argsize = len(argbytes)

    # TODO: There are no absolute jumps in CPython >= 3.10
    class AJump(Jump):
        __opcodes__ = set(dis.hasjabs)

        def __init__(self, start: int, arg: list[int]) -> None:
            super().__init__(start, arg)
            self.end = self.arg << 1  # TODO: Depends on the Python version

    class RJump(Jump):
        __opcodes__ = set(dis.hasjrel)

        def __init__(self, start: int, arg: list[int], direction: JumpDirection) -> None:
            super().__init__(start, arg)

            self.direction = direction
            # TODO: Depends on the Python version
            self.end = start + (self.arg << 1) * self.direction + 2

    class Instruction:
        __slots__ = ("offset", "opcode", "arg", "targets")

        def __init__(self, offset: int, opcode: int, arg: int) -> None:
            self.offset = offset
            self.opcode = opcode
            self.arg = arg
            self.targets: t.List["Branch"] = []

    class Branch:
        def __init__(self, start: Instruction, end: Instruction) -> None:
            self.start = start
            self.end = end

        @property
        def arg(self) -> int:
            return abs(self.end.offset - self.start.offset - 2) >> 1

    EXTENDED_ARG = dis.EXTENDED_ARG

    def instr_with_arg(opcode: int, arg: int) -> t.List[Instruction]:
        instructions = [Instruction(-1, opcode, arg & 0xFF)]
        arg >>= 8
        while arg:
            instructions.insert(0, Instruction(-1, EXTENDED_ARG, arg & 0xFF))
            arg >>= 8
        return instructions


if sys.version_info >= (3, 11):

    def from_varint(iterator: t.Iterator[int]) -> int:
        b = next(iterator)
        val = b & 63
        while b & 64:
            val <<= 6
            b = next(iterator)
            val |= b & 63
        return val

    def to_varint(value: int, set_begin_marker: bool = False) -> bytes:
        # Encode value as a varint on 7 bits (MSB should come first) and set
        # the begin marker if requested.
        temp = bytearray()
        assert value >= 0
        while value:
            temp.insert(0, value & 63 | (64 if temp else 0))
            value >>= 6
        temp = temp or bytearray([0])
        if set_begin_marker:
            temp[0] |= 128
        return bytes(temp)

    def consume_varint(stream: t.Iterable[int]) -> bytes:
        a = bytearray()

        b = next(stream)
        a.append(b)

        value = b & 0x3F
        while b & 0x40:
            b = next(stream)
            a.append(b)

            value = (value << 6) | (b & 0x3F)

        return bytes(a)

    consume_signed_varint = consume_varint  # They are the same thing for our purposes

    def update_location_data(
        code: CodeType, trap_map: t.Dict[int, int], ext_arg_offsets: t.List[t.Tuple[int, int]]
    ) -> bytes:
        # DEV: We expect the original offsets in the trap_map
        new_data = bytearray()

        data = code.co_linetable
        data_iter = iter(data)
        ext_arg_offset_iter = iter(sorted(ext_arg_offsets))
        ext_arg_offset, ext_arg_size = next(ext_arg_offset_iter, (None, None))

        original_offset = offset = 0
        while True:
            try:
                chunk = bytearray()

                b = next(data_iter)

                chunk.append(b)

                offset_delta = ((b & 7) + 1) << 1
                loc_code = (b >> 3) & 0xF

                if loc_code == 14:
                    chunk.extend(consume_signed_varint(data_iter))
                    for _ in range(3):
                        chunk.extend(consume_varint(data_iter))
                elif loc_code == 13:
                    chunk.extend(consume_signed_varint(data_iter))
                elif 10 <= loc_code <= 12:
                    for _ in range(2):
                        chunk.append(next(data_iter))
                elif 0 <= loc_code <= 9:
                    chunk.append(next(data_iter))

                if original_offset in trap_map:
                    # No location info for the trap bytecode
                    trap_size = trap_map[original_offset]
                    n, r = divmod(trap_size, 8)
                    for _ in range(n):
                        new_data.append(0x80 | (0xF << 3) | 7)
                    if r:
                        new_data.append(0x80 | (0xF << 3) | r - 1)
                    offset += trap_size << 1

                # Extend the line table record if we added any EXTENDED_ARGs
                original_offset += offset_delta
                offset += offset_delta
                if ext_arg_offset is not None and offset > ext_arg_offset:
                    room = 7 - offset_delta
                    chunk[0] += min(room, t.cast(int, ext_arg_size))
                    if room < t.cast(int, ext_arg_size):
                        chunk.append(0x80 | (0xF << 3) | t.cast(int, ext_arg_size) - room)
                    offset += ext_arg_size << 1

                    ext_arg_offset, ext_arg_size = next(ext_arg_offset_iter, (None, None))

                new_data.extend(chunk)
            except StopIteration:
                break

        return bytes(new_data)

    @dataclass
    class ExceptionTableEntry:
        start: t.Union[int, Instruction]
        end: t.Union[int, Instruction]
        target: t.Union[int, Instruction]
        depth_lasti: int

    def parse_exception_table(code: CodeType):
        iterator = iter(code.co_exceptiontable)
        try:
            while True:
                start = from_varint(iterator) << 1
                length = from_varint(iterator) << 1
                end = start + length - 2  # Present as inclusive, not exclusive
                target = from_varint(iterator) << 1
                dl = from_varint(iterator)
                yield ExceptionTableEntry(start, end, target, dl)
        except StopIteration:
            return

    def compile_exception_table(exc_table: t.List[ExceptionTableEntry]) -> bytes:
        table = bytearray()
        for entry in exc_table:
            size = entry.end.offset - entry.start.offset + 2
            table.extend(to_varint(entry.start.offset >> 1, True))
            table.extend(to_varint(size >> 1))
            table.extend(to_varint(entry.target.offset >> 1))
            table.extend(to_varint(entry.depth_lasti))
        return bytes(table)

    PUSH_NULL = dis.opmap["PUSH_NULL"]
    LOAD_CONST = dis.opmap["LOAD_CONST"]
    PRECALL = dis.opmap["PRECALL"]
    CACHE = dis.opmap["CACHE"]
    CALL = dis.opmap["CALL"]
    POP_TOP = dis.opmap["POP_TOP"]
    RESUME = dis.opmap["RESUME"]

    def trap_call(trap_index: int, arg_index: int) -> t.Tuple[Instruction, ...]:
        return (
            Instruction(-1, PUSH_NULL, 0),
            *instr_with_arg(LOAD_CONST, trap_index),
            *instr_with_arg(LOAD_CONST, arg_index),
            Instruction(-1, PRECALL, 1),
            Instruction(-1, CACHE, 0),
            Instruction(-1, CALL, 1),
            Instruction(-1, CACHE, 0),
            Instruction(-1, CACHE, 0),
            Instruction(-1, CACHE, 0),
            Instruction(-1, CACHE, 0),
            Instruction(-1, POP_TOP, 0),
        )

    SKIP_LINES = frozenset([dis.opmap["END_ASYNC_FOR"]])

    def instrument_all_lines(code: CodeType, hook: HookType, path: str) -> t.Tuple[CodeType, t.Set[int]]:
        # TODO[perf]: Check if we really need to << and >> everywhere
        trap_func, trap_arg = hook, path

        instructions: t.List[Instruction] = []

        new_consts = list(code.co_consts)
        trap_index = len(new_consts)
        new_consts.append(trap_func)

        seen_lines = set()

        exc_table = list(parse_exception_table(code))
        exc_table_offsets = {_ for e in exc_table for _ in (e.start, e.end, e.target)}
        offset_map = {}

        # Collect all the original jumps
        jumps: t.Dict[int, Jump] = {}
        traps: t.Dict[int, int] = {}  # DEV: This uses the original offsets
        line_map = {}
        line_starts = dict(dis.findlinestarts(code))

        # Find the offset of the RESUME opcode. We should not add any
        # instrumentation before this point.
        try:
            resume_offset = code.co_code[::2].index(RESUME) << 1
        except ValueError:
            resume_offset = -1

        try:
            code_iter = iter(enumerate(code.co_code))
            ext: list[bytes] = []
            while True:
                original_offset, opcode = next(code_iter)

                if original_offset in exc_table_offsets:
                    offset_map[original_offset] = len(instructions) << 1

                if original_offset in line_starts and original_offset > resume_offset:
                    line = line_starts[original_offset]
                    if code.co_code[original_offset] not in SKIP_LINES:
                        # Inject trap call at the beginning of the line. Keep
                        # track of location and size of the trap call
                        # instructions. We need this to adjust the location
                        # table.
                        trap_instructions = trap_call(trap_index, len(new_consts))
                        traps[original_offset] = len(trap_instructions)
                        instructions.extend(trap_instructions)
                        new_consts.append((line, trap_arg))

                        line_map[original_offset] = trap_instructions[0]

                    seen_lines.add(line)

                _, arg = next(code_iter)

                offset = len(instructions) << 1

                # Propagate code
                instructions.append(Instruction(original_offset, opcode, arg))

                # Collect branching instructions for processing
                if opcode in AJump.__opcodes__:
                    jumps[offset] = AJump(original_offset, [*ext, arg])
                elif opcode in RJump.__opcodes__:
                    jumps[offset] = RJump(original_offset, [*ext, arg], JumpDirection.from_opcode(opcode))

                if opcode is EXTENDED_ARG:
                    ext.append(arg)
                else:
                    ext.clear()
        except StopIteration:
            pass

        # Collect all the old jump start and end offsets
        jump_targets = {_ for j in jumps.values() for _ in (j.start, j.end)}

        # Adjust all the offsets and map the old offsets to the new ones for the
        # jumps
        for index, instr in enumerate(instructions):
            new_offset = index << 1
            if instr.offset in jump_targets:
                offset_map[instr.offset] = new_offset
            instr.offset = new_offset

        # Adjust all the jumps, neglecting any EXTENDED_ARGs for now
        branches: t.List[Branch] = []
        for jump in jumps.values():
            new_start = offset_map[jump.start]
            new_end = offset_map[jump.end]

            # If we are jumping at the beginning of a line, jump to the
            # beginning of the trap call instead
            target_instr = line_map.get(jump.end, instructions[new_end >> 1])
            branch = Branch(instructions[new_start >> 1], target_instr)
            target_instr.targets.append(branch)

            branches.append(branch)

        # Resolve the exception table
        for e in exc_table:
            e.start = instructions[offset_map[e.start] >> 1]
            e.end = instructions[offset_map[e.end] >> 1]
            e.target = instructions[offset_map[e.target] >> 1]

        # Process all the branching instructions to adjust the arguments. We
        # need to add EXTENDED_ARGs if the argument is too large.
        process_branches = True
        exts: t.List[t.Tuple[Instruction, int]] = []
        while process_branches:
            process_branches = False
            for branch in branches:
                jump_instr = branch.start
                new_arg = branch.arg
                jump_instr.arg = new_arg & 0xFF
                new_arg >>= 8
                c = 0
                index = jump_instr.offset >> 1

                # Update the argument of the branching instruction, adding
                # EXTENDED_ARGs if needed
                while new_arg:
                    if index and instructions[index - 1].opcode is EXTENDED_ARG:
                        index -= 1
                        instructions[index].arg = new_arg & 0xFF
                    else:
                        ext_instr = Instruction(index << 1, EXTENDED_ARG, new_arg & 0xFF)
                        instructions.insert(index, ext_instr)
                        c += 1
                        # If the jump instruction was a target of another jump,
                        # make the latest EXTENDED_ARG instruction the target
                        # of that jump.
                        if jump_instr.targets:
                            for target in jump_instr.targets:
                                assert target.end is jump_instr
                                target.end = ext_instr
                            ext_instr.targets.extend(jump_instr.targets)
                            jump_instr.targets.clear()
                    new_arg >>= 8

                # Check if we added any EXTENDED_ARGs because we would have to
                # reprocess the branches.
                # TODO[perf]: only reprocess the branches that are affected.
                # However, this branch is not expected to be taken often.
                if c:
                    exts.append((ext_instr, c))
                    # Update the instruction offset from the point of insertion
                    # of the EXTENDED_ARGs
                    for instr_index, instr in enumerate(instructions[index + 1 :], index + 1):
                        instr.offset = instr_index << 1

                    process_branches = True

        # Create the new code object
        new_code = bytearray()
        for instr in instructions:
            new_code.append(instr.opcode)
            new_code.append(instr.arg)

        # Instrument nested code objects recursively
        for original_offset, nested_code in enumerate(code.co_consts):
            if isinstance(nested_code, CodeType):
                new_consts[original_offset], nested_lines = instrument_all_lines(nested_code, trap_func, trap_arg)
                seen_lines.update(nested_lines)

        return code.replace(
            co_code=bytes(new_code),
            co_consts=tuple(new_consts),
            co_stacksize=code.co_stacksize + 4,  # TODO: Compute the value!
            co_linetable=update_location_data(code, traps, [(instr.offset, s) for instr, s in exts]),
            co_exceptiontable=compile_exception_table(exc_table),
        ), seen_lines

elif sys.version_info >= (3, 10):

    def update_location_data(
        code: CodeType, trap_map: t.Dict[int, int], ext_arg_offsets: t.List[t.Tuple[int, int]]
    ) -> bytes:
        # DEV: We expect the original offsets in the trap_map
        new_data = bytearray()

        data = code.co_linetable
        data_iter = iter(data)
        ext_arg_offset_iter = iter(sorted(ext_arg_offsets))
        ext_arg_offset, ext_arg_size = next(ext_arg_offset_iter, (None, None))

        original_offset = offset = 0
        while True:
            try:
                if original_offset in trap_map:
                    # Give no line number to the trap instrumentation
                    trap_offset_delta = trap_map[original_offset] << 1
                    new_data.append(trap_offset_delta)
                    new_data.append(128)  # No line number
                    offset += trap_offset_delta

                offset_delta = next(data_iter)
                line_delta = next(data_iter)

                original_offset += offset_delta
                offset += offset_delta
                if ext_arg_offset is not None and offset > ext_arg_offset:
                    new_offset_delta = offset_delta + (ext_arg_size << 1)
                    new_data.append(new_offset_delta & 0xFF)
                    new_data.append(line_delta)
                    new_offset_delta >>= 8
                    while new_offset_delta:
                        new_data.append(new_offset_delta & 0xFF)
                        new_data.append(0)
                        new_offset_delta >>= 8
                    offset += ext_arg_size << 1

                    ext_arg_offset, ext_arg_size = next(ext_arg_offset_iter, (None, None))
                else:
                    new_data.append(offset_delta)
                    new_data.append(line_delta)
            except StopIteration:
                break

        return bytes(new_data)

    LOAD_CONST = dis.opmap["LOAD_CONST"]
    CALL = dis.opmap["CALL_FUNCTION"]
    POP_TOP = dis.opmap["POP_TOP"]

    def trap_call(trap_index: int, arg_index: int) -> t.Tuple[Instruction, ...]:
        return (
            *instr_with_arg(LOAD_CONST, trap_index),
            *instr_with_arg(LOAD_CONST, arg_index),
            Instruction(-1, CALL, 1),
            Instruction(-1, POP_TOP, 0),
        )

    def instrument_all_lines(code: CodeType, hook: HookType, path: str) -> t.Tuple[CodeType, t.Set[int]]:
        # TODO[perf]: Check if we really need to << and >> everywhere
        trap_func, trap_arg = hook, path

        instructions: t.List[Instruction] = []

        new_consts = list(code.co_consts)
        trap_index = len(new_consts)
        new_consts.append(trap_func)

        seen_lines = set()

        offset_map = {}

        # Collect all the original jumps
        jumps: t.Dict[int, Jump] = {}
        traps: t.Dict[int, int] = {}  # DEV: This uses the original offsets
        line_map = {}
        line_starts = dict(dis.findlinestarts(code))

        try:
            code_iter = iter(enumerate(code.co_code))
            ext: list[bytes] = []
            while True:
                original_offset, opcode = next(code_iter)

                if original_offset in line_starts:
                    # Inject trap call at the beginning of the line. Keep track
                    # of location and size of the trap call instructions. We
                    # need this to adjust the location table.
                    line = line_starts[original_offset]
                    trap_instructions = trap_call(trap_index, len(new_consts))
                    traps[original_offset] = len(trap_instructions)
                    instructions.extend(trap_instructions)
                    new_consts.append((line, trap_arg))

                    line_map[original_offset] = trap_instructions[0]

                    seen_lines.add(line)

                _, arg = next(code_iter)

                offset = len(instructions) << 1

                # Propagate code
                instructions.append(Instruction(original_offset, opcode, arg))

                # Collect branching instructions for processing
                if opcode in AJump.__opcodes__:
                    jumps[offset] = AJump(original_offset, [*ext, arg])
                elif opcode in RJump.__opcodes__:
                    jumps[offset] = RJump(original_offset, [*ext, arg], JumpDirection.from_opcode(opcode))

                if opcode is EXTENDED_ARG:
                    ext.append(arg)
                else:
                    ext.clear()
        except StopIteration:
            pass

        # Collect all the old jump start and end offsets
        jump_targets = {_ for j in jumps.values() for _ in (j.start, j.end)}

        # Adjust all the offsets and map the old offsets to the new ones for the
        # jumps
        for index, instr in enumerate(instructions):
            new_offset = index << 1
            if instr.offset in jump_targets:
                offset_map[instr.offset] = new_offset
            instr.offset = new_offset

        # Adjust all the jumps, neglecting any EXTENDED_ARGs for now
        branches: t.List[Branch] = []
        for jump in jumps.values():
            new_start = offset_map[jump.start]
            new_end = offset_map[jump.end]

            # If we are jumping at the beginning of a line, jump to the
            # beginning of the trap call instead
            target_instr = line_map.get(jump.end, instructions[new_end >> 1])
            branch = Branch(instructions[new_start >> 1], target_instr)
            target_instr.targets.append(branch)

            branches.append(branch)

        # Process all the branching instructions to adjust the arguments. We
        # need to add EXTENDED_ARGs if the argument is too large.
        process_branches = True
        exts: t.List[t.Tuple[Instruction, int]] = []
        while process_branches:
            process_branches = False
            for branch in branches:
                jump_instr = branch.start
                new_arg = branch.arg
                jump_instr.arg = new_arg & 0xFF
                new_arg >>= 8
                c = 0
                index = jump_instr.offset

                # Update the argument of the branching instruction, adding
                # EXTENDED_ARGs if needed
                while new_arg:
                    if index and instructions[index - 1].opcode is EXTENDED_ARG:
                        index -= 1
                        instructions[index].arg = new_arg & 0xFF
                    else:
                        ext_instr = Instruction(index << 1, EXTENDED_ARG, new_arg & 0xFF)
                        instructions.insert(index, ext_instr)
                        c += 1
                        # If the jump instruction was a target of another jump,
                        # make the latest EXTENDED_ARG instruction the target
                        # of that jump.
                        if jump_instr.targets:
                            for target in jump_instr.targets:
                                assert target.end is jump_instr
                                target.end = ext_instr
                            ext_instr.targets.extend(jump_instr.targets)
                            jump_instr.targets.clear()
                    new_arg >>= 8

                # Check if we added any EXTENDED_ARGs because we would have to
                # reprocess the branches.
                # TODO[perf]: only reprocess the branches that are affected.
                # However, this branch is not expected to be taken often.
                if c:
                    exts.append((ext_instr, c))
                    # Update the instruction offset from the point of insertion
                    # of the EXTENDED_ARGs
                    for instr_index, instr in enumerate(instructions[index + 1 :], index + 1):
                        instr.offset = instr_index << 1

                    process_branches = True

        # Create the new code object
        new_code = bytearray()
        for instr in instructions:
            new_code.append(instr.opcode)
            new_code.append(instr.arg)

        # Instrument nested code objects recursively
        for original_offset, nested_code in enumerate(code.co_consts):
            if isinstance(nested_code, CodeType):
                new_consts[original_offset], nested_lines = instrument_all_lines(nested_code, trap_func, trap_arg)
                seen_lines.update(nested_lines)

        return code.replace(
            co_code=bytes(new_code),
            co_consts=tuple(new_consts),
            co_stacksize=code.co_stacksize + 4,  # TODO: Compute the value!
            co_linetable=update_location_data(code, traps, [(instr.offset, s) for instr, s in exts]),
        ), seen_lines

else:  # Python 3.9 and below
    from bytecode import Bytecode

    from ddtrace.internal.injection import INJECTION_ASSEMBLY
    from ddtrace.internal.injection import HookType

    def instrument_all_lines(code: CodeType, hook: HookType, path: str) -> t.Tuple[CodeType, t.Set[int]]:
        abstract_code = Bytecode.from_code(code)

        lines = set()

        last_lineno = None
        for i, instr in enumerate(abstract_code):
            try:
                # Recursively instrument nested code objects
                if isinstance(instr.arg, CodeType):
                    instr.arg, nested_lines = instrument_all_lines(instr.arg, hook, path)
                    lines.update(nested_lines)

                if instr.lineno == last_lineno:
                    continue

                last_lineno = instr.lineno
                if last_lineno is None:
                    continue

                if instr.name == "NOP":
                    continue

                # Inject the hook at the beginning of the line
                abstract_code[i:i] = INJECTION_ASSEMBLY.bind(
                    dict(hook=hook, arg=(path, last_lineno)), lineno=last_lineno
                )

                # Track the line number
                lines.add(last_lineno)
            except AttributeError:
                # pseudo-instruction (e.g. label)
                pass

        return abstract_code.to_code(), lines
