# Which Terraform and provider versions this configuration is written for.
# Pinning versions means the same code behaves the same way on any machine, today and in a year.
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0" # any 6.x release, but not a future 7.0 with breaking changes
    }

    # Builds the Lambda deployment zip from our Python source on every plan.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}
