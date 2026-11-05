# Team workflow

Nobody pushes directly to `main`. All changes go through a pull request that passes CI.

## Daily flow

```bash
git checkout main
git pull
git checkout -b <area>/<short-description>     # e.g. llm/first-prompt, backend/generate-endpoint

# work, then:
pytest                                          # run tests before pushing
git add -A
git commit -m "Short description of the change"
git push -u origin <area>/<short-description>
```

Then open a pull request on GitHub into `main`.

## Rules

1. One small PR at a time per person. Small PRs are easy to review and rarely break anything.
2. A PR needs a green CI check and one teammate's approval before merging.
3. Pull the latest `main` into your branch before opening the PR: `git pull origin main`.
4. `backend/schemas.py` is the shared contract. If you change it, announce it in the group first, because the LLM prompts, API, frontend and eval all depend on it.
5. If CI fails, fix it on your branch. Do not merge with a red check.
6. Never commit model files, `.env`, or API keys.

## Folders

| Folder | Owner area |
|---|---|
| `backend/` | API, validation, storage |
| `frontend/` | React UI |
| `eval/` | Sample requirements, edge-case checklists, scoring |
| `docs/` | Architecture notes, demo script |
