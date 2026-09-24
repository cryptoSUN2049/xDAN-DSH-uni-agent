export MODEL_PATH=/tmp/models/Qwen3-4B-1cfa9a7
export TRAIN_STEPS=6
export TRAIN_MAX_SAMPLES=20
export VAL_MAX_SAMPLES=5
export TRAIN_BATCH_SIZE=2
export ROLLOUT_N=8
export CONCURRENCY=16
export DAPO=0
export TEACHER=1
export TEACHER_MODEL_PATH=/tmp/models/Qwen3-4B-1cfa9a7
export TEACHER_GPU_MEM=0.8
export GPU_MEMORY_UTILIZATION=0.45
export VAL_BEFORE_TRAIN=True
export TEST_FREQ=6
export HARBOR_REWARD_MODE=pass_ratio
# reconstructed 2026-09-17 from the original detached launch cmd in driver.log (train ran before stage-env.sh existed)
