#!/bin/sh
set -eu
rabbitmq-plugins enable --offline rabbitmq_management
export RABBITMQ_DEFAULT_PASS="$(cat /run/secrets/rabbit_password)"
export RABBITMQ_ERLANG_COOKIE="$(cat /run/secrets/rabbit_cookie)"
exec /usr/local/bin/docker-entrypoint.sh rabbitmq-server
