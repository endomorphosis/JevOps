---
name: jevops-random-forest
description: Rank leftover drafts and search the hierarchical skill tree with a tiny random forest. Use for family→group→skill paths or CALL ptr://skill/port_random_forest / port_skill_tree. Never writes Lean. Lake is the oracle.
---

# Random forest + skill tree

- Forest: `jevops.rankers.train_random_forest` / CALL `ptr://skill/port_random_forest`.
- Tree: `jevops.skill_tree.SKILL_TREE`. Live `decision_tree(tactics)` families merge in.
- Search: `search_with_forest` scores every leaf; returns `ranked_paths` and `pipeline_bias`. JSON-LD of the tree is stored on `nca.jsonld`.
- CALL `ptr://skill/port_skill_tree` for the catalog search alone.

Forest score is not a lake admit. Never docker0.
