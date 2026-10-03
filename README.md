# AWS Cost Threshold Monitor

A cloud-based AWS cost monitoring and alert system with a web dashboard, Lambda backend, Cost Explorer integration, IoT publishing, and SNS email alerts.

The project supports both **DEMO** and **REAL** modes, shows whether spending is within budget, and reports the result of each backend action.

## Live Demo

**GitHub Pages:**  
https://syedrehanuddin.github.io/CostThresholdMonitor/

> The frontend may stay online even when the AWS Academy Learner Lab backend is unavailable. In that case, the dashboard shows an API-unreachable state instead of displaying fake data.

## Screenshots

Project screenshots will be added from clean fullscreen dashboard views.

Recommended screenshots:

- DEMO SAFE
- DEMO LIMIT_EXCEEDED
- REAL mode

## Architecture

```text
                               EventBridge
                          (currently disabled)
                                    |
                                    v
Dashboard ---> API Gateway ---> AWS Lambda
                                |
                 +--------------+--------------+
                 |              |              |
                 v              v              v
        AWS Cost Explorer   AWS IoT Core    Amazon SNS
        (REAL mode only)         |              |
                                 v              v
                         ESP32 (planned)     Email Alert
                              |
                       +------+------+
                       |             |
                       v             v
                 OLED (planned)  Buzzer (planned)
```

## Key Features

- DEMO and REAL monitoring modes
- Configurable budget threshold
- AWS Cost Explorer integration
- AWS Lambda backend
- API Gateway HTTP API
- AWS IoT Core publishing
- SNS email alerts
- EventBridge scheduled monitoring configured, currently disabled
- Interactive web dashboard
- Recent successful check history
- SAFE and LIMIT_EXCEEDED visualization
- API failure handling
- Stale-result handling
- GitHub Pages deployment
- Localhost backup for demonstrations

## Monitoring Modes

### DEMO Mode

DEMO mode uses a simulated cost entered from the dashboard.

It is useful for demonstrating SAFE and LIMIT_EXCEEDED conditions without calling AWS Cost Explorer.

### REAL Mode

REAL mode retrieves the latest completed day's AWS `UnblendedCost` using AWS Cost Explorer.

AWS billing data may be delayed or estimated, so REAL mode does not represent live real-time spending.

## Threshold Rule

```text
Cost < Budget  -> SAFE
Cost = Budget  -> SAFE
Cost > Budget  -> LIMIT_EXCEEDED
```

## Alert Behaviour

Every successful check is published to AWS IoT Core, so a connected device can display both SAFE and LIMIT_EXCEEDED states.

Only when:

```text
Cost > Budget
```

does the system also attempt to send an SNS email alert.

SAFE checks are still published to AWS IoT Core, but they do not send an SNS alert.

## Execution Pipeline

The dashboard reports the result of each backend action.

Example:

```text
Lambda    ✓ Executed
IoT Core  ✓ Published
SNS       ✓ Alert sent
Email     Delivery not tracked
ESP32     Not connected
```

A successful IoT publish means AWS IoT Core accepted the message. It does **not** prove that the ESP32 received it.

A successful SNS publish means AWS accepted the alert request. Downstream email delivery is separate.

## AWS Services Used

- AWS Lambda
- Amazon API Gateway
- AWS Cost Explorer
- AWS IoT Core
- Amazon SNS
- Amazon EventBridge

## Backend Setup

- Runtime: Python on AWS Lambda
- Handler: `lambda_function.lambda_handler`
- Lambda timeout: **20 seconds** (verified with AWS CLI)
- Lambda source: `lambda/lambda_function.py`
- Required IAM permissions:
  - `ce:GetCostAndUsage`
  - `iot:Publish`
  - `sns:Publish`
- API Gateway: HTTP API
- Route: `POST /check`
- API Gateway route throttling configured:
  - Rate limit: 2 requests/second
  - Burst limit: 5
- Environment variable names are documented below.
- Environment variable values are intentionally not stored in this repository.

## Lambda Environment Variables

```text
MODE
BUDGET_LIMIT
DEMO_COST
IOT_ENDPOINT
IOT_TOPIC
SNS_TOPIC_ARN
```

Actual environment-variable values are not stored in this repository.

## API Behaviour

The dashboard sends requests to API Gateway.

The API validates:

- Monitoring mode
- Budget value
- Demo cost
- Numeric ranges
- Malformed JSON
- Missing request values

Important responses:

- `200` for a valid result
- `400` for invalid input
- `502` when REAL mode cannot retrieve AWS cost information
- `429` may occur if API Gateway throttling is triggered

## Cost Explorer Behaviour

REAL mode retrieves the latest completed day's AWS `UnblendedCost`.

The Lambda function uses a best-effort 5-minute warm-instance cache to reduce repeated Cost Explorer API calls.

The cache can reset whenever AWS creates a new Lambda execution environment.

## Failure Handling

IoT and SNS operations are handled independently.

This means:

- An IoT failure does not prevent SNS from running.
- An SNS failure does not destroy a valid API result.
- The dashboard can show which AWS action succeeded or failed.

For EventBridge or direct Lambda invocations, if an SNS alert is required but SNS fails, the Lambda function raises an error so AWS records the invocation as failed.

## Dashboard State Handling

If the API cannot be reached, the dashboard keeps the previous successful result visible but dims it.

It displays:

```text
Previous result. The latest check failed.
```

If the user switches modes while a successful result from another mode is displayed, the dashboard marks it as stale.

Example:

```text
This result is from DEMO mode. Run a check to update it.
```

A failed latest request has priority over the mode-mismatch warning.

## Recent Checks

Recent successful checks are stored in the browser using `localStorage`.

The history includes:

- Time
- Mode
- Cost
- Budget
- Status

The newest successful check is highlighted.

The small chart shows usage as a percentage of the configured budget, with a dashed line at 100%.

## Testing

Testing was performed using direct Lambda invocations, API requests, live browser dashboard checks, failure simulations, CORS preflight checks, and confirmation of SNS email delivery.

The following cases have been verified:

| Test | Result |
|---|---|
| DEMO SAFE | Passed |
| DEMO LIMIT_EXCEEDED | Passed |
| Cost equal to budget | Passed |
| Invalid string budget | Passed |
| Boolean budget | Passed |
| Negative budget | Passed |
| Invalid mode | Passed |
| Missing demo cost | Passed |
| Malformed JSON | Passed |
| Missing API body | Passed |
| REAL Cost Explorer check | Passed |
| IoT publish | Passed |
| SNS email alert | Passed |
| IoT failure handling | Passed |
| SNS failure handling | Passed |
| Direct invocation SNS failure handling | Passed |
| API/network failure UI | Passed |
| Mode-change stale result | Passed |
| Recovery after network failure | Passed |
| GitHub Pages deployment | Passed |
| GitHub Pages origin allowed by CORS (live browser test) | Passed |
| Localhost origin allowed by CORS (preflight test) | Passed |
| Unapproved origin receives no CORS allow header (preflight test) | Passed |
| Lambda timeout verified as 20 seconds | Passed |

API Gateway throttling is configured at 2 requests/second with a burst limit of 5, but a dedicated 429 stress test is not included in the table above.

## Current Hardware Status

ESP32 hardware integration is the next stage of the project.

Planned hardware:

- ESP32 development board
- 0.96-inch I2C SSD1306 OLED display
- Active buzzer module
- 830-point breadboard
- Male-to-Male jumper wires
- Male-to-Female jumper wires
- USB data cable

Until the ESP32 can publish an acknowledgement back to AWS, the dashboard intentionally displays:

```text
ESP32
Not connected
```

The dashboard will only show an acknowledged or connected state when the physical device can actually confirm receipt.

## Planned ESP32 Flow

```text
AWS IoT Core
      |
      v
ESP32
  |      |
  v      v
OLED   Buzzer
```

The ESP32 is planned to subscribe to:

```text
cost-threshold/status
```

When the threshold is exceeded:

- The OLED will display the cost and budget status.
- The buzzer will activate.
- The ESP32 will later publish an acknowledgement message.

## Security

No AWS credentials, secret access keys, session tokens, IoT private keys, certificates, passwords, or secret environment-variable values are stored in this repository.

The frontend contains the API Gateway endpoint because it is required to communicate with the backend. The API Gateway endpoint is not treated as a secret.

API Gateway CORS is currently restricted to the approved GitHub Pages origin and the localhost backup origin:

```text
https://syedrehanuddin.github.io
http://localhost:8000
```

CORS is **not** authentication. Direct tools such as `curl` can still call the public API endpoint.

The public API currently does not use user authentication, so this deployment should be treated as a college/demo deployment rather than a production service.

## Important Limitations

- REAL mode uses AWS billing data for the latest completed day and is not real-time.
- AWS billing information may be delayed or estimated.
- Dashboard settings apply only to the current check and are not saved permanently to Lambda.
- IoT `Published` does not confirm ESP32 delivery.
- SNS `Alert sent` does not confirm downstream email delivery.
- The frontend can remain deployed while the AWS Academy Learner Lab backend may be unavailable.
- The backend may not remain available when the Learner Lab environment is stopped.
- The public API currently does not use authentication.

## Deployment

The dashboard is deployed using GitHub Pages:

```text
https://syedrehanuddin.github.io/CostThresholdMonitor/
```

A localhost version is also retained as a backup for demonstrations.

Local backup command:

```bash
py -m http.server 8000 --bind 127.0.0.1
```

Then open:

```text
http://localhost:8000/
```

## CORS Configuration

API Gateway currently allows these browser origins:

```text
https://syedrehanuddin.github.io
http://localhost:8000
```

The repository path is not part of the origin.

For example:

```text
https://syedrehanuddin.github.io/CostThresholdMonitor/
```

has the origin:

```text
https://syedrehanuddin.github.io
```

The CORS configuration was verified with preflight requests:

- GitHub Pages origin returned `access-control-allow-origin`
- Localhost origin returned `access-control-allow-origin`
- An unapproved origin did not receive `access-control-allow-origin`

## EventBridge

An EventBridge scheduled rule has been configured for automatic monitoring, but it is currently disabled during development and testing.

Before enabling scheduled monitoring:

- Set Lambda `MODE` to `REAL`
- Confirm the budget threshold
- Configure Lambda asynchronous retry settings
- Configure EventBridge target retry settings
- Run a manual REAL check first

This prevents scheduled DEMO executions from generating fake exceeded alerts.

## Project Structure

```text
CostThresholdMonitor/
├── index.html
├── README.md
├── .gitignore
└── lambda/
    └── lambda_function.py
```

## Demo Procedure

Before presenting the project:

1. Start the AWS Academy Learner Lab.
2. Confirm the backend resources are available.
3. Open the deployed dashboard.
4. Run one DEMO SAFE check.
5. Run one DEMO LIMIT_EXCEEDED check.
6. Confirm the execution pipeline.
7. Confirm SNS email delivery.
8. Run one REAL check.
9. Keep localhost available as a backup.

## Future Work

- Connect ESP32 to AWS IoT Core
- Display cost and budget on OLED
- Activate buzzer when the budget is exceeded
- Add ESP32 acknowledgement messages
- Update the dashboard device state only after acknowledgement
- Add authentication before wider public deployment
- Add a permanent production backend outside the temporary Learner Lab
- Improve device-health monitoring

## Status

- Frontend dashboard: **Complete**
- AWS backend: **Complete and tested**
- EventBridge scheduled rule: **Configured, currently disabled**
- GitHub Pages deployment: **Deployed and verified**
- CORS restriction: **Configured and verified**
- Lambda timeout: **20 seconds, verified**
- ESP32 hardware integration: **Pending**
