#!/bin/bash

# Store the current directory
#CURRENT_DIR=$(pwd)

# Navigate to the project directory
#cd ~/projects/python-slip39

# Activate the virtual environment
source venv/bin/activate

# Open a new terminal with the virtual environment activated
#gnome-terminal -- bash -c 'python3 -m slip39.recovery --using-bip39; exec bash'
python3 -m slip39.recovery --using-bip39

# Wait for the new terminal to close
#wait

# Deactivate the virtual environment
deactivate

# Change back to the original directory
#cd $CURRENT_DIR

