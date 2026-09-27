# Strategic AI Agents in a Simulated Courtroom

**Team Saul Goodman** · Track: Demo · Domain: Agents & Game Theory

**Live demo:** <https://saul-goodman-courtroom.vercel.app>

Prosecution and defense agents compete to build the strongest case from structured, synthetic
evidence. A **100 % deterministic, exact-arithmetic judge** rules on objections, weighs evidence
element by element, and delivers a verdict with a hash-chained audit trail. A game-theory layer
estimates payoff matrices by Monte-Carlo and solves them for **exact rational Nash equilibria**.
Everything can be watched live in a terminal dashboard or a web UI.

```bash
pip install -e ".[dev]"
python -m courtroom run --live                      # animated terminal replay of the flagship case
python -m courtroom game --case helix-espionage     # payoff matrix + exact Nash equilibria
python -m courtroom serve                           # web UI + API on http://127.0.0.1:8000
python -m courtroom verify -p chaos -d adaptive     # prove bit-for-bit determinism
python -m courtroom stress --cases 100              # 2,500-trial fuzz run, exits 1 on any failure
python -m pytest                                    # 483 tests, ~15 s
```

The hosted demo is the static web UI (`courtroom/viz/web`, see `vercel.json`) running on the
pre-exported bundle, so it offers seed-0 trials for six strategy pairings per case plus the 2×2
Aggressive/Conservative games. Run `python -m courtroom serve` locally for the live API (any seed,
any pairing, mixed strategies, larger games). After changing cases, agents or
judge constants, run `python -m courtroom export` and redeploy.

## What the demo shows

| Case | Phenomenon | Equilibrium (2×2, Aggressive/Conservative) |
|---|---|---|
| `helix-espionage` (flagship) | Matching-pennies structure: aggressive prosecution beats a passive defense; an aggressive defense punishes it | **Mixed** NE, P ≈ 42 % aggressive, D ≈ 92 % aggressive, no dominant strategy; replicator dynamics orbit the NE |
| `kestrel-av` (civil) | Arms race: aggression is strictly dominant for the plaintiff | Pure NE (Aggressive, Aggressive), flagged dominance-solvable |
| `aurora-defi` | Strong white-hat defense: aggression only burns budget | Pure NE (Conservative, Conservative), flagged dominance-solvable |
| `edge-empty-docket` | Zero evidence | Directed acquittal (rule DV-2) under every strategy pairing, including Chaos |
| `edge-mutual-exclusion` | Two equally credible, contradictory witnesses | Exactly symmetric discount → log-odds exactly `0` → not liable (strict preponderance) |
| `edge-poisoned-tree` | Every exhibit defective | Objecting defense wins; passive defense can still lose |
| `edge-defense-only` | Only exculpatory evidence | Sua-sponte directed acquittal |

The analyzer reports triviality honestly instead of hiding it. Tuning notes are in
[`docs/DESIGN.md`](docs/DESIGN.md).

## How the judge decides (deterministic, auditable)

For each legal element `e`, over admitted items only:

```
S_i   = reliability × witness credibility (halved per successful impeachment)
disc_i = min(9/10, Σ_{j contradicts i} (4/5)·S_j/(S_i+S_j))       symmetric → order-independent
corr  = 1 + ½(1 − 2^-k), k = other facts with same-sign support     bounded → no evidence spam
L_e   = prior + 3 · Σ_{one item per fact} support·S·(1−disc)·corr   exact Fraction arithmetic
verdict = GUILTY/LIABLE iff every element's L_e clears the standard (conjunctive test)
```

Thresholds are exact rationals: beyond reasonable doubt `11/5` (p≈0.90), clear and convincing
`11/10`, preponderance `> 0`. Floats appear only on display fields, never in a decision.
Every ruling carries a rule ID (`OBJ-HEARSAY`, `DV-2`, `STALL-1`, `CONTEMPT-1`, …), and every event is
chained with `h_n = SHA256(h_{n−1} ‖ event_n)`.

## Step 2: seven-engineer architecture

```
                        ┌──────────────────────────────┐
                        │ E1 contracts/ (Pydantic v2)  │  shared, frozen data contracts
                        └──────────────┬───────────────┘
      ┌───────────────┬────────────────┼────────────────┬────────────────┐
      ▼               ▼                ▼                ▼                ▼
 E1 cases/       E3 judge/        E2 procedure/     E4 agents/       E5 gametheory/
 library,        admissibility,   FSM, validator,   oracle, Bayesian payoff MC, exact
 generator       exact scoring,   ledgers           perception,      Nash, IESDS,
                 DV, verdict                        policies, chaos  replicator, stress
      └───────────────┴──────────┬─────┴────────────────┘                │
                                 ▼                                       │
                       E6 engine/ + api/ + cli  ◄────────────────────────┘
                       orchestration, fault barrier, audit chain, HTTP
                                 │  TrialResult / PayoffTable (read-only)
                                 ▼
                       E7 viz/  terminal dashboard (rich) + web UI (vanilla JS)
```

| # | Owner of | Package | Public contract | Tests they defend |
|---|---|---|---|---|
| E1 | Contracts & case library | `contracts/`, `cases/` | `CaseFile`, `EvidenceItem`, `Action`, `TrialEvent`, `TrialResult`… | `test_contracts_and_cases.py` |
| E2 | Procedure & objection arbiter | `procedure/` | `ProcedureState.expected()`, `validate() → Violation \| None` | `test_procedure.py` |
| E3 | Deterministic judge | `judge/` | `Judge.rule_on_objection / directed_verdict_review / deliberate`, `score_record` | `test_judge.py` |
| E4 | Strategic agents | `agents/` | `Agent.act(PartyView, Oracle) → Action`, `make_agent(name, rng)` | `test_agents.py` |
| E5 | Game theory & tournament | `gametheory/` | `estimate_payoffs → PayoffTable`, `analyze → GameAnalysis`, `stress → StressReport` | `test_gametheory.py` |
| E6 | Engine, API, CLI | `engine/`, `api/`, `cli.py` | `run_trial → TrialResult`, `/api/*` | `test_engine.py`, `test_api.py` |
| E7 | Visualisation | `viz/` | consumes `TrialResult`/`PayoffTable` only; never calls the engine | `test_api.py::test_ui_is_served` + manual |

Dependency rule: arrows only point down. The judge knows nothing about agents, agents see the judge
only through the read-only `Oracle`, and visualisation can't influence outcomes.

## Robustness guarantees (Demo-track feedback)

* **Weak/no evidence**: prior-only scoring, mandatory directed-verdict review (DV-2 sua sponte).
* **Contradictions**: symmetric discount; permutation-invariance test.
* **Bad-faith actions**: 11 typed violation rules; violation → PASS + fine + sanction; 3 → contempt.
* **Loops/deadlocks**: one-action response windows (an objection can't be objected to), stall rule,
  turn caps, global watchdog.
* **Agent crashes**: caught at the fault barrier (V-AGENT-FAULT), including in `opening_statement()`.
* **Demo infrastructure**: the web UI falls back to a pre-exported bundle (`data/bundle.js`), works from `file://`, and uses `no-cache` headers.
* **Verified**: 2,500-trial fuzz (including the Chaos agent): 0 crashes, 0 invariant violations, 250/250 replays bit-identical.

*All cases, people, and organisations are synthetic. This is a stylised model and not legal advice.*
