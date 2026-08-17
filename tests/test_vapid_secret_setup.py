"""Tests for profile-driven Web Push VAPID Docker-secret setup."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VAPID_MODULE = REPOSITORY_ROOT / "setup" / "modules" / "vapid-secrets.sh"
SECRET_MENU = (
    REPOSITORY_ROOT / "setup" / "modules" / "docker-secrets-menu.sh"
)
MENU_HANDLERS = REPOSITORY_ROOT / "setup" / "modules" / "menu_handlers.sh"
ENGLISH_LOCALE = (
    REPOSITORY_ROOT / "setup" / "locales" / "operator-menu.en.sh"
)
GERMAN_LOCALE = (
    REPOSITORY_ROOT / "setup" / "locales" / "operator-menu.de.sh"
)
NATIVE_BASH_AVAILABLE = (
    not sys.platform.startswith("win") and shutil.which("bash") is not None
)
NATIVE_VAPID_TOOLS = (
    NATIVE_BASH_AVAILABLE
    and shutil.which("openssl") is not None
    and shutil.which("python3") is not None
)


def bash_quote(path: Path) -> str:
    """Return one safely single-quoted Bash path."""

    return "'" + str(path).replace("'", "'\"'\"'") + "'"


class VapidSecretSetupStaticTests(unittest.TestCase):
    """Protect the profile and menu contracts on every host."""

    def test_felix_declares_both_vapid_secret_mounts(self) -> None:
        """Keep the paired secret names discoverable from profile data."""

        profile = json.loads(
            (REPOSITORY_ROOT / "site-configs" / "felix.json").read_text(
                encoding="utf-8"
            )
        )
        mounts = profile["capabilities"]["webPush"]["secretMounts"]
        by_env_key = {mount["envKey"]: mount["name"] for mount in mounts}

        self.assertEqual(
            by_env_key["WEB_PUSH_VAPID_PUBLIC_KEY_FILE"],
            "FELIX_WEB_PUSH_VAPID_PUBLIC_KEY",
        )
        self.assertEqual(
            by_env_key["WEB_PUSH_VAPID_PRIVATE_KEY_FILE"],
            "FELIX_WEB_PUSH_VAPID_PRIVATE_KEY",
        )

    def test_vapid_setup_is_available_from_both_menus(self) -> None:
        """Expose dedicated top-level and secret-menu pair actions."""

        secret_menu = SECRET_MENU.read_text(encoding="utf-8")
        main_menu = MENU_HANDLERS.read_text(encoding="utf-8")

        self.assertIn(
            "Generate or replace the Web Push VAPID key pair",
            secret_menu,
        )
        self.assertIn(
            "Generate or replace Web Push VAPID secrets",
            main_menu,
        )
        self.assertIn("run_profile_vapid_secret_setup", secret_menu)
        self.assertIn("run_profile_vapid_secret_setup", main_menu)

    def test_individual_vapid_entry_redirects_to_pair_setup(self) -> None:
        """Prevent public and private keys from being edited independently."""

        source = SECRET_MENU.read_text(encoding="utf-8")
        editor = source[
            source.index("_create_profile_editor_secret()") : source.index(
                "# _create_selected_profile_secret"
            )
        ]

        self.assertIn("_profile_secret_is_vapid", editor)
        self.assertIn("run_profile_vapid_secret_setup", editor)

    def test_module_does_not_print_key_values(self) -> None:
        """Keep key values out of operator-facing success and error output."""

        source = VAPID_MODULE.read_text(encoding="utf-8")

        self.assertNotIn('echo "$public_key"', source)
        self.assertNotIn('echo "$private_key"', source)
        self.assertIn(
            'docker secret create "$public_name" "$public_file"',
            source,
        )
        self.assertIn(
            'docker secret create "$private_name" "$private_file"',
            source,
        )
        setup_flow = source[source.index("run_profile_vapid_secret_setup()") :]
        self.assertIn("_offer_vapid_recovery_view", setup_flow)

    def test_recovery_prompts_are_localized_in_english_and_german(self) -> None:
        """Keep the new recovery decision complete in both operator locales."""

        english = ENGLISH_LOCALE.read_text(encoding="utf-8")
        german = GERMAN_LOCALE.read_text(encoding="utf-8")

        for key in (
            "vapid.recovery_view_prompt",
            "vapid.recovery_copy_notice",
            "vapid.recovery_deleted",
            "vapid.recovery_not_viewed",
        ):
            with self.subTest(key=key):
                self.assertIn(f"[{key}]", english)
                self.assertIn(f"[{key}]", german)


@unittest.skipUnless(
    NATIVE_VAPID_TOOLS,
    "VAPID generation requires native Bash, OpenSSL, and python3.",
)
class VapidSecretGenerationLinuxTests(unittest.TestCase):
    """Exercise generation with production host dependencies."""

    def test_generated_pair_has_web_push_key_dimensions(self) -> None:
        """Generate an uncompressed P-256 public point and 32-byte scalar."""

        script = f"source {bash_quote(VAPID_MODULE)}; _generate_vapid_key_pair"
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        values = dict(
            line.split("=", maxsplit=1)
            for line in completed.stdout.splitlines()
        )
        public_key = base64.urlsafe_b64decode(values["PUBLIC_KEY"] + "=")
        private_key = base64.urlsafe_b64decode(values["PRIVATE_KEY"] + "=")
        self.assertEqual(len(public_key), 65)
        self.assertEqual(public_key[0], 4)
        self.assertEqual(len(private_key), 32)


@unittest.skipUnless(
    NATIVE_BASH_AVAILABLE,
    "VAPID menu failure propagation requires native Bash.",
)
class VapidSecretMenuLinuxTests(unittest.TestCase):
    """Exercise VAPID-specific secret-menu control flow."""

    def test_successful_pair_setup_offers_recoverable_exact_values(self) -> None:
        """Connect Docker-secret creation to the shared temporary viewer."""

        public_key = "A" * 87
        private_key = "B" * 43
        with tempfile.TemporaryDirectory() as temporary:
            project_root = Path(temporary)
            script = f"""
source {bash_quote(VAPID_MODULE)}
PROJECT_ROOT={bash_quote(project_root)}
profile_supports_vapid_secret_setup() {{ return 0; }}
_profile_vapid_secret_name_for_env_key() {{
    case "$1" in
        WEB_PUSH_VAPID_PUBLIC_KEY_FILE)
            printf '%s\n' FELIX_WEB_PUSH_VAPID_PUBLIC_KEY
            ;;
        WEB_PUSH_VAPID_PRIVATE_KEY_FILE)
            printf '%s\n' FELIX_WEB_PUSH_VAPID_PRIVATE_KEY
            ;;
    esac
}}
docker() {{ return 1; }}
_generate_vapid_key_pair() {{
    printf 'PUBLIC_KEY=%s\n' {public_key}
    printf 'PRIVATE_KEY=%s\n' {private_key}
}}
_create_vapid_docker_secret_pair() {{ return 0; }}
python3() {{
    local source_file=""
    while [ "$#" -gt 0 ]; do
        if [ "$1" = --source-file ]; then
            source_file="$2"
            shift 2
            continue
        fi
        shift
    done
    test -f "$source_file"
    test "$(stat -c '%a' "$source_file")" = 600
    grep -Fqx 'FELIX_WEB_PUSH_VAPID_PUBLIC_KEY={public_key}' "$source_file"
    grep -Fqx 'FELIX_WEB_PUSH_VAPID_PRIVATE_KEY={private_key}' "$source_file"
    rm -f -- "$source_file"
}}
run_profile_vapid_secret_setup
"""
            completed = subprocess.run(
                ["bash", "-c", script],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse((project_root / "backup").exists())
            self.assertNotIn(public_key, completed.stdout + completed.stderr)
            self.assertNotIn(private_key, completed.stdout + completed.stderr)

    def test_recovery_offer_uses_mode_0600_ephemeral_handoff(self) -> None:
        """Pass both exact-name values privately to the shared viewer."""

        public_key = "A" * 87
        private_key = "B" * 43
        script = f"""
source {bash_quote(VAPID_MODULE)}
python3() {{
    local source_file=""
    while [ "$#" -gt 0 ]; do
        if [ "$1" = --source-file ]; then
            source_file="$2"
            shift 2
            continue
        fi
        shift
    done
    printf 'MODE=%s\n' "$(stat -c '%a' "$source_file")"
    grep -Fqx 'FELIX_WEB_PUSH_VAPID_PUBLIC_KEY={public_key}' "$source_file"
    grep -Fqx 'FELIX_WEB_PUSH_VAPID_PRIVATE_KEY={private_key}' "$source_file"
    rm -f -- "$source_file"
}}
_offer_vapid_recovery_view \\
    FELIX_WEB_PUSH_VAPID_PUBLIC_KEY \\
    FELIX_WEB_PUSH_VAPID_PRIVATE_KEY \\
    {public_key} \\
    {private_key}
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("MODE=600", completed.stdout)
        self.assertNotIn(public_key, completed.stdout + completed.stderr)
        self.assertNotIn(private_key, completed.stdout + completed.stderr)

    def test_pair_writer_creates_both_protected_docker_secrets(self) -> None:
        """Pass both values through mode-0600 files to exact secret names."""

        public_key = "A" * 87
        private_key = "B" * 43
        script = f"""
source {bash_quote(VAPID_MODULE)}
log_file="$(mktemp)"
docker() {{
    if [ "$1" = secret ] && [ "$2" = inspect ]; then
        return 1
    fi
    if [ "$1" = secret ] && [ "$2" = create ]; then
        mode="$(stat -c '%a' "$4")"
        bytes="$(wc -c < "$4")"
        printf 'CREATE=%s:%s:%s\n' "$3" "$mode" "$bytes" >> "$log_file"
        return 0
    fi
    return 0
}}
_create_vapid_docker_secret_pair \
    VAPID_PUBLIC VAPID_PRIVATE {public_key} {private_key}
status=$?
printf 'STATUS=%s\n' "$status"
cat "$log_file"
rm -f -- "$log_file"
[ "$status" -eq 0 ]
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("STATUS=0", completed.stdout)
        self.assertIn("CREATE=VAPID_PUBLIC:600:87", completed.stdout)
        self.assertIn("CREATE=VAPID_PRIVATE:600:43", completed.stdout)
        self.assertNotIn(public_key, completed.stdout)
        self.assertNotIn(private_key, completed.stdout)

    def test_failed_vapid_setup_is_returned_on_menu_exit(self) -> None:
        """Prevent a failed pair setup from disappearing on menu redraw."""

        script = f"""
source {bash_quote(SECRET_MENU)}
_show_profile_secret_status() {{ :; }}
profile_supports_secret_file_workflow() {{ return 1; }}
profile_supports_vapid_secret_setup() {{ return 0; }}
profile_supports_keycloak_bootstrap() {{ return 1; }}
run_profile_vapid_secret_setup() {{
    echo vapid-failed
    return 29
}}
list_docker_secrets() {{ :; }}
_manage_profile_docker_secrets <<< $'3\n0\n'
status=$?
printf 'STATUS=%s\n' "$status"
[ "$status" -eq 29 ]
"""
        completed = subprocess.run(
            ["bash", "-c", script],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("vapid-failed", completed.stdout)
        self.assertIn(
            "Web Push VAPID setup did not complete",
            completed.stdout,
        )
        self.assertIn("STATUS=29", completed.stdout)


if __name__ == "__main__":
    unittest.main()
