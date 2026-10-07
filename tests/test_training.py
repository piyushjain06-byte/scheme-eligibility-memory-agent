import json

import pytest

from train_chat_model import validate_training_file


def test_validate_training_file_accepts_chat_jsonl(tmp_path):
    path = tmp_path / "examples.jsonl"
    path.write_text(
        json.dumps(
            {
                "messages": [
                    {"role": "user", "content": "Explain a scheme."},
                    {"role": "assistant", "content": "I need a reviewed source to answer."},
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert validate_training_file(path) == 1


def test_validate_training_file_rejects_non_assistant_final_message(tmp_path):
    path = tmp_path / "examples.jsonl"
    path.write_text(
        '{"messages":[{"role":"user","content":"Question"},{"role":"system","content":"Context"}]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="assistant response"):
        validate_training_file(path)
