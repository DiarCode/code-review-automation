#!/usr/bin/env python3
"""
export_pr.py — Export a GitHub Pull Request to a structured Markdown file.

Usage:
    python export_pr.py <PR_URL>
    python export_pr.py https://github.com/org/repo/pull/123

Requirements:
    pip install requests

Auth (pick one):
    export GITHUB_TOKEN=ghp_your_token_here   # recommended
    # or pass --token YOUR_TOKEN flag
"""

import os
import re
import sys
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("❌  Missing dependency. Run:  pip install requests")
    sys.exit(1)


# ─── Argument Parsing ────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Export a GitHub PR to a structured Markdown folder."
    )
    parser.add_argument(
        "pr_url",
        help="Full GitHub PR URL — e.g. https://github.com/org/repo/pull/123"
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN", ""),
        help="GitHub personal access token (or set GITHUB_TOKEN env var)"
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Parent directory to create the PR folder in (default: current dir)"
    )
    parser.add_argument(
        "--context-lines",
        type=int,
        default=10,
        help="Lines of context around each diff hunk (default: 10)"
    )
    return parser.parse_args()


# ─── URL Parsing ─────────────────────────────────────────────────────────────

def parse_pr_url(url: str) -> tuple[str, str, int]:
    """Extract (owner, repo, pr_number) from a GitHub PR URL."""
    pattern = r"github\.com/([^/]+)/([^/]+)/pull/(\d+)"
    match = re.search(pattern, url)
    if not match:
        print(f"❌  Could not parse PR URL: {url}")
        print("    Expected format: https://github.com/owner/repo/pull/123")
        sys.exit(1)
    owner, repo, number = match.groups()
    return owner, repo, int(number)


# ─── GitHub API Client ───────────────────────────────────────────────────────

class GitHubClient:
    BASE = "https://api.github.com"
    DEFAULT_TIMEOUT = 60

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        else:
            print("⚠️  No GITHUB_TOKEN set — rate limits apply (60 req/hr).")
            print("    For private repos or full data, set GITHUB_TOKEN.\n")

    def get(self, path: str, params: dict = None) -> dict | list:
        url = f"{self.BASE}{path}"
        resp = self.session.get(url, params=params, timeout=self.DEFAULT_TIMEOUT)
        if resp.status_code == 401:
            print("❌  GitHub API: Unauthorized. Check your GITHUB_TOKEN.")
            sys.exit(1)
        if resp.status_code == 404:
            print(f"❌  GitHub API: Not found — {url}")
            sys.exit(1)
        resp.raise_for_status()
        return resp.json()

    def get_paginated(self, path: str, params: dict = None) -> list:
        """Fetch all pages of a paginated endpoint."""
        results = []
        page = 1
        params = params or {}
        while True:
            params["per_page"] = 100
            params["page"] = page
            batch = self.get(path, params=params)
            if not batch:
                break
            results.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return results

    def _is_diff_too_large(self, resp: requests.Response) -> bool:
        if resp.status_code != 406:
            return False
        try:
            payload = resp.json()
        except ValueError:
            return False

        for err in payload.get("errors", []):
            if err.get("field") == "diff" and err.get("code") == "too_large":
                return True
        return False

    def _get_pr_diff(self, owner: str, repo: str, pr: int) -> str:
        """Fetch unified diff from pull request media type."""
        url = f"{self.BASE}/repos/{owner}/{repo}/pulls/{pr}"
        resp = self.session.get(url, headers={
            **self.session.headers,
            "Accept": "application/vnd.github.v3.diff"
        }, timeout=self.DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def _get_compare_diff(self, owner: str, repo: str, base_sha: str, head_sha: str) -> str:
        """Fetch unified diff from compare endpoint."""
        url = f"{self.BASE}/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"
        resp = self.session.get(url, headers={
            **self.session.headers,
            "Accept": "application/vnd.github.v3.diff"
        }, timeout=self.DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.text

    def get_diff(
        self,
        owner: str,
        repo: str,
        pr: int,
        *,
        base_sha: str | None = None,
        head_sha: str | None = None,
        files: list[dict] | None = None,
    ) -> tuple[str, str]:
        """
        Fetch raw unified diff for a PR.

        Returns:
            (diff_text, diff_source)
        """
        try:
            return self._get_pr_diff(owner, repo, pr), "pull_request_media_type"
        except requests.HTTPError as err:
            if err.response is None or not self._is_diff_too_large(err.response):
                raise
            print("    ⚠️  PR diff endpoint exceeded GitHub line cap (20k). Falling back ...")

        if base_sha and head_sha:
            try:
                return self._get_compare_diff(owner, repo, base_sha, head_sha), "compare_endpoint"
            except requests.HTTPError as err:
                code = err.response.status_code if err.response is not None else "unknown"
                print(f"    ⚠️  Compare diff fallback failed (HTTP {code}).")

        if files is not None:
            return synthesize_diff_from_files(files), "synthesized_from_files"

        raise RuntimeError("Unable to fetch diff from GitHub API and no file data available.")


# ─── Data Fetching ───────────────────────────────────────────────────────────

def fetch_all_pr_data(client: GitHubClient, owner: str, repo: str, pr_num: int) -> dict:
    base = f"/repos/{owner}/{repo}"
    print(f"📡  Fetching PR #{pr_num} from {owner}/{repo} ...")

    pr          = client.get(f"{base}/pulls/{pr_num}")
    files       = client.get_paginated(f"{base}/pulls/{pr_num}/files")
    comments    = client.get_paginated(f"{base}/issues/{pr_num}/comments")
    reviews     = client.get_paginated(f"{base}/pulls/{pr_num}/reviews")
    review_cmts = client.get_paginated(f"{base}/pulls/{pr_num}/comments")
    commits     = client.get_paginated(f"{base}/pulls/{pr_num}/commits")
    labels      = pr.get("labels", [])
    diff, diff_source = client.get_diff(
        owner,
        repo,
        pr_num,
        base_sha=pr["base"]["sha"],
        head_sha=pr["head"]["sha"],
        files=files,
    )

    print(f"    ✓ Metadata, {len(files)} files, {len(commits)} commits, "
          f"{len(reviews)} reviews, {len(comments) + len(review_cmts)} comments")
    print(f"    ✓ Diff source: {diff_source}")

    return {
        "pr": pr,
        "files": files,
        "comments": comments,
        "reviews": reviews,
        "review_comments": review_cmts,
        "commits": commits,
        "labels": labels,
        "diff": diff,
        "diff_source": diff_source,
    }


# ─── Markdown Rendering ──────────────────────────────────────────────────────

def fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d %H:%M UTC")

def user(obj: dict | None) -> str:
    if not obj:
        return "—"
    return f"[@{obj['login']}]({obj['html_url']})"

def safe(text: str | None, fallback: str = "_None provided_") -> str:
    if not text or not text.strip():
        return fallback
    return text.strip()

def wrap_diff(patch: str | None) -> str:
    if not patch:
        return "_No diff available (binary file or file moved without changes)_"
    return f"```diff\n{patch}\n```"

def synthesize_diff_from_files(files: list[dict]) -> str:
    """
    Build an approximate unified diff by stitching together /pulls/{pr}/files patches.
    This fallback keeps the export running when GitHub refuses full PR diff media type.
    """
    lines: list[str] = []
    missing_patch_count = 0

    for f in files:
        filename = f["filename"]
        status = f.get("status", "modified")
        previous_filename = f.get("previous_filename", filename)
        old_path = previous_filename if status == "renamed" else filename
        patch = f.get("patch")

        lines.append(f"diff --git a/{old_path} b/{filename}")
        if status == "added":
            lines.append("new file mode 100644")
            before, after = "/dev/null", f"b/{filename}"
        elif status == "removed":
            lines.append("deleted file mode 100644")
            before, after = f"a/{old_path}", "/dev/null"
        elif status == "renamed":
            lines.append(f"rename from {previous_filename}")
            lines.append(f"rename to {filename}")
            before, after = f"a/{previous_filename}", f"b/{filename}"
        else:
            before, after = f"a/{old_path}", f"b/{filename}"

        lines.append(f"--- {before}")
        lines.append(f"+++ {after}")

        if patch:
            lines.append(patch.rstrip("\n"))
        else:
            missing_patch_count += 1
            lines.append("@@ -0,0 +0,0 @@")
            lines.append(
                f"# Patch omitted by GitHub API for {filename} "
                f"(status={status}, additions={f.get('additions', 0)}, deletions={f.get('deletions', 0)})."
            )

        lines.append("")

    summary = (
        "# Synthesized fallback diff from /pulls/{pr}/files.\n"
        f"# Files with omitted patch text: {missing_patch_count}.\n\n"
    )
    return summary + "\n".join(lines)

def render_markdown(data: dict, owner: str, repo: str, pr_num: int) -> str:
    pr  = data["pr"]
    md  = []
    W   = md.append   # shorthand

    repo_url = f"https://github.com/{owner}/{repo}"
    pr_url   = pr["html_url"]

    # ── Header ────────────────────────────────────────────────────────────────
    W(f"# PR #{pr_num} — {pr['title']}\n")
    W(f"> **Repository:** [{owner}/{repo}]({repo_url})  ")
    W(f"> **URL:** {pr_url}  ")
    W(f"> **State:** `{pr['state'].upper()}`{'  🔀 **MERGED**' if pr.get('merged') else ''}\n")

    # ── Metadata table ────────────────────────────────────────────────────────
    W("## 📋 Metadata\n")
    W("| Field | Value |")
    W("|---|---|")
    W(f"| **Author** | {user(pr.get('user'))} |")
    W(f"| **Branch** | `{pr['head']['ref']}` → `{pr['base']['ref']}` |")
    W(f"| **Base commit** | `{pr['base']['sha'][:10]}` |")
    W(f"| **Head commit** | `{pr['head']['sha'][:10]}` |")
    W(f"| **Created** | {fmt_date(pr.get('created_at'))} |")
    W(f"| **Updated** | {fmt_date(pr.get('updated_at'))} |")
    W(f"| **Merged** | {fmt_date(pr.get('merged_at'))} |")
    W(f"| **Closed** | {fmt_date(pr.get('closed_at'))} |")
    W(f"| **Merged by** | {user(pr.get('merged_by'))} |")
    W(f"| **Draft** | {'Yes' if pr.get('draft') else 'No'} |")
    W(f"| **Mergeable** | {pr.get('mergeable_state', '—')} |")
    W(f"| **Commits** | {pr.get('commits', '—')} |")
    W(f"| **Changed files** | {pr.get('changed_files', '—')} |")
    W(f"| **Additions** | `+{pr.get('additions', 0)}` |")
    W(f"| **Deletions** | `-{pr.get('deletions', 0)}` |")

    # Assignees
    assignees = pr.get("assignees") or []
    if assignees:
        W(f"| **Assignees** | {', '.join(user(a) for a in assignees)} |")
    else:
        W("| **Assignees** | — |")

    # Reviewers
    reviewers = pr.get("requested_reviewers") or []
    if reviewers:
        W(f"| **Requested reviewers** | {', '.join(user(r) for r in reviewers)} |")
    else:
        W("| **Requested reviewers** | — |")

    # Labels
    labels = data["labels"]
    if labels:
        label_badges = " ".join(f"`{l['name']}`" for l in labels)
        W(f"| **Labels** | {label_badges} |")
    else:
        W("| **Labels** | — |")

    # Milestone
    milestone = pr.get("milestone")
    W(f"| **Milestone** | {milestone['title'] if milestone else '—'} |")

    W("")

    # ── Description ───────────────────────────────────────────────────────────
    W("## 📝 Description\n")
    W(safe(pr.get("body")))
    W("")

    # ── Commits ───────────────────────────────────────────────────────────────
    commits = data["commits"]
    if commits:
        W(f"## 🔖 Commits ({len(commits)})\n")
        for c in commits:
            sha   = c["sha"][:10]
            msg   = c["commit"]["message"].split("\n")[0]
            author = c["commit"]["author"].get("name", "—")
            date   = fmt_date(c["commit"]["author"].get("date"))
            url    = c["html_url"]
            W(f"- [`{sha}`]({url}) **{msg}**  _by {author} at {date}_")
        W("")

    # ── Changed Files Summary ─────────────────────────────────────────────────
    files = data["files"]
    if files:
        W(f"## 📁 Changed Files ({len(files)})\n")
        W("| Status | File | +Lines | -Lines |")
        W("|---|---|---|---|")
        status_icon = {
            "added":    "🟢 added",
            "removed":  "🔴 removed",
            "modified": "🟡 modified",
            "renamed":  "🔵 renamed",
            "copied":   "🔵 copied",
            "changed":  "🟡 changed",
        }
        for f in sorted(files, key=lambda x: x["filename"]):
            icon    = status_icon.get(f["status"], f["status"])
            fname   = f["filename"]
            adds    = f.get("additions", 0)
            dels    = f.get("deletions", 0)
            W(f"| {icon} | `{fname}` | `+{adds}` | `-{dels}` |")
        W("")

    # ── Per-File Diffs ────────────────────────────────────────────────────────
    W("## 🔍 File Diffs\n")
    for f in files:
        fname   = f["filename"]
        status  = f.get("status", "modified")
        adds    = f.get("additions", 0)
        dels    = f.get("deletions", 0)
        W(f"### `{fname}`")
        W(f"**Status:** {status} &nbsp;|&nbsp; `+{adds}` additions &nbsp;`-{dels}` deletions\n")
        if f.get("previous_filename"):
            W(f"_Renamed from: `{f['previous_filename']}`_\n")
        W(wrap_diff(f.get("patch")))
        W("")

    # ── Full Raw Diff ─────────────────────────────────────────────────────────
    W("## 📄 Full Raw Diff\n")
    diff = data["diff"]
    diff_source = data.get("diff_source", "unknown")
    diff_lines = diff.count("\n") + 1 if diff else 0
    W(f"_Source: `{diff_source}` · lines: `{diff_lines}`_\n")
    if diff_lines > 25000:
        W(
            "_Diff is very large, so it is stored in `changes.diff` and not embedded here to keep the markdown usable._\n"
        )
    else:
        W("<details>")
        W("<summary>Click to expand full unified diff</summary>\n")
        W("```diff")
        W(diff)
        W("```")
        W("</details>\n")

    # ── Reviews ───────────────────────────────────────────────────────────────
    reviews = data["reviews"]
    if reviews:
        W(f"## 👁️ Reviews ({len(reviews)})\n")
        state_icon = {
            "APPROVED":          "✅ Approved",
            "CHANGES_REQUESTED": "❌ Changes Requested",
            "COMMENTED":         "💬 Commented",
            "DISMISSED":         "🚫 Dismissed",
            "PENDING":           "⏳ Pending",
        }
        for r in reviews:
            state = state_icon.get(r["state"], r["state"])
            W(f"#### {state} — {user(r.get('user'))} at {fmt_date(r.get('submitted_at'))}\n")
            body = safe(r.get("body"), "_No review comment body_")
            W(body)
            W("")

    # ── Review Comments (inline) ──────────────────────────────────────────────
    review_cmts = data["review_comments"]
    if review_cmts:
        W(f"## 💬 Inline Review Comments ({len(review_cmts)})\n")

        # Group by file
        by_file: dict[str, list] = {}
        for c in review_cmts:
            key = c.get("path", "unknown")
            by_file.setdefault(key, []).append(c)

        for filepath, cmts in sorted(by_file.items()):
            W(f"### `{filepath}`\n")
            for c in cmts:
                line_ref = f"Line {c.get('line') or c.get('original_line', '?')}"
                W(f"**{user(c.get('user'))}** — {fmt_date(c.get('created_at'))} @ _{line_ref}_\n")
                W(safe(c.get("body")))
                if c.get("diff_hunk"):
                    W(f"\n_Context:_\n```diff\n{c['diff_hunk']}\n```")
                W("")

    # ── General Comments ──────────────────────────────────────────────────────
    comments = data["comments"]
    if comments:
        W(f"## 🗨️ General Comments ({len(comments)})\n")
        for c in comments:
            W(f"**{user(c.get('user'))}** — {fmt_date(c.get('created_at'))}\n")
            W(safe(c.get("body")))
            W("")

    # ── Footer ────────────────────────────────────────────────────────────────
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    W("---")
    W(f"_Exported by export\\_pr.py on {exported_at}_")

    return "\n".join(md)


# ─── Folder & File Naming ────────────────────────────────────────────────────

def slugify(text: str, max_len: int = 50) -> str:
    """Convert a PR title to a filesystem-safe slug."""
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = text.strip("-")
    return text[:max_len].strip("-")

def make_output_folder(base_dir: str, owner: str, repo: str,
                        pr_num: int, pr_title: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug      = slugify(pr_title)
    folder_name = f"PR_{pr_num}_{slug}__{timestamp}"
    folder = Path(base_dir) / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    args   = parse_args()
    owner, repo, pr_num = parse_pr_url(args.pr_url)

    client = GitHubClient(token=args.token)
    data   = fetch_all_pr_data(client, owner, repo, pr_num)

    pr_title = data["pr"]["title"]
    folder   = make_output_folder(args.output_dir, owner, repo, pr_num, pr_title)

    # ── Main review MD ────────────────────────────────────────────────────────
    print("📝  Rendering Markdown ...")
    md_content = render_markdown(data, owner, repo, pr_num)
    md_path    = folder / "PR_REVIEW.md"
    md_path.write_text(md_content, encoding="utf-8")

    # ── Raw diff file ─────────────────────────────────────────────────────────
    diff_path = folder / "changes.diff"
    diff_path.write_text(data["diff"], encoding="utf-8")

    # ── Raw JSON dump (full API data for debugging/automation) ────────────────
    json_path = folder / "raw_data.json"
    json_path.write_text(
        json.dumps({k: v for k, v in data.items() if k != "diff"},
                   indent=2, default=str),
        encoding="utf-8"
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n✅  Done! Output folder:")
    print(f"    📂  {folder.resolve()}")
    print(f"    ├── PR_REVIEW.md     ← Full structured Markdown (feed to review agent)")
    print(f"    ├── changes.diff     ← Raw unified diff")
    print(f"    └── raw_data.json    ← Full API payload\n")


if __name__ == "__main__":
    main()
