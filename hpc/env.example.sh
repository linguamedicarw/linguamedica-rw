# Copy to ~/data/linguamedica-env.sh on Hellbender, then adjust the module line to the one
# the environment was built with. Every job script sources that file, so the scripts in
# this folder hold nothing specific to one person's account.

module load python                      # the module the venv was made with (module avail python)
source "$HOME/data/venvs/linguamedica/bin/activate"
export HF_HOME="$HOME/data/hf"          # models live in the 500 GB data folder, not in home
export HF_HUB_OFFLINE=1                 # jobs read models from that folder, never the network
export TRANSFORMERS_OFFLINE=1
