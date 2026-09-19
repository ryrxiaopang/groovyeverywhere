# Project Proposal: Hidden Gems — Discovering Similar Underrated Songs and Artists

## 1. Overview

This project builds a music recommendation system that takes songs a user already likes as input and surfaces "hidden gems" — songs and artists that are musically/emotionally similar but have low mainstream popularity (low streams/followers), helping users discover music they'd likely enjoy but haven't encountered.

A second mode extends this further: rather than only asking *which* songs a user likes, the system asks *what* they like about them (lyrics/theme, beat/instrumentation, or overall mood), separates similarity into these two independent dimensions (lyrical/thematic vs. audio/vibe), and can deliberately recommend "cross" matches — songs with similar lyrical themes but a contrasting sonic vibe — to test whether users enjoy discovery along an axis they didn't explicitly ask for.

## 2. Motivation

Most mainstream recommenders (Spotify's own included) are partly driven by popularity signals, which tends to surface songs users likely already know. This project isolates *content similarity* (sound and mood) from *popularity*, deliberately filtering toward the underrated end, to test whether a purely feature-based approach can find genuinely useful, non-obvious recommendations — and to produce something people would actually enjoy using.

## 3. Research Questions

- Can audio features and/or genre/embedding data reliably capture "vibe similarity" between songs, independent of popularity?
- How should "hidden gem" be defined and thresholded (relative to genre/era, not just an absolute popularity cutoff)?
- Does a feature-based similarity approach surface meaningfully different (and better-received) recommendations than a naive "same genre" or "same artist's related artists" baseline?
- Do "sound neighborhoods" (clusters of musically similar songs) reveal any interesting structure — e.g., genre-blurring clusters, underrated pockets within popular genres?
- Can lyrical/thematic similarity be meaningfully separated from audio/vibe similarity, so that a song can be "close" on one dimension and "far" on the other?
- When users are shown hidden gems that share their stated reason for liking a song (e.g., similar lyrics) but *contrast* on a dimension they didn't ask about (e.g., a very different mood/tempo), do they still rate the recommendation positively — i.e., does explicit reasoning about *why* someone likes a song reveal preferences a pure similarity search would miss?

## 4. Data Sources

**⚠️ API access risk (validate in Week 1):** Spotify deprecated its Audio Features API for new developer apps on November 27, 2024. Any app created after that date gets a 403 on `/v1/audio-features` and `/v1/audio-analysis`, and 30-second preview URLs were also removed from multi-get responses; only apps with a pre-existing quota extension keep access. Basic metadata endpoints (track/artist lookup, search, popularity, follower counts) are unaffected. This means the first row of the table below — the core similarity feature set — cannot be assumed available and needs a fallback plan (see 5b).

| Data | Source | Use |
|---|---|---|
| Audio features per track | Spotify Web API **(likely blocked for new apps — see risk note above; fallback: ReccoBeats, self-hosted Essentia, or audio embeddings, detailed in 5b)** | Danceability, energy, valence, tempo, acousticness, instrumentalness, speechiness, loudness — the core similarity features |
| Popularity/follower data | Spotify Web API (unaffected by the deprecation — standard track/artist endpoints still return this) | Track popularity score, artist follower count — used to define "hidden gem" status |
| Genre/tag metadata | Spotify API + supplementary datasets (e.g., Every Noise at Once genre mappings) | Baseline comparison ("same genre" recommender) and cluster labeling |
| Large candidate pool | A broad Spotify catalog sample (e.g., via curated large playlists or an existing Kaggle Spotify tracks dataset with 100k+ songs) | Needed so there's a wide enough pool to actually contain "hidden gems" |
| Lyrics per track | Genius API or a pre-built Kaggle lyrics dataset (matched to your catalog sample by title/artist) | Required for the lyrical-similarity dimension of the "what do you like about it" feature — this is a new dependency not needed by the base recommender |
| 15–30s audio clips per track (new — only needed if using embeddings) | Deezer API (still serves 30s previews without Spotify's new restrictions), or `yt-dlp` against YouTube for short clips, or a pre-embedded dataset (e.g., MTG-Jamendo, FMA) that skips raw-audio fetching entirely | Required input for computing audio embeddings (see 5b); not needed if relying solely on ReccoBeats/Essentia-style scalar features |

## 5. Methodology

- **Similarity engine:** represent each song as a feature vector (audio features, possibly genre one-hot or embedding); compute similarity via cosine similarity, or reduce dimensionality first with PCA to see which combinations of features actually drive similarity.
- **"Hidden gem" definition:** relative popularity threshold *within* a similar-sound neighborhood (e.g., bottom 20% popularity among the top-50 most similar songs) rather than an absolute cutoff — avoids simply recommending obscure songs from unrelated genres.
- **Recommendation pipeline:** user inputs 1–3 songs they like → system finds nearest neighbors in feature space → filters/ranks by the hidden-gem criterion → returns a ranked list with a similarity score and popularity contrast (e.g., "92% similar, 1/10th the streams").
- **Clustering layer (adds analytical depth):** run k-means or hierarchical clustering over the full catalog sample to define "sound neighborhoods," and use these to explain *why* a recommendation was chosen, not just present a black-box ranked list.
- **Baseline comparison:** build a simple "same genre, sorted by similarity" or "Spotify related-artists" baseline to compare against — this gives you something concrete to benchmark your approach against, rather than presenting your system's output in isolation.

### 5a. "What Do You Like About It" Feature (Lyrics vs. Beat vs. Vibe)

- **User input:** after the user names a song they like, ask them to indicate what draws them to it — lyrics/theme, beat/instrumentation, or overall mood/vibe (a simple multiple-choice or weighted-slider input).
- **Two independent similarity spaces:**
  - **Audio/vibe similarity:** the existing feature-vector approach (danceability, energy, valence, tempo, etc.).
  - **Lyrical/thematic similarity:** represent each song's lyrics as embeddings (e.g., sentence-transformer embeddings, or a simpler TF-IDF/topic-model vector reused from the earlier lyrics-analysis idea) and compute similarity in that space independently of audio features.
- **Recommendation modes:**
  - **Matched mode** (baseline behavior): recommend songs similar on the dimension the user said they care about (e.g., they like the lyrics → find lyrically similar hidden gems).
  - **Cross/contrast mode** (the new feature): recommend songs that are lyrically similar but *audio-contrasting* (e.g., similar breakup narrative, but one is a slow ballad and the other is upbeat) — or the reverse (similar vibe, different lyrical theme) — explicitly surfaced as "songs with the theme you liked, in a different mood."
- **Presentation:** each cross-mode recommendation should show *both* similarity scores (lyrical similarity % and audio-feature distance) so the contrast is visible and explainable, not just asserted.

### 5b. Audio Embeddings as an Alternative/Complement to Spotify's Audio Features

Given the API risk noted in section 4, this project should not assume Spotify's 8–10 scalar audio features (danceability, energy, valence, etc.) will be reachable. Audio embeddings are the primary fallback, and they also directly address a limitation the original plan already flagged (features "may miss vibe").

**What an embedding is:** a dense vector (typically 128–1024 dimensions) produced by a neural network trained on raw audio — usually via a spectrogram input — where musical/perceptual similarity corresponds to closeness (cosine or Euclidean distance) in the vector space. Unlike Spotify's named, human-interpretable features, embedding dimensions have no individual meaning; the model learned the representation from data rather than from hand-picked musicological definitions.

**What embeddings capture beyond BPM/tempo:**
- **Timbre and instrumentation** — actual sonic texture (distorted vs. clean guitar, breathy vs. belted vocals, presence of specific instruments) without manual tagging
- **Production style/era** — compressed/loud modern mastering vs. dynamic older recordings, lo-fi vs. polished
- **Harmonic content** — chord complexity, key, major/minor "feel," harmonic tension and resolution
- **Rhythmic feel beyond raw BPM** — swing vs. straight, syncopation, groove density (two tracks can share a BPM and feel completely different)
- **Dynamics/energy contour** — how intensity builds and drops across a track, not just an averaged score
- **Vocal characteristics** — presence/absence, texture, singing vs. rapping vs. instrumental
- **Fine-grained "vibe"** — exactly the gap the project's own limitations section (9) already identifies as missing from Spotify's scalar features

**Candidate models:** OpenL3 and Essentia's embedding models are the most practical for a class-project timeline (lighter weight, well-documented Python interfaces); CLAP or MERT are viable if more compute/time is available and would let similarity be computed directly in a shared audio-text space.

**Trade-off vs. Spotify's features (decide early, ideally by end of Week 1):**
- *Pro:* captures texture/vibe the scalar features miss; no dependency on Spotify API access at all — only needs raw audio
- *Con:* not interpretable — loses the "80% due to high danceability" explanation the clustering/interpretability goal in section 5 relies on; needs actual audio (30s clips), which is its own sourcing problem (see 4); heavier compute and an added model/checkpoint choice to justify in the report
- *Recommended approach given the timeline:* use embeddings as the primary similarity signal (since they're not gated by Spotify access risk), but keep a small set of interpretable scalar features — either from ReccoBeats/Essentia or basic derived stats (tempo via `librosa`, spectral energy) — purely for the "why was this picked" explanation layer, so the clustering/interpretability deliverable in section 7 isn't lost.

## 6. Evaluation Plan (the hardest and most important part of this project)

This project doesn't have a single obvious ground-truth label, so evaluation has to be built deliberately:

- **Held-out "known similar" test:** for users/classmates who report liking a set of songs, hold one out and check whether it appears in the system's top-N recommendations generated from the rest — a way to sanity-check that "similar" actually holds up.
- **Comparative test:** for the same input songs, show recommendations from your system vs. the naive baseline (blind, unlabeled) and have a few classmates rate which set feels more relevant and/or more "new to me."
- **Small user study:** 5–10 people, each gives 3 favorite songs, rates the resulting hidden-gem list on relevance (does it match the vibe?) and discovery value (did they know it already?). This is a qualitative but very presentation-friendly result — plotting relevance vs. discovery for your system vs. baseline is a strong final chart.
- **Quantitative sanity check:** confirm your "hidden gems" really are less popular (verify the popularity gap) while still scoring high on similarity — a two-metric scatter plot (similarity vs. popularity) for recommended songs makes a clean visual.
- **Matched vs. cross-mode comparison (new):** for the same user and input song, show both a matched-mode recommendation and a cross-mode (contrasting) recommendation, and ask users to rate each independently on relevance and discovery value. This directly tests your core new research question — whether users respond well to recommendations that deliberately break the dimension they didn't ask about — and gives you a clean paired comparison (matched-mode rating vs. cross-mode rating per participant) to plot and discuss.

## 7. Deliverables

- Cleaned catalog dataset with audio features, genre tags, and popularity metrics
- Similarity/clustering pipeline with visualized "sound neighborhoods" (e.g., a 2D projection via PCA/t-SNE colored by genre)
- Working recommender (script or simple interactive notebook/app) that takes song input and returns ranked hidden-gem output
- Lyrical-similarity pipeline (embeddings + comparison logic) and a working matched-mode / cross-mode recommendation toggle
- Baseline comparison and user-study results, including the matched-vs-cross-mode paired comparison
- Final report and live demo

## 8. Timeline (adjust to course schedule)

| Week | Task |
|---|---|
| 1 | **Validate Spotify audio-features access first (new apps are likely blocked — see 4/5b);** decide feature strategy (Spotify features if available, else ReccoBeats/Essentia/embeddings); set up chosen audio/data source; collect large catalog sample |
| 2 | Data cleaning; feature and/or embedding extraction; exploratory analysis of feature distributions |
| 3 | Build similarity engine (cosine similarity / PCA); initial recommendations |
| 4 | Define and tune "hidden gem" threshold; build baseline comparison |
| 5 | Collect/match lyrics data; build lyrical-similarity embedding space; validate it separately from audio similarity |
| 6 | Build "what do you like about it" input + matched-mode / cross-mode recommendation logic |
| 7 | Clustering layer + sound-neighborhood visualization |
| 8 | Run held-out test + user study, including matched-vs-cross-mode paired comparison; collect and analyze feedback |
| 9 | Build interactive demo; polish visualizations |
| 10 | Report writing, presentation prep, buffer |

*(Note: adding the lyrics/vibe-contrast feature extends the original 8-week plan to roughly 10 weeks — compress weeks 5–6 into one if your course timeline is fixed at 8 weeks, treating the cross-mode feature as a stretch goal rather than core scope.)*

## 9. Known Limitations

- **Spotify audio-features access is likely unavailable (new, critical):** the `/v1/audio-features` and `/v1/audio-analysis` endpoints were deprecated for new developer apps in November 2024, and 30-second preview URLs were removed from multi-get responses at the same time. This must be validated in Week 1, not assumed — the fallback path (ReccoBeats, self-hosted Essentia, or audio embeddings via Deezer previews) changes the interpretability and compute profile of the whole project, so committing to a feature strategy early is essential.
- **No universal ground truth:** "good recommendation" is inherently subjective; the project leans on proxy evaluations (held-out test, user study) rather than a single clean accuracy number — this needs to be explicitly acknowledged, not glossed over.
- **Popularity data can be noisy/incomplete:** Spotify's popularity score is influenced by recency and doesn't perfectly capture "underrated," so the hidden-gem definition is an approximation, not a precise measure of quality-vs-fame mismatch.
- **Audio features may miss "vibe":** things like cultural context or fine-grained vocal/production texture aren't captured by scalar features (Spotify's or ReccoBeats/Essentia equivalents) alone, so similarity may sometimes feel technically close but emotionally off. Audio embeddings (section 5b) directly target this gap but trade away interpretability, so this remains a real limitation whichever feature strategy is chosen, and should be discussed explicitly in the report rather than glossed over.
- **User study sample size will be small** (classmates/friends), so results are illustrative, not statistically robust — frame conclusions accordingly.
- **Lyrics matching is imperfect:** not every catalog track will have lyrics available or cleanly matched by title/artist (especially instrumental tracks, live versions, or less mainstream songs — ironically the exact songs you most want lyrics for as "hidden gems"), so the lyrical-similarity pool may be meaningfully smaller than the audio-feature pool; this needs to be measured and reported, not assumed away.
- **"What you like about it" is self-reported and imprecise:** a user's stated reason (lyrics/beat/vibe) is a simplification of what actually draws them to a song, and people may not accurately introspect on this — worth noting as a limitation of the input design itself.
- **Cross-mode is a genuinely riskier hypothesis:** it's entirely possible users *don't* like contrasting-vibe recommendations even with matching lyrics — that's a valid and interesting negative result, but the project should be framed so a "no" answer is still a successful outcome, not a failed feature.

## 10. Tools

Python (pandas, scikit-learn for similarity/clustering/PCA, matplotlib/seaborn/plotly for visualization), Spotify Web API (metadata/popularity endpoints — expected to remain available), optionally Streamlit or a simple notebook widget for the interactive demo.

**Feature/embedding extraction (pick based on Week 1 API validation):** ReccoBeats (free, Spotify-feature-shaped drop-in) or self-hosted Essentia (open-source, no API dependency) for interpretable scalar features; OpenL3 or Essentia's embedding models (lighter-weight, well-documented) or CLAP/MERT (heavier, more expressive) for audio embeddings; `librosa` for basic derived stats (tempo, spectral energy) if a lightweight interpretable layer is needed alongside embeddings.

**Audio sourcing (only needed for embeddings/Essentia, not for ReccoBeats' upload option):** Deezer API for 30-second previews, `yt-dlp` against YouTube as a fallback, or a pre-embedded dataset (MTG-Jamendo, FMA) to skip raw-audio fetching for at least part of the candidate pool.

## 11. Critical Assessment

**Pros**
- Highly demo-friendly — "give me 3 songs you like, get back a song you've never heard that fits perfectly" is an instantly understandable, engaging live demo, arguably the most crowd-pleasing of your options.
- Forces you to think carefully about problem framing and evaluation design (defining "hidden gem," building a fair baseline, running a small user study) — this is genuinely good data-science practice and gives you a lot to discuss critically in your report.
- Natural extensions and depth available if you have time (clustering/sound-neighborhood visualization, dimensionality reduction, baseline comparisons) without needing a fundamentally new dataset.
- Personally interesting output — you'll likely end up with something you and classmates actually enjoy using, which tends to translate into a more engaged, polished final product.
- **The lyrics-vs-vibe cross-recommendation feature is a genuine research contribution, not just an extra bell/whistle** — it turns the project from "build a recommender" into "test a hypothesis about how people relate to music across independent dimensions," which reads as more sophisticated and gives you a real, falsifiable question to answer (and a negative result is still a valid, interesting finding).
- The matched-vs-cross paired comparison gives you a clean, gradeable quantitative result (per-participant rating pairs) on top of the qualitative discovery-value story, strengthening the weakest part of the original proposal (lack of hard numbers).

**Cons**
- **Spotify's core feature endpoint is likely inaccessible for a new app (new, address first):** the audio-features/audio-analysis deprecation means the original plan's primary similarity signal may not exist without a workaround. This isn't fatal — ReccoBeats, Essentia, and audio embeddings are all viable substitutes (section 5b) — but it needs a Week 1 decision, and each substitute has its own cost (coverage risk, compute, or lost interpretability) that should be budgeted for rather than discovered mid-project.
- No clean, objective ground truth — unlike the hit-prediction project, you can't report a single "accuracy" number and be done; you'll need to build and justify a multi-part evaluation strategy yourself, which is more open-ended (and to some graders, that's a plus; to others expecting hard metrics, you'll need to explain your reasoning carefully).
- The most interesting parts (clustering, "why was this picked" interpretability, baseline comparison) are additive — a minimal version of this project (just cosine similarity + a ranked list) is fairly thin, so you'll want to budget real time for the extensions to make it stand out.
- User-study logistics take coordination (getting 5–10 people to actually rate song lists) and the sample will be too small to be statistically rigorous — a real limitation to state upfront, not discover late.
- Depends on catalog breadth: if your sampled dataset doesn't have good coverage of lesser-known artists, there won't be genuine "hidden gems" to find — worth validating early (week 1–2) rather than assuming it'll work.
- **The new feature adds real scope, not just polish:** you now need a second, independent similarity pipeline (lyrics), a lyrics dataset cleanly matched to your catalog, and a second round of user testing (matched vs. cross-mode) — this pushes the timeline out by roughly 2 weeks (see revised timeline) and should be treated as a stretch goal if your course has a hard, shorter deadline.
- **Lyrics coverage gaps compound the existing "hidden gem" data-sparsity problem** — you're already filtering to less-popular songs, and now also need lyrics for them, which may shrink your usable pool more than expected; validate this early rather than discovering it late.
- The user study now needs to test *two* things (does the recommender work at all, and does the cross-mode hypothesis hold) with the same small sample size — statistical power will be thin, so keep conclusions appropriately modest.

**Learning Curve**
- **Medium.** Cosine similarity and k-means/PCA are standard and well-documented, so the core mechanics aren't hard to pick up.
- **Medium-high** on the *design* side — defining a good "hidden gem" metric and building a credible evaluation pipeline (held-out test + baseline + user study) requires more independent judgment than following a modeling tutorial; there's no single "correct" recipe to look up.
- **Low** if you add an interactive demo via Streamlit (simple to learn, lots of templates) — but budget a bit of extra time if you've never built even a minimal interactive app before.
- **Medium (new)** for the lyrics-similarity pipeline: text embeddings (e.g., via a pretrained sentence-transformer) are well-documented and not hard to call, but matching lyrics to your catalog by title/artist and cleaning that data reliably is fiddly, unglamorous work that tends to take longer than expected.
- **Medium-high (new)** for designing the matched-vs-cross user study itself — running a fair paired comparison (same user, two recommendation types, unbiased ordering/labeling so they don't just guess which is the "test" condition) requires more careful experimental design than the base project's user study.
- Overall: **a meaningful step up in scope and rigor from the base version** — still more open-ended than the hit-prediction project, and now also requires basic experimental-design thinking (paired comparisons, avoiding bias in how options are presented) on top of the original recommender-system skills.