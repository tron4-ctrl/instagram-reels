# Free Setup — One Time

## 1. Put these files at the repository root

Keep:

```text
index.html
data/
reel_covers/
automation/
.github/
```

Do not move them under a `site/` directory. The live Pages site is configured around the repository root.

## 2. GitHub Actions secrets

Go to:

`Settings → Secrets and variables → Actions`

Add only what you use:

- `INSTAGRAM_COOKIES` (preferred, multiline Netscape/Mozilla cookie content) OR `INSTAGRAM_COOKIES_B64`
- `TELEGRAM_BOT_TOKEN` (optional)
- `TELEGRAM_ALLOWED_CHAT_ID` (optional)

Never commit cookie files or bot tokens.

## 3. Add a Reel

Simplest free method: open **Issues → New issue → Add Instagram Reel** and paste the Reel URL(s), one per line.

The workflow will:

`URL → shortcode → dedup → metadata → explicit cover → category → validation → commit → Pages`

## 4. No review queue

Every new Reel receives a category automatically. The classifier uses strong topic signals first, existing-category vocabulary second, and the true `General / Relatable & Miscellaneous Content` fallback only when the available metadata does not support a more specific category.

## 5. Test safely

Use **Actions → Instagram Reel Auto Sync → Run workflow** with one test Reel first.

Check that:

- the new Reel appears at the top;
- the cover displays;
- the category is present;
- the Total Reels count increases by exactly one;
- category counts update;
- the Reel URL is correct.

The workflow validates the entire library before pushing changes.
