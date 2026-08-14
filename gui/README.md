# watermarks-remover — desktop app

A point-and-click front end for the `remove-ai-marks` scripts. No terminal, no
Python packages to install, and nothing leaves your computer.

Works on **Windows, macOS and Linux**.

---

## Start it

| Your system | What to do |
| --- | --- |
| **Windows** | Double-click **`WatermarksRemover.bat`** |
| **macOS** | Double-click **`watermarks-remover.command`** |
| **Linux** | `./watermarks-remover.command`, or `python3 gui/launch.py` |

The app opens in its own window if you have [pywebview](https://pywebview.flowrl.com/)
installed, and in your default browser otherwise. Both are the same app — the
page is served from your own machine on `127.0.0.1`.

On macOS and Linux the launcher needs its executable bit, which git only keeps
if it was committed that way:

```bash
git update-index --chmod=+x gui/watermarks-remover.command
```

**Requirements:** Python 3.10 or newer, and nothing else. If Windows says Python
is missing, install it from [python.org](https://www.python.org/downloads/) and
tick *“Add python.exe to PATH”* during setup.

Optional native window:

```bash
pip install pywebview
```

---

## What each screen does

### 01 · Files

Drag files in, or press **Browse…**. Every file is scanned as it arrives and
gets a verdict: *marks* or *clean*. Open one to see the findings, the exact
hidden characters it contains, and where they sit in the text.

**Clean this file** writes a stripped copy. Where it lands depends on *Options →
When cleaning, save*:

- **A cleaned copy next to the original** — `draft.md` → `draft.cleaned.md`
- **Over the original** — keeps `draft.md.bak` as a backup
- **Nothing — just let me download it** — the only option for dragged-in files,
  because a drop gives the app the file's contents but not its location

Handles PNG, JPEG, PDF, DOCX, ODT, SVG, HTML, Markdown and plain text. Batch
work is fine: **Clean all**, then **Download all** for a zip.

| Option | Effect |
| --- | --- |
| Treat file as | Overrides format detection, same as the CLI's `--as` |
| Flag look-alike letters | Reports Cyrillic/Greek letters posing as Latin ones |
| Also replace those letters | Rewrites them during a clean (`--aggressive-homoglyphs`) |
| Normalise text (NFKC) | Folds ﬁ, ①, full-width forms into plain equivalents |
| Keep camera metadata | Images: drop only AI/C2PA segments, keep EXIF |
| Score SynthID | Appears only when `REVERSE_SYNTHID_DIR` is configured |

#### Word and ODT documents

A `.docx`/`.odt` is a zip, and its prose lives in `word/document.xml` /
`content.xml`. Two consequences worth knowing:

- **`inspect_text.py` must not be pointed at one.** It reads the file as text,
  so it scans deflate-compressed bytes and reports whatever codepoints happen to
  fall out. The counts are noise: a document with nothing hidden in it can report
  a dozen "suspicious" characters, and the number changes with compression, not
  content. Use `inspect_file.py`, or this app.
- **`inspect_container` only reads metadata**, so hidden characters in the actual
  text were invisible to both the CLI and, until now, this app. The Files screen
  unzips the text parts and reports them under *Hidden characters inside the
  document text*, with the reveal view showing the surrounding sentence.

Cleaning still defaults to upstream behaviour — metadata only. *Word / ODT: also
strip invisible characters from the document text* turns on a text pass that
rewrites only the character data between tags, leaving all markup byte-exact, and
re-zips with the original entry order and compression.

No-break spaces get their own sub-option and stay put by default: in real
documents they are almost always deliberate typography (`Table 1`, `p = 0.05`,
`Fig. 3`) rather than a watermark, and converting them changes how the document
breaks across lines.

### 02 · Text

For everything you copied out of a chat window and never saved to a file. Paste
it, and **Reveal** replaces every invisible character with a labelled chip, in
place, so you can see exactly what came along:

```
Here⟨ZWSP⟩is a paragraph that looks perfectly normal.⟨WJ⟩
```

**Clean text** strips them and tells you the count. Then copy the result or save
it as `.txt`.

### 03 · Rewrite (Layer B)

Invisible characters are one kind of mark. Statistical watermarks live in the
word choice itself, so the only way out is rewriting the text — which replaces
your wording with the rewriting model's. The screen says so, and no tool can
certify the result passes a vendor's detector.

Five approaches (paraphrase, humanize, back-translate, structural, code) and
three ways to run them:

- **Just give me the prompt** — the default. Produces a prompt you can paste into
  any chat model. Nothing is sent anywhere.
- **Ollama on this machine** — local model, press **Test** to list what you have.
- **OpenAI-compatible endpoint** — for a local llama.cpp/vLLM server.

Non-local endpoints are refused unless you tick *Allow a non-local endpoint*,
which is labelled with what it means: your text leaves the machine. API keys
live in memory for the length of one request — never on disk, never in a command
line.

### 04 · Setup

What this machine can do right now. `exiftool` and `c2patool` are optional but
make cleaning meaningfully better (especially for PDFs); this screen tells you
whether they are present and gives you the exact install command for your OS.
Also covers SynthID scoring and the native file dialog.

### 05 · Guide

The project's own reference notes — ethics, mark classes, removal matrix, vendor
notes — rendered offline from `skills/remove-ai-marks/references/`.

---

## What maps to what

Every screen is a front end for the same scripts the CLI uses, called in-process:

| Screen | Script |
| --- | --- |
| Files → scan | `inspect_file.py` · `inspect_image.py` · `inspect_text.py` |
| Files → clean | `clean_file.py` · `clean_image.py` |
| Text | `inspect_text.py` · `clean_text.py` |
| Rewrite | `rewrite_text.py` |
| Setup → SynthID | `score_synthid.py` |

Markdown and HTML get the text scan too, since `clean_container` scrubs their
bodies — the report would otherwise hide characters the clean would remove.

---

## Windows notes

The skill scripts pass `preexec_fn` to `subprocess`, which is POSIX-only — on
Windows that made every `exiftool`/`c2patool` call raise, so the tools looked
broken even when installed. `server/compat.py` drops that argument on Windows
and hides the console window the child would otherwise flash. Nothing in
`skills/` is modified.

`setup_synthid.sh` is still a shell script; run it from Git Bash or WSL if you
want SynthID scoring.

---

## Privacy and safety

- The server binds to `127.0.0.1` only, on a random port.
- Every API call needs a session token generated at launch, so other pages open
  in your browser cannot drive it.
- The only files the server will hand out are the three in `gui/web/`, listed in
  a table built at startup; a request path is never joined onto a directory.
- Dragged-in files are copied to a temporary folder that is deleted when the app
  exits. Files opened with **Browse** are read where they are.
- No telemetry, no network access — except a rewrite backend you configure
  yourself.

---

## Options

```bash
python3 gui/launch.py --port 8731     # fixed port
python3 gui/launch.py --browser       # force the browser over the native window
python3 gui/launch.py --no-browser    # just print the URL
```

Environment variables the app respects: `WATERMARKS_SKILL_DIR`,
`WATERMARKS_MAX_INPUT_BYTES`, `REVERSE_SYNTHID_DIR`, and the
`WATERMARKS_REWRITE_*` family.
