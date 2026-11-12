#!/bin/bash
# The pipeline with Gemma 3 27B at 16-bit (bfloat16), the precision of every reported
# result, on one A100 80 GB:
#
#   cd ~/LinguaMedica-runs/slurm
#   sbatch --export=ALL,ITEMS=$HOME/LinguaMedica-dev/tico19-dev_100_seed20261111_ee7fa896f32d.csv \
#       ~/linguamedica-rw/hpc/gemma3_pipeline.sbatch
#
# The model (about 55 GB) must already be in ~/data/hf. The run refuses to start unless
# the repository is clean, like every run. On the regular partition an A100 can take
# hours to start, so submit early; add --partition=gpu_requeue to sbatch to start sooner,
# since a preempted run continues where it stopped (same job id, same --name).
#SBATCH --job-name=gemma3-27b-bf16
#SBATCH --partition=gpu
#SBATCH --gres=gpu:A100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=02:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
set -euo pipefail
: "${ITEMS:?pass ITEMS=the items file with --export}"
source "$HOME/data/linguamedica-env.sh"
cd "${REPO:-$HOME/linguamedica-rw}"
echo "job $SLURM_JOB_ID on $(hostname), restart count ${SLURM_RESTART_COUNT:-0}"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || true
python -m rag run --items "$ITEMS" --backbone transformers \
    --model google/gemma-3-27b-it --dtype bfloat16 \
    --name "gemma3-27b-bf16_${SLURM_JOB_ID}"
