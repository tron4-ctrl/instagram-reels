TROY — Personal Instagram Library

Deploy the contents of this repository to GitHub Pages from the repository root.

Main page: index.html
Reel data: data/reels.json
Post data: data/posts.json
Reel previews: reel_covers/*.jpg
Post previews: post_covers/*.jpg

The browser loads Reel and Post JSON separately and combines them in the All view. Reels and Posts can also be viewed independently. Post carousel cards store only the first image preview and link to the original Instagram Post for the remaining slides.

Reels and Posts are ingested by separate processors so the existing Reel pipeline remains isolated. See SETUP_FREE.md for setup and testing notes.


Branch-safety note: the updated workflow commits back to the branch on which it runs. Test Post ingestion from a feature branch before merging to main.
