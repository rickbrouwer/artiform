#!/usr/bin/env sh
# Starts and stops the disposable Artifactory OSS the acceptance tests run
# against (docker-compose.yml next to this script). Used locally and by the
# "Acceptance Tests" workflow; see docs/contrib/development.md.
#
#   tests/acceptance/artifactory.sh up      start, wait until ready, print
#                                           ARTIFACTORY_URL=... and
#                                           ARTIFACTORY_TOKEN=... on stdout
#   tests/acceptance/artifactory.sh down    stop and delete everything
#   tests/acceptance/artifactory.sh logs    print the Artifactory logs
#
# Environment:
#   ARTIFACTORY_PORT           host port (default 8082)
#   ARTIFACTORY_READY_TIMEOUT  seconds to wait for the server (default 600)
#
# Only the KEY=value lines go to stdout, so the output can be consumed by
#   export $(tests/acceptance/artifactory.sh up)          # locally
#   tests/acceptance/artifactory.sh up >> "$GITHUB_ENV"   # GitHub Actions
#
# Unlike GitLab, Artifactory cannot be seeded with a fixed, known token at
# startup, so the token is created over REST once the server is up and is
# different on every start.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
port=${ARTIFACTORY_PORT:-8082}
url="http://localhost:$port"
project=artiform-acceptance
# Default credentials of a fresh instance (the UI forces a change on first
# login, the API does not).
admin_user=admin
admin_password=password

compose() {
    docker compose -p "$project" -f "$here/docker-compose.yml" "$@"
}

log() {
    echo "artifactory.sh: $*" >&2
}

die() {
    log "$*"
    exit 1
}

wait_ready() {
    timeout=${ARTIFACTORY_READY_TIMEOUT:-600}
    start=$(date +%s)
    log "waiting for $url (up to ${timeout}s)"
    while :; do
        code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$url/artifactory/api/system/ping" || true)
        if [ "$code" = 200 ]; then
            log "ready after $(( $(date +%s) - start ))s"
            return
        fi
        if [ "$(compose ps --status running -q artifactory | wc -l)" -eq 0 ]; then
            compose logs artifactory >&2 || true
            die "the artifactory container is not running"
        fi
        if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
            compose logs --tail 50 artifactory >&2 || true
            die "Artifactory did not become ready within ${timeout}s"
        fi
        sleep 5
    done
}

create_token() {
    # Needs token.allow-basic-auth, see access.config.patch.yml. Access
    # answers 401 for a few seconds after the ping succeeds, hence the retry.
    attempt=0
    while :; do
        attempt=$((attempt + 1))
        response=$(curl -s -m 30 -u "$admin_user:$admin_password" -X POST "$url/access/api/v1/tokens" \
            -d 'scope=applied-permissions/admin' -d 'description=artiform acceptance tests' -d 'expires_in=0' || true)
        token=$(printf '%s' "$response" | sed -n 's/.*"access_token" *: *"\([^"]*\)".*/\1/p')
        if [ -n "$token" ]; then
            printf '%s\n' "$token"
            return
        fi
        if [ "$attempt" -ge 12 ]; then
            die "creating the admin token failed: $response"
        fi
        sleep 5
    done
}

case "${1:-}" in
    up)
        log "starting Artifactory OSS"
        compose up -d --quiet-pull >&2
        wait_ready
        token=$(create_token)
        echo "ARTIFACTORY_URL=$url"
        echo "ARTIFACTORY_TOKEN=$token"
        ;;
    down)
        compose down -v >&2
        ;;
    logs)
        compose logs artifactory
        ;;
    *)
        echo "usage: $0 up|down|logs" >&2
        exit 2
        ;;
esac
