# AI Lodge Song Recommender — Project Summary (for Claude Code)

## What this is

A music recommendation system that surfaces "hidden gems" — songs similar to
what a user already likes, but with lower mainstream popularity — built on
**audio embeddings** rather than Spotify's audio-features API (which is
largely inaccessible for new developer apps as of late 2024).

Built **genre-by-genre**, piloting on **pop** first. Validate the full
pipeline on pop before generalizing to other genres.

## Why audio embeddings, not Spotify's audio-features endpoint

Spotify deprecated `/v1/audio-features` and `/v1/audio-analysis` for new
apps on Nov 27, 2024 (403 for anyone without a pre-existing quota
extension). 30-second preview URLs were also removed from Spotify's
multi-get responses. Endpoints that still work: `search`, track lookup,
artist lookup, popularity score, follower count.

**Fallback plan:** compute embeddings ourselves from raw audio, sourced via
the **Deezer API** (still serves 30s previews without Spotify's
restrictions). No Spotify-side audio access is needed anywhere in the
pipeline — only Spotify metadata (popularity, followers, search).

## Core design decisions (already made — don't relitigate without reason)

- **Similarity computed independently per input song**, not by averaging
  multiple input songs into one blended vector. If a user gives 1–3 songs,
  find each song's nearest neighbors separately; display grouped by input
  song. A merged/ranked cross-song view is a possible v2 addition, not core.
- **Hidden-gem logic is tiered**: strict popularity/similarity threshold
  first; if that returns nothing, auto-relax (widen the similarity radius,
  loosen the popularity cutoff) rather than returning empty. Always display
  both a **match %** (rescaled cosine similarity) and an **obscurity %**
  per recommendation — never a binary "hidden gem: yes/no."
- **Genre labels come from an audio-based classifier, not Spotify's
  artist-level tags.** Spotify genre data lives at the artist level and is
  messy/inconsistent per track. Plan: run Essentia's pretrained
  (Discogs-based) genre classifier on the same audio pulled for embeddings,
  bucket its output into ~10–15 broad top-level genres, and assign 1 genre
  per song (2 only if a second genre clears a confidence-margin threshold
  near the top one).
- **Embedding model**: start with Essentia or OpenL3 (lighter, faster to
  get working) rather than CLAP or MERT initially. Do not swap the
  embedding model mid-project — that invalidates earlier similarity
  results and sanity checks.
- **Demo/interface**: precompute and cache embeddings + neighbor lists for
  the full pilot catalog ahead of time; the live demo reads from cache
  rather than hitting APIs or running inference live, to avoid network
  flakiness in front of an audience.
- **Baseline for evaluation**: since the pilot is single-genre (pop only),
  the baseline is "popularity-sorted-within-pop," not "same genre" (that
  distinction is meaningless when everything tested is already pop).

## Mood input — scoped as a later addition (Milestone 8, not core path)

Only start after Milestone 4's sanity check passes. Two phases:
- **Phase A (do first)**: Essentia's pretrained mood classifiers
  (happy/sad, aggressive/relaxed, acoustic/electronic, party-suitable/not)
  run on the same audio, stored as tags alongside genre. Cheap, reuses the
  genre-classifier pattern already planned for Milestone 7.
- **Phase B (stretch goal)**: CLAP (joint text-audio embedding model) to
  support free-text mood queries ("introspective," "mellow") that don't
  fit a fixed label set. Heavier lift — do not use this to replace the
  Milestone 2 embedding model; it's an additive, separate similarity
  signal for mood only.

## Known risks / open items

| Risk | Status |
|---|---|
| Cross-source match rate (Spotify metadata ↔ Deezer audio ↔ later, Genius lyrics) | Unmeasured — check during Milestone 1, flag if usable pool shrinks a lot |
| Cross-genre false positives (fast/major-key songs from different genres scoring falsely "similar") | Expected/deferred — give best-guess for now, flag in Milestone 4 sanity check, refine later |
| Recency confound (new releases look like "hidden gems" just because they haven't accumulated streams yet) | Not yet addressed — consider a release-date filter or at least reporting the fraction of gems that are recent releases |
| `yt-dlp`/YouTube ToS exposure | Only relevant if Deezer previews prove insufficient; keep any fallback audio internal to the pipeline, never redistributed |

## Tech stack

- Python, PyTorch (GPU — local GPU available)
- Essentia (embeddings + genre + mood models) and/or OpenL3
- `librosa` for basic audio utilities
- `spotipy` for Spotify metadata (search, track, artist, popularity, followers — NOT audio-features)
- `requests` against the Deezer API for 30s preview audio
- `pandas` / `pyarrow` (Parquet) or SQLite for local storage — no real DB needed yet
- Streamlit (or a CLI) for the demo interface, later

## Milestone plan

**Milestone 0 — Environment & Scope** *(in progress)*
- [x] Confirm pilot genre = pop
- [ ] Set up Python env: GPU PyTorch, Essentia/OpenL3, Deezer client (`requirements.txt` provided)
- [ ] Set up local storage (SQLite or Parquet)
- [ ] Confirm pilot catalog size target: 2,000–5,000 tracks
- [ ] Validate Spotify basic endpoints work with your app credentials — use `validate_spotify_access.py` (provided); confirm `search`/track/artist lookups succeed and `audio_features` fails with 403 as expected

**Milestone 1 — Build the Pop Pilot Catalog**
- Source genre-tagged pop candidates (Kaggle dataset or Spotify `search`)
- Pull popularity/follower data via Spotify
- Match each track to a Deezer preview, download the 30s clip
- Log the match rate (target ≥ ~70–80% recovered)
- Output: ~2,000–5,000 pop tracks with metadata + popularity + audio clip

**Milestone 2 — Extract Embeddings**
- Run Essentia or OpenL3 over every clip on GPU
- Store vectors + track IDs (`.npy` + index, or a simple table)
- Sanity check: known-similar songs should score close; known-different songs should score far apart
- Do not proceed until sanity checks pass

**Milestone 3 — Core Similarity + Hidden-Gem Logic**
- Independent per-song nearest-neighbor lookup
- Grouped display ("Similar to Song A," "Similar to Song B")
- Tiered hidden-gem logic with match % and obscurity % surfaced
- End-to-end test with 1–3 real input songs

**Milestone 4 — Self Sanity-Check**
- Run 5–10 personally-known songs through the full pipeline
- Log anything that looks wrong; flag for later, don't block on fixing now

**Milestone 5 — Minimal Demo Interface + Caching**
- Simple CLI or Streamlit interface
- Precompute + cache embeddings and neighbor lists for the full pilot catalog
- Curate 15–20 pre-cached "known-good" demo input songs
- Decide fallback behavior for songs outside the cache

**Milestone 6 — Small User Study (Pop Only)**
- 5–10 raters, 3 favorite pop songs each
- Baseline = popularity-sorted-within-pop
- Rate relevance and discovery value; plot system vs. baseline
- Confirm the popularity gap holds (gems really are less popular, still similar)

**Milestone 7 — Generalize Beyond Pop**
- Build the genre classifier (Essentia Discogs model → ~10–15 buckets)
- Set the confidence-margin rule for a second genre label
- Run classifier + full pipeline on a larger, multi-genre catalog
- Re-run original pop sanity-check songs through the generalized pipeline; confirm no regression

**Milestone 8 — Mood Input** *(after Milestone 4, scoped addition — see above)*
- Phase A: Essentia mood classifier tags
- Phase B (stretch): CLAP free-text mood matching

## Reference docs from this project

- Full tracked checklist (living doc, check items off as completed): https://claude.ai/artifact/Ge6PzmrcYw7ovUkMBHkT57
- `requirements.txt` and `validate_spotify_access.py` were generated in the prior chat session — recreate or re-request if not already saved locally.

## Immediate next step

Finish Milestone 0: create the venv, install dependencies, register a
Spotify Developer app (Client Credentials flow — no OAuth login needed for
search/track/artist/popularity data), and run the validation script to
confirm basic Spotify access works and `audio-features` fails as expected.
Then move to Milestone 1 (building the pop pilot catalog).
