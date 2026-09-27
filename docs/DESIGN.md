# Step 1 — First-Principles Design Dialectic

Team **Saul Goodman** · Track: Demo · Domain: Agents & Game Theory

This document records the self-critique of the baseline concept ("prosecution and
defense agents with aggressive/conservative strategies, judged by a rule-based
judge") and the upgraded specification the code implements. Every upgrade below
is traceable to a module and a test.

---

## 1. Baseline, restated

Two agents (Prosecution `P`, Defense `D`) take turns adding evidence to a record.
Each follows a strategy (Aggressive / Conservative). A deterministic judge reads
the record and returns a verdict.

## 2. Interrogation of the baseline — failure modes found

| # | Weakness in the baseline | Why it matters | Upgrade (module) |
|---|---|---|---|
| F1 | **Free objections ⇒ "always object" is dominant.** | 2×2 game collapses to a trivial dominant-strategy equilibrium; nothing to demo. | Objections cost budget; *overruled* objections carry a sanction (utility penalty). (`procedure`, `agents`) |
| F2 | **Free presentation ⇒ "dump everything" is dominant.** | Same collapse on the prosecution side. | Finite litigation budget, per-kind costs, per-phase turn caps, bad-faith sanctions for knowingly presenting unlawfully obtained / undisclosed items. (`procedure`) |
| F3 | **"Rule-based judge" can still be subjective** (hand-tuned weights, float rounding, order-dependent tie-breaks). | Feedback explicitly: winning must not be subjective. | Judge computes in **exact rational arithmetic** (`fractions.Fraction`), in log-odds space; every step emits a rule ID; the verdict is a pure function of the record. (`judge`) |
| F4 | **Floating-point non-determinism** across machines. | "Bit-for-bit identical" is impossible with `exp()`. | Verdict decided by comparing an exact rational log-odds with an exact rational threshold. Probabilities are computed only for display. (`judge.numeric`) |
| F5 | **Order-dependent contradiction resolution** ("whoever spoke last wins"). | Same evidence, different order ⇒ different verdict: indefensible. | Symmetric pairwise discount formula; proven by a permutation-invariance test. (`judge.scoring`) |
| F6 | **Evidence piling** (20 weak items beat 1 strong item; duplicates count twice). | Rewards spam, a degenerate strategy. | Cumulative-evidence rule (one item per underlying `fact_id` per element) + bounded, diminishing corroboration bonus `1 + α(1 − 2^-k)`. (`judge.scoring`) |
| F7 | **Single-number burden** hides that crimes have *elements*. | A strong motive can't substitute for missing proof of the act. | Conjunctive element test: conviction iff **every** element clears the standard. Burden gauge = weakest element. (`judge`) |
| F8 | **Zero / weak evidence crashes or produces "0/0"**. | Demo-track robustness requirement. | Prior-only log-odds (presumption of innocence), mandatory directed-verdict review after the prosecution rests (sua sponte rule DV-2 even if the defense never moves). (`judge`, `procedure`) |
| F9 | **Infinite objection loops** (object to the objection…). | Deadlock during a live demo. | Structural impossibility: a response window admits exactly one action (`OBJECT` or `PASS`); objections are not objectionable; contemporaneous-objection rule. Plus a global watchdog. (`procedure`) |
| F10 | **Turn-passing deadlocks.** | Both sides pass forever. | Two consecutive passes ⇒ deemed `REST`; per-phase turn caps; global event cap ⇒ forced deliberation with an audited `WATCHDOG` rule. (`procedure`) |
| F11 | **Bad-faith / malformed agent actions** (unknown IDs, wrong turn, agent exceptions). | A crashing agent kills the demo. | Every action is validated against a typed rule table; violations are converted to `PASS`, fined, and logged; 3 violations ⇒ contempt (forced rest). Agent exceptions are caught and treated as violations. Fuzzed with a Chaos agent. (`procedure`, `engine`) |
| F12 | **Perfect information** makes objection decisions trivial. | No uncertainty ⇒ no strategy. | Opponent perceives each potential defect through a seeded noisy channel (accuracy `a`, default 0.8). Objecting is a decision under uncertainty. (`agents.perception`) |
| F13 | **Winner-take-all payoffs** ignore cost, so the game is constant-sum and uninteresting. | Real litigation trades win probability against cost and sanctions. | Utility `U = V·win − c·spent − μ·sanctions` ⇒ a general-sum bimatrix game. (`gametheory.payoff`) |
| F14 | **"Nash equilibrium" claimed, not verified.** | A reviewer will ask "prove it". | Exact rational support-enumeration solver + independent best-response verifier + iterated elimination of dominated strategies + a triviality diagnosis. (`gametheory.nash`) |
| F15 | **Real legal data**. | Ethical/representational risk (feedback). | Only synthetic cases (corporate cyber-espionage, DeFi exploit, AV liability) + a procedural case generator. Names are fictional. (`cases`) |
| F16 | **Demo depends on network/server.** | Live demos fail. | Web UI is dependency-free vanilla JS, falls back to a pre-exported JSON bundle if the API is down; a terminal dashboard also exists. (`viz`) |

## 3. Upgraded specification

### 3.1 Procedure: finite state machine

```
OPENING → PROSECUTION_CASE → DIRECTED_VERDICT_REVIEW ─(granted)→ DELIBERATION → CLOSED
                                     │(denied)
                                     ▼
                              DEFENSE_CASE → REBUTTAL → DELIBERATION → CLOSED
```

* In a *case phase* the active party takes a **primary** action
  (`PRESENT_EVIDENCE`, `IMPEACH`, `PASS`, `REST`).
* Every `PRESENT_EVIDENCE` opens a **response window** for the opponent: exactly
  one of `OBJECT(ground)` or `PASS`. Then the judge rules and the window closes.
* `REBUTTAL` is scope-limited: the prosecution may only present items that
  contradict admitted defense evidence, max 2 primary turns.
* Termination is guaranteed: each phase has a turn cap `T`, each primary turn
  consumes a turn whether legal or not, and the whole trial has an event cap.
  Worst case length is `O(phases × T)`.

### 3.2 Admissibility: waiver doctrine

Defects are **only** excluded when the opponent objects on the right ground
(as in real procedure — an unobjected defect is waived). This is what makes
objection strategy matter.

| Rule | Ground | Sustained iff |
|---|---|---|
| OBJ-HEARSAY | hearsay | `item.hearsay` |
| OBJ-RELEVANCE | relevance | `max_e |support_e| < 1/20` |
| OBJ-AUTH | authentication | `not item.authenticated` |
| OBJ-EXCLUSIONARY | illegally obtained | `not lawfully_obtained` **and** owner = prosecution **and** criminal case |
| OBJ-DISCLOSURE | late disclosure | `not item.disclosed` |
| OBJ-SPECULATION | speculation | testimony **and** `not personal_knowledge` |

Sanctions: overruled objection `1/4` point; procedural violation `1` point +
budget fine; sustained OBJ-EXCLUSIONARY or OBJ-DISCLOSURE against the presenter
`2` points (bad faith: the presenter *knew*, so it is worse than a slip).

> **Calibration note.** At 1 point the flagship game was knife-edge: the
> prosecution's two strategies differed by 0.01 utility against an aggressive
> defense, so the equilibrium flipped between "mixed" and "dominance-solvable"
> depending on the Monte-Carlo seed range. At 2 points the mixed equilibrium
> holds on five disjoint seed ranges (margin +0.30 … +2.04). A regression test
> pins this.

### 3.3 Scoring: exact log-odds

For each element `e` with admitted items `A`:

```
S_i       = reliability_i × credibility_i                     (credibility = witness base × (1/2)^impeachments)
disc_i    = min(9/10, Σ_{j ∈ contra(i) ∩ A}  β · S_j / (S_i + S_j))        β = 4/5
corr_ie   = 1 + α (1 − (1/2)^k),  k = #admitted items, other fact, same sign on e   α = 1/2
w_ie      = support_ie × S_i × (1 − disc_i) × corr_ie
L_e       = prior + K · Σ_{fact f} w*_fe                     K = 3, w* = strongest item per fact (cumulative rule)
met_e     = L_e ≥ τ   (strict > for preponderance)
```

| Standard | τ (log-odds) | ≈ probability |
|---|---|---|
| Beyond reasonable doubt | 11/5 | 0.90 |
| Clear and convincing | 11/10 | 0.75 |
| Preponderance | 0 (strict) | > 0.50 |

Prior: criminal `−1` (presumption of innocence, p≈0.27); civil `0`.

Properties we test for:
1. **Determinism.** Same seed and case give the same SHA-256 hash chain.
2. **Permutation invariance.** The scores don't depend on the order items were admitted in.
3. **Monotonicity.** Adding an admitted item with positive support never lowers `L_e`, provided the item contradicts nothing.
4. **No single-item conviction.** In a criminal case one perfect item gives `−1 + 3 = 2 < 11/5`. You need corroboration.
5. **Zero evidence.** `L_e = prior` for every element, so the verdict is an acquittal, with no division anywhere.

Directed verdict (after the prosecution rests):
* DV-1 (if the defense moves): granted if any element has `L_e < 0`.
* DV-2 (sua sponte, always checked): granted if any element has no admitted
  item with positive support.

### 3.4 Agents

Agents are expected-utility policies over a **public, deterministic scoring
oracle** (the judge is transparent, so agents can simulate "what if this item
were admitted"). What they don't know is whether the opponent will object, and
whether the opponent's evidence has defects.

| Profile | Presents known-defective items | Objects when belief ≥ | Min. impact to object | Budget reserve |
|---|---|---|---|---|
| Aggressive | yes (≤2 defects) | 0.35 | 0 | 0 % |
| Conservative | no | 0.70 | 0.25 log-odds | 25 % |
| Adaptive | EV-based, learns opponent objection rate (Beta posterior) | EV > 0 | EV-based | 10 % |
| Mixed(p) | samples Aggressive w.p. p per trial | — | — | — |
| Chaos | random, frequently illegal, occasionally raises | — | — | — |

### 3.5 Game-theoretic layer

* Payoff estimation: Monte-Carlo over seeds, giving a bimatrix `(A, B)` with means and standard errors.
* Solver: exact rational support enumeration, pure-NE scan, IESDS, dominance
  diagnosis, and an independent verifier that checks no unilateral deviation pays.
* Two-population replicator dynamics for the "evolution of legal culture" chart.
* **Honesty clause.** Some cases *do* have dominant strategies. The analysis reports
  that fact instead of hiding it. The case library is tuned so the flagship case does not.

### 3.6 Audit trail

Every event is canonical JSON, hashed as `h_n = SHA256(h_{n−1} ‖ event_n)`.
The trial digest is `h_last`. `courtroom verify` re-runs the trial and compares
digests.

## 4. Residual risks (accepted)

* Support enumeration is exponential. That's fine for ≤ 5×5 strategy sets, which is all we use.
* Degenerate games may have continua of equilibria. The solver reports the
  extreme points it finds and flags degeneracy.
* The model is a *stylised* court. It demonstrates game-theoretic
  reasoning and is not legal advice.
