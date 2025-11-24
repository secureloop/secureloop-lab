# Snippets on Git

## Signing

```aiignore
# Tell Git to use SSH for signing
git config --global gpg.format ssh

# Set your signing key (use the PUBLIC key path)
git config --global user.signingkey ~/.ssh/id_ed25519_signing.pub

# Enable automatic signing of commits
git config --global commit.gpgsign true
```