
data "aws_iam_policy_document" "run_task_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type = "Service"
      identifiers = [
        "lambda.amazonaws.com"
      ]
    }
  }
}

resource "aws_iam_role" "run_task" {
  name               = var.function_name
  assume_role_policy = data.aws_iam_policy_document.run_task_assume.json
}

data "aws_iam_policy_document" "run_task" {
  statement {
    effect = "Allow"
    actions = [
      "iam:PassRole"
    ]
    resources = [
      "*"
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecs:RunTask",
    ]
    resources = [
      "arn:aws:ecs:${local.aws_region}:${local.account_id}:task-definition/${var.task_definition_family}:*"
    ]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values = [
        "arn:aws:ecs:${local.aws_region}:cluster:cluster/${var.target_cluster_name}"
      ]
    }
  }

  statement {
    effect = "Allow"
    actions = [
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition"
    ]
    resources = [
      "*"
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "ecs:StopTask",
      "ecs:DescribeTasks",
    ]
    resources = [
      "arn:aws:ecs:${local.aws_region}:${local.account_id}:task/*"
    ]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values = [
        "arn:aws:ecs:${local.aws_region}:cluster:cluster/${var.target_cluster_name}"
      ]
    }
  }

  statement {
    effect = "Allow"
    actions = [
      "logs:*"
    ]
    resources = [
      "arn:aws:logs:${local.aws_region}:${local.account_id}:log-group:${var.function_name}:*"
    ]
  }

  statement {
    effect = "Allow"
    actions = [
      "codepipeline:PutJobSuccessResult",
      "codepipeline:PutJobFailureResult"
    ]
    resources = [
      "*"
    ]
  }
}

resource "aws_iam_policy" "run_task" {
  name   = var.function_name
  policy = data.aws_iam_policy_document.run_task.json
}

resource "aws_iam_role_policy_attachment" "run_task" {
  role       = aws_iam_role.run_task.name
  policy_arn = aws_iam_policy.run_task.arn
}
