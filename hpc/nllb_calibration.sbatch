#!/bin/bash
# NLLB-200 3.3B on TICO-19 English-Kinyarwanda, through CTranslate2, one precision per job:
#
#   cd ~/LinguaMedica-runs/slurm
#   sbatch --export=ALL,COMPUTE=int8    ~/linguamedica-rw/hpc/nllb_calibration.sbatch
#   sbatch --export=ALL,COMPUTE=float16 ~/linguamedica-rw/hpc/nllb_calibration.sbatch
#
# int8 and beam 4 are the settings Moslem et al. (2023a) report; float16 is the precision
# of the reported runs. The preemptible partition starts in seconds; if the job is pushed
# off, Slurm requeues it under the same job id, so the same --name continues where it
# stopped. Scoring afterwards, on the login node: scripts/nllb_calibration.py score RUN.
#SBATCH --job-name=nllb-calibration
#SBATCH --partition=gpu_requeue
#SBATCH --gres=gpu:A100:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
set -euo pipefail
: "${COMPUTE:?pass COMPUTE=int8 or COMPUTE=float16 with --export}"
source "$HOME/data/linguamedica-env.sh"
cd "${REPO:-$HOME/linguamedica-rw}"
echo "job $SLURM_JOB_ID on $(hostname), restart count ${SLURM_RESTART_COUNT:-0}"
python scripts/nllb_calibration.py translate \
    --tico "$HOME/data/tico19/tico19-testset" \
    --model "$HOME/data/ct2/nllb-200-3.3B" \
    --compute-type "$COMPUTE" \
    --name "nllb-calibration_${COMPUTE}_${SLURM_JOB_ID}"
