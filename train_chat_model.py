"""Submit a curated, de-identified conversational dataset for OpenAI fine-tuning."""

import argparse
import json
import os
from pathlib import Path


def validate_training_file(path):
    """Validate basic chat fine-tuning JSONL shape and return the example count."""
    count = 0
    with Path(path).open(encoding="utf-8") as training_file:
        for line_number, line in enumerate(training_file, start=1):
            if not line.strip():
                continue
            try:
                example = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc.msg}") from exc
            messages = example.get("messages") if isinstance(example, dict) else None
            if not isinstance(messages, list) or len(messages) < 2:
                raise ValueError(f"Line {line_number} must contain a messages array")
            if any(
                not isinstance(message, dict)
                or not isinstance(message.get("role"), str)
                or message["role"] not in {"system", "user", "assistant"}
                or not isinstance(message.get("content"), str)
                for message in messages
            ):
                raise ValueError(f"Line {line_number} contains an invalid chat message")
            if not any(message["role"] == "user" for message in messages):
                raise ValueError(f"Line {line_number} has no user message")
            if messages[-1]["role"] != "assistant":
                raise ValueError(f"Line {line_number} must end with an assistant response")
            count += 1
    if count == 0:
        raise ValueError("Training file contains no examples")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("training_file", help="Curated JSONL chat examples")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    base_model = os.environ.get("OPENAI_FINE_TUNE_BASE_MODEL")
    if not api_key:
        parser.error("Set OPENAI_API_KEY in the environment")
    if not base_model:
        parser.error("Set OPENAI_FINE_TUNE_BASE_MODEL to a fine-tunable base model")

    example_count = validate_training_file(args.training_file)
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    with Path(args.training_file).open("rb") as training_file:
        uploaded_file = client.files.create(file=training_file, purpose="fine-tune")
    job = client.fine_tuning.jobs.create(
        training_file=uploaded_file.id,
        model=base_model,
    )
    print(f"Fine-tuning job submitted: {job.id}")
    print(f"Status: {job.status}; examples: {example_count}")
    print("Check the OpenAI fine-tuning dashboard for completion and the resulting model ID.")


if __name__ == "__main__":
    main()
