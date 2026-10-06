# Shared bootstrap contract

The AWS and GCP examples provision an Ubuntu 24.04 x86-64 host. They deliberately do not download or execute application code in instance metadata. After reviewing/applying an environment plan, follow `deploy/cloud.md` to install Docker, check out a reviewed source revision and run the existing Compose configuration with an immutable image tag.

Persistent data stays on the protected host disk. This is a supported single-workspace deployment, not the proposed distributed runtime. No application token, private template, cloud credential or Terraform state belongs in Git.
