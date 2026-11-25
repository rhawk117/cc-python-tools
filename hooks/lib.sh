# shellcheck shell=sh
# Sourced by hook.sh. The caller sets `here`.

root=${CLAUDE_PLUGIN_ROOT:-${here%/*}}
export UV_PROJECT="${root}"
export UV_PROJECT_ENVIRONMENT="${root}/.venv"

# run_launcher OVERRIDE ARGS...: run OVERRIDE when set, else the packaged launcher.
run_launcher() {
  override=$1
  shift
  if test -n "${override}"; then
    exec "${override}" "$@"
  fi
  exec uv run --locked --no-dev --package python-agent-tools-hooks python-agent-tools-hooks "$@"
}
