# Sophyane 18.12.0

## Validator convergence ownership

This release fixes the remaining local-first rescue handoff problem.

Previously, Sophyane correctly escalated a repeated validator failure to Gemini or another configured cloud provider, but returned to the local model on the very next repair call. That could discard a useful cloud repair and restart the same failing loop.

### New behavior

1. Local model remains primary.
2. Repeated validator failures trigger configured cloud rescue.
3. The selected cloud provider owns all subsequent validator-repair prompts for that repair sequence.
4. Rescue prompts explicitly require the complete corrected artifact, including a full self-contained HTML document for browser tasks.
5. Sophyane returns to local-first only after the runtime sends a non-repair request, indicating that validation completed or the task ended.

### Result

A snake-game repair now follows:

`local -> local repair -> cloud rescue -> cloud repair until pass -> local for next task`

instead of:

`local -> cloud rescue -> local -> local -> failure`
