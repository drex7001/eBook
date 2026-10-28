# කොළ: Multilingual Reading & Study Studio — private beta

Local, bring-your-own-key reading and study app. Upload a PDF, read its original or translated text,
compare it with the source page, and check your understanding with chapter quizzes or full-book exams.
App-wide settings control languages, reading purpose, translation style, display, AI models and audio.
Existing Sinhala translations, notes, vocabulary and reading positions are migrated automatically.

This release is a **private local beta**. Public distribution, installers, accounts/billing, OCR and additional
document formats are future work. Broad text-language selection is available; real translation quality depends
on the selected provider/model. Automated checks use mock AI, with Sinhala, Tamil, English and Arabic samples.

### Settings and deliberate AI actions

- Open **Settings** from the library or reader. Preferences are stored on the local server and apply to all books.
- Choose Original / Translation / Both. A paragraph opens the opposite text, with the original PDF crop.
- Tablets/desktops (768px+) use a right-side inspector; phones use a bottom sheet.
- A word tap offers Translate / Open paragraph / Cancel. Lookup starts only after Translate is selected.
- **Upload & translate** authorizes whole-book translation, enabled by default. Original view is a display setting;
  switch off automatic upload translation separately if you want to upload without generating a translation.
- Target language/style changes preserve existing output. Use **Versions → Create new version · AI** to generate
  another translation; switching saved versions does not call AI. Glossary edits belong to the active version.
- Voice starts **Off**. Device speech uses available browser voices with no automatic cloud fallback.
  Cloud speech asks you to authorize one paragraph or the remainder of a chapter, then generates only as needed.
  Stopping revokes further generation; a provider request already in flight cannot be undone.
- Cloud word lessons ask separately. Vocabulary question generation is an explicit action on **My words**.
  Opening settings, practice, study or a saved paper never generates AI content.
- Settings shows usage by action/model, estimated costs, pricing date and generated audio duration. Unknown
  prices are labelled unavailable, and omitted from the estimated total. This is an estimate, not a provider bill.

### Subject learning and progress

Open **Study / exam** in a book. Select chapters, a paragraph range, or the entire book; choose Easy (recall),
Medium (understanding), or Hard (application/analysis). Generation creates a saved, versioned paper and validates
four distinct options plus a source reference in the original language. PDF typography/spacing is normalized locally.
Every response, including rejected/malformed output, is saved before validation. Generation stops at the first
failed/incomplete response, with **no automatic paid retry**. Accepted questions remain usable. Batches combine
small sections (up to four questions per response; a 50-question paper has at most 13 response batches).
New versions cost an AI operation; retrying a saved paper does not.

Use **View saved responses** to inspect original output, source excerpts, token counts and exact rejection reasons.
**Recheck saved responses · no AI** reruns local validation without a provider request; it cannot modify papers
that already have attempts. Stop generation prevents the next batch while preserving a response already in flight.
Raw response details are hidden during an active attempt. Papers generated before this recovery update did not
retain rejected output; those old responses cannot be recovered from the local database. Old repeated error
messages are collapsed, and the UI reports the missing archive explicitly. Restart the server after updating:
the new UI disables generation against an older backend that lacks these safeguards.

Study mode reveals explanations and source links after each answer. Exam mode withholds solutions until submission,
grades on the server and persists answers/deadlines across reloads. Defaults: 10 chapter questions, or a 20-question,
30-minute exam. Attempts, weak chapters and scheduled reviews stay in the local database.

Progress includes a daily 10-minute reading / 5-answer challenge, streaks, chapter badges and boss-quiz setup links.
Active reading earns 1 XP/minute (30/day cap); the first correct answer to a distinct subject question earns
5/10/15 XP by difficulty. Completing both daily goals earns 20 XP; each 100 XP gains a level. Replaying a question
does not award its correct-answer XP again. Gamification can be hidden while study history remains available.

## Run it (Windows)

Needs **Python 3.11+** (PyMuPDF 2 requires it). Node is only needed if you change the UI.

```bat
start.bat
```

or by hand:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

`start.bat` creates `.venv`, installs packages (from the local `wheels\` folder when it exists, so a slow
connection to PyPI doesn't break the install), then opens `http://localhost:8000` in your browser.
Set `OPEN_BROWSER=0` in `.env` to stop it opening a tab.

The default bind is **127.0.0.1**. For a phone/tablet on a trusted Wi-Fi network, explicitly set `HOST=0.0.0.0`
in `.env`, restart, and use the LAN URL printed by `run.py`. This beta shares one library/settings profile on
that server and has no account system. API key changes are accepted only from localhost.

### Check the Gemini setup first

```bat
python scripts\check_gemini.py
```

Lists the models your key can see, translates two sample sentences, and writes `scripts\check_tts.wav`
from a code-mixed Sinhala sentence. If a model name is reported MISSING, change it in `.env`.

## Configuration (`.env`)

See `.env.example` for every option. The important ones:

The Settings screen can save a Gemini key encrypted with Windows user-scoped DPAPI. It never returns the raw key.
Existing `GEMINI_API_KEY` environment configuration is supported until a UI-saved key overrides it. Removing a
saved key disables that environment fallback until another key is saved. Other operating systems can continue
to use an environment key. Non-secret settings are saved in SQLite; `.env` still controls bind address and data location.

| Key | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | | required for Gemini translation and TTS |
| `LLM_PROVIDER` | `gemini` | `gemini`, `ollama`, or `mock` (fake output, for UI work) |
| `GEMINI_MODEL` | `gemini-3.8-flash` | translation model |
| `GEMINI_UNDERSTAND_MODEL` | same as above | pass-1 model; a Flash-Lite model is enough |
| `GEMINI_THINKING_LEVEL` | `low` | dropped automatically if a model rejects it |
| `OLLAMA_MODEL` | `gemma3:12b` | any local model; Sinhala quality depends heavily on the model |
| `GEMINI_TTS_MODEL` | `gemini-3.8-flash-tts` | `GEMINI_TTS_API=generate_content` for older `*-preview-tts` models |
| `TTS_VOICE` | `Kore` | can also be changed per device in the reader settings |

## Cost

Every LLM call is logged with input, cached, output and thinking tokens, and priced with the paid-tier table in
`server/config.py` (`PRICES`). The book menu and the reader settings show the total; `GET /api/usage` breaks it
down. On the free tier the real cost is zero and the number is what it *would* cost.

What actually moves the bill (output tokens were ~63% of the cost of the first paper, because Sinhala output is long):

- **Batch mode** (choose it when uploading, or in the book's ⋯ menu): pass 1 and pass 2 go to the Gemini Batch API at
  half price. Results can take hours. Previous-passage context is English-only in this mode, because nothing is
  translated yet when the job is built. Not available on the free tier; the app falls back to normal mode.
- **Fewer calls**: short sections are merged so each call carries ~8,000 characters (papers went from 10 to 5 calls).
- **Cheaper pass 1**: summaries, glossary, word lookups and practice questions use `gemini-3.5-flash-lite`.
- **Prompt caching** does little here: implicit caching needs a 4,096-token identical prefix on gemini-3.8-flash
  and our fixed prefix is ~1,500 tokens; the rest of each prompt changes every call. Cached tokens are still
  logged, so if Gemini starts caching more you'll see it.

## English learning

- Tap a word in the reader (or paragraph inspector), then confirm Translate for a contextual meaning and examples
  in the selected language. Word selection supports Unicode scripts. Device pronunciation requires an installed voice.
- **මගේ වචන වලට දාන්න** saves it. **මගේ වචන** lists saved words, plays them as audio (word, Sinhala meaning,
  example), and runs a daily practice: four question types per word (meaning, fill the blank, correct usage,
  listening) with spaced repetition (right: 1, 3, then ~2.5x days; wrong: again in 10 minutes).
- Pronunciation uses browser voices when audio is enabled. Cloud audio with a word's meaning requires confirmation.

## How it works

```
PDF ─► parse ─► pass 1: understand ─► pass 2: translate ─► reader (React PWA)
```

1. **Parse** (`server/parser/layout_parser.py`): PyMuPDF 2's layout model classifies boxes (text, heading,
   picture, table, formula, caption, footnote, header/footer). On top of that the parser fixes two-column reading
   order, glues figure labels into the figure, merges side-by-side sub-figures, joins paragraphs split across
   columns/pages, drops running headers and footers, and marks the bibliography. Figures, equations and numeric
   tables are cropped from the page at 200 dpi, so they are pixel-identical to the original. Text-heavy tables
   are rebuilt as HTML and translated cell by cell.
2. **Understand**: the document is read in English in ~24k-character chunks. Each chunk gives a summary and
   glossary terms (`keep_en` / `translate` / `transliterate`). One more call writes a document brief.
3. **Translate**: sections run in parallel; inside a section, batches of ~6k characters run in order. Each call
   gets the brief, the glossary terms that occur in the batch, summaries of what came before, the last three
   translated passages, and the next two English passages. Automatic checks catch empty output, missing Sinhala,
   dropped numbers or citation markers, and suspiciously short output, then retry once. Your reading position's
   section is translated first, so you can start reading while the rest is still being translated.
4. **Reader**: every block has a stable `seq`. Position, notes, highlights and audio all key off it.

Data lives in `data/` (SQLite + per-document folder with the PDF, crops, page renders and audio).

## Development

```bat
cd web
npm install
npm run dev      :: UI on :5173, proxies /api to python run.py on :8000
npm run build    :: writes web/dist, which run.py serves
```

```bat
pip install pytest
pytest           :: parser + full pipeline (mock LLM) on sample\1706.03762v7.pdf, provider/TTS adapters with canned HTTP
python scripts\parse_preview.py sample\GEBen.pdf 200   :: see how a PDF gets split
```

Beta acceptance tests also cover confirmation gates, duplicate upload/lookup/audio actions, encrypted key storage,
LAN key restrictions, saved translation migration, source validation, exam answer hiding/deadlines and XP/timezones.
For browser verification with synthetic data and no external AI:

```bat
.venv\Scripts\python.exe scripts\beta_smoke_server.py --port 8765
```

This isolated demo stores its data in `output/beta-smoke`, never in your normal library. API keys are disabled
and its provider is mock. Open `http://127.0.0.1:8765` and use the normal reader/study UI.

## Known limits

- Scanned PDFs (no text layer) only show page images; there is no OCR step yet.
- Inline math inside paragraphs comes through as plain text (e.g. `dmodel`); display equations are images.
- Numeric tables are shown as the original image (their numbers stay exact); only the caption is translated.
- Parsing speed is about 0.3 s per page (GEB, 801 pages: ~4 minutes).
- Gemini and TTS calls have only been checked against the documented request/response format. Run
  `scripts\check_gemini.py` for a live check.
- Phone install as an app (PWA) needs HTTPS. Over plain `http://192.168…` the reader works in the browser but
  can't be installed.
- PyMuPDF is dual-licensed under AGPL/commercial terms. Public distribution is deferred; before releasing publicly,
  choose an AGPL-compliant distribution or appropriate commercial terms. See https://pymupdf.io/licensing.
