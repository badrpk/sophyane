"""Fsynced JSONL audit events and exclusive, digest-checked checkpoints."""
from dataclasses import asdict, is_dataclass
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
from .authority import Operation, require


def json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f'Not JSON evidence: {type(value).__name__}')


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, default=json_default)


class Journal:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def append(self, provider, iteration_id, state, evidence):
        require(provider, Operation.JOURNAL_MUTATION)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        event = dict(iteration_id=iteration_id, state=state, evidence=evidence,
                     timestamp=datetime.now().astimezone().isoformat())
        with (self.root / 'iterations.jsonl').open('a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(encoded(event) + '\n'); stream.flush(); os.fsync(stream.fileno())

    def events(self):
        try:
            return [json.loads(line) for line in (self.root / 'iterations.jsonl').read_text().splitlines()]
        except FileNotFoundError:
            return []

    def checkpoint(self, provider, iteration_id, evidence):
        require(provider, Operation.PROMOTION_OPERATION)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', iteration_id):
            raise ValueError('Invalid checkpoint iteration identifier')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.root / (iteration_id + '.checkpoint.json')
        payload = encoded(evidence)
        with path.open('x') as stream:
            stream.write(encoded({'evidence': json.loads(payload), 'sha256': hashlib.sha256(payload.encode()).hexdigest()}))
            stream.flush(); os.fsync(stream.fileno())
        path.chmod(0o400)
        fd = os.open(self.root, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
        return path

    def load_checkpoint(self, path):
        path = Path(path).resolve()
        if path.parent != self.root:
            raise PermissionError('Checkpoint outside authoritative journal')
        value = json.loads(path.read_text())
        if hashlib.sha256(encoded(value['evidence']).encode()).hexdigest() != value['sha256']:
            raise ValueError('Checkpoint evidence digest mismatch')
        return value['evidence']
