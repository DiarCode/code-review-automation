# 📦 Export PR for Code Review

Export any GitHub Pull Request into a fully structured Markdown folder — metadata, diffs, reviews, comments, and more — ready to read, archive, or feed into an AI code review agent.

---

## ✨ What it does

One command. One URL. One complete folder.

```
PR_96_fix-auth-flow__20250312_143022/
├── PR_REVIEW.md     ← Full structured Markdown
├── changes.diff     ← Raw unified diff
└── raw_data.json    ← Complete GitHub API payload
```

`PR_REVIEW.md` contains everything about the pull request in one clean document:

| Section | Content |
|---|---|
| Header | Title, repo, state, merge status |
| Metadata | Author, branches, SHAs, dates, assignees, reviewers, labels, milestone |
| Description | Full PR body |
| Commits | All commits with SHA, message, author, timestamp |
| Changed files | Summary table with status and line counts per file |
| File diffs | Per-file patches in fenced `diff` blocks |
| Full diff | Complete unified diff (collapsible) |
| Reviews | Every review with state, reviewer, and body |
| Inline comments | Grouped by file with line reference and diff hunk context |
| General comments | Full PR discussion thread |

---

## 🚀 Quickstart

### 1. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone and set up the project

```bash
git clone [https://github.com/your-org/export-pr.git](https://github.com/DiarCode/code-review-automation.git)
cd code-review-automation

uv init .
uv add requests
```

### 3. Add your GitHub token to `run.sh`

Create `run.sh` file from the `run.example.sh` and replace the placeholder:

```bash
GITHUB_TOKEN="ghp_your_token_here"
```

> See [Creating a token](#-github-token) below for how to generate one.

### 4. Make the runner executable

```bash
chmod +x run.sh
```

### 5. Run

```bash
./run.sh https://github.com/org/repo/pull/123
```

---

## 📁 Project Structure

```
code-review-automation/
├── main.py     ← Main Python script
├── run.sh           ← Shell runner (stores your token, takes URL as argument)
├── pyproject.toml   ← uv/pip project config
└── README.md
```

---

## ⚙️ Usage

### Shell script (recommended)

```bash
./run.sh https://github.com/org/repo/pull/123
```

### Python directly

```bash
# Token via environment variable
export GITHUB_TOKEN=ghp_your_token_here
uv run main.py https://github.com/org/repo/pull/123

# Token inline
uv run main.py https://github.com/org/repo/pull/123 --token ghp_your_token_here

# Custom output directory
uv run main.py https://github.com/org/repo/pull/123 --output-dir ~/reviews
```

### All available flags

| Flag | Default | Description |
|---|---|---|
| `pr_url` | _(required)_ | Full GitHub PR URL |
| `--token` | `$GITHUB_TOKEN` | GitHub personal access token |
| `--output-dir` | `.` (current dir) | Where to create the output folder |
| `--context-lines` | `10` | Lines of context around each diff hunk |

---

## 🔑 GitHub Token

You need a GitHub Personal Access Token to access private repositories and avoid rate limits.

### Classic token (simplest)

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. Click **Generate new token**
3. Set a name and expiration
4. Check the **`repo`** scope (full control of private repositories)
5. Click **Generate token** and copy it

### Fine-grained token (recommended for production)

1. Go to **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**
2. Click **Generate new token**
3. Set **Resource owner** to the org or user that owns the repo
4. Under **Repository access** → select the specific repo
5. Under **Permissions → Repository permissions** set:
   - **Pull requests** → `Read-only`
   - **Contents** → `Read-only`
6. Generate and copy

> ⚠️ **Never commit your token to the repository.** Add `run.sh` to `.gitignore` if it contains a real token, or use an environment variable instead.

---

## 🔒 Security Notes

- The token is stored in `run.sh` — **do not commit this file** if it contains a real token
- Add to `.gitignore`:

```gitignore
# If your run.sh contains a real token
run.sh
```

- Alternatively, keep `run.sh` in the repo with a placeholder and always set the token via environment variable:

```bash
export GITHUB_TOKEN=ghp_your_token_here
./run.sh https://github.com/org/repo/pull/123
```

---

## 🐛 Troubleshooting

### `❌ GitHub API: Not found`

The repo is private and your token either has insufficient permissions or isn't being passed correctly.

```bash
# Test your token directly
curl -H "Authorization: Bearer ghp_your_token_here" \
     https://api.github.com/repos/ORG/REPO/pulls/PR_NUMBER
```

| Response | Meaning |
|---|---|
| PR JSON object | Token works — check how the script passes it |
| `{"message": "Not Found"}` | Token lacks `repo` scope |
| `{"message": "Bad credentials"}` | Token is wrong or expired |

### `❌ Unauthorized`

Your token has expired or was revoked. Generate a new one at https://github.com/settings/tokens.

### `⚠️ No GITHUB_TOKEN set`

Public repos will work at 60 requests/hour. For private repos or consistent access, always set the token.

### `command not found: uv`

Run the installer:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then restart your terminal or run `source ~/.bashrc` / `source ~/.zshrc`.

---

## 📋 Requirements

- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) package manager
- `requests` (installed automatically via `uv add requests`)
- GitHub Personal Access Token

---

## 📄 License

MIT
