from pathlib import Path

from runner.store import DocumentNotFound, DocumentStore
from runner.validation.models import Validation


class ValidationNotFound(DocumentNotFound):
    pass


class ValidationStore(DocumentStore[Validation]):
    def __init__(self, db_path: Path):
        super().__init__(db_path, "validations", Validation, ValidationNotFound)
