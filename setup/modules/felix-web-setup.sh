#!/bin/bash
# ==============================================================================
# felix-web-setup.sh - Guided Felix WebApp image and resource questions
# ==============================================================================
#
# Extends the Felix full-stack wizard with public WebApp inputs. The module is
# sourced after felix-setup-wizard.sh so it can reuse its safe prompt helpers.
# ==============================================================================

# _felix_collect_web
# Collects the required Felix WebApp repository, version, replicas, and memory.
#
# Arguments:
#   None.
#
# Returns:
#   0 after setting every guided WebApp global.
#
# Side effects:
#   Updates guided-wizard globals used to write the public root .env.
_felix_collect_web() {
    echo ""
    echo "Step 5: Felix WebApp image and resources"
    echo "  The WebApp is required in the same felix-new stack as the backend."
    WEB_ENABLED="true"
    WEB_IMAGE_NAME="$(_felix_prompt_value \
        "WebApp image repository" \
        "$(_felix_existing_value WEB_IMAGE_NAME sokrates1989/felix-webapp)")"
    WEB_IMAGE_VERSION="$(_felix_prompt_value \
        "WebApp image version" \
        "$(_felix_existing_value WEB_IMAGE_VERSION 1.0.5)")"
    WEB_REPLICAS="$(_felix_prompt_value \
        "WebApp replicas" \
        "$(_felix_existing_value WEB_REPLICAS 1)")"
    WEB_MEMORY_LIMIT="$(_felix_prompt_value \
        "WebApp memory limit" \
        "$(_felix_existing_value WEB_MEMORY_LIMIT 128M)")"
}
