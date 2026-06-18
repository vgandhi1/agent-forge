#!/usr/bin/env bash
# Scheduled AgentForge review → local commit → push → PR (if changes).
# Not invoked by AgentForge itself; run from cron, systemd, or GitHub Actions.
#
# Requires: git, network for push, ANTHROPIC_API_KEY (or Ollama) for the AgentForge run.
# Optional: gh CLI for PR creation; uv for running from the agent-forge source tree.
#
# Usage:
#   ./scripts/scheduled-review-pr.sh
#   TARGET_REPO=/path/to/app AGENTFORGE_PRESET=debug ./scripts/scheduled-review-pr.sh
#   AGENTFORGE_DRY_PR=1 ./scripts/scheduled-review-pr.sh   # no push/PR
set -euo pipefail

TARGET_REPO="${TARGET_REPO:-$(pwd)}"
TARGET_REPO="$(cd "${TARGET_REPO}" && pwd)"
BASE_BRANCH="${BASE_BRANCH:-main}"
PRESET="${AGENTFORGE_PRESET:-harden}"
GOAL="${AGENTFORGE_GOAL:-Scheduled production review: tests, security, and drift}"
BRANCH_PREFIX="${AGENTFORGE_BRANCH_PREFIX:-agentforge/scheduled}"
TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
BRANCH="${AGENTFORGE_BRANCH:-${BRANCH_PREFIX}-${TIMESTAMP}}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AF_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [[ -n "${AGENTFORGE_BIN:-}" ]]; then
  AF_CMD=("${AGENTFORGE_BIN}")
elif command -v agentforge >/dev/null 2>&1; then
  AF_CMD=(agentforge)
elif [[ -f "${AF_ROOT}/main.py" ]]; then
  AF_CMD=(uv run python "${AF_ROOT}/main.py")
else
  echo "error: set AGENTFORGE_BIN, install agentforge globally, or run from agent-forge checkout" >&2
  exit 1
fi

cd "${TARGET_REPO}"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "error: TARGET_REPO is not a git repository: ${TARGET_REPO}" >&2
  exit 1
fi

git fetch origin "${BASE_BRANCH}" 2>/dev/null || true

export AGENTFORGE_JSON_LOG=1
"${AF_CMD[@]}" \
  --target-repo "${TARGET_REPO}" \
  --preset "${PRESET}" \
  --strict-review \
  --deploy-gate --auto-approve \
  --deploy-commit --deploy-branch "${BRANCH}" \
  --skip-summary \
  --goal "${GOAL}"

DEPLOY_RECORD="${TARGET_REPO}/.agentforge/reports/deploy_record.md"
if [[ ! -f "${DEPLOY_RECORD}" ]]; then
  echo "No deploy record at ${DEPLOY_RECORD}; skipping PR."
  exit 0
fi

if grep -qiE 'blocked|aborted' "${DEPLOY_RECORD}"; then
  echo "Deploy blocked or aborted (see ${DEPLOY_RECORD}); not opening PR."
  exit 0
fi

if git rev-parse "origin/${BASE_BRANCH}" >/dev/null 2>&1; then
  BASE_REF="origin/${BASE_BRANCH}"
else
  BASE_REF="${BASE_BRANCH}"
fi

AHEAD="$(git rev-list --count "${BASE_REF}..HEAD" 2>/dev/null || echo 0)"
if [[ "${AHEAD}" == "0" ]]; then
  echo "No commits on ${BRANCH} ahead of ${BASE_REF}; skipping push/PR."
  exit 0
fi

if [[ "${AGENTFORGE_DRY_PR:-}" == "1" ]]; then
  echo "Dry run: would push ${BRANCH} (${AHEAD} commits) and open PR."
  exit 0
fi

git push -u origin "${BRANCH}"

if ! command -v gh >/dev/null 2>&1; then
  echo "Branch pushed to origin/${BRANCH}; install gh to open a PR automatically."
  exit 0
fi

if gh pr view "${BRANCH}" --json url >/dev/null 2>&1; then
  gh pr view "${BRANCH}"
else
  gh pr create \
    --base "${BASE_BRANCH}" \
    --head "${BRANCH}" \
    --title "chore(agentforge): scheduled ${PRESET} review (${TIMESTAMP})" \
    --body "$(cat <<EOF
Automated scheduled review via AgentForge (\`${PRESET}\` preset).

**Goal:** ${GOAL}

Deploy record: \`.agentforge/reports/deploy_record.md\`

---
*Opened by \`scripts/scheduled-review-pr.sh\`*
EOF
)"
fi
