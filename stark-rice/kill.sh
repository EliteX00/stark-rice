#!/usr/bin/env bash
# Stark Rice UI Killer

pkill -f "python3.*stark_ui.py" 2>/dev/null || true
pkill -f "stark_rice/stark_ui.py" 2>/dev/null || true
echo "Stark UI stopped."
