# EventBridge Scheduler: AWS's cron. Fires the vehicles Lambda every minute.

resource "aws_scheduler_schedule" "vehicles" {
  name = "${var.project}-carris-vehicles-every-minute"

  schedule_expression = "rate(1 minute)" # the minimum interval (decision 009)

  # Kill switch: controlled by a variable, so the pipeline can be paused
  # with one apply, without deleting anything.
  state = var.vehicles_schedule_enabled ? "ENABLED" : "DISABLED"

  # OFF = fire at the exact time. (A flexible window lets AWS spread load,
  # which we don't want for evenly spaced snapshots.)
  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.vehicles.arn
    role_arn = aws_iam_role.scheduler.arn

    # Same reasoning as the Lambda retry config: a late retry is worthless,
    # the next minute's run replaces it.
    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 60
    }
  }
}
