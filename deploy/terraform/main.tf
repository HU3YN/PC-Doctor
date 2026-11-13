# One small AWS server running k3s (a single-node Kubernetes), for PC Doctor.
#
# Not applied by anyone yet: review it, then run it with your own AWS account.
# See deploy/README.md. It costs money while it exists; "terraform destroy"
# removes everything it made.

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = "pc-doctor" }
  }
}

# The newest Ubuntu 24.04 image published by Canonical.
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
}

data "aws_vpc" "default" {
  default = true
}

resource "aws_key_pair" "admin" {
  key_name   = "pcdoctor-admin"
  public_key = var.ssh_public_key
}

resource "aws_security_group" "server" {
  name        = "pcdoctor-server"
  description = "PC Doctor: web traffic from anywhere, SSH and the Kubernetes API from the admin only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP: only redirects to HTTPS and answers the certificate check"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  ingress {
    description = "SSH, from the admin address only"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }
  ingress {
    description = "Kubernetes API, from the admin address only"
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }
  egress {
    description = "Outbound: package and image downloads, certificate issuing"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "server" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.admin.key_name
  vpc_security_group_ids = [aws_security_group.server.id]

  root_block_device {
    volume_type = "gp3"
    volume_size = var.disk_gb
    encrypted   = true
  }

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  # Installs k3s on first boot. Traefik (the ingress) comes with it.
  user_data = <<-SCRIPT
    #!/bin/bash
    set -euo pipefail
    apt-get update -y
    apt-get install -y unattended-upgrades
    curl -sfL https://get.k3s.io | INSTALL_K3S_CHANNEL=stable sh -s - --write-kubeconfig-mode 600
  SCRIPT

  tags = { Name = "pcdoctor" }

  lifecycle {
    ignore_changes = [ami] # a newer image must not replace a server that holds data
  }
}

# A fixed address, so the DNS record survives a restart.
resource "aws_eip" "server" {
  instance = aws_instance.server.id
  domain   = "vpc"
}
