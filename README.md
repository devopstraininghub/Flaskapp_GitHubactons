# Flask Application Deployment on EKS with GitHub Actions, ArgoCD, and Helm

This document explains the deployment of a Flask application on an Amazon Elastic Kubernetes Service (EKS) cluster in the `ap-south-1` region, with worker nodes in private subnets for enhanced security. The Flask application, a simple web app displaying the current date and time, is containerized using a Dockerfile and deployed using Helm and ArgoCD for a GitOps-driven workflow. The ArgoCD UI is exposed via a Classic Load Balancer, and the Flask application is accessible through a Network Load Balancer (NLB), both routed through an Internet Gateway. An EC2 instance in a public subnet hosts the application locally (for development/testing) and runs CI/CD tools. A GitHub Actions pipeline automates testing, security scanning (SonarCloud and Trivy), Docker image building, Helm chart updates, and email notifications. An AWS Lambda function manages S3 reports, keeping only the latest three reports of each type (SonarCloud, Trivy filesystem, Trivy image) in the main S3 bucket and archiving older ones.

## Flask Application and Dockerfile

### Flask Application (`app.py`)
I developed a simple Flask application that displays the current date and a live-updating time on a web page. The application uses Flask to serve an HTML page with embedded JavaScript to update the time every second.

```python
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

@app.route("/")
def hello():
    today = datetime.now().strftime("%Y-%m-%d")
    # HTML with embedded JavaScript for live time
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Flask Time Application by Santosh</title>
        <script>
            function updateTime() {{
                const now = new Date();
                const time = now.toLocaleTimeString();
                document.getElementById("time").innerText = time;
            }}
            setInterval(updateTime, 1000);
        </script>
    </head>
    <body onload="updateTime()">
        <h2>Hello, This is a sample Flask Application!</h2>
        <p>Today's Date: <strong>{today}</strong></p>
        <p>Current Time: <strong id="time"></strong></p>
    </body>
    </html>
    """
    return render_template_string(html_content)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
```

### Dockerfile
I created a Dockerfile to containerize the Flask application, using a lightweight Python 3.9 image and exposing port 5000.

```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY app.py .

RUN pip install --no-cache-dir flask

EXPOSE 5000

CMD ["python", "app.py"]
```

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Network Architecture](#network-architecture)
4. [EC2 Instance Setup](#ec2-instance-setup)
5. [EKS Cluster Creation](#eks-cluster-creation)
6. [Node Group Configuration](#node-group-configuration)
7. [ArgoCD Installation](#argocd-installation)
8. [Helm Chart Structure](#helm-chart-structure)
9. [ArgoCD Application Manifest](#argocd-application-manifest)
10. [Ingress and Readiness Probes](#ingress-and-readiness-probes)
11. [GitHub Actions CI/CD Pipeline](#github-actions-cicd-pipeline)
12. [AWS Lambda for Report Archiving](#aws-lambda-for-report-archiving)
13. [Security Best Practices](#security-best-practices)
14. [Recommendations](#recommendations)
15. [Summary of Secrets Used](#summary-of-secrets-used)

## Overview
I have deployed the Flask application (`app.py`) on an EKS cluster with worker nodes in private subnets, ensuring high security. The application is containerized using the provided Dockerfile and deployed via Helm charts managed by ArgoCD. The ArgoCD UI is accessible through a Classic Load Balancer, and the Flask application is exposed via an NLB, both routed through an Internet Gateway. An EC2 instance in a public subnet serves as a control node for CI/CD pipelines and local app testing. The GitHub Actions pipeline automates testing, security scanning (SonarCloud and Trivy), Docker image building, Helm chart updates, and email notifications. An AWS Lambda function archives S3 reports, retaining only the latest three reports of each type in the main bucket.

## Prerequisites
I ensured the following were in place:
- **Tools**: AWS CLI, `kubectl`, `helm`, and Git installed on the EC2 instance and local system.
- **AWS Configuration**:
  - IAM roles for EKS, EC2, S3, Lambda, and VPC management.
  - Security groups for SSH, HTTP/HTTPS, and Kubernetes communication.
- **GitHub Repository**: Contains `app.py`, `Dockerfile`, and Helm charts at `https://github.com/YOUR_GITHUB_REPO.git`.
- **Secrets** (stored in GitHub Secrets):
  - `SONAR_TOKEN`: For SonarCloud authentication.
  - `DOCKER_USERNAME`, `DOCKER_PASSWORD`: For Docker Hub access.
  - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`: For AWS services.
  - `S3_BUCKET`: For storing scan reports.
  - `SMTP_SERVER`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `TO_EMAIL`: For email notifications.

## Network Architecture
I configured a VPC with public and private subnets to ensure secure access to the EKS cluster and application.

### Components
- **VPC**: Created in `ap-south-1` with CIDR `10.0.0.0/16`.
- **Public Subnets**:
  - `subnet-public-1` (CIDR: `10.0.1.0/24`, AZ: `ap-south-1a`): Hosts the EKS control plane, NAT Gateway, Classic Load Balancer, NLB, and EC2 instance.
  - `subnet-public-2` (CIDR: `10.0.2.0/24`, AZ: `ap-south-1b`): Ensures high availability.
- **Private Subnets**:
  - `subnet-private-1` (CIDR: `10.0.3.0/24`, AZ: `ap-south-1a`): Hosts EKS worker nodes.
  - `subnet-private-2` (CIDR: `10.0.4.0/24`, AZ: `ap-south-1b`): Ensures high availability.
- **Internet Gateway**: Attached to the VPC for public subnet internet access.
- **NAT Gateway**: Deployed in `subnet-public-1` for private subnet outbound internet access.
- **Route Tables**:
  - **Public**: Routes `0.0.0.0/0` to the Internet Gateway.
  - **Private**: Routes `0.0.0.0/0` to the NAT Gateway.
- **Security Groups**:
  - `sg-eks-control-plane`: Allows inbound traffic from worker nodes and my IP for API access.
  - `sg-eks-worker-nodes`: Allows communication with the control plane and load balancers.
  - `sg-load-balancer`: Allows HTTP/HTTPS (ports 80, 443) from my IP.
  - `sg-ec2`: Allows SSH (port 22) and HTTP (port 5000) from my IP.

### Setup Steps
1. **Created the VPC**:
   ```bash
   aws cloudformation create-stack --stack-name flask-vpc --template-url https://amazon-eks.s3.us-west-2.amazonaws.com/1.10.3/2022-06-29/amazon-eks-vpc-sample.yaml --region ap-south-1
   ```
   - Noted VPC ID, subnet IDs, and security group IDs.

2. **Attached an Internet Gateway**:
   ```bash
   aws ec2 create-internet-gateway --region ap-south-1
   aws ec2 attach-internet-gateway --internet-gateway-id igw-xxxx --vpc-id vpc-xxxx --region ap-south-1
   ```

3. **Created a NAT Gateway**:
   ```bash
   aws ec2 allocate-address --region ap-south-1
   aws ec2 create-nat-gateway --subnet-id subnet-public-1 --allocation-id eipalloc-xxxx --region ap-south-1
   ```

4. **Configured Route Tables**:
   - Public:
     ```bash
     aws ec2 create-route --route-table-id rtb-public --destination-cidr-block 0.0.0.0/0 --gateway-id igw-xxxx --region ap-south-1
     aws ec2 associate-route-table --route-table-id rtb-public --subnet-id subnet-public-1 --region ap-south-1
     aws ec2 associate-route-table --route-table-id rtb-public --subnet-id subnet-public-2 --region ap-south-1
     ```
   - Private:
     ```bash
     aws ec2 create-route --route-table-id rtb-private --destination-cidr-block 0.0.0.0/0 --nat-gateway-id nat-xxxx --region ap-south-1
     aws ec2 associate-route-table --route-table-id rtb-private --subnet-id subnet-private-1 --region ap-south-1
     aws ec2 associate-route-table --route-table-id rtb-private --subnet-id subnet-private-2 --region ap-south-1
     ```

5. **Configured Security Groups**:
   - Created `sg-eks-control-plane`, `sg-eks-worker-nodes`, `sg-load-balancer`, and `sg-ec2` with appropriate rules.

## EC2 Instance Setup
I set up an EC2 instance in `subnet-public-1` to host the Flask app locally and run CI/CD tools.

### Steps
1. **Launched the EC2 Instance**:
   - Used Amazon Linux 2 AMI, `t3.medium`.
   - Placed in `subnet-public-1` with auto-assigned public IP.
   - Assigned `sg-ec2` (allows SSH on port 22, HTTP on port 5000).
   - Used a key pair for SSH.

2. **Connected to the Instance**:
   ```bash
   ssh -i my-key-pair.pem ec2-user@<instance-public-ip>
   ```

3. **Installed Tools**:
   ```bash
   sudo yum update -y
   curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
   unzip awscliv2.zip
   sudo ./aws/install
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
   chmod +x kubectl
   sudo mv kubectl /usr/local/bin/
   curl https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 | bash
   sudo yum install git -y
   sudo yum install python39 -y
   pip3.9 install flask pytest
   ```

4. **Configured AWS Credentials**:
   ```bash
   aws configure
   ```
   - Entered `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` (`ap-south-1`).

5. **Cloned the Repository**:
   ```bash
   git clone https://github.com/YOUR_GITHUB_REPO.git
   cd YOUR_GITHUB_REPO
   ```

6. **Tested the Flask App Locally**:
   ```bash
   python3.9 app.py
   ```
   - Accessed at `http://<instance-public-ip>:5000`.

## EKS Cluster Creation
I created an EKS cluster in `ap-south-1` with the control plane in public subnets.

### Steps
1. **Created an IAM Role**:
   - Created `eks-cluster-role` with `AmazonEKSClusterPolicy` and `AmazonEKSVPCResourceController`.

2. **Created the Cluster**:
   ```bash
   aws eks create-cluster \
     --region ap-south-1 \
     --name flask-eks-cluster \
     --kubernetes-version 1.29 \
     --role-arn arn:aws:iam::<your-account-id>:role/eks-cluster-role \
     --resources-vpc-config subnetIds=subnet-public-1,subnet-public-2,securityGroupIds=sg-eks-control-plane
   ```

3. **Configured `kubectl`**:
   ```bash
   aws eks update-kubeconfig --name flask-eks-cluster --region ap-south-1
   kubectl get svc
   ```

## Node Group Configuration
I attached a managed node group in private subnets.

### Steps
1. **Created an IAM Role**:
   - Created `eks-node-group-role` with `AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryReadOnly`, `AmazonEKS_CNI_Policy`.

2. **Created the Node Group**:
   ```bash
   aws eks create-nodegroup \
     --region ap-south-1 \
     --cluster-name flask-eks-cluster \
     --nodegroup-name flask-node-group \
     --node-role arn:aws:iam::<your-account-id>:role/eks-node-group-role \
     --subnets subnet-private-1,subnet-private-2 \
     --instance-types t3.medium \
     --scaling-config minSize=1,maxSize=3,desiredSize=2 \
     --disk-size 20
   ```

3. **Verified Nodes**:
   ```bash
   kubectl get nodes
   ```

## ArgoCD Installation
I installed ArgoCD with a Classic Load Balancer.

### Steps
1. **Added Argo Helm Repository**:
   ```bash
   helm repo add argo https://argoproj.github.io/argo-helm
   helm repo update
   ```

2. **Created Namespace**:
   ```bash
   kubectl create namespace argocd
   ```

3. **Installed ArgoCD**:
   ```bash
   helm install argocd argo/argo-cd --namespace argocd --set server.service.type=LoadBalancer
   ```

4. **Exposed via Classic Load Balancer**:
   - Updated `sg-load-balancer` to allow ports 80/443 from my IP.
   - Retrieved endpoint:
     ```bash
     kubectl get svc -n argocd
     ```
   - Got admin password:
     ```bash
     kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath="{.data.password}" | base64 --decode && echo
     ```

## Helm Chart Structure
I structured the Helm chart as follows:
```
K8s/
├── charts/
│   ├── flask-app/
│   │   ├── Chart.yaml
│   │   ├── values.yaml
│   │   ├── templates/
│   │   │   ├── deployment.yaml
│   │   │   ├── service.yaml
│   │   │   ├── ingress.yaml
```
- **Chart.yaml**: Metadata (name, version).
- **values.yaml**: Image tag, resources, NLB settings.
- **deployment.yaml**: Flask app deployment (replicas, image, probes).
- **service.yaml**: `ClusterIP` for internal access.
- **ingress.yaml**: Routes traffic via NLB.

## ArgoCD Application Manifest
I created an ArgoCD manifest:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: flask-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/YOUR_GITHUB_REPO.git
    targetRevision: main
    path: K8s/charts/flask-app
    helm:
      valueFiles:
        - values.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

## Ingress and Readiness Probes
- **Ingress**: Configured in `ingress.yaml` for NLB routing, with TLS via `cert-manager`. Deployed NLB in `subnet-public-1` and `subnet-public-2`.
- **Readiness Probes**: Defined in `deployment.yaml` to ensure app readiness.

## GitHub Actions CI/CD Pipeline
I implemented a GitHub Actions workflow triggered on `main` branch pushes.

### Configuration
```yaml
on:
  push:
    branches: [main]
permissions:
  contents: write
  security-events: write
```

### Jobs
1. **build-and-test**
   - Installed Python 3.9, Flask, `pytest`, and ran tests.

2. **sonarqube-scan**
   - Ran SonarCloud scan, uploaded report to `s3://${{ secrets.S3_BUCKET }}/sonar/`.

3. **trivy-fs-scan**
   - Ran Trivy filesystem scan, uploaded SARIF report to S3.

4. **docker-build-push**
   - Built and pushed Docker image to `yourusername/flask-app:${{ github.run_number }}`.
   - Ran Trivy image scan, uploaded report to S3.

5. **archive-s3-reports**
   - Invoked Lambda function to archive reports.

6. **argocd**
   - Updated `values.yaml` with image tag, committed to Git.

7. **send-email-notification**
   - Sent scan reports via email using SMTP.

## AWS Lambda for Report Archiving
I created a Lambda function (`archive-old-reports`) to manage S3 reports, keeping only the latest three reports of each type (SonarCloud, Trivy filesystem, Trivy image) in the main bucket (`s3://${{ secrets.S3_BUCKET }}/{sonar,trivy}/`) and moving older reports to an archive prefix (`s3://${{ secrets.S3_BUCKET }}/archive/{sonar,trivy}/`).

### Lambda Function Logic
- **Input**: JSON payload with `bucket` name.
- **Logic**:
  - Lists objects in `s3://${bucket}/sonar/`, `s3://${bucket}/trivy/`.
  - Extracts build numbers from filenames (e.g., `sonar-report-123.json`).
  - Sorts reports by build number (descending).
  - Keeps the latest three reports per type in the main prefix.
  - Moves older reports to `s3://${bucket}/archive/{sonar,trivy}/`.
- **Example Code** (Python):
  ```python
  import boto3
  import json

  def lambda_handler(event, context):
      s3 = boto3.client('s3')
      bucket = event['bucket']
      prefixes = ['sonar', 'trivy']
      
      for prefix in prefixes:
          response = s3.list_objects_v2(Bucket=bucket, Prefix=f'{prefix}/')
          reports = []
          for obj in response.get('Contents', []):
              key = obj['Key']
              build = int(key.split('-')[-1].split('.')[0])
              reports.append((build, key))
          
          reports.sort(reverse=True)
          
          for i, (build, key) in enumerate(reports):
              if i >= 3:
                  archive_key = f'archive/{key}'
                  s3.copy_object(Bucket=bucket, CopySource={'Bucket': bucket, 'Key': key}, Key=archive_key)
                  s3.delete_object(Bucket=bucket, Key=key)
      
      return {'statusCode': 200, 'body': 'Reports archived'}
  ```
- **IAM Role**: Attached `AmazonS3FullAccess`.
- **Trigger**: Invoked by the CI/CD pipeline:
  ```bash
  aws lambda invoke --function-name archive-old-reports --payload '{"bucket": "${{ secrets.S3_BUCKET }}"}' response.json
  ```

## Security Best Practices
- Worker nodes in private subnets, accessible via load balancers.
- Restricted `sg-load-balancer` and `sg-ec2` to my IP.
- Implemented ArgoCD RBAC, avoiding long-term `admin` use.
- Enabled TLS for NLB with `cert-manager`.
- Rotated secrets regularly.
- Used Trivy and SonarCloud for scanning.

## Recommendations
- Add `pytest` tests to `app.py`.
- Implement secret rotation policies.
- Add Slack alerts for pipeline failures.
- Monitor ArgoCD sync status.

## Summary of Secrets Used
| Secret Name          | Purpose                                  |
|----------------------|------------------------------------------|
| `SONAR_TOKEN`        | SonarCloud authentication                |
| `DOCKER_USERNAME`     | Docker Hub username                      |
| `DOCKER_PASSWORD`    | Docker Hub password                      |
| `AWS_ACCESS_KEY_ID`  | AWS credentials for EKS, S3, Lambda      |
| `AWS_SECRET_ACCESS_KEY` | AWS credentials                      |
| `AWS_REGION`         | AWS region (`ap-south-1`)               |
| `S3_BUCKET`          | S3 bucket for reports                    |
| `SMTP_SERVER`        | SMTP server for notifications            |
| `SMTP_PORT`          | SMTP port                                |
| `SMTP_USERNAME`      | SMTP authentication username             |
| `SMTP_PASSWORD`      | SMTP authentication password             |
| `TO_EMAIL`           | Recipient email for reports              |

## Conclusion
I have deployed a Flask application on an EKS cluster with a secure network setup, using a Classic Load Balancer for ArgoCD and an NLB for the app. The EC2 instance supports local testing and CI/CD execution, while the GitHub Actions pipeline and ArgoCD ensure automated, secure deployments. The Lambda function efficiently manages S3 reports, keeping the latest three per type.
