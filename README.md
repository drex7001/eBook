# කොළ: PDF → spoken Sinhala reader

Personal tool. Give it a PDF (book or research paper); it splits the PDF into blocks, translates them into
spoken, code-mixed Sinhala, and serves a phone-first reader. Tap any paragraph to see the English original
and the original page region. Notes and highlights, resume-where-you-stopped, and paragraph-by-paragraph audio
(Gemini TTS) are built in.

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

For the phone later: `run.py` also prints a `http://192.168.x.x:8000` URL; open it on the same Wi-Fi and allow
Python through Windows Firewall (Private networks) when it asks.

### Check the Gemini setup first

```bat
python scripts\check_gemini.py
```

Lists the models your key can see, translates two sample sentences, and writes `scripts\check_tts.wav`
from a code-mixed Sinhala sentence. If a model name is reported MISSING, change it in `.env`.

## Configuration (`.env`)

See `.env.example` for every option. The important ones:

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

- Tap an English word in the reader (or in the original text of a paragraph) for its meaning in Sinhala and
  English, what it means in that sentence, pronunciation, and two everyday example sentences.
- **මගේ වචන වලට දාන්න** saves it. **මගේ වචන** lists saved words, plays them as audio (word, Sinhala meaning,
  example), and runs a daily practice: four question types per word (meaning, fill the blank, correct usage,
  listening) with spaced repetition (right: 1, 3, then ~2.5x days; wrong: again in 10 minutes).
- English pronunciation uses the browser's own voices (free). The "with Sinhala meaning" audio uses Gemini TTS.

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

## Known limits

- Scanned PDFs (no text layer) only show page images; there is no OCR step yet.
- Inline math inside paragraphs comes through as plain text (e.g. `dmodel`); display equations are images.
- Numeric tables are shown as the original image (their numbers stay exact); only the caption is translated.
- Parsing speed is about 0.3 s per page (GEB, 801 pages: ~4 minutes).
- Gemini and TTS calls have only been checked against the documented request/response format. Run
  `scripts\check_gemini.py` for a live check.
- Phone install as an app (PWA) needs HTTPS. Over plain `http://192.168…` the reader works in the browser but
  can't be installed.
- PyMuPDF is AGPL-3.0. That's fine for personal use; a public service would need a license or another parser.
