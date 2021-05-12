from typing import Any
from typing import List
from typing import Union

class StringTable(list):
    def index(self, string: str) -> int: ...  # type: ignore[override]

class MsgpackEncoder(object):
    content_type: str
    def _decode(self, data: Union[str, bytes]) -> Any: ...

class MsgpackEncoderV03(MsgpackEncoder):
    def encode_trace(self, trace: List[Any]) -> bytes: ...
    def join_encoded(self, objs: List[bytes]) -> bytes: ...

class MsgpackEncoderV05(MsgpackEncoder):
    def encode_trace(self, trace: List[Any]) -> bytes: ...
