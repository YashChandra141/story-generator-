from types import SimpleNamespace

from app import llm


def test_message_text_uses_reasoning_when_content_empty():
    message = SimpleNamespace(
        content="",
        reasoning_content="MINU can see the dog.",
        reasoning=None,
        model_extra={"reasoning": "ignored"},
    )
    assert llm._message_text(message) == "MINU can see the dog."


def test_apply_names_swaps_placeholders_case_insensitive():
    assert (
        llm._apply_names("Minu and the pet ran. MINU's ball.", "Asha", "Moti")
        == "Asha and the pet ran. Asha's ball."
    )
    assert (
        llm._apply_names("Minu can hug Pip. Pip can run.", "Asha", "")
        == "Asha can hug the pet. the pet can run."
    )


def test_question_names_swapped_back(monkeypatch):
    captured = {}

    def fake_call(client, model, messages, temperature, max_tokens):
        captured["messages"] = [dict(m) for m in messages]
        return (
            "Q: Can MINU run?\n"
            "A: PIP can.\n"
            "Q: What is in the grass?\n"
            "A: A ball.\n"
            "Q: Why is the enormous day fun?\n"
            "A: Because it is.",
            100,
        )

    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setattr(llm, "_call", fake_call)

    questions = llm.generate_questions(
        "Asha and Moti can run in the park. The ball is in the grass.",
        1,
        "Asha",
        "Moti",
        [],
    )

    user_msg = captured["messages"][1]["content"]
    assert "MINU" in user_msg and "PIP" in user_msg
    assert "Asha" not in user_msg and "Moti" not in user_msg

    assert len(questions) == 2
    assert questions[0]["q"] == "Can Asha run?"
    assert questions[0]["a"] == "Moti can."
    assert all("enormous" not in q["q"] for q in questions)