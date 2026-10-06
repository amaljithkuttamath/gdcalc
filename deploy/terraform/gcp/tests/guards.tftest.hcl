mock_provider "google" {}
variables {
  project_id   = "synthetic-project"
  region       = "us-central1"
  zone         = "us-central1-a"
  ubuntu_image = "projects/ubuntu-os-cloud/global/images/ubuntu-2404-noble-amd64-synthetic"
  admin_ipv4   = "203.0.113.10/32"
}
run "protected_workspace" {
  command = plan
  assert {
    condition     = google_compute_instance.app.deletion_protection && !google_compute_instance.app.boot_disk[0].auto_delete
    error_message = "Preserve the persistent data disk."
  }
  assert {
    condition     = google_compute_instance.app.metadata["enable-oslogin"] == "TRUE" && google_compute_instance.app.shielded_instance_config[0].enable_secure_boot
    error_message = "Keep OS Login and secure boot enabled."
  }
  assert {
    condition     = google_compute_firewall.https.source_ranges == toset([var.admin_ipv4]) && google_compute_firewall.iap.source_ranges == toset(["35.235.240.0/20"])
    error_message = "Limit HTTPS and SSH ingress."
  }
}
run "reject_public_admin" {
  command = plan
  variables { admin_ipv4 = "0.0.0.0/0" }
  expect_failures = [var.admin_ipv4]
}
