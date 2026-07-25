from collections.abc import Sequence

class Document:
    body_text: str
    textboxes: Sequence[str]

def parse_doc(data: bytes, strip_fields: bool = True) -> Document: ...
