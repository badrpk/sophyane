"""Local GGUF provider via persistent llama-server or bounded llama-cli."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from sophyane.providers.base import (
    Provider,
    ProviderCapabilities,
    ProviderError,
    ProviderMetadata,
)
from sophyane.providers.http import post_json
from sophyane.runtime_cancel import cancelled, register, unregister

DEFAULT_ENDPOINT = os.environ.get("SOPHYANE_LLAMA_SERVER", "http://127.0.0.1:8766").rstrip("/")


# SOPHYANE_LOCAL_GGUF_CONTEXT_BUDGET_V1

def _configured_context_size() -> int:
    """Return the local llama context configured for this runtime."""
    explicit = os.environ.get(
        "SOPHYANE_LLAMA_CONTEXT",
        "",
    ).strip()

    if explicit:
        try:
            value = int(
                explicit
            )

            if value >= 512:
                return value

        except ValueError:
            pass

    try:
        state = (
            load_gguf_runtime_state()
        )

        value = int(
            state.get(
                "context"
            )
            or 0
        )

        if value >= 512:
            return value

    except Exception:
        pass

    return 2048


def _estimate_chat_prompt_tokens(
    prompt: str,
    system_prompt: str,
) -> int:
    """Conservatively estimate Qwen chat prompt occupancy.

    This is intentionally an upper-biased transport budget estimate rather
    than a tokenizer replacement. Exact tokenization remains llama.cpp's job.
    """
    total_chars = (
        len(
            prompt
            or ""
        )
        + len(
            system_prompt
            or ""
        )
    )

    # Coding/JSON content often tokenizes more densely than ordinary prose.
    # 3 characters/token is deliberately conservative for admission control.
    estimated_content = (
        total_chars
        + 2
    ) // 3

    # Reserve chat-template / role / control-token overhead.
    return max(
        1,
        estimated_content
        + 64,
    )


def _safe_completion_budget(
    *,
    prompt: str,
    system_prompt: str,
    configured_max_tokens: int,
) -> int:
    """Return output tokens that fit safely inside the local context."""
    context_size = (
        _configured_context_size()
    )

    prompt_tokens = (
        _estimate_chat_prompt_tokens(
            prompt,
            system_prompt,
        )
    )

    # Keep unused context so chat-template variance and tokenizer estimation
    # errors do not drive generation directly into the context boundary.
    safety_reserve = max(
        160,
        int(
            context_size
            * 0.08
        ),
    )

    available = (
        context_size
        - prompt_tokens
        - safety_reserve
    )

    return max(
        0,
        min(
            int(
                configured_max_tokens
            ),
            1536,
            available,
        ),
    )


class LocalGgufProvider(Provider):
    metadata = ProviderMetadata(
        provider_id="local_gguf",
        display_name="Local GGUF (Hugging Face / llama.cpp)",
        default_model="local-gguf",
        environment_variable="",
        requires_api_key=False,
    )

    def __init__(self, api_key: str = "", model: str = "local-gguf", timeout: int = 300,
                 temperature: float = 0.3, max_tokens: int = 1024, endpoint: str = "",
                 gguf_path: str = "", cli_path: str = "") -> None:
        super().__init__(api_key, model, timeout, temperature, max_tokens)
        # Resolve the endpoint at construction time.  Mode-3 profile
        # selection is transient process state and may be established after
        # this module itself was imported.
        self.endpoint = (
            endpoint
            or os.environ.get("SOPHYANE_LLAMA_SERVER")
            or DEFAULT_ENDPOINT
        ).rstrip("/")
        self.gguf_path = gguf_path or os.environ.get("SOPHYANE_GGUF_PATH", "")
        self.cli_path = cli_path or os.environ.get("SOPHYANE_LLAMA_CLI", "")

    # SOPHYANE_LOCAL_DYNAMIC_PROVIDER_CAPACITY_V1
    def get_capabilities(self) -> ProviderCapabilities:
        """Expose the active llama.cpp context rather than a global guess.

        The exact safe completion for a particular request remains
        prompt-dependent and is enforced by ``_safe_completion_budget``.
        """
        return ProviderCapabilities(
            context_window_tokens=_configured_context_size(),
            max_output_tokens=max(0, int(self.max_tokens)),
            provider_managed_context=False,
            provider_managed_output=False,
        )

    def generate(self, prompt: str, system_prompt: str) -> str:
        if cancelled():
            raise ProviderError("local generation cancelled")

        local_profile = str(
            os.environ.get(
                "SOPHYANE_LOCAL_PROFILE"
            )
            or "qwen"
        ).strip().lower()

        # SOPHYANE_MODE3_SHARED_LOCAL_CONTEXT_BOUND_V1
        #
        # All Mode-3 local profiles, including comparison, must receive the
        # same bounded mobile-safe request context.  Previously comparison
        # returned before the historical local prompt bounds below, allowing
        # full CLI/system context to reach both llama.cpp servers.
        system_prompt = (system_prompt or "")[:800]
        prompt = (prompt or "")[:4000]

        # SOPHYANE_MODE3_LOCAL_COMPARE_V1
        #
        # Comparison is deliberately sequential.  Running both models at the
        # same time on mobile hardware would create RAM/cache contention and
        # distort tokens/sec.  Both requests receive the same prompt, system
        # prompt, temperature and completion budget.
        if local_profile == "compare":
            return self._generate_comparison(
                prompt,
                system_prompt,
            )

        started_at = time.monotonic()
        # SOPHYANE_LOCAL_GGUF_GENERATION_BUDGET_V2
        #
        # self.timeout is the configured end-to-end provider generation
        # budget. Do not silently clamp real on-device generation to
        # 90 seconds: 7B GGUF coding turns can legitimately require
        # several minutes on mobile hardware.
        # SOPHYANE_LOCAL_GGUF_PRIVATE_SHORT_TIMEOUT_V4
        #
        # Normal/authorized local generations retain the historical
        # >=20-second minimum so real coding turns are never accidentally
        # downgraded.
        #
        # Only a private speculation clone created by
        # global_txq_speculation may explicitly opt into the short 3-8
        # second Global-TXQ budget.
        short_speculation = bool(
            getattr(
                self,
                "_sophyane_allow_short_speculative_timeout",
                False,
            )
        )

        total_budget = max(
            (
                2.0
                if short_speculation
                else 20.0
            ),
            float(
                self.timeout
            ),
        )
        # SOPHYANE_LOCAL_GGUF_SINGLE_REAL_GENERATION_V1
        #
        # Readiness recovery and real inference are separate phases.
        #
        # A completed health probe does not consume model inference. If the
        # server is not ready, startup/recovery may run here. Once readiness is
        # established, exactly one real completion request owns the remaining
        # provider budget. A timeout/error from that request must propagate;
        # retrying the same coding generation after hundreds of seconds wastes
        # mobile compute and disguises the original timeout.
        from sophyane.local_server import (
            ensure_server_background,
            failure_detail,
            wait_until_ready,
        )

        ready = False
        readiness_error = ""

        if local_profile == "spark":
            from sophyane.local_model_profiles import (
                ensure_profile_servers,
            )

            ready, readiness_error = (
                ensure_profile_servers(
                    "spark"
                )
            )

            if not ready:
                raise ProviderError(
                    "Spark local server readiness failed. "
                    + readiness_error
                )

        else:
            try:
                ready = wait_until_ready(
                    timeout=3.0,
                )
            except Exception as error:  # noqa: BLE001
                readiness_error = (
                    f"{type(error).__name__}: {error}"
                )

        if not ready:
            if cancelled():
                raise ProviderError(
                    "local generation cancelled"
                )

            try:
                server_started, startup_message = (
                    ensure_server_background()
                )

                # SOPHYANE_LOCAL_GGUF_STARTUP_WAIT_AUTHORITY_V1
                #
                # ensure_server_background() already owns lifecycle
                # classification.  True means the configured server is ready,
                # loading, or a verified startup is in progress.  Do not
                # downgrade that authoritative state to the short failure
                # window by parsing human-readable message wording.
                server_loading = bool(
                    server_started
                )

                remaining = (
                    total_budget
                    - (
                        time.monotonic()
                        - started_at
                    )
                )

                if remaining <= 2.0:
                    raise ProviderError(
                        "local generation budget expired "
                        "during server readiness recovery"
                    )

                if server_loading:
                    wait_budget = max(
                        1.0,
                        min(
                            70.0,
                            remaining - 2.0,
                        ),
                    )
                else:
                    wait_budget = max(
                        1.0,
                        min(
                            8.0,
                            remaining - 2.0,
                        ),
                    )

                ready = wait_until_ready(
                    timeout=wait_budget,
                )

                if not ready:
                    detail = (
                        failure_detail()
                        or startup_message
                        or readiness_error
                    )

                    raise ProviderError(
                        "llama-server did not become "
                        "inference-ready. "
                        + detail
                    )

            except ProviderError:
                raise

            except Exception as error:  # noqa: BLE001
                detail = (
                    failure_detail()
                    or readiness_error
                    or str(
                        error
                    )
                )

                raise ProviderError(
                    "local_gguf server readiness failed. "
                    + detail
                ) from error

        if cancelled():
            raise ProviderError(
                "local generation cancelled"
            )

        remaining = (
            total_budget
            - (
                time.monotonic()
                - started_at
            )
        )

        if remaining <= 2.0:
            raise ProviderError(
                "local generation budget expired "
                "before inference started"
            )

        # This is the one and only model generation owned by this
        # LocalGgufProvider.generate() call.
        try:
            # SOPHYANE_LOCAL_GGUF_SPECULATIVE_HTTP_BUDGET_V5
            #
            # int(remaining) rounds a nominal 3-second speculative budget
            # down to 2 seconds as soon as any setup time has elapsed.
            #
            # Only the explicitly marked private speculative clone rounds the
            # residual window upward. Normal/authorized Mode-3 keeps the
            # historical timeout conversion unchanged.
            if short_speculation:
                import math as _speculation_math

                request_timeout = max(
                    2,
                    int(
                        _speculation_math.ceil(
                            remaining
                        )
                    ),
                )

            else:
                request_timeout = max(
                    2,
                    int(
                        remaining
                    ),
                )

            return self._generate_via_server(
                prompt,
                system_prompt,
                request_timeout=request_timeout,
            )

        except Exception:
            # SOPHYANE_LOCAL_GGUF_POST_CANCEL_QUIESCENCE_V1
            #
            # urllib/HTTP timeout cancellation can precede llama-server's
            # asynchronous slot release. Wait briefly for real quiescence
            # before returning control to an agent that may issue another
            # local generation.
            try:
                from sophyane.local_server import (
                    wait_until_idle,
                )

                # SOPHYANE_LOCAL_GGUF_SHORT_BUDGET_QUIESCENCE_V3
                #
                # Normal authorized Mode-3 generations retain the historical
                # 20-second post-error quiescence gate.
                #
                # A deliberately short <=20-second speculative provider clone
                # must not add another unconditional 20 seconds after its
                # inference deadline. Five seconds is enough to give the local
                # server a bounded slot-release window before the caller's
                # drain gate decides whether authorized generation may proceed.
                cleanup_timeout = (
                    5.0
                    if float(
                        self.timeout
                    ) <= 20.0
                    else 20.0
                )

                wait_until_idle(
                    timeout=cleanup_timeout,
                )

            except Exception:
                # Never replace the original inference exception with cleanup
                # diagnostics.
                pass

            raise


    def _generate_comparison(
        self,
        prompt: str,
        system_prompt: str,
    ) -> str:
        """Run the exact same local request through Qwen and Spark."""

        from sophyane.local_model_profiles import (
            ensure_profile_servers,
            qwen_profile,
            spark_profile,
        )

        ok, message = ensure_profile_servers(
            "compare"
        )

        if not ok:
            raise ProviderError(
                "local comparison servers unavailable: "
                + message
            )

        # Use the smaller active context so both models receive an identical
        # mathematically safe completion request.
        comparison_context = min(
            int(
                qwen_profile().get(
                    "context"
                )
                or 4096
            ),
            int(
                spark_profile().get(
                    "context"
                )
                or 4096
            ),
        )

        previous_context = os.environ.get(
            "SOPHYANE_LLAMA_CONTEXT"
        )

        os.environ[
            "SOPHYANE_LLAMA_CONTEXT"
        ] = str(
            comparison_context
        )

        try:
            completion_budget = (
                _safe_completion_budget(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    configured_max_tokens=self.max_tokens,
                )
            )
        finally:
            if previous_context is None:
                os.environ.pop(
                    "SOPHYANE_LLAMA_CONTEXT",
                    None,
                )
            else:
                os.environ[
                    "SOPHYANE_LLAMA_CONTEXT"
                ] = previous_context

        # SOPHYANE_MODE3_COMPARE_BOUNDED_OUTPUT_V2
        #
        # Comparison is a benchmark rather than an unrestricted coding turn.
        # Keep the same total completion allowance for both models while
        # preventing long reasoning traces from consuming the entire mobile
        # wall-clock budget.
        completion_budget = min(
            completion_budget,
            512,
        )

        if completion_budget < 256:
            raise ProviderError(
                "Local comparison requires decomposition: "
                f"safe_completion_tokens={completion_budget}"
            )

        def run_one(
            *,
            label: str,
            endpoint: str,
            model: str,
        ) -> dict:
            started = time.monotonic()

            request_payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "temperature": self.temperature,
                "max_tokens": completion_budget,
                "stream": False,
            }

            # Spark-X2.5 is a reasoning model.  Its unrestricted thinking can
            # consume hundreds of tokens before emitting visible content,
            # making a sequential phone benchmark take several minutes.
            # The XHToken llama.cpp server supports this per-request field, so
            # standalone Spark behavior remains completely unchanged.
            if "spark" in model.lower():
                request_payload[
                    "reasoning_budget_tokens"
                ] = 128

            response = post_json(
                endpoint.rstrip("/")
                + "/v1/chat/completions",
                request_payload,
                headers={
                    "Authorization": "Bearer local"
                },
                timeout=self.timeout,
            )

            elapsed = max(
                0.000001,
                time.monotonic()
                - started,
            )

            try:
                content = (
                    response["choices"][0]
                    ["message"]["content"]
                )
            except (
                KeyError,
                IndexError,
                TypeError,
            ) as error:
                raise ProviderError(
                    f"{label} returned an unexpected "
                    "llama-server response: "
                    + json.dumps(
                        response
                    )[:1000]
                ) from error

            if not isinstance(
                content,
                str,
            ) or not content.strip():
                raise ProviderError(
                    f"{label} returned no text"
                )

            usage = (
                response.get("usage")
                if isinstance(
                    response,
                    dict,
                )
                else {}
            )

            if not isinstance(
                usage,
                dict,
            ):
                usage = {}

            completion_tokens = int(
                usage.get(
                    "completion_tokens"
                )
                or 0
            )

            tokens_per_second = (
                completion_tokens
                / elapsed
                if completion_tokens
                else 0.0
            )

            timings = (
                response.get("timings")
                if isinstance(
                    response,
                    dict,
                )
                else {}
            )

            if not isinstance(
                timings,
                dict,
            ):
                timings = {}

            predicted_per_second = float(
                timings.get(
                    "predicted_per_second"
                )
                or 0.0
            )

            if predicted_per_second > 0:
                tokens_per_second = (
                    predicted_per_second
                )

            return {
                "label": label,
                "content": content.strip(),
                "elapsed": elapsed,
                "completion_tokens": completion_tokens,
                "tokens_per_second": tokens_per_second,
                "characters": len(
                    content.strip()
                ),
            }

        qwen = qwen_profile()
        spark = spark_profile()

        # Sequential execution is intentional for a fair mobile benchmark.
        qwen_result = run_one(
            label="Qwen2.5-1.5B",
            endpoint=str(
                qwen["endpoint"]
            ),
            model=str(
                qwen["model"]
            ),
        )

        if cancelled():
            raise ProviderError(
                "local comparison cancelled"
            )

        spark_result = run_one(
            label="Spark-X2.5-4B",
            endpoint=str(
                spark["endpoint"]
            ),
            model=str(
                spark["model"]
            ),
        )

        faster = min(
            (
                qwen_result,
                spark_result,
            ),
            key=lambda item: float(
                item["elapsed"]
            ),
        )

        longer = max(
            (
                qwen_result,
                spark_result,
            ),
            key=lambda item: int(
                item["characters"]
            ),
        )

        def metric(
            result: dict,
        ) -> str:
            tps = float(
                result[
                    "tokens_per_second"
                ]
            )

            token_text = (
                str(
                    result[
                        "completion_tokens"
                    ]
                )
                if int(
                    result[
                        "completion_tokens"
                    ]
                )
                else "n/a"
            )

            tps_text = (
                f"{tps:.2f}"
                if tps > 0
                else "n/a"
            )

            return (
                f"elapsed={result['elapsed']:.3f}s, "
                f"completion_tokens={token_text}, "
                f"tokens/sec={tps_text}, "
                f"characters={result['characters']}"
            )

        return (
            "LOCAL MODEL COMPARISON\n\n"
            "=== Qwen2.5-1.5B ===\n"
            + metric(
                qwen_result
            )
            + "\n\n"
            + str(
                qwen_result[
                    "content"
                ]
            )
            + "\n\n"
            "=== Spark-X2.5-4B ===\n"
            + metric(
                spark_result
            )
            + "\n\n"
            + str(
                spark_result[
                    "content"
                ]
            )
            + "\n\n"
            "=== Comparison ===\n"
            f"Faster: {faster['label']}\n"
            f"Longer output: {longer['label']}\n"
            "Execution: sequential; identical prompt/system/"
            "temperature/max_tokens; Spark reasoning budget=128 tokens."
        )


    def _generate_via_server(
        self,
        prompt: str,
        system_prompt: str,
        *,
        request_timeout: int | None = None,
    ) -> str:
        completion_budget = (
            _safe_completion_budget(
                prompt=prompt,
                system_prompt=system_prompt,
                configured_max_tokens=self.max_tokens,
            )
        )

        # SOPHYANE_LOCAL_GGUF_SPECULATIVE_EVIDENCE_FLOOR_V5
        #
        # The historical 256-token floor protects candidate/file
        # materialization from predictably truncated implementation output.
        #
        # A private Global-TXQ speculative clone has no implementation or
        # mutation authority and returns only a compact repository observation.
        # It may therefore use a much smaller evidence-only completion window.
        #
        # Authorized/local coding providers retain the original 256-token
        # decomposition threshold unchanged.
        minimum_completion_tokens = (
            64
            if bool(
                getattr(
                    self,
                    "_sophyane_allow_short_speculative_timeout",
                    False,
                )
            )
            else 256
        )

        # A tiny remaining output window means the requested operation no
        # longer belongs in one local generation turn.
        if completion_budget < minimum_completion_tokens:
            raise ProviderError(
                "Local generation requires decomposition: "
                f"context={_configured_context_size()}, "
                f"estimated_prompt_tokens="
                f"{_estimate_chat_prompt_tokens(prompt, system_prompt)}, "
                f"safe_completion_tokens={completion_budget}."
            )

        response = post_json(
            f"{self.endpoint}/v1/chat/completions",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": self.temperature,
                # SOPHYANE_LOCAL_GGUF_OUTPUT_BUDGET_V3
                #
                # Large coding actions routinely exceed the historical
                # 768-token ceiling. Keep a conservative local-server
                # ceiling for the current 2048-token context while allowing
                # materially larger complete source-file actions.
                #
                # The configured max_tokens remains authoritative whenever
                # it is lower than this local context-safe ceiling.
                # SOPHYANE_LOCAL_GGUF_CONTEXT_BUDGET_V1
                #
                # Never request a completion that mathematically competes
                # with the prompt for more tokens than the active llama
                # context can safely hold.
                "max_tokens": (
                    completion_budget
                ),
                "stream": False,
            },
            headers={"Authorization": "Bearer local"},
            # SOPHYANE_LOCAL_GGUF_HTTP_TIMEOUT_V2
            #
            # The caller may supply a small timeout for readiness/retry
            # probes. A real generation request without an override gets
            # the complete configured provider timeout.
            timeout=(
                request_timeout
                if request_timeout is not None
                else self.timeout
            ),
        )
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                f"Unexpected llama-server response: {json.dumps(response)[:1000]}"
            ) from error
        if not isinstance(content, str) or not content.strip():
            raise ProviderError("llama-server returned no text")
        return content.strip()

    @staticmethod
    def _clean_cli_output(text: str) -> str:
        text = (text or "").replace("\r", "\n")
        fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S | re.I)
        if fenced:
            return fenced[-1].strip()
        starts = [match.start() for match in re.finditer(r"\{", text)]
        for start in reversed(starts):
            candidate = text[start:text.rfind("}") + 1].strip()
            if candidate:
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    pass
        if "Assistant:" in text:
            text = text.split("Assistant:")[-1]
        text = re.sub(r"^User:.*$", "", text, flags=re.M)
        text = re.sub(r"^>\s*$", "", text, flags=re.M)
        return text.strip()

    def _run_cli(self, cmd: list[str], deadline: int) -> tuple[int, str, str]:
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if os.name == "posix":
            kwargs["start_new_session"] = True
        process = subprocess.Popen(cmd, **kwargs)
        register(process)
        try:
            stdout, stderr = process.communicate(timeout=deadline)
            return process.returncode or 0, stdout or "", stderr or ""
        except subprocess.TimeoutExpired:
            try:
                process.terminate()
                stdout, stderr = process.communicate(timeout=1.5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            cleaned = self._clean_cli_output(stdout or "")
            if cleaned:
                return 0, cleaned, stderr or ""
            if cancelled():
                raise ProviderError("llama-cli cancelled")
            raise ProviderError(f"llama-cli produced no complete answer within {deadline}s")
        finally:
            unregister(process)

    def _generate_via_cli(
        self,
        prompt: str,
        system_prompt: str,
        *,
        deadline: int = 40,
    ) -> str:
        full = f"{system_prompt.strip()}\n\nUser: {prompt}\nAssistant:"
        tokens = str(max(32, min(self.max_tokens, 384)))
        variants = [
            [self.cli_path, "-m", self.gguf_path, "-p", full, "-n", tokens,
             "--temp", str(self.temperature), "--single-turn", "--simple-io",
             "--no-display-prompt"],
            [self.cli_path, "-m", self.gguf_path, "-p", full, "-n", tokens,
             "--temp", str(self.temperature), "-no-cnv"],
        ]
        errors: list[str] = []
        for cmd in variants:
            if cancelled():
                raise ProviderError("llama-cli cancelled")
            code, stdout, stderr = self._run_cli(cmd, deadline)
            text = self._clean_cli_output(stdout)
            if code == 0 and text:
                return text
            errors.append(f"exit={code}: {stderr[:180]}")
        raise ProviderError("llama-cli failed: " + " | ".join(errors))


def load_gguf_runtime_state() -> dict:
    path = Path.home() / ".local" / "state" / "sophyane" / "gguf_runtime.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
