# deploy (Phase 3)

Three things live here:

| Folder | What | Checked how |
|---|---|---|
| `monitoring/` | Prometheus config, alert rules, a Grafana dashboard | Loaded by the Compose stack below |
| `loadtest/` | A k6 load test for the upload service | Run against a local stack |
| `terraform/` | One AWS server with k3s on it | `terraform fmt` only - **never applied** |
| `k8s/` | The app on k3s, HTTPS only | Schema check only - **never applied to a cluster** |

The Terraform and k3s files have not been run against a real AWS account or
cluster. Read them before you use them, and expect to fix things the first time.

## 1. The queue path and monitoring on your own computer

Needs Docker Desktop running.

```bash
docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d --build
```

- Dashboard: http://localhost:8080 (as before)
- Upload service: http://localhost:8090
- Prometheus: http://localhost:9090 (Status > Targets should show three "UP")
- Grafana: http://localhost:3000 - sign in as `admin` / `pcdoctor`, open the "PC Doctor" dashboard

Send a run through the queue and open its private link:

```bash
curl -F file=@PCDoctor-run.zip -F label="bench 1" http://localhost:8090/upload
```

The reply has a `status_url` (ask it until it says `done`) and a `share_key`:
open `http://localhost:8080/r/<share_key>`.

Stop it with:

```bash
docker compose -f docker-compose.yml -f docker-compose.scale.yml down
```

## 2. Load test

Install [k6](https://grafana.com/docs/k6/latest/set-up/install-k6/). Start the
stack with the hourly upload limit lifted (for the test only):

```bash
PCDOCTOR_UPLOADS_PER_HOUR=1000000 docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d
```

```bash
python deploy/loadtest/make_run.py
```

```bash
k6 run -e VUS=20 -e DURATION=2m deploy/loadtest/upload.js
```

Record requests per second, the 95th percentile, the error rate and the load
(VUs, duration, which machine) in `docs/results.md`. Test only your own
machines.

## 3. The cloud: one AWS server, k3s, HTTPS

**Rule: the app is never reachable from the internet without HTTPS.** The
ingress here redirects HTTP and gets a Let's Encrypt certificate, which needs
a domain name pointed at the server. Do not open the server's port 8080 or use
its bare IP address instead.

You need: an AWS account, a domain name, [Terraform](https://developer.hashicorp.com/terraform/install),
and an SSH key.

### Make the server

```bash
cd deploy/terraform
cp terraform.tfvars.example terraform.tfvars   # then fill it in
terraform init
terraform plan      # read what it will create
terraform apply
```

It prints the server's address. Create an **A record** for your domain
pointing at it. `terraform destroy` removes everything (and the data on it).

### Put the app on it

On the server (`ssh ubuntu@<address>`):

```bash
git clone https://github.com/HU3YN/PC-Doctor.git && cd PC-Doctor
sudo apt-get install -y docker.io
for name in api upload web; do
  dir=$([ $name = upload ] && echo upload-service || echo $name)
  sudo docker build -t pcdoctor/$name:local -f $dir/Dockerfile .
  sudo docker save pcdoctor/$name:local | sudo k3s ctr images import -
done
```

Install cert-manager (it gets and renews the HTTPS certificate):

```bash
sudo k3s kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
```

Create the secrets. They live only in the cluster - never in this repository:

```bash
sudo k3s kubectl create namespace pcdoctor
sudo k3s kubectl -n pcdoctor create secret generic pcdoctor-secrets \
  --from-literal=postgres-password="$(openssl rand -hex 24)" \
  --from-literal=metrics-token="$(openssl rand -hex 24)" \
  --from-literal=grafana-password="$(openssl rand -hex 12)"
```

The monitoring config comes from the files in `deploy/monitoring`:

```bash
k="sudo k3s kubectl -n pcdoctor"
$k create configmap prometheus-alerts --from-file=deploy/monitoring/alerts.yml
$k create configmap grafana-datasources --from-file=deploy/monitoring/grafana/provisioning/datasources
$k create configmap grafana-providers --from-file=deploy/monitoring/grafana/provisioning/dashboards
$k create configmap grafana-dashboards --from-file=deploy/monitoring/grafana/dashboards
```

Put your domain and email into `deploy/k8s/ingress.yaml` (two placeholders), then:

```bash
sudo k3s kubectl apply -k deploy/k8s
sudo k3s kubectl -n pcdoctor get pods     # wait for all "Running"
```

### Create the master account straight away

Until it exists, whoever has the setup code can claim the server. Read the code
and use it at `https://<your domain>` immediately:

```bash
sudo k3s kubectl -n pcdoctor exec deploy/api -- cat /data/setup-code.txt
```

### Look at the monitoring

Prometheus and Grafana are not published. From your own computer:

```bash
ssh -L 3000:localhost:3000 ubuntu@<address> sudo k3s kubectl -n pcdoctor port-forward svc/grafana 3000:3000
```

then open http://localhost:3000.

### Before you rely on it

- Back up: **Work log > Backup** in the dashboard, and `pg_dump` from the `db` pod.
- The Grafana password is in the secret:
  `kubectl -n pcdoctor get secret pcdoctor-secrets -o jsonpath='{.data.grafana-password}' | base64 -d`
- Check current AWS pricing and free-tier terms; a `t3.small` with an Elastic IP is not free.
