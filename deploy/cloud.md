# AWS and GCP deployment

**Scaffolding only; no live deployment has been verified.** The examples provision a single trusted-team workspace. They reuse the tested MCDXKit image and Compose configuration. They do not make the current in-memory session registry distributed or tenant-isolated. For the scale-out contract see [distributed architecture](../docs/distributed-architecture.md).

## Choose a delivery mode

| Mode | Use today | Persistence and limits |
| --- | --- | --- |
| Local CLI/browser | Private, offline calculation after installation | Local output folder; no cloud account |
| AWS EC2 + encrypted EBS | One team, one app instance | Protected persistent disk; operator backup required |
| GCP Compute Engine + persistent disk | One team, one app instance | Protected persistent disk; operator backup required |
| ECS/Cloud Run API + workers | Planned after job/storage/identity adapters | Do not enable replicas on today's shared-workspace app |

Managed service ephemeral filesystems cannot replace the engine's current durable output folder. In particular, do not mount an object bucket through FUSE and assume it supports atomic hard links. Stage calculation on a real local filesystem; a future object-store adapter publishes verified objects and a final manifest.

## Prerequisites and validation

Use Terraform 1.13.3+, an authorized account/project, budget alerts, an approved region, a domain, and an administrator IP. Billing must be enabled. The examples create a small x86-64 VM, 40 GiB disk, static public IP and networking; these incur charges after apply, including retained disks/IPs when the VM is stopped. Review provider pricing and a plan for the chosen region before applying. Neither example creates billing limits or promises a fixed cost.

Use short-lived provider authentication (AWS SSO or Google Application Default Credentials), never keys in `.tfvars`. Copy the provider example to a private `terraform.tfvars` and replace every placeholder:

```bash
cd deploy/terraform/aws                 # or ../gcp
cp terraform.tfvars.example terraform.tfvars
terraform init                         # review the committed provider lock file
terraform fmt -check
terraform validate
terraform test                         # mocked providers; creates no cloud resources
terraform plan -out=staging.tfplan
# Only after reviewing resource access, cost, region and persistent-storage plan:
terraform apply staging.tfplan
```

For AWS, select a specific Ubuntu 24.04 amd64 AMI from Canonical in your region and an existing EC2 SSH key pair. For GCP, choose a specific Ubuntu 24.04 amd64 image, not a moving family. Ensure region and zone agree. The GCP operator needs Compute administration, Service Usage for Compute API activation, OS Login administration and IAP tunnel access; the VM receives no application cloud credentials. DNS and those human IAM grants are intentionally not created by this scaffold.

State contains infrastructure identifiers. Keep it out of Git. Before a team apply, configure an encrypted, access-controlled remote backend with locking (S3 for AWS or GCS for GCP), separate state per environment and recovery/versioning. Create that state backend separately; do not share one state file across providers. Generated plan files are private too.

## Start the app on the host

The infrastructure creates a host, not a running app. Connect to AWS as `ubuntu` using the configured key from the allowed address; use GCP IAP with OS Login:

```bash
gcloud compute ssh INSTANCE --project PROJECT --zone ZONE --tunnel-through-iap
```

On the Ubuntu host, install Git, Python and Docker Compose from the distribution, then clone the public source. Keep the application checkout owned by the deployment administrator:

```bash
sudo apt-get update
sudo apt-get install -y git python3 docker.io docker-compose-v2
sudo systemctl enable --now docker
git clone https://github.com/amaljithkuttamath/mcdxkit.git
cd mcdxkit
git checkout REVIEWED_FULL_COMMIT_SHA
python3 scripts/setup_deploy.py
```

Point the domain's A record at Terraform's `address` output. In `.env`, set the exact HTTPS origin/domain and `MCDXKIT_IMAGE=ghcr.io/amaljithkuttamath/mcdxkit:sha-REVIEWED_FULL_COMMIT_SHA`. Use an image whose main CI publication succeeded; not every commit has a published image. Do not bake a private template or secret into the image.

```bash
sudo docker compose -f compose.yaml -f compose.registry.yaml --profile cloud pull
sudo docker compose -f compose.yaml -f compose.registry.yaml --profile cloud up --no-build -d
sudo docker compose ps
curl --fail https://YOUR_DOMAIN/healthz
```

HTTPS and SSH are restricted to the configured administrator/client IP (GCP SSH uses IAP). Port 80 permits ACME certificate validation; Caddy redirects ordinary HTTP requests. The application port 8765 is loopback-only. To allow more teammates, deliberately review narrow HTTPS CIDRs; do not open SSH or remove app authentication. For public HTTPS access, review the shared-token threat model first.

Read `.secrets/access-token` privately on the host and sign in at your HTTPS URL. Do not paste the token into a ticket, chat or log. Everyone who holds this token can see the shared saved outputs.

## Engineer workflow

1. **Files:** upload GROUP reports and choose a compatible private `.mcdx` design template. A cloud upload sends files to your server; local mode keeps them on your machine.
2. **Inputs:** inspect the final local-load values, selected cases, units and explicit overrides. Open the source/template when something is unclear.
3. **Changes:** prepare and review the proposed native expression changes. Unsupported calculations are errors, not cached success.
4. **Outputs:** generate, inspect fresh Calcpad results and download `.mcdx`, `.cpd`, HTML and audit. Progress is UI state, not part of the worksheet. Native Prime execution and engineering approval are separate.
5. **Saved outputs:** reopen completed bundles after a restart. The upload queue and selected temporary template must be reselected; they are not durable project records yet.

## Backup, upgrade and rollback

The disk holds Docker volumes with outputs, private source/template snapshots and Caddy state. Record the volume names with `sudo docker volume ls`. Back up the **whole disk** with an encrypted EBS/GCE disk snapshot under a retention policy; quiesce conversion and stop Compose first for a consistent snapshot. Test restoration into an isolated staging host, confirm source/artifact hashes and reopen Saved outputs. A snapshot that has never been restored is not recovery evidence.

Before upgrading, back up and record the source revision and image digest. Pull the new tested immutable image, change only `MCDXKIT_IMAGE`, and run Compose `up --no-build -d`. Verify health, unauthenticated API rejection and a synthetic conversion before admitting engineering work. Roll back the image tag if validation fails; restore data from backup if an explicitly documented schema migration requires it. Do not overwrite original outputs.

The VM and disk have deletion protections. Do not disable them or run `docker compose down -v` as routine cleanup. Decommissioning requires explicit data export, a tested backup and deliberate removal of protections; retained disks and static addresses continue billing. Restart invalidates login sessions.

## Validation evidence and gaps

CI checks formatting, provider schemas and mocked plans for restricted admin access, persistent disks and metadata protections. It does not authenticate to AWS/GCP, provision hosts, validate IAM privileges, obtain certificates or prove restore/network performance. A real staging deployment and restore drill are required before production use. Linux container CI does not verify Windows or Prime.

Provider references: [EC2 instance](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/instance), [Compute Engine instance](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/compute_instance), [ECS storage](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/using_data_volumes.html), [Cloud Run asynchronous tasks](https://docs.cloud.google.com/run/docs/triggering/using-tasks).
