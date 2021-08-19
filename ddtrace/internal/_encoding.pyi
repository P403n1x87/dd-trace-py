from typing import Any
from typing import List
from typing import Optional
from typing import Union

from ddtrace.span import Span

Trace = List[Span]

class BufferFull(Exception):
    pass

class BufferItemTooLarge(Exception):
    pass

class BufferedEncoder(object):
    max_size: int
    max_item_size: int
    def __init__(self, max_size: int, max_item_size: int) -> None: ...
    def __len__(self) -> int: ...
    def put(self, item: Any) -> None: ...
    def encode(self) -> Optional[bytes]: ...
    @property
    def size(self) -> int: ...

class MsgpackEncoderBase(BufferedEncoder):
    content_type: str
    def get_bytes(self) -> bytes: ...
    def _decode(self, data: Union[str, bytes]) -> Any: ...

class MsgpackEncoder(MsgpackEncoderBase): ...
