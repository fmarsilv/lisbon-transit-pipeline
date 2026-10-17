# The AWS provider is the plugin that translates our resource blocks into AWS API calls.
provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  # Every resource created by this configuration gets these tags automatically,
  # so in the AWS console (and on the bill) you can always see what belongs to this project.
  default_tags {
    tags = {
      Project   = "lisbon-transit-pipeline"
      ManagedBy = "terraform"
    }
  }
}

# A "data source" reads existing information instead of creating anything.
# We use it to look up your AWS account ID, so it never has to be hard-coded in a public repo.
data "aws_caller_identity" "current" {}
