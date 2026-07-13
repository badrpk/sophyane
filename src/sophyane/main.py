#!/usr/bin/env python3
"""
Sophyane Agentic Harness v4.1

First-run provider setup with support for:
- OpenAI
- Google Gemini
- Anthropic Claude
- xAI Grok
- Groq
- DeepSeek
- OpenRouter
- Ollama
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from sophyane.agent_runtime import memory_context, route_local_request


VERSION = "4.1.0"

CONFIG_DIR = Path.home() / ".config" / "sophyane"
CONFIG_FILE = CONFIG_DIR / "config.json"
SECRETS_FILE = CONFIG_DIR / "secrets.json"


PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "name": "OpenAI",
        "model": "gpt-5-mini",
        "requires_key": True,
    },
    "gemini": {
        "name": "Google Gemini",
        "model": "gemini-2.5-flash",
        "requires_key": True,
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "model": "claude-sonnet-4-20250514",
        "requires_key": True,
    },
    "xai": {
        "name": "xAI Grok",
        "model": "grok-4",
        "requires_key": True,
    },
    "groq": {
        "name": "Groq",
        "model": "llama-3.3-70b-versatile",
        "requires_key": True,
    },
    "deepseek": {
        "name": "DeepSeek",
        "model": "deepseek-chat",
        "requires_key": True,
    },
    "openrouter": {
        "name": "OpenRouter",
        "model": "openai/gpt-4o-mini",
        "requires_key": True,
    },
    "ollama": {
        "name": "Ollama — local, no API key",
        "model": "llama3.2",
        "requires_key": False,
    },
}


SYSTEM_PROMPT = """You are Sophyane, a capable local agentic harness for developers.

Provide accurate, practical answers. When generating code:
- produce complete runnable code;
- explain important commands briefly;
- do not claim that a command was executed unless it was actually executed;
- prioritize safety and avoid destructive operations without clear warning.
"""


class SophyaneError(Exception):
    """User-facing Sophyane error."""


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass


def save_json(path: Path, data: dict[str, Any], private: bool = False) -> None:
    ensure_config_dir()

    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)

    temporary.replace(path)

    if private:
        try:
            path.chmod(0o600)
        except OSError:
            pass


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def api_key_environment_name(provider: str) -> str:
    names = {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "xai": "XAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }

    return names.get(provider, "")


def get_api_key(provider: str) -> str:
    environment_name = api_key_environment_name(provider)

    if environment_name:
        environment_value = os.getenv(environment_name, "").strip()
        if environment_value:
            return environment_value

    secrets = load_json(SECRETS_FILE)
    return str(secrets.get(provider, "")).strip()


def choose_provider() -> str:
    provider_ids = list(PROVIDERS)

    print()
    print("Choose an LLM provider:")
    print()

    for number, provider_id in enumerate(provider_ids, start=1):
        provider = PROVIDERS[provider_id]
        print(f"  {number}. {provider['name']}")

    print()

    while True:
        selection = input(
            f"Select provider [1-{len(provider_ids)}]: "
        ).strip()

        try:
            index = int(selection) - 1
        except ValueError:
            print("Please enter a valid number.")
            continue

        if 0 <= index < len(provider_ids):
            return provider_ids[index]

        print("Selection is outside the available range.")


def run_setup() -> dict[str, Any]:
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║        Sophyane First-Run Configuration      ║")
    print("╚══════════════════════════════════════════════╝")

    provider = choose_provider()
    provider_info = PROVIDERS[provider]

    print()
    print(f"Selected: {provider_info['name']}")

    default_model = str(provider_info["model"])
    selected_model = input(
        f"Model [{default_model}]: "
    ).strip() or default_model

    secrets = load_json(SECRETS_FILE)

    if provider_info["requires_key"]:
        print()
        print("Your API key will be stored locally with private permissions.")
        print(
            f"You may instead use the "
            f"{api_key_environment_name(provider)} environment variable."
        )

        api_key = getpass.getpass("Enter API key: ").strip()

        if not api_key:
            raise SophyaneError("An API key is required for this provider.")

        secrets[provider] = api_key
        save_json(SECRETS_FILE, secrets, private=True)

    config = {
        "provider": provider,
        "model": selected_model,
        "temperature": 0.3,
        "max_tokens": 4096,
    }

    save_json(CONFIG_FILE, config)

    print()
    print("Configuration saved.")
    print(f"Provider: {provider_info['name']}")
    print(f"Model:    {selected_model}")
    print()

    return config


def load_or_create_config() -> dict[str, Any]:
    config = load_json(CONFIG_FILE)

    provider = str(config.get("provider", "")).strip()
    model = str(config.get("model", "")).strip()

    if provider not in PROVIDERS or not model:
        return run_setup()

    if PROVIDERS[provider]["requires_key"] and not get_api_key(provider):
        print("The configured provider has no API key.")
        return run_setup()

    return config


def http_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: int = 180,
) -> dict[str, Any]:
    encoded_payload = json.dumps(payload).encode("utf-8")

    request_headers = {
        "Content-Type": "application/json",
        "User-Agent": f"Sophyane/{VERSION}",
    }

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url=url,
        data=encoded_payload,
        headers=request_headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw_response = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        error_body = error.read().decode("utf-8", errors="replace")
        raise SophyaneError(
            f"Provider returned HTTP {error.code}: {error_body}"
        ) from error
    except urllib.error.URLError as error:
        raise SophyaneError(
            f"Could not connect to the provider: {error.reason}"
        ) from error
    except TimeoutError as error:
        raise SophyaneError("The provider request timed out.") from error

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as error:
        raise SophyaneError(
            f"Provider returned invalid JSON: {raw_response[:500]}"
        ) from error

    if not isinstance(parsed, dict):
        raise SophyaneError("Provider returned an unexpected response.")

    return parsed


def openai_compatible_request(
    url: str,
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    extra_headers: dict[str, str] | None = None,
) -> str:
    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    if extra_headers:
        headers.update(extra_headers)

    response = http_json(
        url,
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        headers,
    )

    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise SophyaneError(
            f"Unexpected provider response: {json.dumps(response)[:1000]}"
        ) from error

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        pieces: list[str] = []

        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    pieces.append(text)

        if pieces:
            return "\n".join(pieces).strip()

    raise SophyaneError("The provider returned no text response.")


def call_openai(
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    response = http_json(
        "https://api.openai.com/v1/responses",
        {
            "model": model,
            "instructions": SYSTEM_PROMPT,
            "input": prompt,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        },
        {
            "Authorization": f"Bearer {api_key}",
        },
    )

    output_text = response.get("output_text")

    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    collected: list[str] = []

    for output_item in response.get("output", []):
        if not isinstance(output_item, dict):
            continue

        for content_item in output_item.get("content", []):
            if not isinstance(content_item, dict):
                continue

            text = content_item.get("text")
            if isinstance(text, str):
                collected.append(text)

    if collected:
        return "\n".join(collected).strip()

    raise SophyaneError(
        f"OpenAI returned no text: {json.dumps(response)[:1000]}"
    )


def call_gemini(
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    encoded_model = urllib.parse.quote(model, safe="")
    encoded_key = urllib.parse.quote(api_key, safe="")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{encoded_model}:generateContent?key={encoded_key}"
    )

    response = http_json(
        url,
        {
            "system_instruction": {
                "parts": [{"text": SYSTEM_PROMPT}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        },
    )

    try:
        parts = response["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as error:
        raise SophyaneError(
            f"Unexpected Gemini response: {json.dumps(response)[:1000]}"
        ) from error

    text_parts = [
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]

    if not text_parts:
        raise SophyaneError("Gemini returned no text response.")

    return "\n".join(text_parts).strip()


def call_anthropic(
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:
    response = http_json(
        "https://api.anthropic.com/v1/messages",
        {
            "model": model,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    content = response.get("content", [])
    text_parts: list[str] = []

    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                text_parts.append(text)

    if not text_parts:
        raise SophyaneError(
            f"Anthropic returned no text: {json.dumps(response)[:1000]}"
        )

    return "\n".join(text_parts).strip()


def call_ollama(
    model: str,
    prompt: str,
    temperature: float,
) -> str:
    response = http_json(
        "http://127.0.0.1:11434/api/chat",
        {
            "model": model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "options": {
                "temperature": temperature,
            },
        },
    )

    try:
        text = response["message"]["content"]
    except (KeyError, TypeError) as error:
        raise SophyaneError(
            f"Unexpected Ollama response: {json.dumps(response)[:1000]}"
        ) from error

    if not isinstance(text, str) or not text.strip():
        raise SophyaneError("Ollama returned no text response.")

    return text.strip()


def call_provider(config: dict[str, Any], prompt: str) -> str:
    provider = str(config["provider"])
    model = str(config["model"])
    temperature = float(config.get("temperature", 0.3))
    max_tokens = int(config.get("max_tokens", 4096))
    api_key = get_api_key(provider)

    if provider == "openai":
        return call_openai(
            api_key,
            model,
            prompt,
            temperature,
            max_tokens,
        )

    if provider == "gemini":
        return call_gemini(
            api_key,
            model,
            prompt,
            temperature,
            max_tokens,
        )

    if provider == "anthropic":
        return call_anthropic(
            api_key,
            model,
            prompt,
            temperature,
            max_tokens,
        )

    if provider == "xai":
        return openai_compatible_request(
            "https://api.x.ai/v1/chat/completions",
            api_key,
            model,
            prompt,
            temperature,
            max_tokens,
        )

    if provider == "groq":
        return openai_compatible_request(
            "https://api.groq.com/openai/v1/chat/completions",
            api_key,
            model,
            prompt,
            temperature,
            max_tokens,
        )

    if provider == "deepseek":
        return openai_compatible_request(
            "https://api.deepseek.com/chat/completions",
            api_key,
            model,
            prompt,
            temperature,
            max_tokens,
        )

    if provider == "openrouter":
        return openai_compatible_request(
            "https://openrouter.ai/api/v1/chat/completions",
            api_key,
            model,
            prompt,
            temperature,
            max_tokens,
            {
                "HTTP-Referer": "https://github.com/badrpk/sophyane",
                "X-Title": "Sophyane",
            },
        )

    if provider == "ollama":
        return call_ollama(model, prompt, temperature)

    raise SophyaneError(f"Unsupported provider: {provider}")


def show_status(config: dict[str, Any]) -> None:
    provider = str(config["provider"])
    provider_name = PROVIDERS[provider]["name"]

    print(f"Sophyane {VERSION}")
    print(f"Provider: {provider_name}")
    print(f"Model:    {config['model']}")

    if PROVIDERS[provider]["requires_key"]:
        print(f"API key:  {'configured' if get_api_key(provider) else 'missing'}")
    else:
        print("API key:  not required")


def execute_prompt(config: dict[str, Any], prompt: str) -> int:
    prompt = prompt.strip()

    if not prompt:
        print("Error: prompt cannot be empty.", file=sys.stderr)
        return 1

    try:
        local_result = route_local_request(prompt)
    except Exception as error:
        print(f"Local tool error: {error}", file=sys.stderr)
        return 1

    if local_result.get("handled"):
        direct_output = str(local_result.get("direct", "")).strip()
        tool_context = str(local_result.get("context", "")).strip()

        if direct_output:
            print(direct_output)
            return 0

        if tool_context:
            enriched_prompt = f"""
The user asked:

{prompt}

Sophyane executed a local tool on the user's actual computer.
Analyze and summarize the following real tool output.

Important rules:
- Do not say you cannot access the user's computer.
- Sophyane already accessed it through an approved local tool.
- Clearly distinguish facts from recommendations.
- Mention any errors or missing commands.
- Do not invent hardware or operating-system details.

LOCAL TOOL OUTPUT:

{tool_context}
""".strip()

            try:
                answer = call_provider(config, enriched_prompt)
            except SophyaneError as error:
                print("Local tool completed, but LLM summarization failed.")
                print(f"Provider error: {error}", file=sys.stderr)
                print()
                print(tool_context)
                return 1
            except KeyboardInterrupt:
                print("\nRequest cancelled.", file=sys.stderr)
                return 130

            print(answer)
            return 0

    stored_memory = memory_context()

    if stored_memory:
        final_prompt = f"""
{stored_memory}

Current user request:
{prompt}

Use the memories only when relevant. Do not mention stored memory unless it
helps answer the request.
""".strip()
    else:
        final_prompt = prompt

    try:
        answer = call_provider(config, final_prompt)
    except SophyaneError as error:
        print(f"Sophyane error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nRequest cancelled.", file=sys.stderr)
        return 130

    print(answer)
    return 0

def interactive_mode(config: dict[str, Any]) -> int:
    provider = str(config["provider"])

    print()
    print(f"🧠 Sophyane {VERSION}")
    print(
        f"Provider: {PROVIDERS[provider]['name']} | "
        f"Model: {config['model']}"
    )
    print("Commands: /tools, /setup, /status, /clear, /exit")
    print()

    while True:
        try:
            prompt = input("sophyane> ").strip()
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("\nUse /exit to close Sophyane.")
            continue

        if not prompt:
            continue

        if prompt in {"/exit", "/quit"}:
            return 0

        if prompt == "/setup":
            try:
                config = run_setup()
            except SophyaneError as error:
                print(f"Setup error: {error}", file=sys.stderr)
            continue

        if prompt == "/status":
            show_status(config)
            continue

        if prompt == "/clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue

        execute_prompt(config, prompt)
        print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sophyane",
        description=(
            "Sophyane is a configurable local AI-agent harness "
            "supporting multiple LLM providers."
        ),
    )

    parser.add_argument(
        "prompt",
        nargs="*",
        help="prompt to send to the selected LLM",
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="select or change the LLM provider, model, and API key",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="show the current provider and model",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.setup:
            config = run_setup()
        else:
            config = load_or_create_config()
    except SophyaneError as error:
        print(f"Setup error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSetup cancelled.", file=sys.stderr)
        return 130

    if args.status:
        show_status(config)
        return 0

    if args.prompt:
        return execute_prompt(config, " ".join(args.prompt))

    return interactive_mode(config)


if __name__ == "__main__":
    raise SystemExit(main())
