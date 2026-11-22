# Free Setup — TROY Instagram Library

## 1. Repository layout

Keep the site at the repository root so GitHub Pages can serve it directly:

```text
index.html
data/
  reels.json
  posts.json
  meta.json
  cover_index.json
reel_covers/
post_covers/
automation/
.github/
```

`reels.json` and `reel_covers/` remain the existing Reel library. Posts are stored separately in `posts.json` and `post_covers/`.

## 2. GitHub Actions secrets

Go to **Settings → Secrets and variables → Actions** and configure:

- `INSTAGRAM_COOKIES` (preferred, multiline Netscape/Mozilla cookie content) OR `INSTAGRAM_COOKIES_B64`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_CHAT_ID`

Never commit cookie files or bot tokens.

## 3. Submit a Reel or Post

The existing Telegram-to-Cloudflare-Worker-to-GitHub-Actions path is intended to remain the normal submission method. Send either URL to the same Telegram bot:

- Reel: `https://www.instagram.com/reel/SHORTCODE/`
- Post: `https://www.instagram.com/p/SHORTCODE/`

The GitHub Actions workflow routes `/reel/` to `automation/sync_reels.py` and `/p/` to `automation/sync_posts.py`.

The Post processor saves one preview image only. For carousel Posts, the TROY card links to the original Instagram Post so the remaining slides can be viewed there.

## 4. Processing and publishing

The workflow performs:

`URL → shortcode deduplication → metadata/media extraction → preview validation → shared TROY categorization → library validation → Git commit → GitHub Pages`

Reels continue to use `yt-dlp`. Posts use `gallery-dl` to obtain the first media item and Pillow to normalize its preview image. Both processors reuse the existing Instagram cookie secrets and TROY category classifier.

## 5. Safe testing before enabling Telegram Posts

Use **Actions → TROY Instagram Library Auto Sync → Run workflow** and submit one known public `/p/` URL. Check that:

- `data/posts.json` receives exactly one record;
- `post_covers/<shortcode>.jpg` is created;
- the preview is displayed in the **Posts** and **All** views;
- the category and caption/creator are present;
- clicking **Open on Instagram** opens the original `/p/` URL;
- the existing Reel count and Reel cover files are unchanged.

The workflow validates the complete Reel library and the Post library before committing. A Post validation failure prevents publishing. It commits back to the branch used for the run: testing from `feature/posts-support` pushes to that feature branch; a run from `main` pushes to `main`. This prevents a feature-branch test from writing directly to the live branch.

## 6. Cloudflare Worker note

The Cloudflare Worker is maintained separately from this repository. Its URL filter has already been updated to accept both `/reel/` and `/p/`, its health endpoint was verified after deployment, and the existing Reel duplicate test succeeded. No second Worker or bot is needed. Do not send a new Post through Telegram until the GitHub changes have been installed and a manual Post test on the feature branch has passed.
