"""Owned detached Git candidates and constrained text replacement application."""
import hashlib
from pathlib import Path
import uuid
from .authority import AuthorityViolation, Operation, require
from .baseline import assert_baseline, git
from .models import CandidateRecord


class IsolationViolation(PermissionError):
    pass


class Candidate:
    def __init__(self, baseline, path, identifier):
        self.baseline, self.path = baseline, Path(path).resolve()
        self.record = CandidateRecord(identifier, baseline.commit, 'rsi-' + identifier, str(self.path))

    @classmethod
    def create(cls, baseline, root):
        assert_baseline(baseline.repository, baseline.commit)
        root = Path(root).resolve()
        if root.is_relative_to(Path(baseline.repository)):
            raise IsolationViolation('Candidate root must be outside baseline')
        root.mkdir(parents=True, exist_ok=True)
        identifier = uuid.uuid4().hex
        path = root / identifier
        git(baseline.repository, 'worktree', 'add', '--detach', str(path), baseline.commit)
        return cls(baseline, path, identifier)

    def assert_isolated(self, *, check_baseline=True):
        if self.path == Path(self.baseline.repository) or not self.path.joinpath('.git').is_file():
            raise IsolationViolation('Candidate ownership lost')
        common = Path(git(self.path, 'rev-parse', '--git-common-dir')).resolve()
        if common != Path(self.baseline.repository_identity):
            raise IsolationViolation('Candidate repository identity changed')
        if git(self.path, 'rev-parse', 'HEAD') != self.baseline.commit:
            raise IsolationViolation('Candidate HEAD changed outside controller')
        if check_baseline:
            assert_baseline(self.baseline.repository, self.baseline.commit)

    def apply(self, provider, files, allowed_paths):
        require(provider, Operation.SOPHYANE_SOURCE_MUTATION)
        self.assert_isolated()
        replacements = []
        for name, content in files.items():
            relative = Path(name)
            if (name not in allowed_paths or relative.is_absolute() or '..' in relative.parts or
                any(part.casefold() == '.git' for part in relative.parts) or not isinstance(content, str)):
                raise IsolationViolation('Unauthorized candidate replacement path')
            if relative.parts and relative.parts[0] == 'tests':
                require(provider, Operation.CANDIDATE_TEST_MUTATION)
            target = self.path / relative
            if not target.resolve().is_relative_to(self.path):
                raise IsolationViolation('Replacement escapes candidate')
            for part in (target, *target.parents):
                if part == self.path:
                    break
                if part.is_symlink() or (part.is_file() and part.stat().st_nlink > 1):
                    raise IsolationViolation('Linked candidate files are not writable')
            replacements.append((target, content))
        # Validate the whole batch before the first write.
        for target, content in replacements:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        self.record.provider_used = provider
        self.record.source_mutation_authority = True

    def fingerprint(self):
        """Bind evidence to exact file bytes, including untracked candidate files."""
        result = {}
        names = git(self.path, 'ls-files', '--cached', '--others', '--exclude-standard', '-z')
        for name in filter(None, names.split('\0')):
            path = self.path / name
            if path.is_symlink():
                raise IsolationViolation('Candidate tree contains a symbolic link')
            result[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        return result

    def seal(self):
        require(self.record.provider_used, Operation.SOPHYANE_SOURCE_MUTATION)
        self.assert_isolated()
        git(self.path, 'add', '--all')
        tree = git(self.path, 'write-tree')
        commit = git(self.path, 'commit-tree', tree, '-p', self.baseline.commit,
                     input=f'RSI candidate {self.record.candidate_id}\n')
        self.record.candidate_commit = commit
        return commit

    def cleanup(self):
        self.assert_isolated(check_baseline=False)
        git(self.baseline.repository, 'worktree', 'remove', '--force', str(self.path))
