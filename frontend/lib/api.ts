const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");

export interface CheckReport {
  ok: boolean;
  bad_words: string[];
  long_sentences: string[];
  n_sentences: number;
  n_words: number;
  in_list_rate: number;
}

export interface StoryResponse {
  story: string;
  story_placeholder: string;
  level: number;
  ok: boolean;
  first_try_ok: boolean;
  attempts: number;
  first_draft: string;
  report: CheckReport;
  prompt_tokens: number;
}

export interface WordBankTier {
  tier: number;
  name: string;
  words: string[];
}

export interface QA {
  q: string;
  a: string;
}

export interface StoryRequest {
  level: number | null;
  known_words: string[];
  child_name: string;
  pet_name: string;
  new_words: string[];
  topic: string;
  n_sentences: number;
}

export interface QuestionsRequest {
  story: string;
  level: number | null;
  child_name: string;
  pet_name: string;
  new_words: string[];
  known_words: string[];
  learning_goal: string;
  n_questions: number;
}

async function detail(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    const d = data?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d
        .map((e) => {
          const m = (e as { msg?: string })?.msg;
          return m || JSON.stringify(e);
        })
        .join("; ");
    }
    if (d != null) return JSON.stringify(d);
  } catch {
    // ignore body parse errors
  }
  return `Request failed (${res.status})`;
}

export async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()) as T;
}

export async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()) as T;
}