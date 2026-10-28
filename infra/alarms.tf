# Alarms: AWS tells me when the pipeline breaks, instead of me running a check to find out.
#
#   alert email <── SNS topic <── alarm 1: "it keeps failing"   (Lambda Errors)
#                             <── alarm 2: "it stopped running" (Lambda Invocations, the heartbeat)

# ---------- Where alerts go ----------

# SNS (Simple Notification Service) is a publish/subscribe channel: alarms publish to the
# topic, and every subscriber (here, one email address) receives the message.
resource "aws_sns_topic" "alerts" {
  name = "${var.project}-alerts"
}

# Email subscriptions start as "PendingConfirmation": AWS emails a link that must be clicked
# before any alert is delivered. Same address as the budget alerts (terraform.tfvars).
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------- Alarm 1: repeated failures ----------

# One failed run now and then is normal: the Carris API is outside my control.
# More than 5 failures in 15 minutes (a third of all runs) means something is really wrong.
resource "aws_cloudwatch_metric_alarm" "vehicles_errors" {
  alarm_name        = "${var.project}-carris-vehicles-errors"
  alarm_description = "Vehicles poller failed more than 5 times in 15 minutes. Check: aws logs tail <log group> --since 30m"

  namespace   = "AWS/Lambda"
  metric_name = "Errors" # unhandled exceptions AND timeouts both count as errors
  dimensions = {
    FunctionName = aws_lambda_function.vehicles.function_name
  }

  statistic           = "Sum"
  period              = 900 # seconds: one 15-minute window
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5

  # No error datapoints simply means no errors.
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn] # email when it starts failing
  ok_actions    = [aws_sns_topic.alerts.arn] # and again when it recovers
}

# ---------- Alarm 2: the heartbeat ----------

# The errors alarm can't see a function that never runs (schedule disabled or broken,
# permissions revoked...). So this alarm watches for the ABSENCE of runs: fewer than
# 10 invocations in 15 minutes, when 15 are expected.
resource "aws_cloudwatch_metric_alarm" "vehicles_heartbeat" {
  alarm_name        = "${var.project}-carris-vehicles-heartbeat"
  alarm_description = "Vehicles poller ran fewer than 10 times in 15 minutes (expected 15). Check the schedule state and the function."

  namespace   = "AWS/Lambda"
  metric_name = "Invocations"
  dimensions = {
    FunctionName = aws_lambda_function.vehicles.function_name
  }

  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  comparison_operator = "LessThanThreshold"
  threshold           = 10

  # The key setting: zero runs produce NO datapoints, so missing data must count as bad.
  treat_missing_data = "breaching"

  # When I pause ingestion on purpose with the kill switch, the heartbeat goes quiet too.
  actions_enabled = var.vehicles_schedule_enabled

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}
