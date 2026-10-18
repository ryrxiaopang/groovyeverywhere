# Round 2 success rule (written 11 Oct 2026, BEFORE the round-2 sheets are sent)

Why this file exists: the model checks have pass marks set in advance (the pass-mark table in `archive/README_first_kit.md`), but the friend test had none, so any result could be
read as a win. This file fixes what counts as success *before* anyone has rated a song. The commit date of this file is the
timestamp. Do not edit the numbers after results arrive; if something must change, add a dated note at the bottom saying what and why.

## What is compared

Each friend rates songs from four lists, shuffled and unlabelled (3 songs per list per song they gave us):

| List | How it is picked |
| --- | --- |
| A | The 3 closest matches in Sound alone (best match first) |
| B | Sound plus the feature the friend said they love (mood, rhythm or instruments), best matches first |
| C | 3 random songs of the same genre as the closest match |
| D | The 3 most-viewed songs of the same style (sub-style group) as the closest match: a popularity baseline |

Songs a friend was already shown in an earlier round never appear again. AI-tagged songs with under 10,000 views are not in the pool.
The AI tags are not shown to friends.

## Primary outcome

"Would you add this to your own playlist?" (yes or no), on **all** rated songs from **all** friends who rated. Rows where the friend said
the link did not work are left out and counted.

## The three claims, and what counts as success

A claim is **supported** only if, for the paired difference between the two lists (the same friends rated both):

1. the difference is at least **+10 points** in would-add, **and**
2. its **95% range**, found by resampling friends and then each friend's own ratings, is entirely **above 0**, **and**
3. at least **4 friends** rated both lists, with at least **8 rated songs in each list**.

| Claim | Lists | In words |
| --- | --- | --- |
| H1 | A minus C | Sound matching beats random songs of the same genre |
| H2 | A minus D | Sound matching beats the most-viewed songs of the same style (the stronger claim) |
| H3 | B minus A | Adding the feature the friend loves beats Sound alone |

Possible verdicts, printed by `python blind_test.py --score <round-2 sheets>`:

* **SUPPORTED**: all three conditions above hold.
* **CONTRADICTED**: the whole 95% range is below 0 (the first list is clearly worse).
* **NOT CLEAR**: anything else. This means "no clear difference with this many friends", **not** "no effect".
* **CANNOT JUDGE**: fewer than 4 friends or fewer than 8 rated songs per list.

## What the result means for the project

* H1 and H2 supported: Sound matching recommends songs friends would keep, beyond random and beyond popularity. Continue.
* H1 supported, H2 not clear or contradicted: Sound beats random but not "just show popular songs of that style". Report it as such.
* H1 not clear or contradicted: matching has not been shown to work with this pool and these friends. Do not claim it does.
* H3 is only about the chosen feature. If it is not supported, the feature filter has not been shown to help.

## Not allowed after the results are seen

* Changing the +10 points, the 4 friends, the 8 songs or the 95% range.
* Dropping friends or songs because they hurt a claim. Exclusions are only the ones listed above (broken links).
* Switching the primary outcome to rating, or reporting only the table (all songs or without AI-tagged songs) that looks better.
  Both tables are printed; the "all songs" table decides.

## Reported alongside, but not deciding

* Mean rating (1 to 5) per list.
* The same tables without songs tagged AI, and without songs the friend had heard before. (Differences between these and the primary
  table are reported, not used to change a verdict.)
* Would-add by the feature the friend said they love (descriptive only).
* How many friends took part. With only a handful of friends the ranges are rough guides.

## Known limits (stated now so they are not discovered later)

* The pool was seeded partly from the friends' own artists and from Spotify and Deezer related-artist lists, so even list C may sit near their taste.
* List D uses YouTube views, which are not comparable with Spotify streams.
* A few friends with similar taste cannot speak for everyone.

## Notes added later

* **18 Oct 2026:** the round-2 ratings did not come back before the hackathon deadline, so round 2 was **not scored** and no claim is made about it.
  The numbers above are unchanged. If ratings arrive later, score only the round-2 sheets against this rule, and say that the lists were built with the
  AI policy of 11 Oct (AI-tagged songs under 10,000 views left out); the policy was later changed to leave out every AI-tagged song.
