#!/bin/bash

# KubeGuardian — Incident Simulator
# Usage: ./simulate.sh [incident] [service]
# Example: ./simulate.sh crashloop payment-service

INCIDENT=$1
SERVICE=${2:-payment-service}
NAMESPACE="app"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

case $INCIDENT in

  crashloop)
    echo -e "${RED}[SIMULATE] Triggering CrashLoopBackOff on $SERVICE...${NC}"
    kubectl set env deployment/$SERVICE \
      -n $NAMESPACE \
      FORCE_CRASH=true \
      BAD_ENV_VAR=this_will_break_startup
    kubectl patch deployment $SERVICE -n $NAMESPACE \
      -p '{"spec":{"template":{"spec":{"containers":[{"name":"'$SERVICE'","command":["sh","-c","exit 1"]}]}}}}'
    echo -e "${YELLOW}Watch: kubectl get pods -n $NAMESPACE -w${NC}"
    ;;

  readiness)
    echo -e "${RED}[SIMULATE] Triggering readiness probe failure on $SERVICE...${NC}"
    kubectl patch deployment $SERVICE -n $NAMESPACE -p '{
      "spec": {
        "template": {
          "spec": {
            "containers": [{
              "name": "'$SERVICE'",
              "readinessProbe": {
                "httpGet": {
                  "path": "/status/503",
                  "port": 80
                }
              }
            }]
          }
        }
      }
    }'
    echo -e "${YELLOW}Watch: kubectl get pods -n $NAMESPACE -w${NC}"
    ;;

  errorrate)
    echo -e "${RED}[SIMULATE] Triggering high error rate on $SERVICE...${NC}"
    kubectl patch deployment $SERVICE -n $NAMESPACE -p '{
      "spec": {
        "template": {
          "spec": {
            "containers": [{
              "name": "'$SERVICE'",
              "readinessProbe": {
                "httpGet": {
                  "path": "/status/500",
                  "port": 80
                }
              },
              "livenessProbe": {
                "httpGet": {
                  "path": "/status/500",
                  "port": 80
                }
              }
            }]
          }
        }
      }
    }'
    echo -e "${YELLOW}Watch: kubectl get pods -n $NAMESPACE -w${NC}"
    ;;

  restore)
    echo -e "${GREEN}[RESTORE] Restoring $SERVICE to healthy state...${NC}"
    kubectl rollout undo deployment/$SERVICE -n $NAMESPACE
    kubectl set env deployment/$SERVICE -n $NAMESPACE FORCE_CRASH-
    echo -e "${GREEN}Rollout restored. Watching...${NC}"
    kubectl rollout status deployment/$SERVICE -n $NAMESPACE
    ;;

  status)
    echo -e "${GREEN}[STATUS] Current pod health in namespace $NAMESPACE:${NC}"
    kubectl get pods -n $NAMESPACE
    ;;

  *)
    echo "Usage: ./simulate.sh [crashloop|readiness|errorrate|restore|status] [service-name]"
    echo ""
    echo "Services: api-gateway, payment-service, user-service"
    echo "Examples:"
    echo "  ./simulate.sh crashloop payment-service"
    echo "  ./simulate.sh readiness user-service"
    echo "  ./simulate.sh errorrate api-gateway"
    echo "  ./simulate.sh restore payment-service"
    ;;
esac
