mock_provider "aws" {}
variables {
  region     = "us-east-1"
  ubuntu_ami = "ami-0123456789abcdef0"
  admin_ipv4 = "203.0.113.10/32"
  key_name   = "synthetic-key"
}
run "protected_workspace" {
  command = plan
  assert {
    condition     = aws_instance.app.disable_api_termination && !aws_instance.app.root_block_device[0].delete_on_termination && aws_instance.app.root_block_device[0].encrypted
    error_message = "Protect the persistent encrypted data disk."
  }
  assert {
    condition     = aws_instance.app.metadata_options[0].http_tokens == "required"
    error_message = "Require IMDSv2."
  }
  assert {
    condition     = alltrue([for rule in aws_security_group.app.ingress : rule.from_port == 80 || toset(rule.cidr_blocks) == toset([var.admin_ipv4])])
    error_message = "Only ACME HTTP may be open to the world."
  }
}
run "reject_public_admin" {
  command = plan
  variables { admin_ipv4 = "0.0.0.0/0" }
  expect_failures = [var.admin_ipv4]
}
