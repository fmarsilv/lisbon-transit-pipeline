# Two roles, one job each (least privilege):
#   1. The Lambda's execution role: what the function itself may do.
#   2. The scheduler's role: what EventBridge Scheduler may do (invoke this one function).
#
# Every IAM role has two halves:
#   - a TRUST policy: WHO may wear the role (here, an AWS service)
#   - a PERMISSION policy: WHAT the wearer may do

# ---------- 1. Lambda execution role ----------

data "aws_iam_policy_document" "lambda_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "vehicles_lambda" {
  name               = "${var.project}-carris-vehicles-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_trust.json
}

data "aws_iam_policy_document" "vehicles_lambda" {
  # Write raw files, but ONLY under the vehicles prefix. It cannot read, delete,
  # or touch any other part of the bucket.
  statement {
    sid       = "WriteRawVehicles"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.raw.arn}/raw/carris/vehicles/*"]
  }

  # Write its own logs, and only to its own log group.
  statement {
    sid       = "WriteOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.vehicles.arn}:*"]
  }
}

resource "aws_iam_role_policy" "vehicles_lambda" {
  name   = "write-raw-vehicles-and-logs"
  role   = aws_iam_role.vehicles_lambda.id
  policy = data.aws_iam_policy_document.vehicles_lambda.json
}

# ---------- 2. Scheduler role ----------

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    # Only schedules in OUR account may wear this role (protects against the
    # "confused deputy" problem, where another account tricks the service into acting for it).
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "InvokeVehiclesLambda"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.vehicles.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invoke-vehicles-lambda"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}
