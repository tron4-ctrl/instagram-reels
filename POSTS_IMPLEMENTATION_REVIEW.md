# TROY Posts Implementation — Review Copy

This folder is an isolated working copy based on the user-provided latest `main` ZIP. It is **not deployed** and has not been pushed to GitHub. The separate `classifier-v2` branch and the live repository were not accessed or modified.

## What this change adds

- `data/posts.json` as a separate Post dataset (initially empty).
- `post_covers/` for first-image preview files.
- `automation/sync_posts.py` as a separate Post ingester.
- `gallery-dl` in `automation/requirements.txt` for Post metadata and first-media extraction; `--range 1` limits extraction to the first item. Pillow validates and normalizes the preview to JPEG.
- Existing Instagram cookie secrets are reused through the current cookie-file helper. No new secret is required.
- Existing TROY category classifier and category vocabulary are reused.
- The existing GitHub Actions workflow (`.github/workflows/reel-sync.yml`) accepts both `/reel/` and `/p/` URLs while retaining the same workflow file path and `url` input.
- `automation/validate_library.py` validates Posts independently while retaining the Reel checks.
- `index.html` loads `reels.json` and `posts.json` separately and provides All / Reels / Posts views using the current TROY card, search, filters, sorting and pagination patterns.
- Post cards display only the first-image preview. Carousel cards link to the original Instagram Post; remaining slides are viewed on Instagram, as selected.

## Safety boundaries

- Existing `data/reels.json`, `reel_covers/`, `automation/sync_reels.py`, `data/meta.json`, `data/cover_index.json` and the established classifier implementation are left unchanged.
- The optional `automation/poll_telegram.py` is also left unchanged. The current path described for this project is Telegram → Cloudflare Worker → GitHub Actions, not that optional local poller.
- No Telegram bot, Cloudflare Worker, GitHub secret, GitHub Pages setting, repository branch or deployment was changed.
- The workflow file name and `workflow_dispatch` input name (`url`) are retained to minimize the change to the existing Worker-to-Actions handoff. The workflow pushes commits back to the branch from which it was run (`GITHUB_REF_NAME`), so a manual test on `feature/posts-support` stays on that branch rather than pushing to `main`. A run on `main` continues to publish to `main`.

## Validation performed in the isolated copy

- Python unit tests: **16 passed**.
- Python bytecode compilation: passed.
- Existing Reel library integrity validation: **PASS** — 3,804 Reels, 3,804 covers; no Reel data or cover changes.
- New Post dataset validator: passes with an empty initial Post dataset.
- Frontend JavaScript syntax check: passed.
- Browser UI smoke test with actual Reel JSON and a mocked carousel Post: passed. All view showed 3,805 items, Reels showed 3,804, Posts showed the mocked Post, the carousel label appeared, the original `/p/` link was correct, and no browser JS errors occurred.
- GitHub Actions YAML parsing and embedded Bash syntax checks: passed.
- Gallery-dl event-output parsing was tested with representative directory, first-file and error events.

## Not yet verified

The deployed Cloudflare Worker source was supplied separately in chat. Its URL matcher was updated by the user to accept both `/reel/` and `/p/`, and its health endpoint was verified after deployment. The Worker continues dispatching the existing workflow file and `url` input. A Telegram duplicate-Reel test also confirmed that the existing Reel route still works. A real Post dispatch is still pending until the GitHub-side changes are safely installed and tested.

A real Instagram Post fetch was not performed in this environment: the `gallery-dl` package was not installed locally, and the repository's Instagram session-cookie secrets are not available in this isolated copy. The GitHub Actions workflow installs the dependency from `automation/requirements.txt`; a real end-to-end test should be done on a test branch or with a manually dispatched workflow before enabling the Telegram route.

## Suggested next step

Create a review branch from the latest `main`, apply this bundle, and run a manual `/p/` workflow test on that branch. Only merge after the Post test passes and the Reel integrity checks remain green. The Cloudflare Worker URL matcher has already been updated and health-checked; no Worker change is needed for this stage.
