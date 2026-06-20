# gh-pages — the project landing site

A single self-contained `index.html` (no build, no dependencies) that foregrounds
**what the project does and what it doesn't (yet)** — the same can/can't surfaced
in the root [`README.md`](../README.md) and tracked authoritatively in
[`docs/STATUS.md`](../docs/STATUS.md).

## Publish to GitHub Pages

Pick whichever matches the repo's Pages config:

- **`gh-pages` branch**: copy the contents of this folder to the root of a
  `gh-pages` branch and push.
  ```bash
  git subtree push --prefix gh-pages origin gh-pages
  # or: git worktree add /tmp/ghp gh-pages && cp gh-pages/* /tmp/ghp && (cd /tmp/ghp && git add -A && git commit -m site && git push)
  ```
- **`/docs` source**: GitHub Pages can also serve from `/docs` on the default
  branch — in that case move `index.html` to `docs/` (note: `docs/` currently
  holds the design Markdown, so a `gh-pages` branch keeps things separate).

Then enable Pages in the repo settings (Source → the branch/folder above).

## Keep it in sync

When the capability set changes, update three places together so users aren't
misled: the root `README.md` "What it does / what it doesn't" section,
`docs/STATUS.md`, and this page's two cards.
