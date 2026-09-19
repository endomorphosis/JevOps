---
name: jevops-graph
description: Board-graph traversal, GraphRAG search, and milles neural message-passing. Use for GraphRAG, BFS/DFS, GNN-style reasoning, or CALL ptr://skill/port_{graph_traverse,graphrag,neural_graph}. Never writes Lean.
---

# Graph skills

`jevops.graph` + `jevops.jsonld`.

- **`port_graph_traverse`** — BFS (default) or DFS on `board_edges`, max 4 hops.
- **JSON-LD first.** Canonical graph is `@context` + `@graph`. DuckDB is an optional adapter, never required for traverse/GraphRAG/neural-graph.
- **`port_graphrag`** — search JSON-LD, then KG/AST/rg. Hits are not lake admits.
- **`port_neural_graph`** — integer 2-hop sum of neighbor energy milles. Not CUDA.

Jev does not write Lean. Never docker0.
