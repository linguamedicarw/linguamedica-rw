#!/bin/bash
# Converts NLLB-200 3.3B (already in ~/data/hf) to CTranslate2 with float32 weights, once,
# on a CPU node (it needs more memory than a login node allows). No GPU, no network.
#
#   cd ~/LinguaMedica-runs/slurm && sbatch ~/linguamedica-rw/hpc/nllb_convert.sbatch
#SBATCH --job-name=nllb-convert
#SBATCH --partition=requeue
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=01:00:00
#SBATCH --requeue
#SBATCH --open-mode=append
set -euo pipefail
source "$HOME/data/linguamedica-env.sh"
cd "${REPO:-$HOME/linguamedica-rw}"
python scripts/nllb_calibration.py convert --to "$HOME/data/ct2/nllb-200-3.3B"
