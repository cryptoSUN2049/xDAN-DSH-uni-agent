"""Factory entry + trainer-facing adapter for the agent framework stack.

`build_gateway_manager` owns gateway-universal wiring (driver-side); the trainer
adapter creates the manager and injects it so the framework only handles its own
agent runner, reward dispatch, and framework-specific config fields.

`AgentFrameworkRolloutAdapter` satisfies the trainer's
`agent_loop_manager_class` extension-point contract; recipes wire it in via
yaml without authoring per-recipe glue:

    actor_rollout_ref.rollout.agent.agent_loop_manager_class:
        uni_agent.framework.entry.AgentFrameworkRolloutAdapter
"""

from __future__ import annotations

import math

import ray
from omegaconf import OmegaConf

from uni_agent.framework.base import AgentFramework
from uni_agent.gateway.config import GatewayActorConfig
from uni_agent.gateway.manager import GatewayManager
from uni_agent.rlinsight_adapter import init_rollout_trace_config
from verl.utils import tensordict_utils as tu
from verl.utils.config import omega_conf_to_dataclass
from verl.utils.import_utils import load_class_from_fqn
from verl.utils.transferqueue_utils import tq
from verl.workers.config.model import HFModelConfig

_DEFAULT_FRAMEWORK_CLASS = "uni_agent.framework.framework.GatewayAgentFramework"


def build_gateway_manager(*, config, llm_client) -> GatewayManager:
    """Spawn the gateway actor pool (driver-side, driver-owned) and return its manager."""
    # TODO(phase-b): switch this to actor_rollout_ref.rollout.agent_framework.*
    af_cfg = OmegaConf.select(config, "actor_rollout_ref.rollout.custom.agent_framework", default={}) or {}
    apply_chat_template_kwargs = OmegaConf.select(config, "data.apply_chat_template_kwargs", default={}) or {}
    if OmegaConf.is_config(apply_chat_template_kwargs):
        apply_chat_template_kwargs = OmegaConf.to_container(apply_chat_template_kwargs, resolve=True)

    # Match AgentLoopWorker pattern: self-load tokenizer/processor via HFModelConfig.
    model_config: HFModelConfig = omega_conf_to_dataclass(config.actor_rollout_ref.model)
    gateway_actor_config = GatewayActorConfig(
        tokenizer=model_config.tokenizer,
        processor=model_config.processor,
        tool_parser_name=config.actor_rollout_ref.rollout.get("multi_turn", {}).get("format"),
        rollout_backend=config.actor_rollout_ref.rollout.get("name"),
        enable_tool_parser_cache=af_cfg.get("enable_tool_parser_cache", True),
        apply_chat_template_kwargs=dict(apply_chat_template_kwargs),
        prompt_length=config.actor_rollout_ref.rollout.prompt_length,
        response_length=config.actor_rollout_ref.rollout.response_length,
        enable_last_assistant_rollback=af_cfg.get("enable_last_assistant_rollback", True),
    )

    return GatewayManager(
        llm_client=llm_client,
        gateway_count=int(af_cfg["gateway_count"]),
        gateway_actor_config=gateway_actor_config,
    )


def build_agent_framework(
    *,
    config,
    gateway_manager,
    reward_loop_worker_handles=None,
) -> AgentFramework:
    """Wire the configured framework subclass over an injected gateway manager."""
    # TODO(phase-b): switch this to actor_rollout_ref.rollout.agent_framework.*
    af_cfg = OmegaConf.select(config, "actor_rollout_ref.rollout.custom.agent_framework", default={}) or {}
    model_config: HFModelConfig = omega_conf_to_dataclass(config.actor_rollout_ref.model)

    framework_cls = load_class_from_fqn(str(af_cfg.get("framework_class_fqn", _DEFAULT_FRAMEWORK_CLASS)))
    return framework_cls.from_config(
        config=config,
        gateway_manager=gateway_manager,
        processor=model_config.processor,
        reward_loop_worker_handles=reward_loop_worker_handles,
    )


@ray.remote
class AgentFrameworkWorker:
    """Ray actor host: initializes TQ in this process and owns one AgentFramework.

    Construction is synchronous (no async setup round-trip); the gateway manager
    is created driver-side and injected so its actors are not owned by this worker.
    """

    def __init__(self, *, config, gateway_manager, reward_loop_worker_handles=None) -> None:
        tq.init()
        init_rollout_trace_config(config)
        self.framework = build_agent_framework(
            config=config,
            gateway_manager=gateway_manager,
            reward_loop_worker_handles=reward_loop_worker_handles,
        )

    async def generate_sequences(self, prompts) -> None:
        await self.framework.generate_sequences(prompts)


class AgentFrameworkRolloutAdapter:
    """Trainer-facing adapter satisfying the `agent_loop_manager_class` contract.

    Holds zero recipe-specific logic; every agent-framework recipe wires the
    same class in yaml. The adapter owns the gateway manager (driver-side) and
    injects it into the framework worker.
    """

    def __init__(self) -> None:
        self.framework_worker = None
        # Driver-owned so the gateway actors outlive the framework worker; also
        # the handle through which teardown can be driven once a call site exists.
        self.gateway_manager = None

    @classmethod
    def create(
        cls,
        *,
        config,
        llm_client,
        teacher_client=None,
        reward_loop_worker_handles=None,
        **_,
    ) -> AgentFrameworkRolloutAdapter:
        if teacher_client is not None:
            raise ValueError(
                "AgentFrameworkRolloutAdapter does not support teacher_client yet; "
                "disable teacher policy/distillation or use an AgentLoopManager that supports it."
            )

        gateway_manager = build_gateway_manager(config=config, llm_client=llm_client)
        framework_worker = AgentFrameworkWorker.remote(
            config=config,
            gateway_manager=gateway_manager,
            reward_loop_worker_handles=reward_loop_worker_handles,
        )

        instance = cls()
        instance.framework_worker = framework_worker
        instance.gateway_manager = gateway_manager
        return instance

    def generate_sequences(self, prompts) -> None:
        """Submit a TQ batch generation task without waiting for rollout results."""
        if self.framework_worker is None:
            raise RuntimeError("framework must be initialized before generate_sequences")

        self.framework_worker.generate_sequences.remote(prompts)
        return None

    def generate_sequences_and_wait(self, prompts) -> None:
        """Blocking variant of :meth:`generate_sequences` for standalone (non-trainer) runs.

        :meth:`generate_sequences` is fire-and-forget (the trainer consumes TQ asynchronously
        via its ReplayBuffer); this awaits the framework worker so the caller knows every
        session's trajectory has landed in TQ, and re-raises any worker-side error.
        """
        if self.framework_worker is None:
            raise RuntimeError("framework must be initialized before generate_sequences")

        ray.get(self.framework_worker.generate_sequences.remote(prompts))
        return None


class StrictSyncValidationRolloutAdapter(AgentFrameworkRolloutAdapter):
    """Opt-in: propagate strict validation failures before the trainer samples TQ.

    Training retains fire-and-forget dispatch and sync ReplayBuffer refill.
    Timeout cancellation targets only our submitted Ray call; owned run supervision
    remains responsible for confirming DSH/process cleanup.
    """

    @classmethod
    def create(cls, *, config, **kwargs):
        if OmegaConf.select(config, "trainer.v1.trainer_mode") != "sync":
            raise ValueError("Strict validation adapter requires sync trainer mode")
        prefix = "actor_rollout_ref.rollout.custom.agent_framework"
        if OmegaConf.select(config, prefix + ".fail_on_rollout_error") is not True:
            raise ValueError("Strict validation adapter requires fail_on_rollout_error=True")
        timeout = OmegaConf.select(config, prefix + ".strict_validation_timeout_seconds", default=1800)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Strict validation timeout must be finite and positive")
        instance = super().create(config=config, **kwargs)
        instance._validation_timeout = float(timeout)
        return instance

    def generate_sequences(self, prompts) -> None:
        if not bool(tu.get(prompts, "validate", False)):
            return super().generate_sequences(prompts)
        if self.framework_worker is None:
            raise RuntimeError("framework must be initialized before generate_sequences")
        reference = self.framework_worker.generate_sequences.remote(prompts)
        try:
            ray.get(reference, timeout=self._validation_timeout)
        except ray.exceptions.GetTimeoutError as error:
            requested = False
            try:
                ray.cancel(reference, force=False)
                requested = True
            except Exception:
                pass  # Preserve the timeout as the primary failure, not cancellation details.
            raise TimeoutError(
                f"Strict validation timed out; cancellation_requested={requested}; "
                "cleanup unconfirmed, owned run supervisor must confirm cleanup"
            ) from error
        return None
