terraform {
  required_version = ">= 1.13.3, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
provider "aws" { region = var.region }
variable "region" { type = string }
variable "name" {
  type    = string
  default = "mcdxkit"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Use 3–31 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "ubuntu_ami" {
  description = "Reviewed Ubuntu 24.04 amd64 AMI ID in this region; pin an ID, not latest."
  type        = string
  validation {
    condition     = can(regex("^ami-[a-f0-9]+$", var.ubuntu_ami))
    error_message = "Supply a reviewed Ubuntu amd64 AMI ID."
  }
}
variable "admin_ipv4" {
  description = "Administrator/client IPv4 /32 allowed to reach SSH and HTTPS."
  type        = string
  validation {
    condition     = can(cidrhost(var.admin_ipv4, 0)) && !strcontains(var.admin_ipv4, ":") && endswith(var.admin_ipv4, "/32")
    error_message = "Supply a single IPv4 address as a /32 CIDR; do not open SSH to the world."
  }
}
variable "key_name" {
  description = "Name of an existing EC2 SSH key pair. No private key is created or stored by Terraform."
  type        = string
}
resource "aws_vpc" "app" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = var.name }
}
resource "aws_subnet" "app" {
  vpc_id                  = aws_vpc.app.id
  cidr_block              = "10.42.1.0/24"
  map_public_ip_on_launch = true
  tags                    = { Name = var.name }
}
resource "aws_internet_gateway" "app" { vpc_id = aws_vpc.app.id }
resource "aws_route_table" "app" {
  vpc_id = aws_vpc.app.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.app.id
  }
}
resource "aws_route_table_association" "app" {
  subnet_id      = aws_subnet.app.id
  route_table_id = aws_route_table.app.id
}
resource "aws_security_group" "app" {
  name_prefix = "${var.name}-"
  vpc_id      = aws_vpc.app.id
  # ACME HTTP validation only. Caddy redirects other HTTP requests to HTTPS.
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  dynamic "ingress" {
    for_each = [22, 443]
    content {
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = [var.admin_ipv4]
    }
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_instance" "app" {
  ami                         = var.ubuntu_ami
  instance_type               = "t3.medium"
  subnet_id                   = aws_subnet.app.id
  vpc_security_group_ids      = [aws_security_group.app.id]
  key_name                    = var.key_name
  disable_api_termination     = true
  associate_public_ip_address = true
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }
  root_block_device {
    volume_size           = 40
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = false
  }
  lifecycle { prevent_destroy = true }
  tags = { Name = var.name, Application = "mcdxkit", Mode = "shared-workspace" }
}
resource "aws_eip" "app" {
  instance   = aws_instance.app.id
  domain     = "vpc"
  depends_on = [aws_internet_gateway.app]
}
output "address" { value = aws_eip.app.public_ip }
output "instance_id" { value = aws_instance.app.id }
output "persistent_disk_id" { value = aws_instance.app.root_block_device[0].volume_id }
