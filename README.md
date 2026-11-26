# ZCode Expert System v3.2.5

**English** · [简体中文](README_CN.md)

## 📋 Overview

**ZCode Expert System** is an expert-routing system that runs on **ZCode, Claude Code, and Qoder Desktop**. It ships the full persona prompts of **331 specialists** from [dsh-agency-agents](https://github.com/MichengAI/dsh-agency-agents), adapted with **two-axis routing**: the *scale axis* decides how long a workflow runs, the *domain axis* decides which expert handles it.

The same package deploys to all three hosts. ZCode reads `.zcode-plugin/` and `hooks/hooks.json`; Claude Code reads `.claude-plugin/` and `hooks/claude-hooks.json`; Qoder uses user-level Skills, Commands, Agents, and a merged `settings.json` Hook. All three deployments are isolated — installing on one never modifies the other two.

| Host | Manifest | Hooks config | Sub-agent location | Dispatch name |
|---|---|---|---|---|
| ZCode | `.zcode-plugin/plugin.json` | `hooks/hooks.json` (`type: process`) | `~/.zcode/agents/` | `后端架构师` (Chinese bare name) |
| Claude Code | `.claude-plugin/plugin.json` | `hooks/claude-hooks.json` (`type: command`) | `agents/` inside plugin | `zcode-expert-system:后端架构师` (qualified name) |
| Qoder Desktop | user-level dirs + deployment manifest | `~/.qoder/settings.json` → `UserPromptSubmit` | `~/.qoder/agents/` | `后端架构师` (Chinese bare name) |

## 🏗️ Plugin Architecture

### System Overview

ZCode Expert System v3.2.5 is an expert-routing system for ZCode, Claude Code, and Qoder Desktop. It ships the full persona prompts of **331 specialists** from [dsh-agency-agents](https://github.com/MichengAI/dsh-agency-agents), fused with **Superpowers engineering discipline** and **OpenSpec spec-driven development**. The plugin uses **two-axis orthogonal routing**:

| Axis | Question | Implementation |
|---|---|---|
| **Scale axis** | How long to run (which stages, how many gates) | `zcode_dev_workflow.py` → readonly/light/medium/large/bug, `trim_matrix` + `minimum_gates` |
| **Domain axis** | Which expert handles it | `zcode_expert_system.py` → 32 categories → 331 specialists, `subagent_type` |

**Two axes are independent**: scale decides stage trimming, domain decides `subagent_type`. All tasks (including readonly and mechanical tasks) must complete both-axis triage — domain routing cannot be skipped (W10).

```
User task
  │
  ├─── Scale axis (zcode_dev_workflow.py) ─────────────────────┐
  │    readonly / light / medium / large / bug                 │
  │    → which of the 9 stages to run (trim_matrix)            │
  │    → how many gates must pass (minimum_gates)              │
  │                                                            │
  └─── Domain axis (zcode_expert_system.py) ──────────────────┐
       32 categories → 331 specialists                        │
       → subagent_type (expert display name)                  │
                                                              ▼
                                       Two-axis dispatch plan
```

### Three-Layer Routing (Domain Axis)

Within the domain axis, routing happens in three layers:

```
User task
  │
  ▼
┌─────────────────────────────────┐
│  Layer 1: Task Classification   │
│  32 top-level categories        │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  Layer 2: Domain Manager (32)   │
│  Task decomposition & dispatch  │
│  addressed by slug `manager-<cat>`│
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│  Layer 3: Specialist (331)      │
│  Registered as host sub-agents  │
│  addressed by Chinese display   │
│  name, e.g. "后端架构师"            │
└─────────────────────────────────┘
```

**Dispatch flow**:

1. **Classify** the task into one of 32 categories (`zcode_expert_system.classify_task_detailed`)
2. **Route** to the matching domain manager (`manager-<category>`)
3. **Coarse-screen** candidate specialists in that category (Top-5 by embedding or token-overlap)
4. **Semantic selection** — the controller (host model) must review `top_candidates[].score_detail` and make the final judgment; Python's choice is only token-counting heuristic, not semantic judgment
5. **Dispatch** via `Agent(subagent_type="<specialist display name>")` with a process-contract prefix
6. **Propagate** context across stages via return values

> **Semantic selection contract**: The plugin deliberately does not configure an external LLM/Embedding service — it depends on the model already active in the session. `scripts/llm_client.py` `_call_llm` and `embedding_client.py` `get_embedding` return `None`, so coarse screening degrades to local token-overlap scoring. When `semantic_selection_required=true`, the controller must review `score_detail` and may override with `build_dispatch_for_expert("<specialist name>", task)`. A wrong specialist name raises `ValueError` with the closest matches (difflib suggestion) rather than silently degrading.

**Confidence guard rails** (applied during plan generation):

| Condition | Behaviour |
|---|---|
| `confidence ≥ 0.5` and sufficient margin | Dispatch proceeds, with a `semantic_recheck` action; the controller must inspect `score_detail`. **No blocking is emitted alongside dispatch** |
| `confidence < 0.5` **and** `selection_basis: heuristic` | **Analyst/implementer dispatch is blocked** (`action: blocked_low_confidence` + `plan.blocking` + `clarify_options`); clarify the domain first |
| `confidence_detail.margin < 0.15` | Treated as low confidence — top1/top2 are too close; the winner is only declaration-order / noise |
| `confidence < 0.5`, semantic review already done | Dispatch proceeds, but a `semantic_recheck` action is emitted so the controller re-checks `score_detail` |
| `confidence = 0` | `domain.no_signal = true` — the category is only the `business-support` default, not a real domain judgement |

> `confidence` now means **absolute evidence × top1-top2 margin**: a single 2-character keyword caps at 0.5, a true tie caps at 0.45, and only long composite keywords / multiple evidence can approach 1.0.

> **Word-boundary guards**: `返回500` does not fire on `返回5000行数据` (a trailing numeric segment must not be followed by another digit), and zero-width characters (ZWSP / BOM / soft hyphen) are stripped before matching, so they cannot be used to slip past Bug detection.

### Routing quality (batches 1–4) and the dispatch-evidence gate

Routing accuracy was hardened in four batches; the eval set that pins it lives in
`tests/test_routing_eval.py` (**64 positive cases = 32 categories × 2**, plus
5 hard negatives and 9 specialist top-1 cases; gates are top-1 ≥ 0.95 and
hard-negative correct/blocked ≥ 0.8).

| Batch | What it fixed |
|---|---|
| 1 | Explanation intent ("explain / compare / what is") prefers readonly; a lone "fix" verb with no second fault signal no longer becomes a Bug; quoted meta-labels (≤12 chars, no action verb) stop participating in signal matching |
| 2 | `confidence = absolute evidence × top1-top2 margin` (single 2-char keyword caps at 0.5, a true tie at 0.45); `confidence < 0.5` or `margin < 0.15` emits `blocked_low_confidence` + `clarify_options` and **no** analyst/implementer/reviewer dispatch row; high confidence emits `semantic_recheck` only (the old "blocking text next to a dispatch row" contradiction is gone) |
| 3 | IDF weighting and field de-noising (expert prompt read capped at 800 chars; generic words such as 专家/测试/评估/审计 are filtered in context; `score_detail` exposes `name_idf`/`desc_idf`/`prompt_idf`); composite keywords added (搜索相关性 / 评测集 / 专家路由 / 安装注册 / CLI 工具 …) without harvesting bare 搜索/插件/安装; **category profiles** read from `config/categories.json` — all **32 categories now carry a `description`** (previously only `frontend-client`) |
| 4 | Keyword length weighting: 2 chars 1.0 / 3 chars 1.5 / 4 chars 2.0 / 5+ chars +0.2 each (cap 3.0), so "客户成功流程" outranks "客户成功" |

**Dispatch-evidence gate** (`scripts/workflow_check.py`): the ledger's
`## Dispatches` section and the plan's `## Review` identity lines are now parsed
mechanically, with seven checks — `S5.DISPATCH_IMPLEMENTER` (a completed task with
no implementer dispatch row fails: "the controller edited code itself" cannot
count as done), `S5.DISPATCH_ORPHAN_REPORT`, `S5.IMPLEMENTER_IS_EXPERT`,
`S6.REVIEWER_DISPATCH`, `S6.REVIEWER_DIFFERENT_EXPERT` (same registered expert
name = self-review, regardless of the self-declared category),
`S6.L0_REQUIRES_DISPATCH` and `S6.REVIEW_IDENTITIES`. Deleting the ledger while
briefs/reports remain is itself a failure — deleting evidence is not cleanup.
Covered by `tests/test_dispatch_evidence.py`.

### Role × Specialist Matrix (Workflow Roles)

Workflow roles are **responsibilities**; 331 specialists are **domain capabilities**. They combine orthogonally:

| Role | Dispatched by | Core constraints |
|---|---|---|
| **Orchestrator** | ❌ Controller self-tasks | Sole state writer, runs verification, records Rulings |
| **Implementer** | ✅ Domain specialist | No sub-delegation; cannot exceed brief scope; TDD required |
| **Reviewer** | ✅ **Different-domain** specialist | Read-only; does not trust self-assessment; must give spec + quality dual conclusions |
| **Investigator** | ✅ Domain specialist | Read-only; conclusions carry `file:line` evidence |
| **Analyst** | ✅ Domain specialist | Read-only analysis; four-part "phenomenon → cause → impact → suggestion"; domain judgment not left to controller; view-only tools, no create/delete/modify |

**Process contract takes precedence over specialist persona** — the dispatch prompt's first segment hard-declares this, otherwise architecture-type specialists will re-architect on their own.

### Reviewer Independence

Only 1 of the 331 specialists is "Code Reviewer", so independence cannot rely on "more types". Three guarantees:

1. `type ≠` Implementer (different specialist)
2. `instance ≠` independently dispatched, independent context
3. `input isolation` — only brief / report / change-set, no dialogue context

Independence level must be recorded: **L0** (independent sub-agent, deliverable) / **L1** (controller self-review downgrade, must be declared) / **L2** (no review, delivery prohibited).

### Seven-State State Machine (Single Source of Truth)

`PENDING → IN_PROGRESS → REVIEW → NEEDS_FIX → DONE`, plus `BLOCKED` and `PARKED`. SDD's four statuses (`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`) are **edge labels**, not states — they convert to state transitions immediately.

Key transitions:

| Transition | Trigger | Evidence |
|---|---|---|
| `IN_PROGRESS → REVIEW` | Implementer reports DONE / DONE_WITH_CONCERNS | Non-empty change set + report contains command exit codes |
| `REVIEW → DONE` | Reviewer gives spec ✅ + quality pass | Dual conclusions + controller runs full test suite green |
| `NEEDS_FIX → PARKED` | 5 fix rounds still open, controller decision | Ruling line with cost |
| `DONE → NEEDS_FIX` | Regression breakage found before archive | Real RED output + tasks.md rollback |

Invariants: one task has exactly one state at a time; `DONE` iff tasks.md shows `- [x]`; non-DONE is always `- [ ]` (including PARKED); ledger first line must be `# SDD ledger — plan: <path>`; every DONE traces back to non-empty change set + review conclusions.

### Evidence Levels (Anti-Loss)

| Level | Location | Content | Lifecycle |
|---|---|---|---|
| **P1** | File snapshot hash or git commit | What actually changed | Archived after delivery |
| **P2** | `openspec/changes/<n>/tasks.md` + plan `## Rulings` | Completion, ADR decisions | Permanent after archive |
| **P3** | Plan doc `## Bug Investigation` / `## Baseline` / `## Review` / `## Rulings` / `## Integration Verification` | Root cause, baseline, review, ruling, delivery re-test | With repository |
| **P4** | `.superpowers/sdd/<plan>/` | ledger / brief / report / snapshot | **Deleted after final review; must export to P3 first** |

> **Iron rule: P4 not exported, workspace not deleted.** Otherwise baseline, rulings, and re-test records vanish — this is the spec's most dangerous loss point.

### No-Git-Worktree Parallel Model

The system **does not use Git Worktree**. Conserved relationship:

| Kept parallel | Cancelled parallel |
|---|---|
| ✅ Read-only investigation parallel (multiple unrelated failure investigations by domain) | ❌ **Multi-agent implementation parallel** |
| ✅ Review parallel (multiple Reviewers same batch, read-only, no conflict) | — |

**Reason**: without an isolated workspace there cannot be two writers. Implementation is **always serial** — this is conservation, not conservatism.

**Git is an optional enhancement layer**:

| Detection | Change-set source | Wrap-up |
|---|---|---|
| Has git | `review-package` `BASE..HEAD` diff | Finishing: one of three options |
| No git (default) | File snapshot sha256 difference + changed file full text | Change-list acceptance |

**Snapshot mechanism**: before dispatch, sha256 of each file in the task Files list; after implementation, recompute; difference = added / modified / deleted. The change-set is computed independently by the controller, **not** by the implementer's self-report — this is what makes it trustworthy in a no-git environment.

The controller does **not** run `git init` for the boss's project without permission.

### Conflict Resolutions (10 Rulings, `workflow.json` → `conflict_rulings`)

| # | Ruling |
|---|---|
| W1 | No worktree → no implementation parallel; keep read-only investigation & review parallel |
| W2 | Medium/large task `design.md` is the single source of truth; stage-one does not persist; small tasks land in `docs/superpowers/specs/` marked "non-authoritative" |
| W3 | `apply-change` straight-through and SDD mode are **mutually exclusive**; same change must not mix |
| W4 | Baseline red does not block starting, but must be recorded; later red-item comparison: in-list = pre-existing, out-of-list = introduced by this task |
| W5 | Three evidences: change set + report with command exit codes + **controller runs full suite personally** |
| W6 | Dispatch prompt's first segment hard-declares "process contract takes precedence over specialist persona" |
| W7 | Git detection failure → snapshot evidence + controller self-review (record L1), declare downgrade in delivery |
| W8 | PARKED defaults to **no archive**; "accept not fix" must migrate to a new change |
| W9 | Agent dispatch has no `model` parameter; control cost by **specialist granularity + task granularity**; "upgrade" = switch to a more specialized expert |
| W10 | Two-axis strong serial: all tasks (including readonly and mechanical) scale-then-domain, domain routing not skipped; exemptions only two levels — chit-chat/greeting, boss explicitly exempts and records Ruling |

### Nine-Stage Workflow (Detailed)

Each stage has a clear owner role, gate, evidence level, artifacts, and stop-for-owner checkpoint. `trim_matrix` marks `必` (required), `简` (simplified), `条` (conditional, currently treated as required), `-` (skipped). Scale can only be upgraded, never downgraded.

#### S0 — Requirement Triage (G0, P4)
- **Owner**: Orchestrator (controller)
- **Artifacts**: category conclusion, domain routing result (category + expert name), impact scope identification
- **Gate**: Requirement clear, classified, impact identified, domain routing completed and stated
- **Exit criteria**: Classification stated in session; impact scope identified; no blocking ambiguity; git/openspec root detected and branched accordingly; domain routing completed and stated
- **Fail return**: S0

#### S1 — Requirement Clarification & Design (G1, no evidence level, stop for owner)
- **Owner**: Orchestrator (controller)
- **Components**: zes-brainstorming
- **Artifacts**: 2-3 options comparison + recommendation, acceptance criteria, explicit exclusions (not persisted to design.md, shown in conversation only)
- **Gate**: Boss explicitly approves (yes); acceptance criteria written; exclusions explicit
- **Fail return**: S1

#### S2 — OpenSpec Spec Planning (G2, P2, stop for owner)
- **Owner**: Orchestrator (controller)
- **Components**: zes-openspec-propose, zes-openspec-update-change
- **Artifacts**: `openspec/changes/<change>/proposal.md`, `design.md`, `tasks.md`, `.openspec.yaml`, `openspec/changes/<change>/specs/<capability>/spec.md`
- **Gate**: OpenSpec artifacts complete and boss-reviewed; applyRequires and reachable products via requires edges all done/skipped; seven spec reviews passed
- **Fail return**: S2

#### S3 — Implementation Plan (G3, P3)
- **Owner**: Orchestrator (controller)
- **Components**: zes-writing-plans
- **Artifacts**: `docs/superpowers/plans/<date>-<feature>.md` containing Goal / Architecture / Tech Stack / Spec / Review Focus / Global Constraints / Dependencies / File Scope
- **Gate**: Task decomposition reasonable, dependencies clear, no placeholders (TBD/TODO/"appropriate error handling"); each tasks.md entry has Task承接; execution mode declared (sdd | apply-change)
- **Fail return**: S2

#### S4 — Environment & Baseline Test (G4, P3+P4, stop for owner when baseline red)
- **Owner**: Orchestrator (controller)
- **Components**: baseline-test
- **Artifacts**: `.superpowers/sdd/<plan>/.gitignore`, `progress.md` (first line `# SDD ledger — plan:`)
- **Gate**: Baseline test recorded; baseline failure list persisted (if any); baseline master copy written into plan `## Baseline` section; ledger first line is account identity
- **Fail return**: S4

#### S5 — Code Implementation & Multi-Agent Collaboration (G5 per task, P4→P2)
- **Owner**: Implementer (domain specialist)
- **Components**: zes-sdd + zes-tdd + zes-openspec-apply-change
- **Artifacts**: `task-<N>-brief.md`, `task-<N>-report.md`, `snapshot-before-/after-<N>.json` (no-git: downgraded to non-required)
- **Gate**: brief + report + change-set all ready; review dual conclusions ready (spec conformance + code quality); ledger has Task N done line; tasks.md entry checked; every deviation recorded as Ruling
- **Fail return**: S5; max_fix_rounds 5

#### S6 — Verification & Review (G6+G7, P3)
- **Owner**: Reviewer (different-domain specialist)
- **Components**: zes-verification + zes-code-review
- **Artifacts**: `review-<range>.diff` (git only), `review-<N>.md`
- **Gate**: Five-layer verification passed per task property; verification gate 5 steps executed in this session; reviewer independence marked L0/L1/L2 (L2 prohibits delivery); Rulings list generated and written into plan `## Rulings` section; Critical/Important fixed or ruled
- **Fail return**: S5

#### S7 — Delivery & Integration (G8a, P3, stop for owner)
- **Owner**: Orchestrator (controller)
- **Components**: zes-finishing
- **Artifacts**: `docs/superpowers/plans/<plan>#Integration Verification` section
- **Gate**: Post-integration re-test green (must not reuse old results); delivery method chosen by boss; re-test command and exit code written into `## Integration Verification`
- **Fail return**: S5

#### S8 — Spec Sync & Archive (G8b, P2, stop for owner)
- **Owner**: Orchestrator (controller)
- **Components**: zes-openspec-sync-specs, zes-openspec-archive-change
- **Artifacts**: `openspec/specs/<capability>/spec.md`, `openspec/changes/archive/<date>-<change>/`
- **Gate**: delta unique source = artifactPaths.specs.existingOutputPaths; main spec merged and `openspec validate --specs` passed; completedTasks == totalTasks (only x/X counted); archive dates don't overlap; openspec/ has no uncommitted artifacts
- **Fail return**: S8

#### Scale Trim Matrix (`trim_matrix`)

| Scale | S0 | S1 | S2 | S3 | S4 | S5 | S6 | S7 | S8 |
|---|---|---|---|---|---|---|---|---|---|
| readonly | 必 | - | - | - | - | - | - | - | - |
| light | 必 | 简 | 条 | 简 | 必 | 必 | 简 | 必 | 条 |
| medium | 必 | 必 | 必 | 必 | 必 | 必 | 必 | 必 | 必 |
| large | 必 | 必 | 必 | 必 | 必 | 必 | 必 | 必 | 必 |
| bug | 必 | 条 | 条 | 条 | 条 | 必 | 必 | 必 | 条 |

> `必` = full execution, `简` = simplified, `条` = conditional (currently treated as `必`, see workflow-fusion-design.md section 3), `-` = skipped. **Scale can only be upgraded, never downgraded.**

#### Bug Special Method (zes-systematic-debugging core)

**Iron rule: no root cause, no fix; no failing test, no code change.**

- **Phase 1 Root Cause Investigation** (before touching code): ① Read error & stack trace (line/path/error code); ② Stable reproduction (if can't reproduce, collect more data, don't guess); ③ Check recent changes (git diff/new deps/config changes); ④ In multi-component systems record in/out data at each layer boundary, locate which layer breaks; ⑤ Trace back along call chain to the bad value source (root-cause-tracing), **fix at source not symptom**
- **Phase 2 Pattern Analysis**: Find similar working code in same repo, diff every condition, don't dismiss any difference, clarify dependencies and assumptions
- **Phase 3 Hypothesis & Verification**: State single hypothesis "I believe X is root cause because Y" → minimal test (one variable at a time) → verify; if fails, switch to **new hypothesis**, don't stack fixes on old fix
- **Phase 4 Implementation**: Write failing test first (reproduce) → single fix (no stacking refactoring) → verify (test passes + other tests not broken + problem solved, verification-before-completion before claiming success)
- **3 Failures → Question Architecture**: 3 failed fixes, stop fixing — "every fix exposes a new problem somewhere else" is an architecture signal, discuss with boss whether to refactor, not a 4th attempt
- **Double Confirmation Gate** (boss item): ① Boss picks A/B/C option, no code change before selection; ② After selection, confirm execution ("okay"/"OK" doesn't count, needs explicit verb like "execute/start/fix")
- **Red Flags** (appear → back to Phase 1): "quick fix first", "try changing X see if works", "skip test manual verify", "I roughly know where" — guesswork fixing is the mother of failure

#### Seven-State State Machine (Single Source of Truth)

`PENDING → IN_PROGRESS → REVIEW → NEEDS_FIX → DONE`, plus `BLOCKED` and `PARKED`. SDD's four statuses (`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`) are **edge labels**, not states — they convert to state transitions immediately.

Invariants: exactly one state per task at a time; `DONE` iff tasks.md shows `- [x]`; non-DONE always `- [ ]` (including PARKED); sole state writer = controller; no sub-agent writes state.

### Mechanical Checks (No Reliance on Consciousness)

```bash
python "${CLAUDE_PLUGIN_ROOT:-${ZCODE_PLUGIN_ROOT:-$QODER_PLUGIN_ROOT}}/skills/zcode-expert-system/scripts/workflow_check.py" --change <change> --plan <plan.md> --scale medium
```

Check items: environment detection / spec artifacts / plan required sections / task title format / placeholders / dual-ledger alignment / baseline dual-write / ledger identity / three-element alignment / independence marking / Ruling persistence / post-integration re-test / archive completeness.

Exit code: `0` no FAIL, `1` has FAIL (must not proceed to next stage).

`--expect-archive` supports post-archive verification: when the active
`openspec/changes/<change>/` is gone but the archived copy exists, S2 switches
to `openspec/changes/archive/YYYY-MM-DD-<change>/` instead of failing
`S2.CHANGE_DIR` permanently.

> A pure Markdown checklist will be skipped — it must be mechanically verifiable.

### 32 categories

| Category | Experts | Category | Experts |
|---|---|---|---|
| frontend-client | 8 | supply-chain | 5 |
| backend-architecture | 18 | legal-compliance | 6 |
| data-database | 8 | hr | 7 |
| devops-operations | 7 | finance-tax | 14 |
| ai-llm | 9 | academic-research | 10 |
| embedded-iot | 6 | government-public | 1 |
| network-engineering | 3 | business-support | 6 |
| engineering-quality | 10 | data-knowledge | 2 |
| security-compliance | 19 | game-dev | 21 |
| data-testing | 15 | spatial-computing | 6 |
| design-creative | 14 | gis | 13 |
| marketing-growth | 45 | project-management | 9 |
| paid-media | 7 | product-management | 6 |
| sales-customer | 10 | customer-support | 10 |
| business-strategy | 18 | language-translation | 2 |
| healthcare | 7 | agent-governance | 9 |

## 📦 Installation

The CLI exposes exactly two commands:

```bash
zcode-expert-system install
zcode-expert-system uninstall
```

### install

```bash
npm install -g zcode-expert-system
zcode-expert-system install
```

A multi-select menu appears:

```text
ZCode
Claude Code
Qoder
```

Use `Space` to select one or more targets, then `Enter`. Non-interactive
terminals default to ZCode + Claude Code; select Qoder interactively or pass
`--targets` when scripting:

```bash
zcode-expert-system install --targets zcode
zcode-expert-system install --targets claude-code
zcode-expert-system install --targets qoder
zcode-expert-system install --targets zcode,claude-code,qoder
```

`--dry-run` prints the planned actions without touching disk.

From a cloned source tree, `npm install` only fetches dependencies — it does **not**
create a `zcode-expert-system` binary in `node_modules/.bin`. Run the CLI through
`node` (or `npx .`) instead:

```bash
git clone https://github.com/wutian122/zcode-expert-system.git
cd zcode-expert-system
npm install                 # dependencies only
node bin/cli.js install     # same as `npx . install`
node bin/cli.js uninstall   # same as `npx . uninstall`
```

> **Breaking change:** the CLI is now exactly two commands — `install` and
> `uninstall`. The per-platform subcommands (`cc-install`, `cc-uninstall`,
> `qoder-install`, `qoder-uninstall`, `qoder-status`, `version`, `help`) and the
> `npm run cc:install` / `qoder:install` script aliases have been removed.
> Platform selection happens inside the `install` / `uninstall` menu, or via
> `--targets` / `--zcode --claude-code --qoder`.

Host deployment:

| Host | What is installed |
|---|---|
| ZCode | plugin cache + skill (`~/.zcode/skills/zcode-expert-system`) + commands + hooks + 363 agents + plugin registration + icon marketplace |
| Claude Code | local marketplace `zcode-local` → `claude plugin install` + 363 agents (plugin root `agents/`) |
| Qoder Desktop | user-level `~/.qoder/skills`, `~/.qoder/commands/wf`, `~/.qoder/agents`, merged `UserPromptSubmit` Hook in `~/.qoder/settings.json` |

Each host deployment carries the full runtime set — `scripts/workflow_check.py`
(mechanical gate checker, including the dispatch-evidence gate),
`config/categories.json` (32 category profiles with descriptions),
`config/experts.json`, `config/workflow.json`, `templates/`, `references/`,
`hooks/`, `SKILL.md` and the three root Python entry points. Claude Code
additionally ships `context/` and `bin/`; Qoder additionally merges the
`UserPromptSubmit` Hook.

Every installer **verifies the deployed copy** and exits non-zero if a runtime
component is missing — a partial copy never reports success:

```text
✅ ZCode 技能部署校验通过：workflow_check / categories(32 类) / templates / references 均在位
```

> Claude Code registration requires the `claude` CLI. The installer builds a local
> marketplace and runs `claude plugin marketplace add` / `claude plugin install`;
> copying files without registration will not make the plugin appear in `/plugin`.
> If the CLI is missing, files are copied to the legacy cache but a warning is printed —
> that copy is **not** loaded by Claude Code. After a successful install, run
> `/reload-plugins` or restart Claude Code.

`--dry-run` runs the same source-tree preflight (missing `templates/`,
`references/`, `scripts/workflow_check.py` or category descriptions fail with a
non-zero exit) but only prints planned actions — it never claims an install
completed. The Claude Code path also fails closed when the plugin is registered
but absent from `settings.json.enabledPlugins`: you get a non-zero exit with the
hint to enable it via `/plugin` (or `/reload-plugins`) instead of a success banner.
The preflight also rejects `.claude-plugin/plugin.json` when it declares an
`agents` field: Claude Code requires that field to be a single `.md` path, and a
directory declaration makes the whole plugin fail to load; the 363 agents are
registered by convention-based scanning of `agents/`.

Restart the selected host after installation (the Agent list is loaded at session start).

### uninstall

```bash
zcode-expert-system uninstall
```

The same multi-select menu appears:

```text
ZCode
Claude Code
Qoder
```

Detected hosts are pre-selected. Press `Enter` to remove the selected plugin
files, commands, Agents and Hook/registration entries.

- **Claude Code**: unregisters the plugin, removes the `zcode-local` marketplace
  registration and directory, then deletes this plugin's two cache
  subdirectories (`cache/zcode-local/zcode-expert-system` and the legacy
  `cache/claude-plugins-official/zcode-expert-system`). Other plugins' caches
  are never touched. If the `claude` CLI is unavailable or the uninstall command
  fails, the installer falls back to editing `installed_plugins.json`,
  `settings.json.enabledPlugins` and `known_marketplaces.json` directly (this
  plugin's keys only); if any registration entry survives, it exits non-zero and
  does **not** claim completion.
- **Qoder**: removes only files this plugin owns (deployment manifest, or the
  `<!-- zcode-expert-system:qoder-adapter -->` ownership marker when the
  manifest is lost). User commands/agents with the same name are preserved, and
  only this plugin's `UserPromptSubmit` entry is removed from
  `~/.qoder/settings.json`. Backups and the runtime context store are kept by
  default; `--purge` deletes them.
- **ZCode**: manifest-driven deletion only (never prefix sweeps), with the old
  skill directory backed up before overwrite. `skills/zcode-expert-system.bak-*`
  backups are cleaned automatically only when they contain nothing but plugin
  output; a backup holding user-added files is kept and its path is printed.
  `--purge` additionally removes those backups and
  `~/.zcode/expert-system/context/`.

In a non-interactive terminal the historical default remains Claude Code + ZCode.

## ⚙️ Configuration

### No separate LLM/Embedding service needed

The plugin uses **the model already active in your session**:

- **Classification**: current session model
- **Expert selection**: current session model
- **Coarse screening**: Embedding when available, otherwise token-overlap scoring

> Accuracy improves automatically as your session model improves — nothing to configure.

### Fallback behaviour

- **LLM unavailable** → longest-keyword match + token-overlap scoring
- **Embedding unavailable** → token-overlap scoring (name weighted 3×, plus description and prompt content)

Both fallbacks run locally with no network dependency; routing never fails.

**Runtime context is host-scoped**:

| Host | Context directory |
|---|---|
| ZCode | `~/.zcode/expert-system/context/` |
| Claude Code | `~/.claude/expert-system/context/` |
| Qoder | `$QODER_HOME/expert-system/context/` |

`ZCODE_EXPERT_CONTEXT_DIR` can override the location for tests or custom deployments.
The test suite sets it per test, so pytest never writes into a real user context store.

**Expert name visibility**: every dispatch plan includes `display_name` / `display_label`;
the controller must announce `正在调用专家：<专家名>` and pass
`description = "专家：<专家名>"` to `Agent` / `Task`. Plans, dispatch orders and
readonly audit artifacts all carry the same expert name.

## 🚀 Usage

### Invoking the expert system

Just describe a professional task in any supported host session (ZCode, Claude Code, or
Qoder Desktop) — the `UserPromptSubmit` hook injects the routing rules automatically and
the skill triggers on domain keywords.

Explicit entry points that actually exist:

| Entry | What it does |
|---|---|
| `Skill(zcode-expert-system)` | Invoke the skill with a task description |
| `/wf:triage <task>` | Dual-axis triage: scale + domain routing in one call (readonly/light/medium/large/bug; readonly dispatches analyst with view-only tools) |
| `/wf:plan <task>` | Full dispatch plan (role × expert) |
| `/wf:check` | Mechanical gate check on the current change/plan |

> Note: there is **no** `/zcode-expert-system` slash command. The plugin's `commands/`
> namespace only contains the `/wf:*` family (`commands/wf/*.md`).

What happens:

1. Task is classified (e.g. `backend-architecture`)
2. Domain manager is resolved (`manager-backend-architecture`)
3. Best-matching specialist is selected from that category
4. An executable dispatch order is returned (`status: pending_dispatch`)
5. The controller dispatches via `Agent(subagent_type="后端架构师")`
6. Context flows across stages

### Categories covered

| Category | Description |
|---|---|
| frontend-client | Frontend & client apps |
| backend-architecture | Backend & architecture |
| data-database | Data & databases |
| devops-operations | DevOps & operations |
| ai-llm | AI & large models |
| embedded-iot | Embedded & IoT |
| network-engineering | Network engineering |
| engineering-quality | Engineering quality |
| security-compliance | Security & compliance |
| data-testing | Data & testing |
| design-creative | Design & creative |
| marketing-growth | Marketing & growth |
| paid-media | Paid media |
| sales-customer | Sales & customer |
| business-strategy | Business & strategy |
| healthcare | Healthcare |
| supply-chain | Supply chain & logistics |
| legal-compliance | Legal & compliance |
| hr | Human resources |
| finance-tax | Finance & tax |
| academic-research | Academic research |
| government-public | Government & public service |
| business-support | Business support services |
| data-knowledge | Knowledge services |
| game-dev | Game development |
| spatial-computing | Spatial computing & XR |
| gis | Geographic information systems |
| project-management | Project management |
| product-management | Product management |
| customer-support | Customer support |
| language-translation | Language & translation |
| agent-governance | Agent identity & governance |

Full rosters live in each manager's "管辖范围" (scope) table, or in `config/experts.json`.

## 🤖 Registered sub-agents

After installation, all three hosts can dispatch **363 sub-agents**:

| Host | Managers | Specialists | Location | Dispatch |
|---|---|---|---|---|
| ZCode | 32 | 331 | `~/.zcode/agents/` | `Agent(subagent_type="后端架构师")` |
| Claude Code | 32 | 331 | plugin `agents/` | `Agent(subagent_type="zcode-expert-system:后端架构师")` |
| Qoder Desktop | 32 | 331 | `~/.qoder/agents/` | `Agent(subagent_type="后端架构师")` |

> Note: managers are addressed by their **slug** (`manager-<category>`), because
> the installers write `name: "<slug>"` into the deployed agent frontmatter.
> Specialists are addressed by their **Chinese display name**. Mixing the two up
> makes the `Agent` call fail to resolve. Claude Code additionally uses the
> plugin-qualified form `zcode-expert-system:<name>`.

> `subagent_type` takes the **display name** (the `name:` field in the agent markdown).
> If a name is missing from the session's agent list, fall back to reading that expert's
> prompt file and adopting its persona directly.

⚠️ **Restart the selected host after changing agent files** — the agent list is a snapshot
taken at session start; additions or edits made mid-session are not picked up.

## 📁 Project layout

```
zcode-expert-system/
├── .zcode-plugin/plugin.json           # Plugin manifest
├── .claude-plugin/plugin.json          # Claude Code manifest
├── SKILL.md                            # Skill entry (all hosts)
├── README.md / README_CN.md            # English / Chinese docs
├── zcode_expert_system.py              # Domain axis (32 categories → 331 experts)
├── zcode_dev_workflow.py               # Scale axis (triage → stages → dispatch plan)
├── skill_entry.py                      # Skill invocation wrapper
├── package.json                        # npm package config
├── src/
│   └── auth/                           # jwt-auth-system (openspec, in progress; not shipped — UNPACKED_COMPONENTS)
├── scripts/
│   ├── install.js                      # Unified deploy / uninstall (ZCode + Claude + Qoder target)
│   ├── install-claude-code.js          # Claude Code deploy (preflight + backup + rollback)
│   ├── cc-uninstall.js                 # Claude Code uninstall
│   ├── install-qoder.js                # Qoder user-level deploy / status / uninstall
│   ├── workflow_check.py               # Mechanical gate checker (+ --self-check)
│   ├── openspec_engine.py              # OpenSpec change/spec engine
│   ├── llm_client.py                   # LLM call helper
│   └── embedding_client.py             # Embedding client
├── config/
│   ├── experts.json                    # 331 expert records
│   ├── categories.json                 # 32 category definitions
│   └── workflow.json                   # Single source of truth: stages/gates/states/trim
├── commands/
│   └── wf/*.md                         # 12 slash commands (/wf:triage, /wf:check, …)
├── references/
│   ├── stage-S0..S8*.md                # 9 stage specs
│   ├── roles/*.md                      # 4 role contracts (orchestrator/implementer/reviewer/investigator)
│   └── workflow-tree.md                # Workflow tree & recovery
├── templates/
│   ├── plan-sections.md                # Plan doc template (12 required sections)
│   ├── progress.md                     # SDD ledger template (7-state)
│   └── *.md                            # task-report / review-report / bug-report / minimal-contract
├── docs/
│   └── workflow-fusion-design.md       # Design baseline (why this architecture)
├── context/
│   └── context-manager.py              # Context manager (data in ~/.zcode/expert-system/context/)
├── tests/                              # Regression tests (pytest, 817 passed / 1 skipped)
├── hooks/
│   ├── hooks.json                      # Hook config (ZCode standard schema)
│   ├── claude-hooks.json               # Hook config (Claude Code format)
│   └── prepend-global-rules-reminder.mjs  # Injects trigger rules before each prompt
└── agents/
    ├── manager-*.md                    # 32 domain manager definitions
    └── expert-*.md                     # 331 expert persona prompts
```

## 🛠️ Development

### Local development

```bash
git clone https://github.com/wutian122/zcode-expert-system.git
cd zcode-expert-system

# Run routing only (no dispatch)
python zcode_expert_system.py "Design a high-concurrency backend API"

# Check classification
python -c "from zcode_expert_system import zcode_expert_system; print(zcode_expert_system('run a penetration test')['category'])"
```

### Contributing

1. Fork this repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Commit your changes: `git commit -m 'feat: add your feature'`
4. Push the branch: `git push origin feat/your-feature`
5. Open a Pull Request

Before opening the PR, make sure the full regression suite is green:

```bash
python -m pytest tests/ -q   # must end with "passed", 0 failed
```

Expected baseline: **817 passed, 1 skipped** — 801 runtime cases (v3.2.5 baseline:
Claude registration + S1/P3 + routing batches 1-4 + dispatch gate), plus 9
deployment-integrity guards that pin the three-host runtime-component checks and
uninstall symmetry, plus 7 install/uninstall safety guards added by the review
batch (user-file backup preservation on `--zcode` uninstall and `--purge`,
Claude ghost-registration cleanup without the `claude` CLI, Claude dry-run
preflight + no "install complete" wording, and fail-closed when `enabledPlugins`
is missing).

> The 817 count is from the full development tree. The GitHub runtime release
> intentionally ships the runtime file set only and does not add or update
> `tests/` or `docs/`; a clone that excludes the development tests will not
> reproduce this exact count. The runtime release is still verified locally with
> the full suite before publishing.

> Note on `src/auth/`: the JWT auth module (`jwt-auth-system` OpenSpec change) is under
> construction and covered by `tests/test_auth_login.py`. Its implementation choices are
> deliberate: password hashing is **PBKDF2-HMAC-SHA256, 100 000 iterations**, 16-byte
> random salt, stored base64(`salt||dk`) (bcrypt is a documented fallback, not a
> dependency); refresh tokens are **`secrets.token_urlsafe(32)`** (256-bit entropy) and
> only their **sha256 hash** is persisted; `expires_at` is stored and parsed as an
> **ISO 8601 string** via `datetime.fromisoformat`; JWT verification parses the header
> and whitelists **`alg=HS256` and `typ=JWT`** before checking the signature.

## 📄 License

Released under the [MIT License](LICENSE).

## 🔗 引用来源与开源依赖

本项目在以下开源项目与能力体系的基础上进行了 ZCode / Claude Code / Qoder 平台适配与工程化改造：

| 来源 | 用途 | 项目地址 |
|---|---|---|
| **dsh-agency-agents** | 331 位专家完整人格提示词（专家库来源） | https://github.com/MichengAI/dsh-agency-agents |
| **Superpowers** | 工程能力体系（brainstorming、writing-plans、sdd、tdd、verification、code-review、finishing 等能力） | 待项目方补充 GitHub 地址 |
| **OpenSpec** | 规格驱动开发体系（change 提案、规格同步、归档工作流） | 待项目方补充 GitHub 地址 |

本项目在此基础上增加了三平台适配与工程化改造：三层路由架构（分类 → 总经理 → 专家）、两轴正交路由（规模轴 + 域轴）、九阶段受控工作流、机械门禁核对、七态状态机、证据分级与冲突裁决。

## 🙏 Acknowledgements

Expert persona prompts come from the [dsh-agency-agents](https://github.com/MichengAI/dsh-agency-agents)
open-source project. This plugin adds ZCode / Claude Code / Qoder adaptation and engineering
work: three-layer routing, domain manager task decomposition, and dynamic expert dispatch.

## 📞 Contact

Questions or suggestions? Open a GitHub Issue.

---

**ZCode Expert System v3.2.5** — smarter collaboration between AI experts 🚀
