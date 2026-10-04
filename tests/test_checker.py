from app import checker, levels


def count_lines(name: str) -> int:
    path = levels.LEVELS_DIR / name
    return len([line for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()])


def test_word_list_counts():
    assert count_lines("preprimer.txt") == 40
    assert count_lines("primer.txt") == 52
    assert count_lines("grade1.txt") == 41
    assert count_lines("grade2.txt") == 46
    assert count_lines("grade3.txt") == 41
    assert count_lines("nouns.txt") == 95


def test_level1_pass():
    result = checker.check("I can see the big dog.", 1, [])
    assert result["ok"] is True
    assert result["bad_words"] == []


def test_level1_fail_enormous():
    result = checker.check("The enormous dog.", 1, [])
    assert result["ok"] is False
    assert result["bad_words"] == ["enormous"]


def test_long_sentence_level_gap():
    story = "I can see the big dog run to me."
    at_level1 = checker.check(story, 1, [])
    assert at_level1["ok"] is False
    assert at_level1["long_sentences"]
    assert at_level1["n_sentences"] == 1
    at_level3 = checker.check(story, 3, [])
    assert at_level3["ok"] is True


def test_extra_words_and_possessive():
    assert checker.check("Moti can run.", 1, ["moti"])["ok"] is True
    assert checker.check("Moti's ball is red.", 1, ["moti"])["ok"] is True


def test_inflections_need_level_2():
    at_level1 = checker.check("The dog is jumping.", 1, [])
    assert at_level1["ok"] is False
    assert "jumping" in at_level1["bad_words"]
    assert checker.check("The dog is jumping.", 2, [])["ok"] is True


def test_curly_apostrophe_passes_level_3():
    result = checker.check("I don\u2019t like it.", 3, [])
    assert result["ok"] is True
