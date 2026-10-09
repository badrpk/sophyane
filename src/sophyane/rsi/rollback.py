"""RSI rollback adapter; the trusted host broker owns primary mutation."""
from sophyane.rsi_host_broker import recover_pending, restore_checkpoint


def rollback(journal, checkpoint, *, provider):
    from .authority import Operation, require

    require(provider, Operation.ROLLBACK_OPERATION)
    evidence = journal.load_checkpoint(checkpoint)
    restore_checkpoint(evidence)
    journal.append(provider, evidence["iteration_id"], "ROLLED_BACK",
                   {"checkpoint": str(checkpoint),
                    "rollback_result": "restored recorded baseline"})


__all__ = ["recover_pending", "restore_checkpoint", "rollback"]
