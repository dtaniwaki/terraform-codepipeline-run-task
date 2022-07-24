data "archive_file" "run_task" {
  type        = "zip"
  source_file = "${path.module}/function/src/handler.py"
  output_path = "${path.module}/dist/run_task.zip"
}

resource "aws_lambda_function" "run_task" {
  function_name = var.function_name
  handler       = "handler.lambda_handler"
  role          = aws_iam_role.run_task.arn
  runtime       = "python3.8"
  timeout       = 900

  filename         = data.archive_file.run_task.output_path
  source_code_hash = data.archive_file.run_task.output_base64sha256

  depends_on = [aws_iam_role_policy_attachment.run_task, aws_cloudwatch_log_group.run_task]
}
