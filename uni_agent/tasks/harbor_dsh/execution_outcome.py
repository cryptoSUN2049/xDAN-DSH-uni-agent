"""Executor-only acknowledgement of cleanly stopped, inadmissible evidence.

This is never a reward or successful trajectory. Construct only after both
Harbor environments independently pass Docker resource inventory checks.
"""


class CleanExecutionRejected(RuntimeError):
    error_code = "evidence-rejected-after-cleanup"

    def __init__(self, *, trial_id: str):
        super().__init__(self.error_code)
        self.trial_id = trial_id
