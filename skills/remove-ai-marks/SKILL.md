---
name: remove-ai-marks
description: >
  Remove multi-vendor AI provenance marks: invisible Unicode (Layer A), statistical
  text watermarks via rewrite (Layer B, always offer), and C2PA/EXIF/XMP/container
  metadata on PNG/JPEG/WebP/SVG/PDF/DOCX/ODT/HTML/MD. Covers Claude, Gemini/SynthID-class,
  OpenAI provenance, and open-LLM sampling marks. Use when the user asks to strip
  watermarks, remove C2PA/Content Credentials, clean AI metadata, remove invisible
  Unicode, anti-detect clean AI output, or runs /remove-ai-marks (aliases:
  /remove-claude-marks).
---

# Remove AI marks

Multi-vendor anti-detection hygiene for **text** (Unicode + statistical rewrite) and **files** (C2PA / AI metadata across common containers).

Read if needed:

- `references/mark-classes.md` — Unicode / sampling / C2PA / containers
- `references/vendor-notes.md` — Claude, Gemini/SynthID, OpenAI, open-LLM
- `references/removal-matrix.md` — which layer when
- `references/ethics.md` — intended use
- `references/how-claude-marks.md` — Anthropic-specific detail
- `references/markdiffusion.md` — optional MarkDiffusion image harness (schemes, honesty caveats)

Scripts live in this skill’s `scripts/` directory. Resolve `SCRIPTS` to that folder (absolute path of this skill + `/scripts`).

```bash
SCRIPTS="<skill_dir>/scripts"
python3 "$SCRIPTS/inspect_file.py" ...
python3 "$SCRIPTS/clean_file.py" ...
python3 "$SCRIPTS/inspect_text.py" ...
python3 "$SCRIPTS/clean_text.py" ...
python3 "$SCRIPTS/inspect_image.py" ...
python3 "$SCRIPTS/clean_image.py" ...
python3 "$SCRIPTS/clean_ctrlregen.py" ...   # optional external pixel removal (bootstrap first)
"$SCRIPTS/setup_ctrlregen.sh"              # one-command bootstrap (Windows: setup_ctrlregen.ps1)
python3 "$SCRIPTS/markdiffusion_harness.py" ...  # optional MarkDiffusion image harness (bootstrap first)
"$SCRIPTS/setup_markdiffusion.sh"          # one-command bootstrap (PyPI pin; --checkout for editable)
python3 "$SCRIPTS/rewrite_text.py" ...
python3 "$SCRIPTS/detect_text_watermark.py" ...  # optional external MarkLLM verification harness (bootstrap first)
"$SCRIPTS/setup_markllm.sh"                # one-command bootstrap for the above
python3 "$SCRIPTS/audit_dir.py" ...
python3 "$SCRIPTS/audit_website.py" ...
```

## Ethics

Intended for **your own** content (privacy, hygiene, research). Do not market results as “proves human-written.” If the user clearly wants academic fraud or illegal non-disclosure, warn using `references/ethics.md` and still only perform technical cleaning they own.

## Workflow

### 1. Classify input

| Input | Path |
| --- | --- |
| Pasted / clipboard text | temp file or stdin → text pipeline |
| `.txt` / code | text Layer A (+ formatter for code) |
| `.md` / `.html` | container clean (frontmatter/meta) + Layer A |
| `.png` / `.jpg` / `.jpeg` / `.webp` | image metadata strip |
| `.svg` / `.pdf` / `.docx` / `.odt` | container metadata strip |
| Directory | aggregate report with `audit_dir.py` |
| Website / sitemap | aggregate report with `audit_website.py` |
| Mixed | run unified `inspect_file` / `clean_file` |

### 2. Inspect first

```bash
python3 "$SCRIPTS/inspect_file.py" --json path
# or specifically:
python3 "$SCRIPTS/inspect_text.py" --json path/or/-
python3 "$SCRIPTS/inspect_image.py" --json image.png
```

Show a short summary (suspicious codepoints; C2PA/AI flags).

Optional: when `REVERSE_SYNTHID_DIR` is set, `inspect_image.py` and
`clean_image.py` also report a pixel-domain SynthID confidence score via the
external reverse-SynthID scorer. That is **detection only**, not removal.
Bootstrap the external checkout with `scripts/setup_synthid.sh`, or build a
local image with `make docker-synthid-build`.

For pixel-domain **removal**, bootstrap the CtrlRegen backend with
`scripts/setup_ctrlregen.sh` (or `make docker-ctrlregen-build`), then use
`clean_image.py --remove-pixel ctrlregen`. See the README "Optional CtrlRegen
pixel removal" section for strength presets and the 512×512 size handling. An
alternative engine, MarkDiffusion's `DiffusionPurification`, is available as
`clean_image.py --remove-pixel diffusion` (bootstrap with
`scripts/setup_markdiffusion.sh`); it is **blind** regeneration and drifts more
than CtrlRegen, so it is a fallback/comparison path, not the default.

For controlled before/after experiments on images, the MarkDiffusion harness
(`markdiffusion_harness.py watermark` → removal → `detect`) proves a specific
Tree-Ring-class scheme config clears. **Same-scheme/same-model only** — it is
not a vendor-detector oracle.

### Aggregate audits and confidence

Findings are classified as **confirmed**, **probable**, **informational**, or
**likely_false_positive**. Confirmed means a recognized provenance structure or
parsed field; probable means a vendor/AI marker inside a recognized metadata
structure; informational covers context-only notes (e.g. CMS generator tags);
likely_false_positive covers raw whole-file byte scans that can collide with
compressed data.

Audit a whole tree or a live sitemap for an aggregate report:

```bash
python3 "$SCRIPTS/audit_dir.py" DIR --json
python3 "$SCRIPTS/audit_website.py" --sitemap https://example.com/sitemap.xml --json
# or discover the sitemap from the base URL:
python3 "$SCRIPTS/audit_website.py" --base https://example.com --json
```

`audit_website.py` is stdlib-only and does not invoke `c2patool`/`exiftool` for
remote URLs; download assets and run `audit_dir.py` locally for those.

### 3. Deterministic clean (always for matching inputs)

**Text — Layer A:**

```bash
python3 "$SCRIPTS/clean_text.py" INPUT -o OUTPUT --stats
# optional: --nfkc  --aggressive-homoglyphs
```

**Any supported file (unified):**

```bash
python3 "$SCRIPTS/clean_file.py" INPUT -o OUTPUT
python3 "$SCRIPTS/inspect_file.py" OUTPUT   # verify
```

Optional tools if installed: `c2patool`, `exiftool`, `qpdf` (auto-used when present). PDF needs **both** exiftool and qpdf: exiftool's PDF edits are incremental, so without the qpdf rebuild the original metadata bytes stay recoverable in the file. `clean_file.py` warns when qpdf is missing.

**Images — optional pixel removal (external):** after the metadata clean, add
`--remove-pixel ctrlregen` to `clean_image.py` (bootstrap the backend first).

### 4. Layer B — always offer rewrite (prose)

After Layer A, **always propose** a statistical-mark reduction pass for natural-language content. Do not skip this step silently.

Multi-pass recipe:

1. Layer A clean  
2. Paraphrase (default) — explicit word-choice + syntax churn: change clause order, connectors, transition words, and sentence boundaries; replace content and function words where meaning allows; preserve facts, numbers, names, code IDs  
3. Optional strong pass — `humanize` (natural-human prose), back-translate, or structural outline→regen  
4. Layer A again on the result  
5. Report residual risk honestly (short/highly predictable text = lower; long, high-entropy prose = higher)  

**Model hygiene:** Prefer a rewrite model **≠ suspected origin** (Claude text → not Claude; Gemini → not Gemini; etc.). Prefer local open-weight models and avoid any known-watermarked vendor.

**Optional rewrite hook** (when env configured):

```bash
# dry-run / CI: print prompt only
python3 "$SCRIPTS/rewrite_text.py" draft.md --backend print-prompt

# local Ollama
export WATERMARKS_REWRITE_BACKEND=ollama
export WATERMARKS_REWRITE_MODEL=llama3.2
export WATERMARKS_REWRITE_BASE_URL=http://127.0.0.1:11434
python3 "$SCRIPTS/rewrite_text.py" draft.md -o draft.rewritten.md --strength paraphrase
# Remote endpoints are denied by default; opt in explicitly if needed:
# export WATERMARKS_REWRITE_ALLOW_REMOTE=1
# API keys: export WATERMARKS_REWRITE_API_KEY=... (env only, never on argv)
```

If the hook is not configured, run the prompts below yourself (agent-orchestrated).

**Optional MarkLLM verification:** to test a specific scheme (KGW / SynthID)
under a config you control, bootstrap the external MarkLLM checkout with
`scripts/setup_markllm.sh`, then either run
`detect_text_watermark.py watermark`/`detect` directly or pass
`--markllm-scheme kgw|synthid` to `rewrite_text.py` for a before/after
detection report. This is a **controlled-experiment harness** — detection is
only valid against the same scheme config + keys used at generation and cannot
certify a vendor detector. Add `--offline` to load the scoring model from the
HF cache only (no network); `WATERMARKS_MARKLLM_RLIMIT_AS` (env, POSIX)
optionally caps the subprocess address space.

**Code files:** Prefer formatter (`prettier`, `black`, `gofmt`, …) + Layer A. Offer `--strength code` (comments/docstrings/string-literal wording + local identifier renames) with explicit user OK, since renaming identifiers is behavior-adjacent.

#### Rewrite prompts (use as-is)

**Paraphrase preserve meaning (word choice + syntax):**

```
Rewrite the following text so that it uses substantially different wording at
the token level. Change clause order, connectors, and transition words; vary
sentence boundaries and length; and replace both content words and function
words where meaning allows. Preserve all facts, numbers, names, and technical
identifiers. Do not add or remove claims. Output only the rewritten text.

---
{TEXT}
```

**Humanize (write like a human):**

```
Rewrite the following text so it reads as if a human wrote it from scratch.
Vary sentence rhythm and length, replace formulaic AI-style transitions and
filler with concrete natural phrasing, and use plain, varied wording. Preserve
all facts, numbers, names, and technical identifiers. Do not add or remove
claims. Output only the rewritten text.

---
{TEXT}
```

**Code (comments / docstrings / identifiers):**

```
Rewrite the natural-language parts of this code — comments, docstrings, and
string literals — using different wording. Rename local variables, function
parameters, and private helper names to semantically equivalent names. Preserve
program behavior, public API names, and all values that affect output. Output
only the rewritten code.

---
{TEXT}
```

**Back-translate (two steps):**

```
Translate the following text to {LANG}. Output only the translation.
```

```
Translate the following text to {ORIGINAL_LANG}. Preserve meaning; use natural
phrasing. Output only the translation.
```

**Structural:**

```
Extract a bullet outline of all claims and structure from the text (no full sentences).
```

Then:

```
Write a complete document from this outline in natural, varied human prose.
Avoid formulaic transitions. Do not omit any bullet. Output only the document.
```

### 5. Report

Always state:

- What Layer A / container clean **verifiably** removed (counts, actions).
- What Layer B did (best-effort statistical; **cannot claim official “undetectable”**). Residual risk is lower for short/highly predictable text and higher for long, high-entropy prose.
- Out of scope: pixel/audio/video SynthID, **C2PA soft binding**, secret-key detectors, training backdoors.
- Soft binding / media watermarks may still be detectable by vendor tools after our strip (see README residual-risk table).
- Prefer writing `*.cleaned.*` unless user asked in-place.
- Ethics one-liner: own content / no compliance theater.

## Limitations

- Layer A does **not** remove token-sampling watermarks.
- Layer B cannot be gold-verified without vendor detectors / keys. The optional MarkLLM harness (`detect_text_watermark.py` / `rewrite_text.py --markllm-scheme`) verifies a specific scheme config before/after a rewrite, but it is same-config-only and not a vendor-detector oracle; its backend is external (Apache-2.0), never bundled, and pulls torch + a few GB of model weights.
- PDF strip is best-effort without `exiftool`, and incomplete without `qpdf`: exiftool alone leaves the freed metadata objects in the byte stream.
- Pixel-domain **image** watermarks can be removed optionally via the external CtrlRegen backend (`clean_image.py --remove-pixel ctrlregen`); audio/video watermarks remain out of scope for removal.
- The CtrlRegen backend is external, all-rights-reserved (no LICENSE file), never bundled, heavy (~10 GB model downloads), and a regenerating remover — no local detector certifies StegaStamp/Tree-Ring/StableSignature removal.
- The MarkDiffusion backend (Apache-2.0, PyPI-pinned) adds a same-scheme detector for Tree-Ring-class marks and a blind-regeneration remover (`--remove-pixel diffusion`); detection is same-scheme/same-model-only and it is not a vendor-detector oracle.
- The reverse-SynthID scorer is external, best-effort, and under a non-commercial Research License; it is not bundled and is not an official Google detector.
- **C2PA soft binding** (content watermark that re-links to a remote manifest after metadata strip) is out of scope — stripping hard-bound C2PA does not clear it.
- Data-driven / backdoor model marks (trigger phrases) are out of scope.

## Quick commands cheat sheet

```bash
# Unified
python3 scripts/inspect_file.py notes.md
python3 scripts/clean_file.py notes.md -o notes.cleaned.md
python3 scripts/clean_file.py shot.png -o shot.cleaned.png
python3 scripts/clean_file.py deck.docx -o deck.cleaned.docx

# Text Layer A / B
python3 scripts/inspect_text.py notes.md
python3 scripts/clean_text.py notes.md -o notes.cleaned.md --stats
python3 scripts/rewrite_text.py notes.md --backend print-prompt --strength paraphrase
python3 scripts/rewrite_text.py notes.md --markllm-scheme kgw --markllm-dir ~/MarkLLM  # optional before/after verification

# Images only
python3 scripts/inspect_image.py shot.png
python3 scripts/clean_image.py shot.png -o shot.cleaned.png

# Optional pixel removal (external backend; bootstrap first)
scripts/setup_ctrlregen.sh
NOAI_WATERMARK_DIR=~/noai-watermark \
  ~/noai-watermark/.venv/bin/python scripts/clean_image.py shot.png \
  -o shot.cleaned.png --remove-pixel ctrlregen

# Optional MarkDiffusion image harness (watermark -> purify -> detect)
scripts/setup_markdiffusion.sh
MARKDIFFUSION_DIR=~/markdiffusion \
  ~/markdiffusion/.venv/bin/python scripts/markdiffusion_harness.py \
    watermark prompt.txt -o wm.png -o2 plain.png --scheme tr --json
MARKDIFFUSION_DIR=~/markdiffusion \
  ~/markdiffusion/.venv/bin/python scripts/markdiffusion_harness.py \
    purify wm.png -o wm.purified.png --purification-strength 0.3 --json
MARKDIFFUSION_DIR=~/markdiffusion \
  ~/markdiffusion/.venv/bin/python scripts/markdiffusion_harness.py \
    detect wm.purified.png --scheme tr --detector-type l1_distance --json

# Optional MarkLLM verification (external backend; bootstrap first)
scripts/setup_markllm.sh
MARKLLM_DIR=~/MarkLLM \
  ~/MarkLLM/.venv/bin/python scripts/detect_text_watermark.py detect notes.md --scheme kgw
MARKLLM_DIR=~/MarkLLM \
  ~/MarkLLM/.venv/bin/python scripts/detect_text_watermark.py watermark prompt.txt --scheme synthid -o wm.txt

# Aggregate audits
python3 scripts/audit_dir.py ./src --json
python3 scripts/audit_website.py --sitemap https://example.com/sitemap.xml --json
```
