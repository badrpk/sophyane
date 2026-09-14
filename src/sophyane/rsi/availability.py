"""Host-pinned external availability observations; no provider secrets or prompts."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import tempfile

from .authority import CODING_PROVIDER_ORDER, AuthorityViolation

QUOTA = re.compile(r'usage limit|quota|rate limit|credits|http\s*429|5.hour limit|weekly limit', re.I)
RESET = re.compile(r'(?:try again at|resets? (?:tomorrow )?at)\s*(\d{1,2}):(\d{2})\s*([ap]\.?m\.?)?', re.I)


def local_now():
    return datetime.now().astimezone()


def aware(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Availability clock must be timezone-aware')
    return value


def parse_reset(message, now):
    match = RESET.search(message.replace('\u202f', ' ').replace('\u00a0', ' '))
    if not match:
        return None
    hour, minute = int(match[1]), int(match[2])
    ampm = (match[3] or '').lower().replace('.', '')
    if minute > 59 or (ampm and not 1 <= hour <= 12) or (not ampm and hour > 23):
        return None
    if ampm:
        hour = hour % 12 + (12 if ampm == 'pm' else 0)
    suffix = message[match.end():].strip()
    zone = re.match(r'(?:UTC|GMT)([+-]\d{1,2}(?::\d{2})?)?', suffix, re.I)
    basis = now
    if zone:
        offset = zone[1]
        minutes = 0
        if offset:
            parts = offset[1:].split(':')
            minutes = (int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)) * (-1 if offset[0] == '-' else 1)
            if abs(minutes) >= 1440:
                return None
        basis = now.astimezone(timezone(timedelta(minutes=minutes)))
    elif re.match(r'[A-Z]{2,5}\b', suffix):
        return None  # Ambiguous timezone abbreviation: use bounded probing.
    result = basis.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if 'tomorrow' in match[0].lower() or result <= now:
        result += timedelta(days=1)
    return result


class AvailabilityStore:
    """Resolve once before candidate execution; reload on every request.

    A clock returning system-local aware times avoids a tzdata dependency.
    Explicit paths are dependency injection for trusted host/test code only.
    """
    def __init__(self, path=None, *, clock=local_now):
        root = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
        self.path = Path(path or root / 'sophyane/provider_availability.json').expanduser().resolve()
        self.clock = clock

    def assert_external(self, workspace):
        if self.path.is_relative_to(Path(workspace).resolve()):
            raise AuthorityViolation('Availability state must be external to candidate/baseline')

    @contextmanager
    def _state(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state = json.loads(self.path.read_text())
            except FileNotFoundError:
                state = {'version': 2, 'providers': {}}
            if not isinstance(state, dict) or not isinstance(state.get('providers'), dict):
                raise ValueError('Invalid authoritative provider state')
            if state.get('version') not in (1, 2):
                raise ValueError('Unsupported authoritative provider state version')
            # Import old single-window observations, dropping freeform diagnostics.
            for name, entry in state['providers'].items():
                if not isinstance(entry, dict):
                    raise ValueError('Invalid provider observation')
                entry.pop('message', None)
                if state['version'] == 2 and 'cooldowns' not in entry:
                    raise ValueError('Incomplete provider observation')
                if 'cooldowns' not in entry:
                    entry['cooldowns'] = ([{'kind': entry.get('failure_class', 'availability'),
                        'scope': 'legacy', 'retry_at': entry.get('retry_at'), 'probe_after': entry.get('probe_after')}]
                        if entry.get('retry_at') or entry.get('probe_after') else [])
            yield state
            state['version'] = 2
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.availability-')
            try:
                with os.fdopen(fd, 'w') as output:
                    json.dump(state, output, sort_keys=True, allow_nan=False)
                    output.write('\n'); output.flush(); os.fsync(output.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)

    def _entry(self, state, provider):
        if provider not in CODING_PROVIDER_ORDER:
            raise AuthorityViolation('Only external coding provider observations are writable')
        return state['providers'].setdefault(provider, {
            'provider': provider, 'observed_at': None, 'unavailable_reason': None,
            'failure_class': None, 'retry_at': None, 'probe_after': None,
            'cooldowns': [], 'last_success_at': None, 'last_probe_at': None})

    def blocked(self, provider):
        now = aware(self.clock())
        with self._state() as state:
            entry = self._entry(state, provider)
            active = []
            for cooldown in entry['cooldowns']:
                value = cooldown.get('retry_at') or cooldown.get('probe_after')
                if not value:
                    raise ValueError('Cooldown missing a retry/probe deadline')
                if aware(datetime.fromisoformat(value)) > now:
                    active.append(cooldown)
            entry['cooldowns'] = active
            return bool(active)

    def revalidation_due(
        self,
        provider,
        *,
        interval=timedelta(minutes=15),
    ):
        """Return whether a cached NIFDU quota is due one live revalidation.

        Known Codex quota windows remain hard blocks until their reset.

        NIFDU is browser/session backed, so its live state may change
        independently of an earlier ChatGPT quota observation. Only an
        active NIFDU quota is eligible, and at most once per interval.
        """
        if provider != "nifdu_browser":
            return False

        now = aware(self.clock())

        with self._state() as state:
            entry = self._entry(state, provider)

            if entry.get("failure_class") != "quota":
                return False

            active_quota = False

            for cooldown in entry.get("cooldowns", []):
                if cooldown.get("kind") != "quota":
                    continue

                value = (
                    cooldown.get("retry_at")
                    or cooldown.get("probe_after")
                )

                if not value:
                    continue

                if aware(datetime.fromisoformat(value)) > now:
                    active_quota = True
                    break

            if not active_quota:
                return False

            anchor = (
                entry.get("last_probe_at")
                or entry.get("observed_at")
            )

            if not anchor:
                return False

            return (
                aware(datetime.fromisoformat(anchor))
                + interval
                <= now
            )

    def probe(self, provider):
        with self._state() as state:
            self._entry(state, provider)['last_probe_at'] = aware(self.clock()).isoformat()

    def failure(self, provider, error):
        now = aware(self.clock())
        message = str(error)
        windows = [part.strip() for part in re.split(r'[;\n]', message) if QUOTA.search(part)]
        if len(windows) > 1:
            for window in windows:
                self.failure(provider, RuntimeError(window))
            return
        quota = bool(QUOTA.search(message))
        retry = parse_reset(message, now) if quota else None
        scope = ('weekly_window' if 'weekly' in message.lower() else
                 'short_window' if re.search(r'5.hour|short.window', message, re.I) else 'provider')
        kind = 'quota' if quota else 'availability'
        cooldown = {'kind': kind, 'scope': scope,
                    'retry_at': retry.isoformat() if retry else None,
                    'probe_after': None if retry else (now + timedelta(minutes=15)).isoformat()}
        with self._state() as state:
            entry = self._entry(state, provider)
            entry['cooldowns'] = [c for c in entry['cooldowns'] if c['scope'] != scope] + [cooldown]
            entry.update(provider=provider, observed_at=now.isoformat(), unavailable_reason=kind,
                         failure_class=kind, retry_at=cooldown['retry_at'], probe_after=cooldown['probe_after'])

    def success(self, provider):
        with self._state() as state:
            entry = self._entry(state, provider)
            entry.update(last_success_at=aware(self.clock()).isoformat(), cooldowns=[],
                         retry_at=None, probe_after=None, unavailable_reason=None)
