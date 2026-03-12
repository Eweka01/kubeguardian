#!/usr/bin/env bash
# Re-install the full observability stack from scratch
set -e

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring \
  -f prometheus-values.yaml \
  --wait

helm install loki grafana/loki-stack \
  --namespace monitoring \
  -f loki-values.yaml \
  --wait

helm install grafana grafana/grafana \
  --namespace monitoring \
  -f grafana-values.yaml \
  --wait
