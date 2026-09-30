#!/bin/sh
set -eu
export RABBITMQ_DEFAULT_PASS="$(cat /run/secrets/rabbit_password)"
export RABBITMQ_ERLANG_COOKIE="$(cat /run/secrets/rabbit_cookie)"
exec /usr/local/bin/docker-entrypoint.sh rabbitmq-server
