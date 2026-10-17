"""Evidence that backs every insight, verified mechanically against the artifacts on disk.

A quote is only accepted if it appears verbatim in the cited document (and on the cited
line, when one is given). An absence claim is only accepted if the text truly does not
occur in the document. Verification re-reads the files independently of the parsers
that produced the claim, so a parsing bug cannot launder an unsupported statement.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

MAX_QUOTE_CHARS = 240


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: str
    source: str
    quote: str
    line: int | None = None
    attempt: int | None = None
    episode: int | None = None
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


def _json_strings(value: Any) -> list[str]:
    match value:
        case str():
            return [value]
        case dict():
            return [s for item in value.values() for s in _json_strings(item)]
        case list():
            return [s for item in value for s in _json_strings(item)]
        case _:
            return []


def load_document(root: Path, source: str) -> str | None:
    """JSON documents are compared by their decoded string values, so quotes of agent
    keystrokes are checked without JSON escaping getting in the way. `file.yaml#key`
    selects a single top-level YAML field, e.g. the task instruction."""
    relative, _, key = source.partition("#")
    path = root / relative
    if not path.is_file():
        return None
    text = path.read_text(errors="replace")
    if key:
        value = yaml.safe_load(text)
        return value.get(key) if isinstance(value, dict) and isinstance(value.get(key), str) else None
    if path.suffix == ".json":
        try:
            return "\n".join(_json_strings(json.loads(text)))
        except json.JSONDecodeError:
            return text
    return text


def verify(root: Path, evidence: Evidence) -> bool:
    document = load_document(root, evidence.source)
    if document is None or not evidence.quote.strip():
        return False
    if evidence.kind == "absence":
        return evidence.quote.lower() not in document.lower()
    if evidence.line is not None:
        lines = document.splitlines()
        return 1 <= evidence.line <= len(lines) and evidence.quote in lines[evidence.line - 1]
    return evidence.quote in document


@dataclass
class EvidenceLedger:
    root: Path
    items: dict[str, Evidence] = field(default_factory=dict)

    def quote(self, source: str, quote: str, **location: int | None) -> str:
        return self._add("quote", source, quote.strip()[:MAX_QUOTE_CHARS], location)

    def absence(self, source: str, text: str) -> str:
        return self._add("absence", source, text, {})

    def _add(self, kind: str, source: str, quote: str, location: dict[str, int | None]) -> str:
        evidence = Evidence(id=f"E{len(self.items) + 1}", kind=kind, source=source, quote=quote, **location)
        evidence = Evidence(**{**asdict(evidence), "verified": verify(self.root, evidence)})
        self.items[evidence.id] = evidence
        return evidence.id

    def all_verified(self, evidence_ids: list[str]) -> bool:
        return bool(evidence_ids) and all(self.items[e].verified for e in evidence_ids)
