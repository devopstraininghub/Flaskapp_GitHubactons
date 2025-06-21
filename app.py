import boto3
import logging
from flask import Flask, render_template_string
from datetime import datetime
import time

app = Flask(__name__)

# Configure logging
logger = logging.getLogger('FlaskApp')
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler()
logger.addHandler(stream_handler)

# CloudWatch client
cloudwatch = boto3.client('cloudwatch', region_name='ap-south-1')

@app.route("/")
def home():
    start_time = time.time()
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        # Render simple HTML with dynamic time
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Flask Time App by SantoshV</title>
            <script>
                function updateTime() {{
                    const now = new Date();
                    document.getElementById("time").textContent = now.toLocaleTimeString();
                }}
                setInterval(updateTime, 1000);
            </script>
        </head>
        <body onload="updateTime()">
            <h2>Hello, this is a sample Flask application!</h2>
            <p>Today's Date: <strong>{today}</strong></p>
            <p>Current Time: <strong id="time"></strong></p>
        </body>
        </html>
        """

        latency = (time.time() - start_time) * 1000  # in milliseconds
        logger.info(f"Request latency: {latency:.2f}ms")

        # Send latency metric to CloudWatch
        cloudwatch.put_metric_data(
            Namespace='FlaskApp',
            MetricData=[{
                'MetricName': 'RequestLatency',
                'Value': latency,
                'Unit': 'Milliseconds'
            }]
        )

        return render_template_string(html_content)

    except Exception as e:
        logger.error(f"Error during request: {e}")

        # Log error metric
        try:
            cloudwatch.put_metric_data(
                Namespace='FlaskApp',
                MetricData=[{
                    'MetricName': 'ErrorCount',
                    'Value': 1,
                    'Unit': 'Count'
                }]
            )
        except Exception as cloudwatch_err:
            logger.error(f"Failed to publish CloudWatch metric: {cloudwatch_err}")

        return "Internal Server Error", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)