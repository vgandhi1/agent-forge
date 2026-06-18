# Security notes

Controls enforced today, and the rules to keep when extending AgentForge — especially in
`--target-repo` mode, where the agents read and write a real repository outside the greenfield
`workspace/` sandbox.

## Target-repo mode

- **Path containment.** The target path must exist and be a directory; reads/writes resolve under
  the explicit `--target-repo` (or workspace) root. All file access goes through `ArtifactStore`,
  which rejects path traversal / escapes outside the root.
- **Bounded inspection.** `grep_code` / `read_file` return bounded output (max bytes, max matches,
  paginated line windows) so a worker cannot pull an unbounded blob into the model context.
- **No credential forwarding.** Never forward host-assistant auth tokens into AgentForge's own LLM
  calls. AgentForge runs its own provider pass with its own key (`ANTHROPIC_API_KEY`) or Ollama.
- **Commit is opt-in.** Git commit happens only with `--deploy-commit` (on a branch via
  `--deploy-branch`); there is no automatic `git push`. Pushing/PR is left to the external wrapper
  (see [`scheduled-review.md`](scheduled-review.md)).
- **Metadata isolation.** AgentForge writes its run metadata under `<repo>/.agentforge/`. Add that
  directory to the target repo's `.gitignore` so run artifacts don't leak into commits.
- **Execution is profile-fixed.** `run_tests` / `run_lint` execute only the operator-configured
  `profile.verify_cmd` / `profile.lint_cmd` — never an arbitrary shell string the model supplies.

## Logging

- Never log secrets (`ANTHROPIC_API_KEY`, tokens). Wrapper scripts and CI must not echo credentials.
- Structured events (`AGENTFORGE_JSON_LOG`) carry status/role/counts, not payloads that could
  contain secrets.

## Future work (Phase C)

- **Web search for API docs (SSRF):** when added, resolve DNS + enforce an allowlist of hosts and
  ports (HTTP/HTTPS only), and never fetch a raw user-/model-supplied URL without validation.
