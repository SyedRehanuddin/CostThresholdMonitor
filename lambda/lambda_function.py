import boto3
import json
import os
import math
import time
import base64

from botocore.config import Config
from datetime import datetime, timedelta, timezone


# ============================================================
# CONFIGURATION
# ============================================================

REGION = "us-east-1"

# Maximum allowed budget/demo amount from dashboard
MAX_AMOUNT = 10_000

# Cache REAL Cost Explorer result for 5 minutes
# inside a warm Lambda instance.
REAL_CACHE_SECONDS = 300


# Short timeout configuration ONLY for IoT and SNS.
#
# total_max_attempts = 2 means:
# 1 initial request + maximum 1 retry.
SHORT_TIMEOUT_CONFIG = Config(
    connect_timeout=3,
    read_timeout=3,
    retries={
        "mode": "standard",
        "total_max_attempts": 2
    }
)


# ============================================================
# AWS CLIENTS
# ============================================================

# IMPORTANT:
# Do NOT use SHORT_TIMEOUT_CONFIG for Cost Explorer.
# Cost Explorer can legitimately take longer.
cost_explorer = boto3.client(
    "ce",
    region_name=REGION
)


# SNS uses short bounded timeouts.
sns_client = boto3.client(
    "sns",
    region_name=REGION,
    config=SHORT_TIMEOUT_CONFIG
)


# IoT client will be created only when required.
_iot_client = None


# Best-effort warm Lambda cache.
# This resets whenever AWS creates a new Lambda instance.
_real_cost_cache = {
    "data": None,
    "cached_at": None
}


# ============================================================
# DETECT API GATEWAY
# ============================================================

def is_api_gateway_event(event):
    """
    Detect an API Gateway HTTP API payload v2.0 request.
    """

    if not isinstance(event, dict):
        return False

    request_context = event.get("requestContext")

    return (
        event.get("version") == "2.0"
        and isinstance(request_context, dict)
        and isinstance(request_context.get("http"), dict)
    )


# ============================================================
# API RESPONSE
# ============================================================

def api_response(status_code, payload):
    """
    Create an explicit HTTP API response.

    CORS is handled by API Gateway,
    so no CORS headers are required here.
    """

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(
            payload,
            allow_nan=False
        )
    }


# ============================================================
# VALIDATION
# ============================================================

def parse_api_amount(value, name):
    """
    Validate values received from the dashboard/API.

    Dashboard must send real JSON numbers.

    Accepted:
        0.50
        1
        25.75

    Rejected:
        "0.50"
        true
        false
        NaN
        Infinity
        negative values
        extremely large values
    """

    # Python treats bool as a subclass of int,
    # so reject bool explicitly.
    if isinstance(value, bool):
        raise ValueError(
            f"{name} must be a number."
        )

    if not isinstance(value, (int, float)):
        raise ValueError(
            f"{name} must be a number."
        )

    number = float(value)

    if not math.isfinite(number):
        raise ValueError(
            f"{name} must be a finite number."
        )

    if number < 0 or number > MAX_AMOUNT:
        raise ValueError(
            f"{name} must be between 0 and {MAX_AMOUNT}."
        )

    return number


def parse_env_amount(value, name):
    """
    Environment variables are strings.

    Convert trusted environment values safely
    into numbers.
    """

    try:
        number = float(value)

    except (TypeError, ValueError):
        raise ValueError(
            f"{name} environment variable is invalid."
        )

    if not math.isfinite(number):
        raise ValueError(
            f"{name} environment variable must be finite."
        )

    if number < 0 or number > MAX_AMOUNT:
        raise ValueError(
            f"{name} environment variable must be "
            f"between 0 and {MAX_AMOUNT}."
        )

    return number


# ============================================================
# API BODY
# ============================================================

def parse_api_body(event):
    """
    Read and validate the API Gateway request body.
    """

    body = event.get("body")

    if body is None:
        raise ValueError(
            "Request body is required."
        )

    if isinstance(body, str):

        if not body.strip():
            raise ValueError(
                "Request body cannot be empty."
            )

        try:

            # Handle Base64 body if API Gateway ever sends one.
            if event.get("isBase64Encoded"):
                body = base64.b64decode(
                    body
                ).decode("utf-8")

            body = json.loads(body)

        except (
            json.JSONDecodeError,
            ValueError,
            UnicodeDecodeError
        ):
            raise ValueError(
                "Request body contains invalid JSON."
            )

    if not isinstance(body, dict):
        raise ValueError(
            "Request body must be a JSON object."
        )

    return body


# ============================================================
# GET REQUEST SETTINGS
# ============================================================

def get_request_values(event, api_request):
    """
    API Gateway/dashboard:
        Uses values sent from dashboard.

    EventBridge/Lambda console:
        Uses event values when supplied.
        Otherwise uses environment variables.
    """

    # --------------------------------------------------------
    # DASHBOARD / API GATEWAY
    # --------------------------------------------------------

    if api_request:

        body = parse_api_body(event)

        mode = body.get("mode")

        if mode not in ("DEMO", "REAL"):
            raise ValueError(
                "Mode must be exactly DEMO or REAL."
            )

        if "budget" not in body:
            raise ValueError(
                "Budget is required."
            )

        budget = parse_api_amount(
            body["budget"],
            "Budget"
        )

        # DEMO mode requires demo_cost.
        if mode == "DEMO":

            if "demo_cost" not in body:
                raise ValueError(
                    "Demo cost is required in DEMO mode."
                )

            demo_cost = parse_api_amount(
                body["demo_cost"],
                "Demo cost"
            )

        else:

            # REAL mode ignores demo_cost completely.
            demo_cost = None

        return mode, budget, demo_cost


    # --------------------------------------------------------
    # EVENTBRIDGE / DIRECT LAMBDA INVOCATION
    # --------------------------------------------------------

    if not isinstance(event, dict):
        event = {}


    # ---------------- MODE ----------------

    if "mode" in event:

        mode = event["mode"]

        if mode not in ("DEMO", "REAL"):
            raise ValueError(
                "Mode must be exactly DEMO or REAL."
            )

    else:

        mode = str(
            os.environ.get(
                "MODE",
                "REAL"
            )
        ).upper()

        if mode not in ("DEMO", "REAL"):
            raise ValueError(
                "MODE environment variable "
                "must be DEMO or REAL."
            )


    # ---------------- BUDGET ----------------

    if "budget" in event:

        budget = parse_api_amount(
            event["budget"],
            "Budget"
        )

    else:

        budget = parse_env_amount(
            os.environ.get(
                "BUDGET_LIMIT",
                "0.50"
            ),
            "Budget"
        )


    # ---------------- DEMO COST ----------------

    if mode == "DEMO":

        if "demo_cost" in event:

            demo_cost = parse_api_amount(
                event["demo_cost"],
                "Demo cost"
            )

        else:

            demo_cost = parse_env_amount(
                os.environ.get(
                    "DEMO_COST",
                    "0.75"
                ),
                "Demo cost"
            )

    else:

        demo_cost = None


    return mode, budget, demo_cost


# ============================================================
# REAL AWS COST
# ============================================================

def get_real_daily_cost():
    """
    Get the latest completed day's AWS Cost Explorer cost.

    AWS Cost Explorer billing data is not real-time.

    A best-effort 5-minute warm Lambda cache is used
    to reduce repeated Cost Explorer API calls.
    """

    global _real_cost_cache


    current_time = time.monotonic()

    cached_data = _real_cost_cache["data"]
    cached_at = _real_cost_cache["cached_at"]


    # --------------------------------------------------------
    # RETURN CACHE IF VALID
    # --------------------------------------------------------

    if (
        cached_data is not None
        and cached_at is not None
        and (
            current_time - cached_at
            < REAL_CACHE_SECONDS
        )
    ):

        print(
            "Using cached REAL Cost Explorer result."
        )

        return cached_data


    # --------------------------------------------------------
    # QUERY COST EXPLORER
    # --------------------------------------------------------

    today = datetime.now(
        timezone.utc
    ).date()

    cost_date = today - timedelta(days=1)


    print(
        "Requesting REAL cost from Cost Explorer "
        f"for {cost_date.isoformat()}"
    )


    response = cost_explorer.get_cost_and_usage(
        TimePeriod={
            "Start": cost_date.isoformat(),
            "End": today.isoformat()
        },
        Granularity="DAILY",
        Metrics=[
            "UnblendedCost"
        ]
    )


    results = response.get(
        "ResultsByTime",
        []
    )


    if not results:
        raise RuntimeError(
            "Cost Explorer returned no daily cost data."
        )


    amount = float(
        results[0][
            "Total"
        ][
            "UnblendedCost"
        ][
            "Amount"
        ]
    )


    if not math.isfinite(amount):
        raise RuntimeError(
            "Cost Explorer returned an invalid cost."
        )


    # AWS can sometimes return an extremely tiny
    # negative adjustment near zero.
    amount = max(
        0.0,
        amount
    )


    estimated = results[0].get(
        "Estimated",
        False
    )


    data = (
        amount,
        cost_date.isoformat(),
        estimated
    )


    # Store result in warm-instance cache.
    _real_cost_cache = {
        "data": data,
        "cached_at": current_time
    }


    return data


# ============================================================
# AWS IOT
# ============================================================

def get_iot_client():
    """
    Create AWS IoT Data client only when needed.

    Short timeout/retry configuration prevents an IoT
    network failure from consuming most of the Lambda
    execution time before SNS gets a chance to run.
    """

    global _iot_client


    if _iot_client is not None:
        return _iot_client


    endpoint = os.environ.get(
        "IOT_ENDPOINT"
    )


    if not endpoint:
        raise RuntimeError(
            "IOT_ENDPOINT is not configured."
        )


    _iot_client = boto3.client(
        "iot-data",
        region_name=REGION,
        endpoint_url=f"https://{endpoint}",
        config=SHORT_TIMEOUT_CONFIG
    )


    return _iot_client


def publish_to_iot(result):
    """
    Publish the latest cost result to AWS IoT Core.

    Successful publish means IoT Core accepted
    the message.

    It does NOT prove that the ESP32 received it.
    """

    topic = os.environ.get(
        "IOT_TOPIC",
        "cost-threshold/status"
    )


    client = get_iot_client()


    client.publish(
        topic=topic,
        qos=0,
        payload=json.dumps(
            result,
            allow_nan=False
        )
    )


    print(
        "Published successfully to IoT:",
        topic
    )


# ============================================================
# AWS SNS
# ============================================================

def send_sns_alert(result):
    """
    Send SNS alert only when threshold is exceeded.

    Returns:
        "sent"
        "skipped"

    Raises:
        Exception if alert was required
        but publishing to SNS failed.
    """

    # SAFE → no alert required.
    if result["status"] != "LIMIT_EXCEEDED":

        print(
            "Cost is within budget. "
            "SNS alert skipped."
        )

        return "skipped"


    sns_topic_arn = os.environ.get(
        "SNS_TOPIC_ARN"
    )


    if not sns_topic_arn:
        raise RuntimeError(
            "SNS_TOPIC_ARN is not configured."
        )


    message = (
        "AWS Cost Threshold Alert\n\n"
        f"Mode: {result['mode']}\n"
        f"Cost: ${result['cost']:.2f}\n"
        f"Budget Limit: ${result['budget']:.2f}\n"
        f"Status: {result['status']}\n\n"
        "The configured cloud spending threshold "
        "has been exceeded."
    )


    sns_client.publish(
        TopicArn=sns_topic_arn,
        Subject="AWS Cost Threshold Alert",
        Message=message
    )


    print(
        "SNS alert sent successfully."
    )


    return "sent"


# ============================================================
# MAIN LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    api_request = is_api_gateway_event(
        event
    )


    # ========================================================
    # STEP 1 — VALIDATE INPUT
    # ========================================================

    try:

        mode, budget, demo_cost = (
            get_request_values(
                event,
                api_request
            )
        )

    except ValueError as error:

        print(
            "INPUT ERROR:",
            str(error)
        )


        # Dashboard/API request.
        if api_request:

            return api_response(
                400,
                {
                    "error": "invalid_input",
                    "message": str(error)
                }
            )


        # EventBridge / Lambda console:
        # raise so AWS records the invocation as failed.
        raise


    # ========================================================
    # STEP 2 — DETERMINE COST
    # ========================================================

    if mode == "DEMO":

        cost = demo_cost
        cost_date = "DEMO"
        estimated = False


    else:

        try:

            (
                cost,
                cost_date,
                estimated
            ) = get_real_daily_cost()


        except Exception as error:

            print(
                "COST LOOKUP ERROR:",
                str(error)
            )


            # API Gateway request.
            if api_request:

                return api_response(
                    502,
                    {
                        "error": "cost_lookup_failed",
                        "message": (
                            "Unable to retrieve "
                            "AWS cost data."
                        )
                    }
                )


            # EventBridge/direct invocation:
            # mark invocation as failed.
            raise


    # ========================================================
    # STEP 3 — CALCULATE STATUS
    # ========================================================

    # Rule:
    #
    # cost < budget  → SAFE
    # cost = budget  → SAFE
    # cost > budget  → LIMIT_EXCEEDED

    status = (
        "LIMIT_EXCEEDED"
        if cost > budget
        else "SAFE"
    )


    checked_at = datetime.now(
        timezone.utc
    ).isoformat()


    result = {
        "mode": mode,
        "date": cost_date,
        "cost": round(
            cost,
            4
        ),
        "budget": round(
            budget,
            4
        ),
        "status": status,
        "estimated": bool(
            estimated
        ),
        "checked_at": checked_at
    }


    print(
        "Calculated result:",
        result
    )


    # ========================================================
    # STEP 4 — PUBLISH TO IOT
    # ========================================================

    iot_status = "failed"


    try:

        publish_to_iot(
            result
        )

        iot_status = "published"


    except Exception as error:

        # IoT failure must NOT stop SNS.
        print(
            "IOT ERROR:",
            str(error)
        )


    # ========================================================
    # STEP 5 — SNS ALERT
    # ========================================================

    sns_status = "failed"


    try:

        sns_status = send_sns_alert(
            result
        )


    except Exception as error:

        # SNS failure must not destroy a valid dashboard result.
        print(
            "SNS ERROR:",
            str(error)
        )


    # ========================================================
    # STEP 6 — BUILD FINAL RESULT
    # ========================================================

    final_result = {
        **result,
        "actions": {
            "iot": iot_status,
            "sns": sns_status
        }
    }


    print(
        "Final result:",
        final_result
    )


    # ========================================================
    # STEP 7 — SCHEDULED SNS FAILURE HANDLING
    # ========================================================

    # For EventBridge/direct scheduled runs:
    #
    # If an alert was required but SNS failed,
    # raise an error so AWS records the scheduled
    # invocation as failed.
    #
    # SAFE runs return sns="skipped", so they do not raise.

    if (
        not api_request
        and sns_status == "failed"
    ):

        raise RuntimeError(
            "SNS alert required but failed."
        )


    # ========================================================
    # STEP 8 — RETURN
    # ========================================================

    # API Gateway gets explicit HTTP 200.
    if api_request:

        return api_response(
            200,
            final_result
        )


    # EventBridge / Lambda console gets plain JSON object.
    return final_result