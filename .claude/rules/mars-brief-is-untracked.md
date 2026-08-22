---
paths:
  - "MARS.md"
---

# MARS.md is a working document, not a source of truth

**It left version control on 2026-08-18**, joining HISTORY.md, which was already gitignored for the same reason. It is a standing brief for one arc of work rather than a description of the shipped system, so a clone does not have it. (Decided 2026-08-09, while working out where the z7 measurement belonged; acted on once the last tracked citation was re-homed.)

- **Nothing tracked may depend on it, and that is now enforced rather than remembered.** `test_no_reference_to_a_file_a_clone_will_not_have` sweeps every tracked file for `MARS.md`, `MARS §` and a bare `see MARS`, beside the HISTORY and PLAN forms it already carried. Two sabotage cases keep it honest. The `\b` on the bare form is load-bearing: without it the pattern also matches `see MARS_ICE_WHITE` in `palette.py`, which names a reachable constant and must go on passing.
- **A measurement that justifies a tracked constant does not get to live only here.** Put the reason where the constant is — a docstring on the registry field, or the test that pins it — and let this file carry the narrative around it. Checked before the shipped half was cut: all but two facts were already in a docstring.
- **It is a fine home for reasoning nobody's build depends on.** That is the whole of what it is for.
- **It is protected on disk, because git can no longer recover it.** `guard-working-docs.py` snapshots it at session end and on compaction, and restores it if a checkout removes it. That is a real exposure rather than a theoretical one: 16 branches still track the path, and git materialises a tracked version over an ignored working copy SILENTLY, exit 0, which is how six HISTORY entries were once destroyed.
  - **It restores only when the file is MISSING, never when it merely shrank**, because this brief is supposed to shrink: the section describing a phase is deleted the day that phase lands. A shrink prints the backup's path and changes nothing. Both directions were drilled on the real file rather than assumed.
- **It still gets the repo's text invariants.** `tracked_text_files()` folds it back in by name, so the table and fence checks keep running here and are silently absent on a clone. It is deliberately NOT in `CITATION_EXEMPT`: it cites nothing unreachable today, and an exemption added before it is needed is coverage that cannot fire.

The general forms live in the user-scope `docs-earn-their-attention` rule; which file carries dates is in memory `user-facing-docs-stay-dateless`. This rule replaced a memory of the same content, retired 2026-08-17 once every one of its bullets was delivered here instead.
