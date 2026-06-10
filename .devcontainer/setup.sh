#!/bin/sh

# Setup log directory
mkdir -p .reports/devcontainer
LOG_FILE=".reports/devcontainer/post_setup.log"

# Use a subshell to capture all output to the log file
(
    echo "--- Starting Post-Create Setup ---"
    
    echo "Configuring Git..."
    git config --global core.fileMode false
    git config --global core.autocrlf input

    echo "Environment: ha-dev-base:latest"

    echo "Refreshing shared config files..."
    if [ -f ".shared/validate-configs/sync_shared_files.sh" ]; then
        RUNNING_FROM_SETUP=1 sh .shared/validate-configs/sync_shared_files.sh
    else
        echo "Warning: sync_shared_files.sh not found — shared files not updated."
    fi

    if [ -f ".pre-commit-config.yaml" ]; then
        echo "Pre-warming pre-commit hook environments..."
        pre-commit install-hooks
    else
        echo "No .pre-commit-config.yaml found — skipping pre-commit pre-warm."
    fi

    echo "--- Setup Complete ---"
) 2>&1 | tee "$LOG_FILE"
