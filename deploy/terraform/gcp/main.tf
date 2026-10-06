terraform {
  required_version = ">= 1.13.3, < 2.0"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 7.0" }
  }
}
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}
variable "project_id" { type = string }
variable "region" { type = string }
variable "zone" { type = string }
variable "name" {
  type    = string
  default = "mcdxkit"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Use 3–31 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "ubuntu_image" {
  description = "Pinned Ubuntu 24.04 amd64 image URL, not an image family."
  type        = string
  validation {
    condition     = can(regex("^projects/ubuntu-os-cloud/global/images/ubuntu-2404-", var.ubuntu_image)) && !strcontains(var.ubuntu_image, "/family/")
    error_message = "Supply a specific Ubuntu 24.04 amd64 image under projects/ubuntu-os-cloud/global/images/."
  }
}
variable "admin_ipv4" {
  description = "Administrator/client IPv4 /32 allowed to reach HTTPS. SSH uses IAP and OS Login."
  type        = string
  validation {
    condition     = can(cidrhost(var.admin_ipv4, 0)) && !strcontains(var.admin_ipv4, ":") && endswith(var.admin_ipv4, "/32")
    error_message = "Supply a single IPv4 address as a /32 CIDR."
  }
}
resource "google_project_service" "compute" {
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}
resource "google_compute_network" "app" {
  name                    = var.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.compute]
}
resource "google_compute_subnetwork" "app" {
  name          = var.name
  ip_cidr_range = "10.42.1.0/24"
  network       = google_compute_network.app.id
}
resource "google_compute_firewall" "http" {
  name          = "${var.name}-acme"
  network       = google_compute_network.app.name
  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.name]
  allow {
    protocol = "tcp"
    ports    = ["80"]
  }
}
resource "google_compute_firewall" "https" {
  name          = "${var.name}-https"
  network       = google_compute_network.app.name
  source_ranges = [var.admin_ipv4]
  target_tags   = [var.name]
  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
}
resource "google_compute_firewall" "iap" {
  name          = "${var.name}-iap-ssh"
  network       = google_compute_network.app.name
  source_ranges = ["35.235.240.0/20"]
  target_tags   = [var.name]
  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}
resource "google_compute_address" "app" { name = var.name }
resource "google_compute_instance" "app" {
  name                = var.name
  machine_type        = "e2-medium"
  deletion_protection = true
  tags                = [var.name]
  boot_disk {
    auto_delete = false
    initialize_params {
      image = var.ubuntu_image
      size  = 40
      type  = "pd-balanced"
    }
  }
  network_interface {
    subnetwork = google_compute_subnetwork.app.id
    access_config { nat_ip = google_compute_address.app.address }
  }
  metadata = { enable-oslogin = "TRUE", block-project-ssh-keys = "TRUE" }
  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }
  # No runtime cloud permissions or service-account keys are required by this mode.
  lifecycle { prevent_destroy = true }
  labels = { application = "mcdxkit", mode = "shared-workspace" }
}
output "address" { value = google_compute_address.app.address }
output "instance_name" { value = google_compute_instance.app.name }
output "persistent_disk" { value = google_compute_instance.app.boot_disk[0].source }
