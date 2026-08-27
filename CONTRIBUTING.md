# Workflow

This is a solo project, but it still uses a branch + pull request workflow
instead of committing straight to `main`. Worth doing even here, because:

- `main` always stays in a working, deployable state — you can walk away
  mid-change on a branch without leaving `main` broken.
- A PR gives you a diff view before the change is permanent, which catches
  typos/mistakes you won't see as easily in an editor.
- It's the same muscle memory you'll want the moment you're on a team, where
  pushing straight to `main` isn't your call to make alone.

This applies to every change, including trivial ones like a README edit.
There's no change small enough to justify a direct push to `main`.

## The loop

1. **Branch off `main`** for whatever you're about to do. Name it by type:
   ```bash
   git checkout main
   git pull
   git checkout -b docs/readme        # or feat/..., fix/...
   ```
2. **Commit on that branch.**
   ```bash
   git add <files>
   git commit -m "Describe the change"
   ```
3. **Push the branch** (not `main`):
   ```bash
   git push -u origin docs/readme
   ```
4. **Open a pull request** on GitHub (the push output prints a direct link,
   or use the "Compare & pull request" button that appears on the repo
   page). Read your own diff here before merging.
5. **Merge the PR** on GitHub, then clean up locally:
   ```bash
   git checkout main
   git pull
   git branch -d docs/readme
   ```

## Branch naming

- `docs/...` — documentation only
- `feat/...` — new functionality
- `fix/...` — bug fixes
- `chore/...` — dependency bumps, config, cleanup

## Commit messages

Say *why*, not just *what* — the diff already shows what changed.
