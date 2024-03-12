from types import CodeType
import typing as t

from bytecode import Bytecode

from ddtrace.internal.injection import INJECTION_ASSEMBLY
from ddtrace.internal.injection import HookType


def instrument_all_lines(code: CodeType, hook: HookType, path: str) -> t.Tuple[CodeType, t.Set[int]]:
    abstract_code = Bytecode.from_code(code)

    lines = set()

    last_lineno = None
    for i, instr in enumerate(abstract_code):
        try:
            if instr.lineno == last_lineno:
                continue
            last_lineno = instr.lineno
            # Some lines might be implemented across multiple instruction
            # offsets, and sometimes a NOP is used as a placeholder. We skip
            # those to avoid duplicate injections.
            if instr.name == "NOP":
                continue
            abstract_code[i:i] = INJECTION_ASSEMBLY.bind(dict(hook=hook, arg=(path, last_lineno)), lineno=last_lineno)
            lines.add(last_lineno)
        except AttributeError:
            # pseudo-instruction (e.g. label)
            pass

    return abstract_code.to_code(), lines