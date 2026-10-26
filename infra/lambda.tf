# The vehicles poller, running the exact code from ingestion/src that we tested locally.

# Zip the Python package. This runs on every plan, so code changes are picked up automatically.
data "archive_file" "ingestion" {
  type        = "zip"
  source_dir  = "${path.module}/../ingestion/src"
  output_path = "${path.module}/build/ingestion.zip"
  excludes    = ["**/__pycache__/**", "**/*.pyc"]
}

# Create the log group ourselves (instead of letting Lambda create it on first run)
# so we control retention. Lambda's default is to keep logs forever, which slowly costs money.
resource "aws_cloudwatch_log_group" "vehicles" {
  name              = "/aws/lambda/${var.project}-carris-vehicles"
  retention_in_days = 14
}

resource "aws_lambda_function" "vehicles" {
  function_name = "${var.project}-carris-vehicles"
  role          = aws_iam_role.vehicles_lambda.arn

  filename         = data.archive_file.ingestion.output_path
  source_code_hash = data.archive_file.ingestion.output_base64sha256 # redeploy only when code changes

  runtime       = "python3.12"                        # same Python version we run locally
  handler       = "ingestion.carris_vehicles.handler" # module path + function name
  architectures = ["arm64"]                           # Graviton: cheaper per ms than x86

  memory_size = 128 # MB; the smallest size, plenty for one HTTP call and a gzip
  timeout     = 60  # seconds; worst case is 3 attempts x 15s timeout + 6s of backoff

  environment {
    variables = {
      RAW_BUCKET = aws_s3_bucket.raw.bucket # the same switch we used in Phase 3
    }
  }

  # Make sure the log group (with its retention) exists before the first run.
  depends_on = [aws_cloudwatch_log_group.vehicles, aws_iam_role_policy.vehicles_lambda]
}

# The scheduler invokes Lambda asynchronously. By default AWS retries a failed async run
# twice, up to 6 hours later. A retry can't recover a missed minute (it would just fetch
# the CURRENT snapshot), so we turn retries off: the next scheduled run is the retry.
resource "aws_lambda_function_event_invoke_config" "vehicles" {
  function_name                = aws_lambda_function.vehicles.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 60
}
