#!/bin/bash
# Script to get vault password from 1Password or environment variable
#
# Option 1: Use 1Password CLI (recommended)
#   Requires: op CLI installed and signed in
#   Vault: secureloop
#   Item: "Ansible Vault"
#
# Option 2: Use environment variable
#   export ANSIBLE_VAULT_PASSWORD="your-password"

# Try 1Password first
if command -v op &> /dev/null; then
    # Check if signed in
    if op account list &> /dev/null; then
        # Use 1Password secret reference (recommended)
        PASSWORD=$(op read "op://secureloop/Ansible Vault/password" 2>/dev/null)

        if [ -n "$PASSWORD" ]; then
            echo "$PASSWORD"
            exit 0
        fi
    fi
fi

# Fallback to environment variable
if [ -z "$ANSIBLE_VAULT_PASSWORD" ]; then
    echo "Error: Cannot retrieve password from 1Password and ANSIBLE_VAULT_PASSWORD not set" >&2
    echo "Make sure you're signed in to 1Password: op signin" >&2
    exit 1
fi

echo "$ANSIBLE_VAULT_PASSWORD"
