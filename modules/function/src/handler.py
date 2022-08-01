import json
import logging
import os
import tempfile
import time
import zipfile
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

import boto3
import botocore
from boto3.session import Session

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
else:
    S3Client = Any

TARGET_KEYS = [
    "containerDefinitions",
    "volumes",
    "taskRoleArn",
    "executionRoleArn",
    "networkMode",
    "placementConstraints",
    "requiresCompatibilities",
    "cpu",
    "memory",
    "pidMode",
    "ipcMode",
    "proxyConfiguration",
    "inferenceAccelerators",
    "ephemeralStorage",
    "runtimePlatform",
]

TARGET_PARAM_KEY = Literal[
    "networkConfiguration",
    "overrides",
    "artifact",
    "file",
    "timeout",
    "launchType",
    "cluster",
    "containerName",
    "taskDefinitionFamily",
]

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def json_serial(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError("Type %s not serializable" % type(obj))


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    region_name = os.environ.get("AWS_REGION", None)
    ecs_client = boto3.client("ecs", region_name=region_name)
    codepipeline_client = boto3.client("codepipeline", region_name=region_name)

    job_id = event["CodePipeline.job"]["id"]
    job_data: Dict[str, Any] = event["CodePipeline.job"]["data"]
    logger.info("actionConfiguration: %s" % json.dumps(job_data["actionConfiguration"]))
    logger.info("inputArtifacts: %s" % json.dumps(job_data["inputArtifacts"]))
    logger.info("outputArtifacts: %s" % json.dumps(job_data["outputArtifacts"]))

    try:
        artifacts = job_data["inputArtifacts"]
        if len(artifacts) == 0:
            raise RuntimeError("inputArtifacts is required")

        params = get_user_params(job_data)
        cluster_name = params["cluster"]
        task_definition_family = params["taskDefinitionFamily"]
        container_name = params["containerName"]
        network_configuration = params.get("networkConfiguration", {})
        overrides = params.get("overrides", {})
        artifact = params.get("artifact", artifacts[0]["name"])
        file_name = params.get("file", "imageDetail.json")
        timeout_sec = int(params.get("timeout", "300"))
        launch_type = params.get("launchType", "FARGATE")

        s3_client = get_s3_client(job_data, region_name)
        artifact_data = find_artifact(artifacts, artifact)
        file_json = json.loads(get_file_content(s3_client, artifact_data, file_name))

        describe_task_definition_response = ecs_client.describe_task_definition(
            taskDefinition=task_definition_family,
        )
        logger.info(
            "Described task definition: %s" % json.dumps(describe_task_definition_response, default=json_serial)
        )
        task_definition = describe_task_definition_response["taskDefinition"]
        for cd in task_definition["containerDefinitions"]:
            if cd["name"] == container_name:
                cd["image"] = file_json["ImageURI"]
                break
        tags = describe_task_definition_response.get("tags", [])

        register_task_definition_response = ecs_client.register_task_definition(
            family=task_definition_family,
            **({"tags": tags} if len(tags) > 0 else {}),
            **{k: v for k, v in task_definition.items() if k in TARGET_KEYS and v is not None},  # type: ignore
        )

        task_definition = register_task_definition_response["taskDefinition"]
        revision = task_definition["revision"]

        run_task_response = ecs_client.run_task(
            cluster=cluster_name,
            taskDefinition="%s:%s" % (task_definition_family, revision),
            launchType=launch_type,
            networkConfiguration=network_configuration,
            overrides=overrides,
        )

        failures = run_task_response["failures"]
        if len(failures) > 0:
            raise RuntimeError("Failed to run a task: %s" % ", ".join([str(s) for s in failures]))

        task_arn = run_task_response["tasks"][0]["taskArn"]
        n_loop = timeout_sec
        for _n in range(0, n_loop):
            describe_tasks_response = ecs_client.describe_tasks(
                cluster=cluster_name,
                tasks=[task_arn],
            )
            task = describe_tasks_response["tasks"][0]

            if task["lastStatus"] == "STOPPED":
                logger.info("Described task on stop: %s", json.dumps(describe_tasks_response, default=json_serial))
                for c in task["containers"]:
                    if c["exitCode"] != 0:
                        raise RuntimeError("Task failed")

                break

            logger.info("Described task: %s", json.dumps(describe_tasks_response, default=json_serial))
            time.sleep(1)
        else:
            raise RuntimeError("Timeout!")

        codepipeline_client.put_job_success_result(jobId=job_id)
    except Exception as e:
        logger.exception(e)
        if "task_arn" in vars():
            try:
                _stop_task_response = ecs_client.stop_task(
                    cluster=cluster_name, task=task_arn, reason="Timeout exceeded"
                )
            except Exception as e2:
                logger.error("Failed to stop the task.")
                logger.exception(e2)

        codepipeline_client.put_job_failure_result(
            jobId=job_id, failureDetails={"message": str(e), "type": "JobFailed"}
        )
        return {"statusCode": 500, "body": json.dumps("NG!")}

    return {"statusCode": 200, "body": json.dumps("OK!")}


def get_user_params(job_data: Dict[str, Any]) -> Dict[TARGET_PARAM_KEY, Any]:
    try:
        user_parameters = job_data["actionConfiguration"]["configuration"]["UserParameters"]
        decoded_parameters = json.loads(user_parameters)
    except Exception as e:
        raise Exception("UserParameters could not be decoded as JSON")

    return decoded_parameters


def get_s3_client(job_data: Dict[str, Any], region_name: Optional[str]) -> S3Client:
    key_id = job_data["artifactCredentials"]["accessKeyId"]
    key_secret = job_data["artifactCredentials"]["secretAccessKey"]
    session_token = job_data["artifactCredentials"]["sessionToken"]

    session = Session(aws_access_key_id=key_id, aws_secret_access_key=key_secret, aws_session_token=session_token)

    return session.client("s3", config=botocore.client.Config(signature_version="s3v4"), region_name=region_name)


def find_artifact(artifacts: List[Dict[str, Any]], name) -> Dict[str, Any]:
    for artifact in artifacts:
        if artifact["name"] == name:
            return artifact

    raise Exception('Input artifact named "{0}" not found in event'.format(name))


def get_file_content(client: S3Client, artifact: Dict[str, Any], filename_in_zip: str) -> bytes:
    tmp_file = tempfile.NamedTemporaryFile()
    bucket = artifact["location"]["s3Location"]["bucketName"]
    key = artifact["location"]["s3Location"]["objectKey"]

    with tempfile.NamedTemporaryFile() as tmp_file:
        client.download_file(bucket, key, tmp_file.name)
        with zipfile.ZipFile(tmp_file.name, "r") as zip:
            return zip.read(filename_in_zip)
