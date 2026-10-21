# Autonomous self-improvement design

Sophyane may continuously observe weaknesses and generate bounded curriculum
candidates. A candidate must pass independent LLM review before the curriculum
scheduler can execute it. Execution remains delegated to the existing isolated
RSI adapters; verification and promotion remain separate gates.

The loop is: observe -> propose -> review -> queue -> execute -> verify ->
promote or reject. A missing reviewer blocks the candidate rather than
granting implicit approval. Existing explicitly seeded tasks retain their
legacy `not_required` review status.
