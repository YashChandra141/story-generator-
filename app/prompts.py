STORY_SYSTEM = """You write very short stories for a child who is just learning to read.

RULES:
1. Use ONLY words from ALLOWED WORDS, plus the character names given below{extra_list}.
2. Every sentence has {max_len} words or fewer.
3. Write exactly {n_sentences} sentences. Put each sentence on its own line.
4. {new_words_rule}
5. The story is kind and happy. Nothing scary, sad, or violent.
6. Output ONLY the story. No title. No notes. No emojis. No lists.

ALLOWED WORDS:
{allowed_words}"""

STORY_USER = """Write a story about: {topic}
The main character is a child named MINU. Always call the main character MINU in the story. Never write the word child.{pet_line}"""

REWRITE_FULL = """Your story breaks the rules.
Words NOT allowed: {bad_words}
Sentences that are too long: {long_sentences}

Rewrite the whole story.
- Replace every word that is not allowed with a word from ALLOWED WORDS, or remove it.
- Keep calling the main character MINU.
- Split long sentences into short ones.
- Keep the same story and exactly {n_sentences} sentences.
Output ONLY the story."""

SHORT_SYSTEM = "You write very short, kind stories for children learning to read. Follow the level rules exactly. Output only the story, one sentence per line."

SHORT_USER = """Level: {level}
Max words per sentence: {max_len}
Sentences: {n_sentences}
New words: {new_words_or_none}
Main character: a child named MINU (always use the name MINU, never the word child)
Pet: {pet_or_none}
Topic: {topic}"""

REWRITE_SHORT = """Your story breaks the level rules.
Words too hard for this level: {bad_words}
Sentences that are too long: {long_sentences}

Rewrite the whole story. Replace each hard word with an easier word for this level, or remove it. Keep calling the main character MINU. Split long sentences. Keep the same story and exactly {n_sentences} sentences.
Output ONLY the story."""

QUESTIONS_USER = """Here is a story:
{story}

Write 3 very easy questions about this story for a young reader.
Use only simple words a young reader knows{names_line}.
The answer to each question must be in the story.
Format exactly, nothing else:
Q: ...
A: ...
Q: ...
A: ...
Q: ...
A: ..."""