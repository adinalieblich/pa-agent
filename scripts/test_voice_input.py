"""CLI that pretends to be the iPhone.

Two modes:

    # Classify + extract a single voice line
    python scripts/test_voice_input.py "remind me to pay the dentist tomorrow"

    # Run the built-in 10-example classifier sweep (no Notion writes)
    python scripts/test_voice_input.py --classify-suite

    # Full pipeline (classify → extract → write to Notion). MILESTONE 6.
    python scripts/test_voice_input.py --commit "remind me to pay the dentist tomorrow"

Useful for sanity-checking the classifier and the extractor without involving
the iOS Shortcut, ngrok, or the FastAPI webhook.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow running this file directly (python scripts/test_voice_input.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_settings  # noqa: E402
from src.integrations.anthropic_client import AnthropicClient  # noqa: E402
from src.utils.logging import configure_logging, get_logger  # noqa: E402

CLASSIFIER_SUITE: list[tuple[str, str]] = [
    # task
    ("remind me to call the dentist tomorrow afternoon", "task"),
    ("take meds 8am every day", "task"),
    ("gym Saturday morning", "task"),  # scheduled, but calendar is out of scope
    # bill
    ("remind me to pay the dentist tomorrow", "bill"),  # 'pay' overrides
    ("pay rent $2400 on the 1st of every month", "bill"),
    ("owe sarah forty quid for dinner", "bill"),
    # project
    (
        "project: build the PWA dashboard. need to design wireframes, "
        "build the shell, wire to Notion, add swipe gestures",
        "project",
    ),
    # brain_dump
    ("maybe I should learn to surf", "brain_dump"),
    ("idea: a daily review email summarising what I shipped", "brain_dump"),
    ("today felt heavy, kept losing my train of thought", "brain_dump"),
    # multi
    (
        "remind me to call the dentist tomorrow and pay the rent $2400",
        "multi",
    ),
]


async def _classify_one(client: AnthropicClient, text: str) -> dict[str, object]:
    return await client.classify(text)


async def _classify_suite(client: AnthropicClient) -> int:
    """Run the 10-example sweep and print pass/fail. Returns exit code."""
    correct = 0
    for text, expected in CLASSIFIER_SUITE:
        result = await _classify_one(client, text)
        actual = result.get("intent")
        ok = actual == expected
        correct += int(ok)
        marker = "OK " if ok else "FAIL"
        print(f"[{marker}] expected={expected:<14} got={actual:<14} :: {text}")
    print(f"\n{correct}/{len(CLASSIFIER_SUITE)} correct.")
    return 0 if correct == len(CLASSIFIER_SUITE) else 1


async def _classify_and_extract(client: AnthropicClient, text: str) -> None:
    classification = await client.classify(text)
    print("--- classification ---")
    print(json.dumps(classification, indent=2))

    intent = classification.get("intent")
    if not isinstance(intent, str):
        print("Classifier returned no usable intent; aborting extract step.")
        return

    extraction = await client.extract(text, intent)
    print("\n--- extraction ---")
    print(json.dumps(extraction, indent=2))


async def _commit(text: str) -> None:
    """Full pipeline: classify → extract → write to Notion. Milestone 6 demo."""
    from src.orchestrator import handle_voice_text  # local import: only needed here

    response = await handle_voice_text(text)
    print(json.dumps(response.model_dump(mode="json"), indent=2))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PA-Agent voice-input simulator.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--classify-suite",
        action="store_true",
        help="Run the built-in 10-example classifier sweep.",
    )
    group.add_argument(
        "--commit",
        action="store_true",
        help="Run the full pipeline and actually write to Notion.",
    )
    parser.add_argument("text", nargs="*", help="Voice text to process.")
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger(__name__)
    client = AnthropicClient(settings)

    if args.classify_suite:
        log.info("voice_cli.suite_start")
        return await _classify_suite(client)

    if not args.text:
        print("Usage: test_voice_input.py [--classify-suite|--commit] '<voice text>'")
        return 2

    text = " ".join(args.text)
    log.info("voice_cli.single", chars=len(text))

    if args.commit:
        await _commit(text)
    else:
        await _classify_and_extract(client, text)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
