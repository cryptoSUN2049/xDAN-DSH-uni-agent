"""Work-state admission over the original resident DSH A/B execution path."""

from examples.dsh.capabilities.work_state import stage
from uni_agent.framework.memory_chain import NativeMemoryFramework


class NativeWorkStateFramework(NativeMemoryFramework):
    operator_type = stage.WorkStateOperator
    contract_id = "work-state-v1"

    def _prepare_writer(self, operator, context, *, sample_fields, **kwargs):
        return stage.prepare_writer_stage(operator, context, sample_fields=sample_fields, **kwargs)

    def _freeze_reader(self, writer_spec, execution, **kwargs):
        return stage.freeze_and_prepare_reader(writer_spec, execution, **kwargs)

    def _validate_stage(self, spec, execution):
        return stage.validate_stage_execution(spec, execution)
