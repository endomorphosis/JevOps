---
title: Lean Refactor Arena
emoji: 🌖
colorFrom: yellow
colorTo: blue
sdk: docker
pinned: false
short_description: Two-track multi-objective Lean 4 proof refactoring
---

Lean Refactor Arena — a two-track competition (closed-source LLM / open-source
LLM) for refactoring real Lean 4 proofs from Strata, PhysLib, CSLib, ArkLib,
and PutnamBench to be shorter, cheaper to compile, and more robust across
toolchain versions.

This Space is UI-only: it accepts submissions and displays results. All Lean
compilation and scoring runs on a dedicated evaluation worker that exchanges
jobs and results with the Space through the shared storage bucket mounted at
`/data`.
