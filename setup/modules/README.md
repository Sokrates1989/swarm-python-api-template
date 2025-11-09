# Setup Modules

This directory contains reusable modular components used by the setup wizards. Each module has both Bash (`.sh`) and PowerShell (`.ps1`) implementations for cross-platform support.

## Module Overview

### 1. user-prompts
**Purpose**: Handles all user input collection with validation

**Functions (Bash)**:
- `prompt_database_type()` - Select PostgreSQL or Neo4j
- `prompt_proxy_type()` - Select Traefik or no proxy
- `prompt_database_mode()` - Select local or external database
- `prompt_stack_name()` - Enter stack name
- `prompt_data_root()` - Enter data directory path
- `prompt_api_domain()` - Enter API domain (for Traefik)
- `prompt_published_port()` - Enter port number (for no proxy)
- `prompt_docker_image()` - Enter and verify Docker image
- `prompt_replicas()` - Enter replica count for services
- `prompt_secret_names()` - Enter Docker secret names
- `prompt_yes_no()` - Generic yes/no prompt

**Functions (PowerShell)**:
- `Get-DatabaseType` - Select PostgreSQL or Neo4j
- `Get-ProxyType` - Select Traefik or no proxy
- `Get-DatabaseMode` - Select local or external database
- `Get-StackName` - Enter stack name
- `Get-DataRoot` - Enter data directory path
- `Get-ApiDomain` - Enter API domain (for Traefik)
- `Get-PublishedPort` - Enter port number (for no proxy)
- `Get-DockerImage` - Enter and verify Docker image
- `Get-Replicas` - Enter replica count for services
- `Get-SecretNames` - Enter Docker secret names
- `Get-YesNo` - Generic yes/no prompt

### 2. config-builder
**Purpose**: Builds `.env` and `swarm-stack.yml` from modular templates

**Functions (Bash)**:
- `build_env_file()` - Concatenates environment templates
- `build_stack_file()` - Builds stack file with snippet injection
- `update_env_values()` - Updates key-value pairs in .env
- `update_stack_secrets()` - Replaces secret placeholders
- `backup_existing_files()` - Creates timestamped backups

**Functions (PowerShell)**:
- `New-EnvFile` - Concatenates environment templates
- `New-StackFile` - Builds stack file with snippet injection
- `Update-EnvValue` - Updates key-value pairs in .env
- `Update-StackSecrets` - Replaces secret placeholders
- `Backup-ExistingFiles` - Creates timestamped backups

**How it works**:
1. Reads base templates from `env-templates/` and `compose-modules/`
2. Concatenates appropriate templates based on user choices
3. Injects configuration snippets into API template
4. Produces final `.env` and `swarm-stack.yml` files

### 3. network-check
**Purpose**: Verifies DNS resolution for Traefik domains

**Functions (Bash)**:
- `network_verify()` - Checks DNS resolution and confirms with user

**Functions (PowerShell)**:
- `Network-Verify` - Checks DNS resolution and confirms with user

**Behavior**:
- Only runs when Traefik proxy is selected
- Uses `nslookup`, `dig`, or `host` (Bash) / .NET DNS (PowerShell)
- Prompts user to confirm resolved IP matches swarm manager
- Allows continuing even if DNS not configured (for testing)

### 4. data-dirs
**Purpose**: Creates required data directories with existence checks

**Functions (Bash)**:
- `create_data_directories()` - Creates all required directories

**Functions (PowerShell)**:
- `New-DataDirectories` - Creates all required directories

**Directories created**:
- Data root directory
- `postgres_data/` (if PostgreSQL local)
- `neo4j_data/` and `neo4j_logs/` (if Neo4j local)
- `redis_data/` (always)

### 5. secret-manager
**Purpose**: Handles Docker secret creation

**Functions (Bash)**:
- `create_docker_secrets()` - Guides user through secret creation
- `list_docker_secrets()` - Lists existing secrets
- `verify_secrets_exist()` - Checks if required secrets exist

**Functions (PowerShell)**:
- `New-DockerSecrets` - Guides user through secret creation
- `Get-DockerSecrets` - Lists existing secrets
- `Test-SecretsExist` - Checks if required secrets exist

**Behavior**:
- Prompts user to create secrets interactively
- Uses text editor (Bash) or secure input (PowerShell)
- Handles existing secrets gracefully
- Can skip creation for manual setup later

### 6. deploy-stack
**Purpose**: Deploys stack and performs health checks

**Functions (Bash)**:
- `deploy_stack()` - Deploys Docker stack
- `check_deployment_health()` - Verifies service health

**Functions (PowerShell)**:
- `Invoke-StackDeploy` - Deploys Docker stack
- `Test-DeploymentHealth` - Verifies service health

**Health checks include**:
- Service replica status
- Service logs inspection
- API health endpoint test (if Traefik)
- Deployment summary with useful commands

## Module Design Principles

### 1. Single Responsibility
Each module handles one specific aspect of the setup process.

### 2. Cross-Platform Compatibility
Every module has both Bash and PowerShell implementations with identical functionality.

### 3. Error Handling
Modules return appropriate exit codes and display clear error messages.

### 4. Idempotency
Modules check for existing resources before creating them.

### 5. User Feedback
Modules provide clear progress indicators and status messages with emojis.

## Adding New Modules

To add a new module:

1. **Create both implementations**:
   ```bash
   setup/modules/my-module.sh
   setup/modules/my-module.ps1
   ```

2. **Follow naming conventions**:
   - Bash: `function_name()` with snake_case
   - PowerShell: `Verb-Noun` with PascalCase

3. **Export functions**:
   - Bash: Functions are automatically available when sourced
   - PowerShell: Use `Export-ModuleMember -Function FunctionName`

4. **Import in wizards**:
   ```bash
   # Bash
   source "$SCRIPT_DIR/setup/modules/my-module.sh"
   
   # PowerShell
   Import-Module "$ScriptDir\setup\modules\my-module.ps1" -Force
   ```

5. **Document in this README**

## Testing Modules

Modules can be tested independently:

```bash
# Bash
source setup/modules/user-prompts.sh
result=$(prompt_database_type)
echo "Selected: $result"

# PowerShell
Import-Module .\setup\modules\user-prompts.ps1
$result = Get-DatabaseType
Write-Host "Selected: $result"
```

## Module Dependencies

Current dependency graph:

```
setup-wizard
├── user-prompts (no dependencies)
├── config-builder (no dependencies)
├── network-check (no dependencies)
├── data-dirs (no dependencies)
├── secret-manager (no dependencies)
└── deploy-stack (no dependencies)
```

All modules are independent and can be used in any order.
