# Running the experiments on Hellbender

Two experiments run here, on public data only (TICO-19). No reviewer score, backup or
side-by-side sheet ever goes on the cluster.

1. **NLLB calibration.** NLLB-200 3.3B on TICO-19 English-Kinyarwanda, at Moslem et al.
   (2023a)'s settings (CTranslate2, int8, beam 4) and at 16-bit. This reproduces the
   published score before the baseline meets the test set.
2. **8-bit against 16-bit.** Gemma 3 27B on 100 TICO-19 dev sentences, at 8-bit on the Mac
   (Ollama `gemma3:27b-it-q8_0`) and at 16-bit here (`--dtype bfloat16`). The comparison
   shows how far development results carry over (Dr. Dastour, 8 November 2026).

Cite Hellbender in any write-up that uses it: https://doi.org/10.32469/10355/97710.

## Once: the environment (OnDemand shell, one command at a time)

```bash
git clone https://github.com/linguamedicarw/linguamedica-rw.git ~/linguamedica-rw
module avail python                         # pick a Python 3.11 or 3.12 module
module load python                          # or the exact name, e.g. python/3.12
python3 -m venv ~/data/venvs/linguamedica
source ~/data/venvs/linguamedica/bin/activate
pip install -r ~/linguamedica-rw/requirements-experiments.txt
cp ~/linguamedica-rw/hpc/env.example.sh ~/data/linguamedica-env.sh   # then fix its module line
mkdir -p ~/data/hf ~/data/tico19 ~/data/ct2 ~/LinguaMedica-runs/slurm ~/LinguaMedica-dev
```

## Once: data and models (login node, which has the network)

```bash
cd ~/data/tico19 && curl -LO https://tico-19.github.io/data/tico19-testset.zip
sha256sum tico19-testset.zip    # 0e82fc7ceaa877606c8934f32ead185716c9d2c54b3818f2a7ae655f5e7a08d8
unzip -q tico19-testset.zip 'tico19-testset/*/*.en-rw.tsv'
export HF_HOME=~/data/hf
hf download facebook/nllb-200-3.3B          # older huggingface_hub: huggingface-cli download
hf auth login                               # Gemma is gated: accept its licence on the Hub first;
hf download google/gemma-3-27b-it           #   the token stays in this terminal
```

Then the development items. The same command on the Mac gives the same file, byte for
byte, which is what lets the two runs be compared:

```bash
cd ~/linguamedica-rw
python scripts/dev_items_tico19.py --tico ~/data/tico19/tico19-testset/dev/dev.en-rw.tsv
```

## The jobs

Submit from `~/LinguaMedica-runs/slurm`, so the Slurm logs land there and not in the
repository.

```bash
cd ~/LinguaMedica-runs/slurm
sbatch ~/linguamedica-rw/hpc/nllb_convert.sbatch                         # once, CPU
sbatch --export=ALL,COMPUTE=int8    ~/linguamedica-rw/hpc/nllb_calibration.sbatch
sbatch --export=ALL,COMPUTE=float16 ~/linguamedica-rw/hpc/nllb_calibration.sbatch
sbatch --export=ALL,ITEMS=$HOME/LinguaMedica-dev/tico19-dev_100_seed20261111_ee7fa896f32d.csv \
    ~/linguamedica-rw/hpc/gemma3_pipeline.sbatch
squeue -u $USER                             # waiting or running
sacct -X -o JobID,JobName,Partition,State,Elapsed,NodeList%20
```

- The calibration jobs use `gpu_requeue`, which starts in seconds. If a job is pushed
  off, Slurm requeues it under the same job id, and the same `--name` continues where it
  stopped (every sentence and item is on disk as soon as it is done).
- The Gemma job asks for the regular `gpu` partition, where an A100 80 GB can take hours to
  start, so submit it early. Adding `--partition=gpu_requeue` to `sbatch` starts it sooner
  if that partition has 80 GB cards.
- Jobs read models from `~/data/hf` with the network off (`HF_HUB_OFFLINE=1`), so any
  download happens on the login node first.
- NLLB is converted with float32 weights, so `COMPUTE=int8` runs int8 weights with float32
  activations (`int8_float32`). Each run.json records the type CTranslate2 actually used;
  check in the paper which int8 variant Moslem et al. ran.

## Afterwards

```bash
python scripts/nllb_calibration.py score ~/LinguaMedica-runs/nllb-calibration_int8_JOBID
python scripts/nllb_calibration.py score ~/LinguaMedica-runs/nllb-calibration_float16_JOBID
```

On the Mac, with the Hellbender run folder copied next to the Mac's run:

```bash
python -m rag run --items ~/LinguaMedica-dev/tico19-dev_100_seed20261111_ee7fa896f32d.csv \
    --backbone ollama --model gemma3:27b-it-q8_0 --name gemma3-27b-q8_mac
python scripts/compare_runs.py ~/LinguaMedica-runs/gemma3-27b-q8_mac \
    ~/LinguaMedica-runs/gemma3-27b-bf16_JOBID \
    --references ~/LinguaMedica-dev/tico19-dev_100_seed20261111_ee7fa896f32d_references.tsv
```

The comparison reports adherence for each run, the difference with a 95% bootstrap
interval, the share of identical outputs and chrF++. The two runs differ in quantization
and in runtime (Ollama on the Mac, transformers on the A100), so the comparison measures
the whole development setup against the reported one, which is the question asked.
