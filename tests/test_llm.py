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


def test_fix_punctuation_capitalizes_after_full_stop():
    assert llm._fix_punctuation("minu can run. the dog can run too.") == "Minu can run. The dog can run too."


def test_fix_punctuation_adds_missing_terminal_mark():
    assert llm._fix_punctuation("Minu can run\nthe dog can run") == "Minu can run.\nThe dog can run."


def test_fix_punctuation_space_after_punctuation_and_standalone_i():
    assert llm._fix_punctuation("Minu ran.and i ran too") == "Minu ran. And I ran too."
    assert llm._fix_punctuation("Minu ran ,  pip ran .") == "Minu ran, pip ran."


def test_fix_punctuation_question_mark_for_question_starters():
    assert llm._fix_punctuation("can minu run", default_mark="?") == "Can minu run?"


def test_fix_articles_agreement():
    assert llm._fix_articles("Minu has a apple and an ball.") == "Minu has an apple and a ball."
    assert llm._fix_articles("An kite flew. A owl sat.") == "A kite flew. An owl sat."
    assert llm._fix_articles("A umbrella is big") == "An umbrella is big"


def test_tense_mixed_detects_past_and_present():
    assert llm._tense_mixed("Minu went to the park. Minu is happy.") is True
    assert llm._tense_mixed("Minu went to the park. Moti went too.") is False
    assert llm._tense_mixed("Minu is happy. Moti is little.") is False
    assert llm._tense_mixed("The ball is red. It is on the grass.") is False


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