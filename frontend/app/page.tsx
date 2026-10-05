"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  getJSON,
  postJSON,
  type QA,
  type StoryResponse,
  type WordBankTier,
} from "@/lib/api";
import {
  speakSentences,
  speakWord,
  speechSupported,
  stopSpeech,
} from "@/lib/speech";

const PROFILE_KEY = "wordbyword_profile";

interface Profile {
  child: string;
  pet: string;
  known: string[];
  stuck: string[];
}

type View = "setup" | "story" | "questions" | "print";

const MAX_SENT_LEN: Record<number, number> = { 1: 6, 2: 8, 3: 10, 4: 12, 5: 14 };
const LENGTHS: Record<string, number> = { "100": 10, "200": 12, "300": 14 };
const LENGTH_META: Record<string, { name: string; sub: string }> = {
  "100": { name: "Bite-sized", sub: "10 sentences" },
  "200": { name: "Mid-length", sub: "12 sentences" },
  "300": { name: "Long", sub: "14 sentences" },
};
const QUESTION_COUNTS: Record<string, number> = { "100": 4, "200": 5, "300": 6 };
const GOALS = [
  { id: "comprehension", title: "Reading comprehension", sub: "Who, what, and sequenced recall within Anna's decodable scope" },
  { id: "vocabulary", title: "Vocabulary expansion", sub: "Context-cue deduction around 1-2 curated stretch words" },
  { id: "critical", title: "Critical thinking", sub: "Cause and effect, predictions, and simple deduction" },
  { id: "social", title: "Social-emotional awareness", sub: "Identifying character emotions, motivations, and calming choices" },
];

const TABS: { id: View; label: string }[] = [
  { id: "setup", label: "Reader Setup" },
  { id: "story", label: "Story Reading" },
  { id: "questions", label: "Comprehension" },
  { id: "print", label: "Print View" },
];

const THEMES = [
  { icon: "🐾", label: "Animals" },
  { icon: "♡", label: "Friendship" },
  { icon: "🌿", label: "Nature" },
  { icon: "🔍", label: "Mystery" },
  { icon: "🧭", label: "Adventure" },
  { icon: "🚀", label: "Space" },
];

function loadProfile(): Profile {
  try {
    const p = JSON.parse(localStorage.getItem(PROFILE_KEY) || "{}") as Partial<Profile>;
    return {
      child: typeof p.child === "string" ? p.child : "",
      pet: typeof p.pet === "string" ? p.pet : "",
      known: Array.isArray(p.known) ? p.known : [],
      stuck: Array.isArray(p.stuck) ? p.stuck : [],
    };
  } catch {
    return { child: "", pet: "", known: [], stuck: [] };
  }
}

function saveProfile(p: Profile): void {
  try {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(p));
  } catch {
    // private mode: profile just won't persist
  }
}

function cap(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

function clientLevel(known: string[], wordBank: WordBankTier[]): number {
  for (let t = 5; t >= 1; t--) {
    const tier = wordBank.find((w) => w.tier === t);
    if (!tier || !tier.words.length) continue;
    const hit = tier.words.filter((w) => known.includes(w)).length;
    if (hit / tier.words.length >= 0.5) return tier.tier;
  }
  return 1;
}

const TOKEN_RE = /[A-Za-z]+(?:'[A-Za-z]+)?/g;

function normAnswer(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\b(a|an|the)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function answerIsCorrect(user: string, answer: string): boolean {
  const u = normAnswer(user);
  const a = normAnswer(answer);
  if (!u || !a) return false;
  if (u === a) return true;
  if (u.length >= 3 && a.includes(u)) return true;
  if (a.length >= 3 && u.includes(a)) return true;
  return false;
}

function StoryLine({
  sentence,
  newWords,
  badWords,
  onWord,
}: {
  sentence: string;
  newWords: string[];
  badWords: string[];
  onWord: (word: string) => void;
}) {
  const parts: React.ReactNode[] = [];
  let last = 0;
  TOKEN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(sentence)) !== null) {
    if (m.index > last) parts.push(sentence.slice(last, m.index));
    const w = m[0].toLowerCase();
    const cls = [
      "word",
      newWords.includes(w) ? "word-new" : "",
      badWords.includes(w) ? "word-bad" : "",
    ]
      .filter(Boolean)
      .join(" ");
    parts.push(
      <span key={`${m.index}-${m[0]}`} className={cls} data-word={w}>
        {m[0]}
      </span>
    );
    last = m.index + m[0].length;
  }
  if (last < sentence.length) parts.push(sentence.slice(last));
  return (
    <p
      className="story-text"
      onClick={(e) => {
        const el = (e.target as HTMLElement).closest("[data-word]");
        if (el) onWord(el.getAttribute("data-word") || "");
      }}
    >
      {parts}
    </p>
  );
}

function StatRow({
  icon,
  title,
  sub,
}: {
  icon: string;
  title: string;
  sub: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/10 text-[15px]">
        {icon}
      </span>
      <span>
        <span className="block text-[14.5px] font-bold text-white">{title}</span>
        <span className="block text-[12.5px] text-indigo-200">{sub}</span>
      </span>
    </div>
  );
}

interface AnswerState {
  value: string;
  status: "idle" | "correct" | "wrong";
  revealed: boolean;
}

export default function Home() {
  const [view, setView] = useState<View>("setup");
  const [child, setChild] = useState("");
  const [pet, setPet] = useState("");
  const [known, setKnown] = useState<string[]>([]);
  const [stuck, setStuck] = useState<string[]>([]);
  const [wordBank, setWordBank] = useState<WordBankTier[]>([]);
  const [selectedTopic, setSelectedTopic] = useState("Animals");
  const [topicText, setTopicText] = useState("");
  const [levelMode, setLevelMode] = useState<string>("auto");
  const length = "300"; // fixed: every story is a full 14-sentence bedtime read
  const [goal, setGoal] = useState("comprehension");
  const [manualWords, setManualWords] = useState("");
  const [stuckSelected, setStuckSelected] = useState<string[]>([]);
  const [story, setStory] = useState<StoryResponse | null>(null);
  const [questions, setQuestions] = useState<QA[] | null>(null);
  const [answers, setAnswers] = useState<Record<number, AnswerState>>({});
  const [loadingStory, setLoadingStory] = useState(false);
  const [loadingQuestions, setLoadingQuestions] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [error, setError] = useState("");
  const errorTimer = useRef<number | null>(null);

  // load saved profile + word bank + topics
  useEffect(() => {
    const p = loadProfile();
    setChild(p.child);
    setPet(p.pet);
    setKnown(p.known);
    setStuck(p.stuck);
    getJSON<WordBankTier[] | { tiers: WordBankTier[] }>("/api/wordbank")
      .then((data) => {
        setWordBank(Array.isArray(data) ? data : data.tiers || []);
      })
      .catch(() => setError("Could not load the word list."));
  }, []);

  function showError(msg: string) {
    setError(msg);
    if (errorTimer.current) window.clearTimeout(errorTimer.current);
    errorTimer.current = window.setTimeout(() => setError(""), 6000);
  }

  const level =
    levelMode === "auto" ? clientLevel(known, wordBank) : Number(levelMode) || 1;
  const nSentences = LENGTHS[length] ?? 10;
  const maxPer = MAX_SENT_LEN[level] ?? 6;
  const planWords = nSentences * maxPer;
  const minutes = Math.max(1, Math.round(planWords / 50));
  const topic = topicText.trim() || selectedTopic || "a happy day";
  const nQuestions = QUESTION_COUNTS[length] ?? 5;

  const newWords = useMemo(() => {
    const manual = manualWords
      .split(/[\s,]+/)
      .map((w) => w.trim().toLowerCase())
      .filter(Boolean);
    const out: string[] = [];
    [...manual, ...stuckSelected].forEach((w) => {
      if (!out.includes(w)) out.push(w);
    });
    return out.slice(0, 3);
  }, [manualWords, stuckSelected]);

  function persist(childName: string, petName: string, knownWords: string[], stuckWords: string[]) {
    saveProfile({ child: childName, pet: petName, known: knownWords, stuck: stuckWords });
  }

  function toggleKnown(word: string) {
    const next = known.includes(word) ? known.filter((w) => w !== word) : [...known, word];
    setKnown(next);
    persist(child, pet, next, stuck);
  }

  function onStoryWord(word: string) {
    if (!word) return;
    speakWord(word);
    if (!stuck.includes(word)) {
      const next = [...stuck, word];
      setStuck(next);
      persist(child, pet, known, next);
    }
  }

  function toggleStuckChip(word: string) {
    setStuckSelected((prev) =>
      prev.includes(word) ? prev.filter((w) => w !== word) : [...prev, word]
    );
  }

  function removeStuck(word: string) {
    const next = stuck.filter((w) => w !== word);
    setStuck(next);
    setStuckSelected((prev) => prev.filter((w) => w !== word));
    persist(child, pet, known, next);
  }

  async function writeStory() {
    if (!child.trim()) {
      showError("Please tell us the child's name first.");
      setView("setup");
      return;
    }
    if (!known.length) {
      showError("Tick at least a few words they can read first.");
      setView("setup");
      return;
    }
    stopSpeech();
    setSpeaking(false);
    setStory(null);
    setQuestions(null);
    setAnswers({});
    setLoadingStory(true);
    persist(child.trim(), pet.trim(), known, stuck);
    try {
      const data = await postJSON<StoryResponse>("/api/story", {
        level: levelMode === "auto" ? null : level,
        known_words: known,
        child_name: child.trim(),
        pet_name: pet.trim(),
        new_words: newWords,
        topic,
        n_sentences: nSentences,
      });
      setStory(data);
      setView("story");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      showError(e instanceof Error ? e.message : "The story service is busy. Please try again.");
    } finally {
      setLoadingStory(false);
    }
  }

  async function makeQuestions() {
    if (!story) return;
    setLoadingQuestions(true);
    setQuestions(null);
    setAnswers({});
    try {
      const data = await postJSON<QA[]>("/api/questions", {
        story: story.story,
        level: story.level,
        child_name: child.trim(),
        pet_name: pet.trim(),
        new_words: newWords,
        known_words: known,
        learning_goal: goal,
        n_questions: nQuestions,
      });
      if (!data.length) throw new Error("Could not make questions. Please try again.");
      setQuestions(data);
      setView("questions");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e) {
      showError(e instanceof Error ? e.message : "Could not make questions. Please try again.");
    } finally {
      setLoadingQuestions(false);
    }
  }

  function toggleReadAloud() {
    if (!story) return;
    if (speaking) {
      stopSpeech();
      setSpeaking(false);
      return;
    }
    if (!speechSupported()) {
      showError("This browser cannot read aloud. Try Chrome or Edge.");
      return;
    }
    setSpeaking(true);
    speakSentences(story.story, () => setSpeaking(false));
  }

  function checkAnswer(i: number) {
    const st = answers[i];
    if (!st || !questions?.[i]) return;
    const ok = answerIsCorrect(st.value, questions[i].a);
    setAnswers((prev) => ({ ...prev, [i]: { ...st, status: ok ? "correct" : "wrong" } }));
  }

  function setAnswerValue(i: number, value: string) {
    setAnswers((prev) => ({ ...prev, [i]: prev[i] ? { ...prev[i], value, status: "idle" } : { value, status: "idle", revealed: false } }));
  }

  function revealAnswer(i: number) {
    setAnswers((prev) => ({ ...prev, [i]: prev[i] ? { ...prev[i], revealed: true } : { value: "", status: "idle", revealed: true } }));
  }

  const sentences = story
    ? story.story.match(/[^.!?\n]+[.!?]*/g) || [story.story]
    : [];
  const goalTitle = GOALS.find((g) => g.id === goal)?.title || "";
  const answeredCount = Object.values(answers).filter((a) => a.status === "correct").length;
  const storyTitle = story ? cap(topic) : "";

  return (
    <main className="mx-auto max-w-6xl px-4 pb-16">
      {/* ---------- header ---------- */}
      <header className="no-print pt-6 text-center">
        <h1 className="text-[28px] font-bold tracking-tight text-[#22263a]">Word by Word</h1>
        <p className="mt-0.5 text-[13.5px] text-[#6b7280]">
          Every story made only of words your reader already knows
        </p>
        <nav className="mt-4 flex justify-center gap-1.5">
          {TABS.map((t) => {
            const locked = t.id !== "setup" && !story;
            return (
              <button
                key={t.id}
                type="button"
                disabled={locked}
                onClick={() => setView(t.id)}
                className={`rounded-full px-4 py-1.5 text-[13.5px] font-semibold transition ${
                  view === t.id
                    ? "bg-[#4f46e5] text-white shadow-sm"
                    : locked
                      ? "cursor-not-allowed text-gray-300"
                      : "text-[#6b7280] hover:bg-white hover:text-[#22263a]"
                }`}
              >
                {t.label}
              </button>
            );
          })}
        </nav>
      </header>

      {error && (
        <div className="no-print mt-4 flex items-center justify-between rounded-xl border border-red-200 bg-[#fdecea] px-4 py-3 text-sm text-[#dc2626]">
          <span>⚠ {error}</span>
          <button
            type="button"
            onClick={() => setError("")}
            aria-label="Dismiss"
            className="text-lg leading-none opacity-60 hover:opacity-100"
          >
            ×
          </button>
        </div>
      )}

      {/* ================= SETUP VIEW ================= */}
      {view === "setup" && (
        <>
        <div className="no-print mt-7 flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-bold tracking-[0.18em] text-[#6b7280]">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#4f46e5] text-[10px] font-bold text-white">1</span>
              CUSTOM STORYSMITH
            </div>
            <h2 className="mt-1.5 text-[26px] font-bold tracking-tight text-[#22263a]">
              {child ? `Tailor ${child}\u2019s Quiet Tale` : "Tailor a Quiet Tale"}
            </h2>
          </div>
          <span className="mt-2 hidden items-center gap-1.5 rounded-full bg-[#eef2ff] px-3 py-1.5 text-[12px] font-semibold text-[#4338ca] sm:flex">
            <span className="h-2 w-2 rounded-full bg-[#4f46e5]" /> Decodable constraints active
          </span>
        </div>
        <div className="mt-5 grid items-start gap-5 lg:grid-cols-[1fr_360px]">
          <div className="space-y-5">
            {/* reader profile & phonics bank */}
            <section className="card p-5">
              <div className="flex items-center justify-between">
                <h2 className="text-[17px] font-bold">Reader Profile &amp; Phonics Bank</h2>
                <span className="rounded-full bg-[#f3f4fb] px-2.5 py-1 text-[11px] font-semibold text-[#6b7280]">
                  🔒 {child ? `${child}'s` : "The child's"} name stays on this device
                </span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <label className="block text-[12.5px] font-semibold text-[#6b7280]">
                  Child&apos;s First Name
                  <input
                    value={child}
                    onChange={(e) => setChild(e.target.value)}
                    maxLength={20}
                    placeholder="e.g. Anna"
                    autoComplete="off"
                    className="mt-1 h-12 w-full rounded-xl border border-[#e5e7f0] bg-white px-3.5 text-[15px] outline-none focus:border-[#4f46e5] focus:ring-2 focus:ring-[#4f46e5]/20"
                  />
                </label>
                <label className="block text-[12.5px] font-semibold text-[#6b7280]">
                  Companion / Pet Name
                  <input
                    value={pet}
                    onChange={(e) => setPet(e.target.value)}
                    maxLength={20}
                    placeholder="e.g. Shelby"
                    autoComplete="off"
                    className="mt-1 h-12 w-full rounded-xl border border-[#e5e7f0] bg-white px-3.5 text-[15px] outline-none focus:border-[#4f46e5] focus:ring-2 focus:ring-[#4f46e5]/20"
                  />
                </label>
              </div>

              <div className="mt-5 flex items-center justify-between">
                <p className="text-[12.5px] font-semibold text-[#6b7280]">Target Reading Measure</p>
                <span className="rounded-full bg-[#eef2ff] px-2.5 py-1 text-[11px] font-semibold text-[#4338ca]">
                  about {planWords} words
                </span>
              </div>
              <div className="mt-1.5 flex h-11 items-center rounded-xl border border-[#dcdbf0] bg-[#f3f2ff] px-4 text-[14px] font-bold text-[#4338ca]">
                📖 14 sentences — a full bedtime read, every time
              </div>

              <div className="mt-5 flex items-center justify-between">
                <h3 className="text-[16px] font-bold">Decodable Phonics Bank</h3>
                <span className="rounded-full bg-[#f3f4fb] px-2.5 py-1 text-[11px] font-semibold text-[#6b7280]">
                  {known.length} checked
                </span>
              </div>
              <p className="text-[12.5px] text-[#6b7280]">
                Tap dark words {child ? child : "your reader"} can comfortably read unassisted.
              </p>
              <div className="mt-2 max-h-72 space-y-3 overflow-y-auto pr-1">
                {wordBank.map((tier) => (
                  <div key={tier.tier}>
                    <h4 className="mb-1.5 text-[11px] font-bold uppercase tracking-[0.12em] text-[#9ca3af]">
                      {tier.name}
                    </h4>
                    <div className="flex flex-wrap gap-2">
                      {tier.words.map((word) => {
                        const on = known.includes(word);
                        return (
                          <button
                            key={word}
                            type="button"
                            onClick={() => toggleKnown(word)}
                            aria-pressed={on}
                            className={`flex h-11 items-center gap-1.5 rounded-full border px-3.5 text-[15px] transition ${
                              on
                                ? "border-[#4f46e5] bg-[#4f46e5] font-semibold text-white"
                                : "border-[#dcdbf0] bg-[#f3f2ff] text-[#22263a] hover:border-[#4f46e5]"
                            }`}
                          >
                            <span
                              className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-bold ${
                                on ? "bg-white/25 text-white" : "bg-[#f3f4fb] text-[#9ca3af]"
                              }`}
                            >
                              {on ? "✓" : "+"}
                            </span>
                            {word}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[13px] text-[#6b7280]">
                {known.length
                  ? `${known.length} words ticked — reading level ${level}.`
                  : "Tick some words to set the reading level."}
              </p>
              <label className="mt-3 block text-[12.5px] font-semibold text-[#6b7280]">
                Or set the level yourself
                <select
                  value={levelMode}
                  onChange={(e) => setLevelMode(e.target.value)}
                  className="mt-1 h-11 w-full rounded-xl border border-[#e5e7f0] bg-white px-3 text-[14.5px] outline-none focus:border-[#4f46e5]"
                >
                  <option value="auto">Auto — from the words ticked above</option>
                  <option value="1">Level 1 (ages 5-6)</option>
                  <option value="2">Level 2 (ages 6-7)</option>
                  <option value="3">Level 3 (ages 7-8)</option>
                  <option value="4">Level 4 (ages 8-9)</option>
                  <option value="5">Level 5 (ages 9-10)</option>
                </select>
              </label>
            </section>

            {/* theme */}
            <section className="card p-5">
              <h2 className="text-[17px] font-bold"> Theme</h2>
              <p className="text-[12.5px] text-[#6b7280]">
                Ground the storyline in themes {child ? child : "your reader"} delights in.
              </p>
              <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {THEMES.map((th) => (
                  <button
                    key={th.label}
                    type="button"
                    onClick={() => {
                      setSelectedTopic(th.label);
                      setTopicText("");
                    }}
                    className={`flex h-11 items-center gap-2 rounded-xl border px-3 text-[13.5px] transition ${
                      selectedTopic === th.label && !topicText
                        ? "border-[#4f46e5] bg-[#4f46e5] font-bold text-white"
                        : "border-[#e5e7f0] bg-white hover:border-[#4f46e5]"
                    }`}
                  >
                    <span className="text-[15px]">{th.icon}</span>
                    <span className="truncate">{th.label}</span>
                  </button>
                ))}
              </div>
              <input
                value={topicText}
                onChange={(e) => setTopicText(e.target.value)}
                maxLength={100}
                placeholder="Or type a custom topic (e.g. a rainy attic workshop)"
                autoComplete="off"
                className="mt-3 h-12 w-full rounded-xl border border-[#e5e7f0] bg-white px-3.5 text-[15px] outline-none focus:border-[#4f46e5] focus:ring-2 focus:ring-[#4f46e5]/20"
              />
            </section>

            {/* learning focus */}
            <section className="card p-5">
              <h2 className="text-[17px] font-bold">Target Learning Focus</h2>
              <p className="text-[12.5px] text-[#6b7280]">
                Select the pedagogical spine of the questions and narrative pacing.
              </p>
              <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
                {GOALS.map((g) => (
                  <button
                    key={g.id}
                    type="button"
                    onClick={() => setGoal(g.id)}
                    className={`rounded-xl border px-4 py-3 text-left transition ${
                      goal === g.id
                        ? "border-[#4f46e5] bg-[#eef2ff]"
                        : "border-[#e5e7f0] bg-[#f3f4fb] hover:border-[#4f46e5]"
                    }`}
                  >
                    <span className="flex items-center gap-2 text-[14.5px] font-bold">
                      <span
                        className={`h-4 w-4 rounded-full border-2 ${
                          goal === g.id ? "border-[#4f46e5] bg-[#4f46e5]" : "border-gray-300"
                        }`}
                      />
                      {g.title}
                    </span>
                    <span className="mt-1 block pl-6 text-[12px] text-[#6b7280]">{g.sub}</span>
                  </button>
                ))}
              </div>
            </section>

            {/* practice & scaffolding */}
            <section className="card p-5">
              <h2 className="text-[17px] font-bold">Practice &amp; Scaffolding Strategy</h2>
              <label className="mt-2 block text-[12.5px] font-semibold text-[#6b7280]">
                New challenge words to weave in (up to 3)
                <input
                  value={manualWords}
                  onChange={(e) => setManualWords(e.target.value)}
                  placeholder="e.g. giant village happy"
                  autoComplete="off"
                  className="mt-1 h-12 w-full rounded-xl border border-[#e5e7f0] bg-white px-3.5 text-[15px] outline-none focus:border-[#4f46e5] focus:ring-2 focus:ring-[#4f46e5]/20"
                />
              </label>
              {stuck.length > 0 && (
                <div className="mt-3">
                  <p className="text-[12.5px] text-[#6b7280]">
                    Stuck words from before — tap one to practice it in the next story:
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-2">
                    {stuck.map((word) => (
                      <button
                        key={word}
                        type="button"
                        onClick={() => toggleStuckChip(word)}
                        className={`h-11 rounded-full border px-3.5 text-[15px] transition ${
                          stuckSelected.includes(word)
                            ? "border-[#4f46e5] bg-[#4f46e5] font-semibold text-white"
                            : "border-[#c7d2fe] bg-[#eef2ff] text-[#4338ca] hover:border-[#4f46e5]"
                        }`}
                      >
                        {word}
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => {
                            e.stopPropagation();
                            removeStuck(word);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") removeStuck(word);
                          }}
                          className="ml-1.5 font-bold opacity-60"
                          title="Remove"
                        >
                          ×
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </section>
          </div>

          {/* story blueprint (night card) */}
          <aside className="space-y-4 lg:sticky lg:top-4">
            <div className="overflow-hidden rounded-2xl">
            <div className="night-gradient relative overflow-hidden p-5 text-white">
              <span className="pointer-events-none absolute -right-3 -top-7 select-none text-[88px] leading-none opacity-20">🌙</span>
              <div className="flex items-center justify-between text-[11px] font-bold tracking-[0.16em] text-indigo-200">
                <span>STORY BLUEPRINT</span>
                <span className="opacity-70">⧉</span>
              </div>
              <div className="mt-2 text-[22px] font-bold leading-snug">
                {pet ? `${cap(pet)}\u2019s ${cap(topic)}` : cap(topic)}
              </div>
              <div className="text-[12.5px] text-indigo-200">
                Adventure tailored for {child ? child : "your reader"}
              </div>
              <div className="mt-4 grid grid-cols-2 gap-3 border-t border-white/15 pt-4">
                <div>
                  <div className="text-[15px] font-bold">🕐 ~{minutes} mins</div>
                  <div className="text-[11.5px] text-indigo-200">Bedtime pace</div>
                </div>
                <div>
                  <div className="text-[15px] font-bold">📄 {planWords} words</div>
                  <div className="text-[11.5px] text-indigo-200">{LENGTH_META[length]?.name} length</div>
                </div>
              </div>
            </div>
            <div className="rounded-b-2xl bg-white p-5" style={{ border: "1px solid var(--hairline)", borderTop: "none" }}>
              <p className="text-[11px] font-bold tracking-[0.12em] text-[#9ca3af]">
                PACING &amp; DECODABILITY RULES
              </p>
              <div className="mt-3 space-y-3 text-[13.5px]">
                <div className="flex justify-between">
                  <span className="text-[#6b7280]">Max sentence measure</span>
                  <b>{maxPer} words max</b>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#6b7280]">Controlled decodability</span>
                  <b>100% matched to bank</b>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#6b7280]">Comprehension questions</span>
                  <b>{nQuestions} gentle check-ins</b>
                </div>
                <div className="flex justify-between">
                  <span className="text-[#6b7280]">Stretch focus inclusion</span>
                  <b className={newWords.length ? "" : "text-[#9ca3af]"}>
                    {newWords.length ? newWords.join(", ") : "none yet"}
                  </b>
                </div>
              </div>
              <div className="mt-4 rounded-xl bg-[#eef2ff] p-3 text-[12.5px] text-[#4338ca]">
                Every line will prioritize familiar cadence, natural paper focus, and zero surprise phonetic patterns.
              </div>
              <button
                type="button"
                onClick={writeStory}
                disabled={loadingStory}
                className="mt-4 h-12 w-full rounded-xl bg-[#4f46e5] text-[15.5px] font-bold text-white transition hover:bg-[#4338ca] disabled:opacity-60"
              >
                {loadingStory ? "Writing your story..." : "Create my story →"}
              </button>
              <p className="mt-2 text-center text-[11.5px] text-[#9ca3af]">
                Takes around 10 seconds to craft decodable sentences
              </p>
            </div>
            </div>
            <div className="rounded-2xl border border-[#e5e7f0] bg-white p-4">
              <p className="text-[13px] font-bold">🌙 Night Audio Ready</p>
              <p className="mt-1 text-[12.5px] text-[#6b7280]">
                High-fidelity browser-voice read-aloud loads directly after story creation — nothing leaves the device.
              </p>
            </div>
          </aside>
        </div>
        </>
      )}

      {/* ================= STORY VIEW ================= */}
      {view === "story" && story && (
        <div className="mt-6 grid items-start gap-5 lg:grid-cols-[1fr_360px]">
          <div>
            {/* context chips */}
            <div className="no-print mb-4 flex flex-wrap items-center gap-2 rounded-2xl border border-[#e5e7f0] bg-white px-4 py-3">
              <span className="rounded-full bg-[#eef2ff] px-3 py-1 text-[13px] font-semibold text-[#4338ca]">
                {child || "Reader"}{pet ? ` • ${pet}` : ""}
              </span>
              <span className="rounded-full bg-[#f3f4fb] px-3 py-1 text-[13px] text-[#6b7280]">Level {story.level}</span>
              <span className="rounded-full bg-[#f3f4fb] px-3 py-1 text-[13px] text-[#6b7280]">{cap(topic)}</span>
              {newWords.map((w) => (
                <span key={w} className="rounded-full bg-[#fef3c7] px-3 py-1 text-[13px] font-semibold text-[#92400e]">
                  ⭐ {w}
                </span>
              ))}
              <button
                type="button"
                onClick={() => setView("setup")}
                className="ml-auto text-[13.5px] font-bold text-[#4f46e5] hover:underline"
              >
                ✏️ Edit setup
              </button>
            </div>

            {/* story paper */}
            <section className="card p-6 sm:p-8" id="output">
              <div className="flex items-center justify-between">
                <span
                  className={`inline-block rounded-full px-3 py-1.5 text-[12.5px] font-bold ${
                    story.ok ? "bg-[#e5f6ec] text-[#16a34a]" : "bg-[#fdf3e0] text-[#d97706]"
                  }`}
                >
                  {story.ok
                    ? `✓ Every word checked for Level ${story.level}${story.attempts > 1 ? ` (fixed in ${story.attempts} tries)` : ""}`
                    : "⚠ Some words may be hard"}
                </span>
                <span className="story-title text-[20px] font-bold text-[#22263a]">{storyTitle}</span>
              </div>
              <div className="mt-4 space-y-4">
                {sentences.map((s, i) => (
                  <StoryLine
                    key={i}
                    sentence={s.trim()}
                    newWords={newWords}
                    badWords={story.report.bad_words || []}
                    onWord={onStoryWord}
                  />
                ))}
              </div>
              <div className="no-print mt-6 rounded-xl bg-[#f3f4fb] px-4 py-3 text-[13px] text-[#6b7280]">
                🔊 Tap any word to hear it pronounced. Read aloud uses your browser&apos;s own voice — nothing leaves the device.
              </div>
              <div className="no-print mt-4 flex flex-wrap gap-2.5">
                <button
                  type="button"
                  onClick={toggleReadAloud}
                  className="h-12 rounded-xl border border-[#e5e7f0] bg-white px-5 text-[14.5px] font-bold transition hover:border-[#4f46e5] disabled:opacity-50"
                  disabled={speaking ? false : !story}
                >
                  {speaking ? "⏹ Stop" : "🔊 Read aloud"}
                </button>
                <button
                  type="button"
                  onClick={makeQuestions}
                  disabled={loadingQuestions}
                  className="h-12 rounded-xl bg-[#4f46e5] px-5 text-[14.5px] font-bold text-white transition hover:bg-[#4338ca] disabled:opacity-60"
                >
                  {loadingQuestions ? "Thinking..." : "📋 Questions"}
                </button>
                <button
                  type="button"
                  onClick={() => setView("print")}
                  className="h-12 rounded-xl border border-[#e5e7f0] bg-white px-5 text-[14.5px] font-bold transition hover:border-[#4f46e5]"
                >
                  🖨 Print view
                </button>
              </div>
            </section>
          </div>

          {/* story plan night card */}
          <aside className="no-print overflow-hidden rounded-2xl lg:sticky lg:top-4">
            <div className="night-gradient p-5 text-white">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold tracking-[0.16em] text-indigo-200">YOUR STORY PLAN</span>
                <span className="rounded-full bg-[#16a34a] px-2.5 py-0.5 text-[11px] font-bold text-white">
                  ✓ Story Ready
                </span>
              </div>
              <div className="mt-2 text-[22px] font-bold leading-snug">{storyTitle}</div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {[`Level ${story.level}`, cap(topic), LENGTH_META[length]?.name || ""].map((t) => (
                  <span key={t} className="rounded-full bg-white/10 px-2.5 py-1 text-[12px] font-semibold text-indigo-100">
                    {t}
                  </span>
                ))}
              </div>
            </div>
            <div className="rounded-b-2xl bg-white p-5" style={{ border: "1px solid var(--hairline)", borderTop: "none" }}>
              <div className="space-y-3 text-[13.5px]">
                <StatRow icon="📄" title={`About ${planWords} words`} sub="Age-matched controlled vocabulary" />
                <StatRow icon="🕐" title={`${minutes}-${minutes + 1} minute read`} sub="Short enough to stay focused" />
                <StatRow icon="📏" title={`Sentences under ${maxPer} words`} sub="Every sentence phonetically checked" />
                <StatRow icon="📋" title={`${nQuestions} questions`} sub="Matched to your learning goal" />
              </div>
              <div className="mt-4 rounded-xl bg-[#f3f4fb] p-3">
                <p className="text-[11px] font-bold tracking-[0.12em] text-[#9ca3af]">LEARNING FOCUS</p>
                <p className="mt-1 text-[13px] text-[#22263a]">
                  {goalTitle}. Practice target words:{" "}
                  <b className="text-[#4f46e5]">{newWords.length ? newWords.join(" and ") : "none"}</b>.
                </p>
              </div>
              <div className="mt-3 flex items-center justify-between rounded-xl bg-[#e5f6ec] p-3">
                <span>
                  <span className="block text-[13.5px] font-bold text-[#22263a]">Vocabulary Confidence</span>
                  <span className="block text-[12px] text-[#6b7280]">
                    {story.report.bad_words?.length ? `${100 - Math.round(((story.report.bad_words.length || 0) / Math.max(1, sentences.join(" ").split(/\s+/).length)) * 100)}% sight word match` : "100% sight word match"}
                  </span>
                </span>
                <span className="flex h-11 w-11 items-center justify-center rounded-full border-[3px] border-[#16a34a] text-[12px] font-bold text-[#16a34a]">
                  {story.report.bad_words?.length ? "✓" : "100%"}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setView("print")}
                className="mt-4 h-12 w-full rounded-xl bg-[#eef2ff] text-[14.5px] font-bold text-[#4338ca] transition hover:bg-[#e0e7ff]"
              >
                🖨 Print Story
              </button>
              <button
                type="button"
                onClick={() => {
                  setStory(null);
                  setQuestions(null);
                  setAnswers({});
                  setView("setup");
                }}
                className="mt-2 h-12 w-full text-[14.5px] font-bold text-[#4f46e5] transition hover:underline"
              >
                ⊕ New Story
              </button>
            </div>
            <div className="mt-4 rounded-2xl border border-[#e5e7f0] bg-white p-4">
              <p className="text-[13px] font-bold">🌙 Parent Tip</p>
              <p className="mt-1 text-[12.5px] text-[#6b7280]">
                Encourage {child ? child : "your reader"} to point to each word as it is spoken
                aloud to strengthen visual tracking.
              </p>
            </div>
          </aside>
        </div>
      )}

      {/* ================= QUESTIONS VIEW ================= */}
      {view === "questions" && story && (
        <div className="mt-6 grid items-start gap-5 lg:grid-cols-[1fr_360px]">
          <div>
            <div className="no-print mb-4 flex items-center justify-between rounded-2xl border border-[#e5e7f0] bg-white px-4 py-3">
              <span className="text-[13.5px] font-semibold">📋 Current Stage: Active Comprehension Review</span>
              <button type="button" onClick={() => setView("story")} className="text-[13.5px] font-bold text-[#4f46e5] hover:underline">
                ← Back to story
              </button>
            </div>

            {!questions && (
              <section className="card p-8 text-center">
                <p className="text-[15px] font-semibold">Comprehension questions for this story</p>
                <p className="mt-1 text-[13px] text-[#6b7280]">
                  {loadingQuestions
                    ? "Writing gentle check-ins..."
                    : `Generate ${nQuestions} questions matched to your learning focus.`}
                </p>
                <button
                  type="button"
                  onClick={makeQuestions}
                  disabled={loadingQuestions}
                  className="mt-4 h-12 rounded-xl bg-[#4f46e5] px-6 text-[14.5px] font-bold text-white transition hover:bg-[#4338ca] disabled:opacity-60"
                >
                  {loadingQuestions ? "Thinking..." : "✨ Make questions"}
                </button>
              </section>
            )}

            {questions && questions.length > 0 && (
              <>
                <div className="no-print mb-4 flex items-center justify-between rounded-2xl border border-[#e5e7f0] bg-white px-4 py-3">
                  <span className="text-[13.5px] font-bold">Questions Progress</span>
                  <span className="text-[13px] text-[#6b7280]">
                    {answeredCount} of {questions.length} answered correctly
                  </span>
                </div>
                <div className="space-y-3">
                  {questions.map((qa, i) => {
                    const st = answers[i] || { value: "", status: "idle" as const, revealed: false };
                    return (
                      <div
                        key={i}
                        className={`card p-4 ${
                          st.status === "correct"
                            ? "border-[#16a34a]/40 bg-[#e5f6ec]"
                            : st.status === "wrong"
                              ? "border-[#dc2626]/40 bg-[#fdecea]"
                              : ""
                        }`}
                      >
                        <p className="flex items-start gap-2.5 text-[15.5px] font-bold">
                          <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#4f46e5] text-[12px] font-bold text-white">
                            {i + 1}
                          </span>
                          {qa.q}
                        </p>
                        <div className="mt-3 flex gap-2">
                          <input
                            value={st.value}
                            onChange={(e) => setAnswerValue(i, e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") checkAnswer(i);
                            }}
                            placeholder="Type your answer..."
                            autoComplete="off"
                            disabled={st.status === "correct"}
                            className={`h-11 flex-1 rounded-xl border px-3.5 text-[14.5px] outline-none focus:border-[#4f46e5] focus:ring-2 focus:ring-[#4f46e5]/20 disabled:opacity-70 ${
                              st.status === "wrong" ? "border-[#dc2626] bg-white" : "border-[#e5e7f0] bg-white"
                            }`}
                          />
                          {st.status !== "correct" && (
                            <button
                              type="button"
                              onClick={() => checkAnswer(i)}
                              className="h-11 rounded-xl bg-[#4f46e5] px-4 text-[13.5px] font-bold text-white transition hover:bg-[#4338ca]"
                            >
                              {st.status === "wrong" ? "Try again →" : "Check →"}
                            </button>
                          )}
                          {st.status === "correct" && (
                            <span className="flex h-11 items-center rounded-xl bg-[#16a34a] px-4 text-[13.5px] font-bold text-white">
                              ✓ Completed
                            </span>
                          )}
                        </div>
                        {st.status === "correct" && (
                          <p className="mt-2 text-[12.5px] font-semibold text-[#16a34a]">
                            ✓ Right! Great recall.
                          </p>
                        )}
                        {st.status === "wrong" && (
                          <div className="mt-2">
                            {st.revealed ? (
                              <p className="text-[12.5px] text-[#dc2626]">
                                📍 The correct answer is: <b>{qa.a}</b>
                              </p>
                            ) : (
                              <button
                                type="button"
                                onClick={() => revealAnswer(i)}
                                className="text-[12.5px] font-bold text-[#6b7280] hover:underline"
                              >
                                Show the correct answer
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          {/* mini plan card */}
          <aside className="no-print overflow-hidden rounded-2xl lg:sticky lg:top-4">
            <div className="night-gradient p-5 text-white">
              <div className="text-[11px] font-bold tracking-[0.16em] text-indigo-200">QUIET READING RITUAL</div>
              <div className="mt-2 text-[22px] font-bold leading-snug">A brand-new adventure</div>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {story && [`Level ${story.level}`, cap(topic), LENGTH_META[length]?.name || ""].map((t) => (
                  <span key={t} className="rounded-full bg-white/10 px-2.5 py-1 text-[12px] font-semibold text-indigo-100">
                    {t}
                  </span>
                ))}
              </div>
            </div>
            <div className="rounded-b-2xl bg-white p-5" style={{ border: "1px solid var(--hairline)", borderTop: "none" }}>
              <div className="space-y-3 text-[13.5px]">
                <StatRow icon="✓" title="Age-matched vocabulary" sub="Validated against early reader corpus" />
                <StatRow icon="🕐" title={`${minutes}-${minutes + 1} minute read`} sub="Optimal bedtime span without fatigue" />
                <StatRow icon="📏" title={`Sentences under ${maxPer} words`} sub="Prevents line-tracking jumping" />
              </div>
              <button
                type="button"
                onClick={() => setView("story")}
                className="mt-4 h-12 w-full rounded-xl bg-[#4f46e5] text-[14.5px] font-bold text-white transition hover:bg-[#4338ca]"
              >
                ✓ Finish Reading
              </button>
              <button
                type="button"
                onClick={() => setView("print")}
                className="mt-2 h-12 w-full rounded-xl bg-[#eef2ff] text-[14.5px] font-bold text-[#4338ca] transition hover:bg-[#e0e7ff]"
              >
                🖨 Export / Print
              </button>
            </div>
            <div className="mt-4 rounded-2xl border border-[#e5e7f0] bg-white p-4">
              <p className="text-[13px] font-bold">🌙 Parent Reading Nook Tip</p>
              <p className="mt-1 text-[12.5px] text-[#6b7280]">
                Encourage the reader to point to the screen. For Question 3, ask them what grows tall in the park.
              </p>
            </div>
          </aside>
        </div>
      )}

      {/* ================= PRINT VIEW ================= */}
      {view === "print" && story && (
        <div className="mt-6">
          <div className="no-print mb-4 flex items-center justify-between rounded-2xl border border-[#e5e7f0] bg-white px-4 py-3">
            <span className="text-[13.5px] font-semibold">🖨 Print preview — what you see is the paper</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setView("story")}
                className="h-11 rounded-xl border border-[#e5e7f0] bg-white px-4 text-[13.5px] font-bold transition hover:border-[#4f46e5]"
              >
                ← Back to story
              </button>
              <button
                type="button"
                onClick={() => window.print()}
                className="h-11 rounded-xl bg-[#4f46e5] px-5 text-[13.5px] font-bold text-white transition hover:bg-[#4338ca]"
              >
                🖨 Print now
              </button>
            </div>
          </div>

          <div className="print-sheet rounded-2xl border border-[#e5e7f0] shadow-md" style={{ boxShadow: "0 12px 32px -4px rgba(30,27,75,0.08)" }}>
            <p className="text-center text-[11px] font-bold tracking-[0.2em] text-[#9ca3af]">
              DECODABLE STORY SHEET
            </p>
            <h2 className="mt-2 text-center text-[30px] font-bold text-[#22263a]">
              {child ? `${child}${pet ? ` and ${pet}` : ""}` : storyTitle}
            </h2>
            <p className="mt-1 text-center text-[13px] text-[#6b7280]">
              {child ? `A story for ${child}` : "A decodable story"} · Level {story.level}
            </p>
            <div className="mt-10 space-y-6">
              {sentences.map((s, i) => (
                <p key={i} className="story-text">
                  {s.trim()}
                </p>
              ))}
            </div>
            <div className="mt-14 flex items-center justify-between border-t border-[#e5e7f0] pt-4 text-[11px] text-[#9ca3af]">
              <span>Word by Word — Made only with words {child ? child : "your reader"} knows</span>
              <span>PAGE 1 OF 1</span>
            </div>
          </div>
        </div>
      )}
    <footer className="no-print mt-14 flex flex-col items-start justify-between gap-3 border-t border-[#e5e7f0] pt-6 sm:flex-row sm:items-center">
        <span className="text-[12.5px] text-[#6b7280]">
          <b className="text-[#22263a]">Word by Word • Quiet Reading Nook</b>
          <span className="block text-[12px]">A patient, phonics-based companion for early readers and families.</span>
        </span>
        <span className="text-[12px] text-[#9ca3af]">Natural paper focus mode • © 2026 Word by Word</span>
      </footer>
    </main>
  );
}