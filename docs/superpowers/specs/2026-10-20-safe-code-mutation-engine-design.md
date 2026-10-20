# Safe Code Mutation Engine Design

## Goal

Provide Sophyane with a fail-closed, copy-on-write engine that turns a
high-level refactoring intent into a validated multi-file candidate entirely
inside `/home/badrpk/shmry_mutation_lab`, computes semantic diff hashes, and
automatically reverses invalid candidates without changing the source tree.

## Safety contract

1. The source tree is read-only input. The engine never writes, deletes,
   renames, chmods, or creates links outside the mutation lab.
2. Every transaction has a unique directory below the configured lab root.
   The default production root is exactly `/home/badrpk/shmry_mutation_lab`.
3. Relative paths are allowlisted by the intent, reject absolute paths,
   traversal components, symlinks, hard-linked files, and paths escaping the
   transaction directory.
4. Proposals contain text replacements only. The engine never executes a
   proposal, imports candidate modules, runs arbitrary shell, or lets a
   proposal choose verification commands.
5. Missing analysis tools, malformed source, failed checks, timeout, ledger or
   filesystem errors produce a failed result and trigger rollback in the lab.
6. A successful mutation is a lab artifact. Promotion, source mutation, and
   commit remain outside this engine and require existing authority gates.

## Data model and API

`src/sophyane/mutation/models.py` defines immutable records:

```python
@dataclass(frozen=True)
class MutationIntent:
    summary: str
    source_root: Path
    allowed_paths: tuple[str, ...]
    invariants: tuple[str, ...] = ()

@dataclass(frozen=True)
class MutationProposal:
    replacements: Mapping[str, str]
    planner_id: str

@dataclass(frozen=True)
class MutationResult:
    status: Literal["accepted", "reversed"]
    transaction_id: str
    lab_path: Path
    baseline_hash: str
    candidate_hash: str
    semantic_diff_hash: str
    reversal_patch: str
    failure_boundary: str | None
    checks: tuple[str, ...]
```

`MutationEngine(lab_root=Path("/home/badrpk/shmry_mutation_lab"),
language_adapters=...)` exposes:

```python
def mutate(self, intent: MutationIntent,
           proposal: MutationProposal,
           *, timeout_seconds: float = 30.0) -> MutationResult: ...
```

The engine copies regular source files into a transaction directory, applies
only proposal replacements that are both allowlisted and text-valued, invokes
language adapters for changed files, runs configured static checks in the lab,
then returns an accepted artifact or a reversed result. A rejected proposal
never changes the source root.

## Language analysis

### Python

The adapter parses every changed `.py` file with `ast.parse`, rejects syntax
errors, checks requested invariants such as required function/class names, and
serializes an attribute-free `ast.dump(..., annotate_fields=True,
include_attributes=False)` for semantic hashing. Optional type checking is
performed by a configured checker command whose executable and arguments are
owned by the engine, not by the proposal.

### C++

The adapter requires `clang++` (or an explicitly injected test adapter), runs
`clang++ -fsyntax-only` against changed `.cc`, `.cpp`, `.cxx`, and header files,
and obtains a normalized AST dump using Clang’s JSON AST mode where supported.
Tool absence, non-zero diagnostics, or an unavailable AST representation is a
reversal boundary rather than a permissive fallback. Include paths are fixed
by engine configuration and cannot be supplied by a proposal.

## Semantic diff and rollback

The baseline and candidate semantic hashes are computed from sorted relative
paths and canonical language representations. The semantic diff hash includes
only changed paths, baseline semantic digests, and candidate semantic digests.

Before any validation, the transaction records baseline bytes and metadata for
the lab copy. On a failed invariant, static check, regression callback, or
unexpected exception, the engine replaces the lab candidate with its baseline
bytes, emits a unified reversal patch from candidate to baseline, and returns
`status="reversed"`. The source root is never a rollback target because it was
never mutated.

## Regression and static verification

The engine accepts an injected deterministic regression verifier for tests and
for integration with Sophyane’s existing verification pipeline. It receives
only the lab path and returns pass/fail evidence. Verification commands run
with the lab transaction as their working directory, bounded timeout, isolated
temporary/cache paths, and no proposal-controlled arguments.

## Testing requirements

The unit suite must cover at least ten complex multi-file mutation scenarios:

1. Python function extraction across two files.
2. Python class rename with import update.
3. Python invariant violation and reversal.
4. Python syntax regression and reversal.
5. C++ header/source signature update.
6. C++ syntax failure and reversal.
7. Mixed Python/C++ transaction with stable semantic hash.
8. Symlink escape and hard-link rejection.
9. Traversal/absolute-path rejection.
10. Static-check or regression failure with generated reversal patch.

Every scenario snapshots the source tree before and after, including file
bytes, modes, symlink entries, and directory names, and asserts no difference
outside the mutation lab. Tests use temporary lab roots injected into the
engine; no test writes to the production default path.

## Explicit non-goals

- No direct source-tree editing, Git commit, promotion, or push.
- No arbitrary code execution from proposals.
- No automatic installation of compilers, type checkers, or dependencies.
- No claim that AST equivalence proves behavioral equivalence; static checks
  and the injected regression verifier remain required.
