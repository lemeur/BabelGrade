# Cutting a release (end to end)

Example with `v0.1.0`; replace it with the version you want (`vMAJOR.MINOR.PATCH`).
Repository: <https://github.com/lemeur/BabelGrade>

## 1. Prerequisites

- Docker (with `docker compose`) to test the bundle.
- Write access to the repository, and a **public** repository if the URL must be downloadable without signing in.
- Optional: GitHub CLI — `brew install gh && gh auth login`.

## 2. Check before publishing

```bash
git switch main && git pull
git status                      # must be clean
ruff check .                    # same check as CI
```

Also make sure CI is green on `main` (*Actions* tab).

## 3. Build the archive

```bash
scripts/make_bundle.sh 0.1.0    # -> dist/babelgrade-bundle.tar.gz
tar tzf dist/babelgrade-bundle.tar.gz | head
```

The archive contains `docker-compose.yml`, `.env.example`, `Dockerfile`, `.dockerignore`,
`requirements.txt`, `run.sh`, `app/`, `static/`, `docs/` (without images), `README.md`,
`LICENSE` and `QUICKSTART.txt`. No real `.env`, no user data. `dist/` is git-ignored.

## 4. Test the archive (clean folder, no real .env)

```bash
rm -rf /tmp/bg-verify && mkdir /tmp/bg-verify
tar xzf dist/babelgrade-bundle.tar.gz -C /tmp/bg-verify
cd /tmp/bg-verify/babelgrade-bundle
cp .env.example .env
BABELGRADE_PORT=8191 docker compose -p bgverify up -d --build
sleep 20 && curl -s localhost:8191/api/health   # {"ok":true,...}
docker compose -p bgverify ps                   # STATUS: healthy
docker compose -p bgverify down -v              # clean up
```

`llm.ok:false` in `/api/health` is expected when no LLM server is running.

## 5. Tag

```bash
git tag -a v0.1.0 -m "BabelGrade v0.1.0"
git push origin v0.1.0
```

Fix a wrong tag (before publishing):
`git tag -d v0.1.0 && git push origin :refs/tags/v0.1.0`.

## 6. Publish the release

### Option A — GitHub CLI

```bash
gh release create v0.1.0 dist/babelgrade-bundle.tar.gz \
  --title "BabelGrade v0.1.0" \
  --notes "Docker bundle: tar xzf babelgrade-bundle.tar.gz && cd babelgrade-bundle && docker compose up -d --build"
# or: --generate-notes for automatic notes, --draft to review first
```

Replace the archive of an existing release:
`gh release upload v0.1.0 dist/babelgrade-bundle.tar.gz --clobber`.

### Option B — Web UI

1. Open <https://github.com/lemeur/BabelGrade/releases/new>.
2. *Choose a tag*: select `v0.1.0` (pushed in step 5), or type it — it will be created on `main`.
3. *Release title*: `BabelGrade v0.1.0`; describe the changes (or click *Generate release notes*).
4. Drag `dist/babelgrade-bundle.tar.gz` into the *Attach binaries* area.
5. Click *Publish release* (or *Save draft* to review first).

## 7. Get the URL

| Purpose | URL |
|---|---|
| Release page | `https://github.com/lemeur/BabelGrade/releases/tag/v0.1.0` |
| **Direct download (the one to submit)** | `https://github.com/lemeur/BabelGrade/releases/download/v0.1.0/babelgrade-bundle.tar.gz` |
| Always the latest version | `https://github.com/lemeur/BabelGrade/releases/latest/download/babelgrade-bundle.tar.gz` |

With the CLI: `gh release view v0.1.0 --json url,assets --jq '.url, .assets[].url'`.
In the UI: right-click `babelgrade-bundle.tar.gz` in the *Assets* section → *Copy link address*.

Final check:

```bash
curl -IL https://github.com/lemeur/BabelGrade/releases/download/v0.1.0/babelgrade-bundle.tar.gz   # final 200
```

## 8. Next release

Run `scripts/make_bundle.sh X.Y.Z`, then repeat steps 2–7 with a new tag.
